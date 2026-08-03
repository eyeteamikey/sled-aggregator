"""Anonymous, bounded connector for Georgia Procurement Registry (GPR).

GPR is modeled as the public-notification layer. Linked GA@WORK, legacy
PeopleSoft/Team Georgia Marketplace, eSource, JAGGAER, Bid Express, and agency
systems remain external relationships; this connector never authenticates or submits.
Only fixture-verified structured JSON and conservative HTML boundaries are parsed.
"""

import asyncio
import email.utils
import hashlib
import ipaddress
import json
import random
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

CANONICAL_FAMILY = "georgia/gpr"
PLATFORM_HOSTS = frozenset({"ssl.doas.state.ga.us", "doas.ga.gov", "gpr.doas.ga.gov"})


class GeorgiaGPRAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    REGISTRATION_REQUIRED = "registration_required"
    LOGIN_REQUIRED = "login_required"
    VENDOR_PROFILE_REQUIRED = "vendor_profile_required"
    RESPONSE_SYSTEM_EXTERNAL = "external_response_system"
    CAPTCHA_REQUIRED = "captcha_required"
    INVITATION_ONLY = "invitation_only"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    CHANGED_MARKUP = "changed_markup"
    MIGRATED = "migrated"
    TRANSIENT_ERROR = "transient_error"


class GeorgiaGPRError(RuntimeError):
    pass


class GeorgiaGPRAccessError(GeorgiaGPRError):
    def __init__(self, state: GeorgiaGPRAccessState):
        self.state = state
        super().__init__(f"GeorgiaGPR access boundary: {state.value}")


@dataclass(frozen=True, slots=True)
class GeorgiaGPRProfile:
    profile_key: str
    jurisdiction: str
    state_code: str
    government_level: str
    agency_name: str
    agency_slug: str
    organization_id: str | None = None
    procurement_landing_url: str | None = None
    agency_page_url: str = ""
    discovery_url: str = ""
    supported_hostname: str = "ssl.doas.state.ga.us"
    detail_url_template: str = ""
    official_procurement_url: str | None = None
    public_notice_url_template: str | None = None
    public_contract_url: str | None = None
    alternate_response_platform: str | None = None
    profile_status: str = "configured_unverified"
    expected_access_model: str = "mixed"
    page_size: int = 25
    maximum_pages: int = 4
    maximum_results: int = 100
    markup_variant: str = "semantic_html_or_json"
    verification_status: str = "configured_unverified"
    verification_timestamp: datetime | None = None
    verification_notes: str = ""
    approved_hosts: tuple[str, ...] = ()
    approved_document_hosts: tuple[str, ...] = ()
    replacement_platform: str | None = None
    replacement_url: str | None = None
    timeout: float = 20
    retries: int = 2
    backoff: float = 0.25
    jitter: float = 0.1
    circuit_threshold: int = 3
    cooldown: float = 60

    def __post_init__(self):
        if self.profile_status not in {
            "active",
            "legacy",
            "migrated",
            "configured_unverified",
            "unavailable",
        }:
            raise ValueError("unsupported profile status")
        if (
            not 1 <= self.page_size <= 100
            or not 1 <= self.maximum_pages <= 20
            or not 1 <= self.maximum_results <= 1000
        ):
            raise ValueError("discovery bounds are invalid")

    def detail_url(self, opportunity_id: str) -> str:
        return self.detail_url_template.format(opportunity_id=opportunity_id)


FIXTURE_PROFILE = GeorgiaGPRProfile(
    profile_key="georgia-statewide",
    jurisdiction="Georgia",
    state_code="GA",
    government_level="state",
    agency_name="Georgia state and participating local public bodies",
    agency_slug="statewide",
    agency_page_url="https://doas.ga.gov/state-purchasing/georgia-procurement-registry-for-local-governments",
    discovery_url="https://ssl.doas.state.ga.us/gpr/eventSearch",
    detail_url_template="https://ssl.doas.state.ga.us/gpr/eventDetails?eventId={opportunity_id}",
    public_notice_url_template="https://ssl.doas.state.ga.us/gpr/eventDetails?eventId={opportunity_id}",
    official_procurement_url="https://doas.ga.gov/state-purchasing",
    profile_status="active",
    verification_status="fixture_verified",
    approved_hosts=("ssl.doas.state.ga.us", "gpr.doas.ga.gov"),
    approved_document_hosts=(
        "ssl.doas.state.ga.us",
        "doas.ga.gov",
        "gpr.doas.ga.gov",
        "sourcing.gawork.com",
        "solutions.sciquest.com",
        "bidexpress.com",
    ),
)
GPR_PROFILES = {FIXTURE_PROFILE.profile_key: FIXTURE_PROFILE}


