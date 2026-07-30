"""Bounded, anonymous, public-read-only BidNet Direct connector.

Registration, subscriptions, bid participation, CAPTCHA, and automated-access
blocks are terminal boundaries.  The connector never accepts credentials.
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

CANONICAL_FAMILY = "bidnet-direct"
PLATFORM_HOSTS = frozenset({"bidnetdirect.com", "www.bidnetdirect.com"})


class BidNetDirectAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    REGISTRATION_REQUIRED = "registration_required"
    LOGIN_REQUIRED = "login_required"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    PREMIUM_AGGREGATION_REQUIRED = "premium_aggregation_required"
    BID_PARTICIPATION_REQUIRED = "bid_participation_required"
    ROBOTS_POLICY_BLOCKED = "robots_policy_blocked"
    AUTOMATED_ACCESS_BLOCKED = "automated_access_blocked"
    CAPTCHA_REQUIRED = "captcha_required"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    CHANGED_MARKUP = "changed_markup"
    MIGRATED = "migrated"
    TRANSIENT_ERROR = "transient_error"


class BidNetDirectError(RuntimeError):
    pass


class BidNetDirectAccessError(BidNetDirectError):
    def __init__(self, state: BidNetDirectAccessState):
        self.state = state
        super().__init__(f"BidNetDirect access boundary: {state.value}")


@dataclass(frozen=True, slots=True)
class BidNetDirectProfile:
    profile_key: str
    jurisdiction: str
    state_code: str
    government_level: str
    agency_name: str
    agency_slug: str
    agency_source_identifier: str | None = None
    regional_purchasing_group_name: str | None = None
    regional_purchasing_group_slug: str | None = None
    procurement_landing_url: str | None = None
    agency_page_url: str = ""
    discovery_url: str = ""
    supported_hostname: str = "www.bidnetdirect.com"
    detail_url_template: str = ""
    official_procurement_url: str | None = None
    profile_status: str = "configured_unverified"
    expected_access_model: str = "mixed"
    default_statuses: tuple[str, ...] = ("open",)
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


FIXTURE_PROFILE = BidNetDirectProfile(
    profile_key="fixture-regional-group",
    jurisdiction="Fixture County, Florida",
    state_code="FL",
    government_level="county",
    agency_name="Fixture County",
    agency_slug="fixture-agency",
    agency_source_identifier="fixture-001",
    regional_purchasing_group_name="Fixture Regional Purchasing Group",
    regional_purchasing_group_slug="fixture-regional-group",
    agency_page_url="https://www.bidnetdirect.com/florida/fixture-regional-group/fixture-agency",
    discovery_url="https://www.bidnetdirect.com/florida/fixture-regional-group/fixture-agency/procurement-opportunities",
    detail_url_template="https://www.bidnetdirect.com/florida/fixture-regional-group/fixture-agency/procurement-opportunities/{opportunity_id}",
    profile_status="active",
    verification_status="fixture_verified",
    approved_hosts=("www.bidnetdirect.com",),
    approved_document_hosts=("docs.fixture.gov",),
)
BIDNET_DIRECT_PROFILES = {FIXTURE_PROFILE.profile_key: FIXTURE_PROFILE}


@dataclass(frozen=True, slots=True)
class BidNetDirectQuery(ConnectorQuery):
    solicitation_number: str | None = None
    agency: str | None = None
    purchasing_group: str | None = None
    location: str | None = None
    solicitation_type: str | None = None
    status: str | None = None
    posted_from: date | None = None
    posted_to: date | None = None
    due_from: date | None = None
    due_to: date | None = None
    page_size: int | None = None
    maximum_pages: int | None = None
    maximum_results: int | None = None
    include_details: bool = True


@dataclass(frozen=True, slots=True)
class BidNetDirectHealth:
    profile_key: str
    configuration_valid: bool
    access_state: str
    consecutive_failures: int
    circuit_open: bool
    last_status_code: int | None
    last_failure_time: datetime | None
    last_success_time: datetime | None
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

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
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


def detect_access_boundary(text: str) -> BidNetDirectAccessState:
    value = re.sub(r"\s+", " ", text).casefold()
    for state, terms in (
        (
            BidNetDirectAccessState.ROBOTS_POLICY_BLOCKED,
            ("disallowed by robots", "robots policy", "robots.txt"),
        ),
        (
            BidNetDirectAccessState.AUTOMATED_ACCESS_BLOCKED,
            ("automated access blocked", "bot protection", "access denied by security"),
        ),
        (BidNetDirectAccessState.CAPTCHA_REQUIRED, ("captcha", "verify you are human")),
        (
            BidNetDirectAccessState.PREMIUM_AGGREGATION_REQUIRED,
            ("premium aggregation", "statewide package", "nationwide package"),
        ),
        (
            BidNetDirectAccessState.SUBSCRIPTION_REQUIRED,
            ("subscription required", "upgrade your plan", "payment required"),
        ),
        (
            BidNetDirectAccessState.BID_PARTICIPATION_REQUIRED,
            (
                "prospective bidder",
                "join the bidders list",
                "acknowledge addendum",
                "rsvp required",
            ),
        ),
        (
            BidNetDirectAccessState.REGISTRATION_REQUIRED,
            ("registration required", "create a supplier account", "register to download"),
        ),
        (
            BidNetDirectAccessState.LOGIN_REQUIRED,
            ("login required", "sign in to continue", "supplier login"),
        ),
        (BidNetDirectAccessState.RESTRICTED, ("access denied", "not authorized")),
        (BidNetDirectAccessState.UNAVAILABLE, ("temporarily unavailable", "scheduled maintenance")),
    ):
        if any(term in value for term in terms):
            return state
    return BidNetDirectAccessState.PUBLIC


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


class BidNetDirectConnector(BaseConnector):
    platform_family = CANONICAL_FAMILY
    jurisdictions = ("configurable",)
    public_read_only = True
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        profile: BidNetDirectProfile = FIXTURE_PROFILE,
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
        self._last_success = None
        self._last_status = None
        self._last_error = None
        self._access = BidNetDirectAccessState.UNKNOWN

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self):
        return BidNetDirectHealth(
            self.profile.profile_key,
            self._configuration_valid(),
            self._access.value,
            self._failures,
            self._circuit_open(),
            self._last_status,
            self._last_failure,
            self._last_success,
            self._last_error,
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, BidNetDirectQuery)
            else BidNetDirectQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if self.profile.profile_status in {"migrated", "legacy", "unavailable"}:
            raise BidNetDirectAccessError(
                BidNetDirectAccessState.MIGRATED
                if self.profile.profile_status != "unavailable"
                else BidNetDirectAccessState.UNAVAILABLE
            )
        if not self._configuration_valid():
            raise BidNetDirectError("invalid or unsafe BidNetDirect profile")
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
            if boundary is not BidNetDirectAccessState.PUBLIC:
                raise BidNetDirectAccessError(boundary)
            items, links = parse_page(response.text)
            if not items:
                if page == 1 and not re.search(
                    r"no (?:open )?(?:opportunities|solicitations)|data-bidnet-list",
                    response.text,
                    re.I,
                ):
                    raise BidNetDirectAccessError(BidNetDirectAccessState.CHANGED_MARKUP)
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
                elif boundary is not BidNetDirectAccessState.PUBLIC:
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
        source_id = f"{CANONICAL_FAMILY}:{self.profile.profile_key}:{raw_id}"
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
                "tenant_key": self.profile.profile_key,
                "displayed_source_id": data.get("displayedSourceId") or raw_id,
                "purchasing_group_identity": self.profile.regional_purchasing_group_slug,
                "regional_purchasing_group": self.profile.regional_purchasing_group_name,
                "agency_identity": self.profile.agency_source_identifier
                or self.profile.agency_slug,
                "source_classification": data.get("sourceClassification", "member_agency_original"),
                "discovered_url": data.get("discoveredUrl") or safe,
                "authoritative_url": safe,
                "official_agency_url": self.profile.official_procurement_url,
                "documents": docs,
                "source_provenance": provenance,
                "access_state": data.get("accessState", "public"),
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
                    addendum_number=doc.get("addendumNumber"),
                    publicly_retrievable=state is AccessState.PUBLIC and doc.get("direct", True),
                    raw_metadata={
                        **doc,
                        "authoritative_opportunity_url": str(opportunity.source.opportunity_url),
                        "intermediate": not doc.get("direct", True),
                    },
                )
            )
        return result

    async def _get(self, url, params=None):
        if self._circuit_open():
            raise BidNetDirectError("profile circuit is open")
        safe = self._safe_url(url)
        if not safe:
            raise BidNetDirectError("unsafe URL")
        for attempt in range(self.profile.retries + 1):
            try:
                response = await self._transport.get(safe, params=params)
                self._last_status = response.status_code
                if response.status_code in self._transient and attempt < self.profile.retries:
                    await self._sleep(self._backoff(attempt, response.headers.get("retry-after")))
                    continue
                if response.status_code in {401, 403}:
                    raise BidNetDirectAccessError(BidNetDirectAccessState.LOGIN_REQUIRED)
                response.raise_for_status()
                self._failures = 0
                self._last_success = self._now()
                self._access = BidNetDirectAccessState.PUBLIC
                return response
            except BidNetDirectAccessError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                self._failures += 1
                self._last_failure = self._now()
                self._last_error = type(exc).__name__
                self._access = BidNetDirectAccessState.TRANSIENT_ERROR
                if attempt >= self.profile.retries:
                    raise BidNetDirectError(str(exc)) from exc

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

    def validate_redirect(self, source_url: str, destination_url: str, *, document=False):
        """Revalidate both sides of every redirect; cross-hosts require explicit approval."""
        source = self._safe_url(source_url, document=document)
        destination = self._safe_url(destination_url, document=document)
        if not source or not destination:
            return None
        source_host = (urlparse(source).hostname or "").casefold()
        destination_host = (urlparse(destination).hostname or "").casefold()
        if source_host != destination_host and destination_host not in {
            host.casefold() for host in self.profile.approved_document_hosts
        }:
            return None
        return destination

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
                not q.solicitation_number
                or q.solicitation_number.casefold() in (item.solicitation_number or "").casefold()
            )
            and (not q.agency or q.agency.casefold() in item.agency.casefold())
            and (
                not q.purchasing_group
                or q.purchasing_group.casefold()
                in (self.profile.regional_purchasing_group_name or "").casefold()
            )
            and (
                not q.location
                or q.location.casefold() in str(item.raw_payload.get("location", "")).casefold()
            )
            and (
                not q.solicitation_type
                or q.solicitation_type.casefold()
                in str(item.raw_payload.get("solicitationType", "")).casefold()
            )
            and self._range(item.posted_at, q.posted_from, q.posted_to)
            and self._range(item.due_at, q.due_from, q.due_to)
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
        if "close" in text:
            return OpportunityStatus.CLOSED
        if "open" in text:
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _access_state(value):
        try:
            return AccessState(str(value or "public").casefold())
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