@dataclass(frozen=True, slots=True)
class GeorgiaGPRQuery(ConnectorQuery):
    status: str | None = None
    title: str | None = None
    description: str | None = None
    project_number: str | None = None
    solicitation_number: str | None = None
    agency: str | None = None
    nigp: str | None = None
    response_type: str | None = None
    government_type: str | None = None
    entity: str | None = None
    posted_from: date | None = None
    posted_to: date | None = None
    due_from: date | None = None
    due_to: date | None = None
    awarded_from: date | None = None
    awarded_to: date | None = None
    page_size: int | None = None
    maximum_pages: int | None = None
    maximum_results: int | None = None
    include_details: bool = True


@dataclass(frozen=True, slots=True)
class GeorgiaGPRHealth:
    profile_key: str
    configuration_valid: bool
    access_state: str
    consecutive_failures: int
    circuit_open: bool
    last_status_code: int | None
    last_failure_time: datetime | None
    last_error: str | None


class Transport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.json_text = []
        self._script = False
        self._text = []
        self.hidden_fields = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("type", "").casefold() == "hidden":
            name = values.get("name")
            if name in {
                "__VIEWSTATE",
                "__VIEWSTATEGENERATOR",
                "__EVENTVALIDATION",
                "__EVENTTARGET",
                "__EVENTARGUMENT",
            }:
                self.hidden_fields[name] = values.get("value", "")
        if tag == "a" and values.get("href"):
            self.links.append(
                (
                    values["href"],
                    values.get("data-document-type"),
                    values.get("data-access-state"),
                    values.get("data-version"),
                )
            )
        if tag == "script" and values.get("type") in {"application/json", "application/ld+json"}:
            self._script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False

    def handle_data(self, data):
        self._text.append(data)
        if self._script:
            self.json_text.append(data)


def detect_access_boundary(text: str) -> GeorgiaGPRAccessState:
    value = re.sub(r"\s+", " ", text).casefold()
    for state, terms in (
        (
            GeorgiaGPRAccessState.CAPTCHA_REQUIRED,
            ("captcha", "g-recaptcha", "hcaptcha", "challenge-form"),
        ),
        (
            GeorgiaGPRAccessState.VENDOR_PROFILE_REQUIRED,
            ("add to my solicitations", "acknowledge receipt", "vendor profile required"),
        ),
        (
            GeorgiaGPRAccessState.INVITATION_ONLY,
            ("by invitation only", "invited vendors only", "invitation only"),
        ),
        (
            GeorgiaGPRAccessState.VENDOR_PROFILE_REQUIRED,
            (
                "prospective bidder",
                "join the bidders list",
                "acknowledge addendum",
                "rsvp required",
            ),
        ),
        (
            GeorgiaGPRAccessState.REGISTRATION_REQUIRED,
            ("registration required", "create a supplier account", "register to download"),
        ),
        (
            GeorgiaGPRAccessState.LOGIN_REQUIRED,
            ("login required", "sign in to continue", "supplier login", "maryland sso", "mdot sso"),
        ),
        (
            GeorgiaGPRAccessState.MIGRATED,
            ("moved to ga@work", "legacy event has moved", "this page has moved"),
        ),
        (GeorgiaGPRAccessState.RESTRICTED, ("access denied", "not authorized")),
        (GeorgiaGPRAccessState.UNAVAILABLE, ("temporarily unavailable", "scheduled maintenance")),
    ):
        if any(term in value for term in terms):
            return state
    return GeorgiaGPRAccessState.PUBLIC


def parse_aspnet_state(text: str) -> dict[str, str]:
    """Return allow-listed navigation markers without enabling form submission."""
    parser = _PageParser()
    parser.feed(text)
    return parser.hidden_fields


def external_platform(url: str) -> str | None:
    """Classify, but never invoke, an upstream response system."""
    host = (urlparse(url).hostname or "").casefold()
    path = urlparse(url).path.casefold()
    if "gawork" in host:
        return "gawork_marketplace"
    if "sciquest" in host or "jaggaer" in host:
        return "jaggaer_sourcing_director"
    if "bidexpress" in host or "bidx" in host:
        return "bid_express"
    if "esource" in host or "esource" in path:
        return "esource"
    if "peoplesoft" in host or "psp" in path:
        return "peoplesoft"
    if "teamgeorgia" in host or "tgm" in host:
        return "team_georgia_marketplace"
    if host in PLATFORM_HOSTS:
        return "gpr_direct"
    if host:
        return (
            "agency_hosted"
            if host.endswith(".ga.us") or host.endswith(".gov")
            else "external_portal"
        )
    return None


def parse_page(
    text: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str | None, str | None, str | None]]]:
    parser = _PageParser()
    parser.feed(text)
    payloads = []
    for block in parser.json_text:
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates = value.get("opportunities") or value.get("items") or [value]
            if isinstance(candidates, list):
                payloads.extend(x for x in candidates if isinstance(x, dict))
        elif isinstance(value, list):
            payloads.extend(x for x in value if isinstance(x, dict))
    return payloads, parser.links


class GeorgiaGPRConnector(BaseConnector):
    platform_family = CANONICAL_FAMILY
    document_pipeline_compatible = True
    jurisdictions = ("configurable",)
    public_read_only = True
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        profile: GeorgiaGPRProfile = FIXTURE_PROFILE,
        *,
        transport: Transport | None = None,
        sleep=asyncio.sleep,
        random_value=random.random,
        now=lambda: datetime.now(UTC),
    ):
        self.profile = profile
        self._transport = transport or httpx.AsyncClient(
            follow_redirects=False, timeout=profile.timeout
        )
        self._owns_transport = transport is None
        self._sleep = sleep
        self._random = random_value
        self._now = now
        self._failures = 0
        self._last_failure = None
        self._last_status = None
        self._last_error = None
        self._access = GeorgiaGPRAccessState.UNKNOWN

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self):
        return GeorgiaGPRHealth(
            self.profile.profile_key,
            self._configuration_valid(),
            self._access.value,
            self._failures,
            self._circuit_open(),
            self._last_status,
            self._last_failure,
            self._last_error,
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, GeorgiaGPRQuery)
            else GeorgiaGPRQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if self.profile.profile_status in {"migrated", "legacy", "unavailable"}:
            raise GeorgiaGPRAccessError(
                GeorgiaGPRAccessState.MIGRATED
                if self.profile.profile_status != "unavailable"
                else GeorgiaGPRAccessState.UNAVAILABLE
            )
        if not self._configuration_valid():
            raise GeorgiaGPRError("invalid or unsafe GeorgiaGPR profile")
        pages = min(q.maximum_pages or self.profile.maximum_pages, self.profile.maximum_pages)
        maximum = min(q.maximum_results or q.limit, self.profile.maximum_results, q.limit)
        seen_pages = set()
        records = {}
        next_url = self.profile.discovery_url
        for page in range(1, pages + 1):
            response = await self._get(
                next_url,
                params={
                    "page": page,
                    "pageSize": min(q.page_size or self.profile.page_size, self.profile.page_size),
                },
            )
            digest = hashlib.sha256(response.content).digest()
            if digest in seen_pages:
                break
            seen_pages.add(digest)
            boundary = detect_access_boundary(response.text)
            if boundary is not GeorgiaGPRAccessState.PUBLIC:
                raise GeorgiaGPRAccessError(boundary)
            items, links = parse_page(response.text)
            if not items:
                if page == 1 and not re.search(
                    r"no (?:matching )?(?:events|opportunities|notices)|data-gpr-list",
                    response.text,
                    re.I,
                ):
                    raise GeorgiaGPRAccessError(GeorgiaGPRAccessState.CHANGED_MARKUP)
                break
            for data in items:
                raw_id = (
                    str(data.get("id") or data.get("opportunityId") or data.get("uuid") or "")
                    .strip()
                    .lower()
                )
                title = str(data.get("title") or data.get("name") or "").strip()
                if not raw_id or not title:
                    continue
                records.setdefault(raw_id, data)
            if len(records) >= maximum:
                break
            if not any(rel == "next" for _, rel, _, _ in links):
                break
        for raw_id, data in sorted(
            records.items(), key=lambda x: (str(x[1].get("postedDate", "")), x[0]), reverse=True
        ):
            if len(records) and maximum <= 0:
                break
            item = self._normalize(data, raw_id)
            if not self._matches(item, q):
                continue
            if q.include_details:
                response = await self._get(self.profile.detail_url(raw_id))
                detail, _ = parse_page(response.text)
                boundary = detect_access_boundary(response.text)
                # Structured opportunity data may legitimately describe individual
                # gated packages; that must not classify the whole public page as gated.
                if detail:
                    item = self._normalize({**data, **detail[0]}, raw_id)
                elif boundary is not GeorgiaGPRAccessState.PUBLIC:
                    item.raw_payload["detail_access_state"] = boundary.value
                else:
                    item.raw_payload["detail_access_state"] = "changed_markup"
            yield item
            maximum -= 1
            if maximum <= 0:
                break

    def _normalize(self, data, raw_id):
        url = str(data.get("url") or self.profile.detail_url(raw_id))
        safe = self._safe_url(url) or self.profile.detail_url(raw_id)
        docs = data.get("documents") if isinstance(data.get("documents"), list) else []
        record_type = str(data.get("recordType", "solicitation"))
        agency_id = str(data.get("agencyId") or self.profile.organization_id or "").strip()
        identity_suffix = f":{record_type}:{agency_id.casefold()}" if data.get("noticeId") else ""
        source_id = f"{CANONICAL_FAMILY}:{self.profile.profile_key}:{raw_id}{identity_suffix}"
        posted = self._datetime(data.get("postedDate"))
        due = self._datetime(data.get("dueDate"))
        provenance = {
            k: {"source": "public embedded JSON", "value": v, "inferred": False}
            for k, v in data.items()
            if v not in (None, "")
        }
        return RawOpportunity(
            source=SourceRef(
                platform_family=CANONICAL_FAMILY,
                jurisdiction=self.profile.jurisdiction,
                source_id=source_id,
                opportunity_url=safe,
            ),
            title=str(data.get("title") or data.get("name")),
            agency=str(data.get("agency") or self.profile.agency_name),
            description=data.get("description"),
            solicitation_number=data.get("solicitationNumber"),
            status=self._status(data.get("status")),
            posted_at=posted,
            due_at=due,
            categories=list(data.get("categories") or []),
            raw_payload={
                **data,
                "raw_upstream_id": raw_id,
                "profile_key": self.profile.profile_key,
                "authoritative_url": safe,
                "official_agency_url": self.profile.official_procurement_url,
                "documents": docs,
                "source_provenance": provenance,
                "access_state": data.get("accessState")
                or ("external_response_system" if data.get("alternateResponseUrl") else "public"),
                "record_type": record_type,
                "public_notice_id": data.get("noticeId"),
                "project_number": data.get("projectNumber"),
                "alternate_id": data.get("alternateId"),
                "solicitation_type": data.get("type"),
                "procurement_method": data.get("procurementMethod"),
                "government_level": data.get("governmentLevel", self.profile.government_level),
                "agency_identifier": data.get("agencyId") or self.profile.organization_id,
                "nigp_codes": data.get("nigpCodes", data.get("commodityCodes", [])),
                "issuing_government_type": data.get("governmentType"),
                "issuing_department": data.get("department"),
                "public_contact": data.get("contact"),
                "award_date": data.get("awardDate"),
                "award_information": data.get("award"),
                "transition_state": data.get("transitionState", "current"),
                "verification_state": self.profile.verification_status,
                "question_deadline": data.get("questionDeadline"),
                "opening_date": data.get("openingDate"),
                "gpr_notice_url": safe,
                "external_response_url": data.get("alternateResponseUrl"),
                "upstream_event_id": data.get("eventId"),
                "alternate_response_url": data.get("alternateResponseUrl"),
                "upstream_sourcing_system": data.get("upstreamSystem")
                or data.get("alternatePlatform")
                or external_platform(str(data.get("alternateResponseUrl", ""))),
                "documents_complete": all(
                    str(x.get("accessState", "public")) == "public"
                    for x in docs
                    if isinstance(x, dict)
                ),
            },
        )

    def document_candidates(self, opportunity):
        result = []
        seen = set()
        for doc in opportunity.raw_payload.get("documents", []):
            if not isinstance(doc, dict):
                continue
            url = self._safe_url(str(doc.get("url", "")), document=True)
            if not url:
                continue
            canonical = self._canonical_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            state = self._access_state(doc.get("accessState"))
            label = str(doc.get("label") or doc.get("filename") or "document")
            filename = re.sub(
                r"[^A-Za-z0-9._ -]",
                "_",
                str(doc.get("filename") or urlparse(url).path.rsplit("/", 1)[-1] or "document"),
            )
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=url,
                    source_opportunity_url=opportunity.source.opportunity_url,
                    filename=filename,
                    label=label,
                    mime_type=doc.get("mediaType"),
                    access_state=state,
                    source_document_id=doc.get("id"),
                    category=doc.get("category") or self._category(label),
                    source_detail_url=opportunity.source.opportunity_url,
                    version_label=doc.get("version"),
                    version_number=self._document_version(doc.get("version")),
                    addendum_number=doc.get("addendumNumber"),
                    amendment_number=doc.get("amendmentNumber"),
                    posted_at=self._datetime(doc.get("postedDate")),
                    modified_at=self._datetime(doc.get("modifiedDate")),
                    publicly_retrievable=state is AccessState.PUBLIC and doc.get("direct", True),
                    raw_metadata={
                        **self._sanitized_document_metadata(doc),
                        "authoritative_opportunity_url": str(opportunity.source.opportunity_url),
                        "intermediate": not doc.get("direct", True),
                    },
                )
            )
        return result

    @staticmethod
    def _document_version(value):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else None

    @staticmethod
    def _sanitized_document_metadata(doc):
        blocked = {"url", "token", "signature", "session", "cookie"}
        return {k: v for k, v in doc.items() if k.casefold() not in blocked}

    async def _get(self, url, params=None):
        if self._circuit_open():
            raise GeorgiaGPRError("profile circuit is open")
        safe = self._safe_url(url)
        if not safe:
            raise GeorgiaGPRError("unsafe URL")
        for attempt in range(self.profile.retries + 1):
            try:
                response = await self._transport.get(safe, params=params)
                self._last_status = response.status_code
                if response.status_code in self._transient and attempt < self.profile.retries:
                    await self._sleep(self._backoff(attempt, response.headers.get("retry-after")))
                    continue
                if response.status_code in {401, 403}:
                    raise GeorgiaGPRAccessError(GeorgiaGPRAccessState.LOGIN_REQUIRED)
                if response.status_code == 404:
                    raise GeorgiaGPRAccessError(GeorgiaGPRAccessState.UNAVAILABLE)
                response.raise_for_status()
                self._failures = 0
                self._access = GeorgiaGPRAccessState.PUBLIC
                return response
            except GeorgiaGPRAccessError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                self._failures += 1
                self._last_failure = self._now()
                self._last_error = type(exc).__name__
                self._access = GeorgiaGPRAccessState.TRANSIENT_ERROR
                if attempt >= self.profile.retries:
                    raise GeorgiaGPRError(str(exc)) from exc

    def _configuration_valid(self):
        return bool(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.profile.profile_key)
            and self.profile.supported_hostname.casefold() in PLATFORM_HOSTS
            and self._safe_url(self.profile.discovery_url)
            and self._safe_url(self.profile.detail_url("fixture"))
        )

    def _safe_url(self, value, document=False):
        try:
            parsed = urlparse(value)
            host = (parsed.hostname or "").casefold()
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or (ip and (not ip.is_global))
        ):
            return None
        allowed = set(PLATFORM_HOSTS) | {x.casefold() for x in self.profile.approved_hosts}
        if document:
            allowed |= {x.casefold() for x in self.profile.approved_document_hosts}
        return urlunparse(parsed._replace(fragment="")) if host in allowed else None

    def _canonical_url(self, value):
        p = urlparse(value)
        query = urlencode(
            [
                (k, v)
                for k, v in parse_qsl(p.query)
                if k.casefold() not in {"utm_source", "session", "token"}
            ]
        )
        return urlunparse(
            p._replace(
                netloc=(p.hostname or "").casefold().removeprefix("www."), query=query, fragment=""
            )
        )

    def _circuit_open(self):
        return bool(
            self._failures >= self.profile.circuit_threshold
            and self._last_failure
            and (self._now() - self._last_failure).total_seconds() < self.profile.cooldown
        )

    def _backoff(self, attempt, retry_after):
        if retry_after:
            try:
                return max(0, float(retry_after))
            except ValueError:
                try:
                    return max(
                        0,
                        (
                            email.utils.parsedate_to_datetime(retry_after) - self._now()
                        ).total_seconds(),
                    )
                except (TypeError, ValueError):
                    pass
        return self.profile.backoff * 2**attempt + self.profile.jitter * self._random()

    def _matches(self, item, q):
        text = f"{item.title} {item.description or ''}".casefold()
        return (
            (not q.keywords or all(k.casefold() in text for k in q.keywords))
            and (
                not q.jurisdiction
                or q.jurisdiction.casefold() in self.profile.jurisdiction.casefold()
            )
            and (not q.status or item.status.value == q.status.casefold())
            and (
                not q.project_number
                or q.project_number.casefold()
                == str(item.raw_payload.get("projectNumber", "")).casefold()
            )
            and (
                not q.solicitation_number
                or q.solicitation_number.casefold()
                == str(item.solicitation_number or "").casefold()
            )
            and (not q.agency or q.agency.casefold() in item.agency.casefold())
            and (not q.nigp or q.nigp in item.raw_payload.get("nigp_codes", []))
            and (not q.title or q.title.casefold() in item.title.casefold())
            and (
                not q.description
                or q.description.casefold() in str(item.description or "").casefold()
            )
            and (
                not q.response_type
                or q.response_type.casefold()
                == str(item.raw_payload.get("solicitation_type", "")).casefold()
            )
            and (
                not q.government_type
                or q.government_type.casefold()
                == str(item.raw_payload.get("issuing_government_type", "")).casefold()
            )
            and (not q.entity or q.entity.casefold() in item.agency.casefold())
            and self._range(item.posted_at, q.posted_from, q.posted_to)
            and self._range(item.due_at, q.due_from, q.due_to)
            and self._range(
                self._datetime(item.raw_payload.get("award_date")), q.awarded_from, q.awarded_to
            )
        )

    @staticmethod
    def _range(value, start, end):
        return not (
            (start and (not value or value.date() < start))
            or (end and (not value or value.date() > end))
        )

    @staticmethod
    def _datetime(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _status(value):
        text = str(value or "").casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if "under evaluation" in text or "evaluation" in text:
            return OpportunityStatus.CLOSED
        if "close" in text:
            return OpportunityStatus.CLOSED
        if "open" in text:
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _access_state(value):
        aliases = {
            "captcha": "captcha_required",
            "prospective_bidder_required": "vendor_profile_required",
        }
        try:
            raw = str(value or "public").casefold()
            return AccessState(aliases.get(raw, raw))
        except ValueError:
            return AccessState.UNKNOWN

    @staticmethod
    def _category(label):
        text = label.casefold()
        if "addend" in text:
            return "addendum"
        if "q&a" in text or "questions" in text:
            return "questions_and_answers"
        if "tabulation" in text:
            return "bid_tabulation"
        if "award" in text:
            return "award_notice"
        if any(x in text for x in ("rfp", "rfq", "ifb", "itb", "specification", "scope")):
            return "solicitation"
        return "other"
