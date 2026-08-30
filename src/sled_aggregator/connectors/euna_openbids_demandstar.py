"""Anonymous Euna OpenBids (formerly DemandStar) platform-family connector.

DemandStar URLs and branding remain common after the Euna OpenBids rename.  This
family is deliberately separate from Euna Bonfire and IonWave; branding/host
changes must not alter identities already collected under the canonical family.
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

CANONICAL_FAMILY = "euna/openbids-demandstar"
PLATFORM_HOSTS = frozenset(
    {"demandstar.com", "www.demandstar.com", "network.demandstar.com", "api.demandstar.com"}
)


class DemandStarAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    REGISTRATION_REQUIRED = "registration_required"
    LOGIN_REQUIRED = "login_required"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    PAYMENT_REQUIRED = "payment_required"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    CHANGED_MARKUP = "changed_markup"
    MIGRATED = "migrated"
    TRANSIENT_ERROR = "transient_error"


class DemandStarError(RuntimeError):
    pass


class DemandStarAccessError(DemandStarError):
    def __init__(self, state: DemandStarAccessState):
        self.state = state
        super().__init__(f"OpenBids/DemandStar access boundary: {state.value}")


@dataclass(frozen=True, slots=True)
class DemandStarProfile:
    profile_key: str
    jurisdiction: str
    state_code: str
    government_level: str
    agency_name: str
    agency_slug: str
    organization_id: str | None = None
    legacy_member_id: int | None = None
    api_base_url: str | None = None
    public_planholders: bool = False
    public_legal: bool = False
    procurement_landing_url: str | None = None
    agency_page_url: str = ""
    discovery_url: str = ""
    supported_hostname: str = "www.demandstar.com"
    detail_url_template: str = ""
    official_procurement_url: str | None = None
    profile_status: str = "configured_unverified"
    expected_access_model: str = "mixed"
    timezone: str = "UTC"
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


FIXTURE_PROFILE = DemandStarProfile(
    profile_key="fixture-county",
    jurisdiction="Fixture County, Florida",
    state_code="FL",
    government_level="county",
    agency_name="Fixture County",
    agency_slug="fixture-county",
    agency_page_url="https://www.demandstar.com/app/agencies/fl/fixture-county",
    discovery_url="https://www.demandstar.com/app/agencies/fl/fixture-county/procurement-opportunities",
    detail_url_template="https://www.demandstar.com/app/agencies/fl/fixture-county/procurement-opportunities/{opportunity_id}",
    profile_status="active",
    verification_status="fixture_verified",
    approved_hosts=("www.demandstar.com",),
    approved_document_hosts=("docs.fixture.gov",),
)
BUTLER_COUNTY = DemandStarProfile(
    profile_key="ks-butler-county",
    jurisdiction="Butler County, Kansas",
    state_code="KS",
    government_level="county",
    agency_name="Butler County",
    agency_slug="butler-county",
    organization_id="b3383e3f-b020-470a-9f48-9e2d4a270e56",
    api_base_url="https://api.demandstar.com/contents/agency",
    public_legal=True,
    agency_page_url="https://www.demandstar.com/app/agencies/kansas/butler-county/procurement-opportunities/b3383e3f-b020-470a-9f48-9e2d4a270e56/",
    discovery_url="https://www.demandstar.com/app/agencies/kansas/butler-county/procurement-opportunities/b3383e3f-b020-470a-9f48-9e2d4a270e56/",
    detail_url_template="https://www.demandstar.com/app/limited/bids/{opportunity_id}/details",
    official_procurement_url="https://www.bucoks.gov/139/Purchasing-Division",
    profile_status="active",
    verification_status="live_har_validated",
    verification_timestamp=datetime(2026, 8, 16, tzinfo=UTC),
    verification_notes="Anonymous agency search, summary, document metadata, commodities, and legal data observed.",
    approved_hosts=("www.demandstar.com", "api.demandstar.com"),
)
LYNN_HAVEN = DemandStarProfile(
    profile_key="fl-lynn-haven",
    jurisdiction="Lynn Haven, Florida",
    state_code="FL",
    government_level="city",
    agency_name="City of Lynn Haven",
    agency_slug="city-of-lynn-haven",
    organization_id="1d8acbbf-7cb5-44a9-962e-62cc58e39a7b",
    api_base_url="https://api.demandstar.com/contents/agency",
    public_planholders=True,
    agency_page_url="https://www.demandstar.com/app/agencies/florida/city-of-lynn-haven/procurement-opportunities/1d8acbbf-7cb5-44a9-962e-62cc58e39a7b/",
    discovery_url="https://www.demandstar.com/app/agencies/florida/city-of-lynn-haven/procurement-opportunities/1d8acbbf-7cb5-44a9-962e-62cc58e39a7b/",
    detail_url_template="https://www.demandstar.com/app/limited/bids/{opportunity_id}/details",
    official_procurement_url="https://www.cityoflynnhaven.gov/bids.aspx",
    profile_status="active",
    verification_status="live_har_validated",
    verification_timestamp=datetime(2026, 8, 16, tzinfo=UTC),
    verification_notes="Anonymous agency search, details, document metadata, commodities, and planholders observed.",
    approved_hosts=("www.demandstar.com", "api.demandstar.com"),
)
WILL_COUNTY = DemandStarProfile(
    profile_key="il-will-county",
    jurisdiction="Will County, Illinois",
    state_code="IL",
    government_level="county",
    agency_name="Will County",
    agency_slug="will-county",
    organization_id="34dea608-18ea-4dae-ab75-e117314d8f28",
    legacy_member_id=122067,
    api_base_url="https://api.demandstar.com/contents/agency",
    public_planholders=True,
    public_legal=True,
    agency_page_url="https://www.demandstar.com/app/agencies/illinois/will-county/procurement-opportunities/34dea608-18ea-4dae-ab75-e117314d8f28",
    discovery_url="https://www.demandstar.com/app/agencies/illinois/will-county/procurement-opportunities/34dea608-18ea-4dae-ab75-e117314d8f28",
    detail_url_template="https://www.demandstar.com/app/limited/bids/{opportunity_id}/details",
    official_procurement_url="https://willcounty.gov/County-Offices/Administration/Purchasing/Current-Bids",
    profile_status="active",
    verification_status="live_public_verified",
    verification_timestamp=datetime(2026, 8, 30, tzinfo=UTC),
    verification_notes="Legacy member 122067 redirects to the modern UUID tenant; anonymous agency API and two details observed.",
    timezone="America/Chicago",
    approved_hosts=("www.demandstar.com", "api.demandstar.com"),
)
RAMSEY_COUNTY = DemandStarProfile(
    profile_key="mn-ramsey-county",
    jurisdiction="Ramsey County, Minnesota",
    state_code="MN",
    government_level="county",
    agency_name="Ramsey County",
    agency_slug="ramsey-county",
    organization_id="98cdb2f5-ed67-485d-8b2e-291e644403e5",
    legacy_member_id=686378,
    api_base_url="https://api.demandstar.com/contents/agency",
    public_planholders=True,
    public_legal=True,
    agency_page_url="https://www.demandstar.com/app/agencies/minnesota/ramsey-county/procurement-opportunities/98cdb2f5-ed67-485d-8b2e-291e644403e5/",
    discovery_url="https://www.demandstar.com/app/agencies/minnesota/ramsey-county/procurement-opportunities/98cdb2f5-ed67-485d-8b2e-291e644403e5/",
    detail_url_template="https://www.demandstar.com/app/limited/bids/{opportunity_id}/details",
    official_procurement_url="https://www.ramseycountymn.gov/businesses/doing-business-ramsey-county/contracts-vendors/how-contract-ramsey-county",
    profile_status="active",
    verification_status="live_public_verified",
    verification_timestamp=datetime(2026, 8, 30, tzinfo=UTC),
    verification_notes="Official member 686378 and supplied modern UUID resolve to the same anonymous agency contract; two details observed.",
    timezone="America/Chicago",
    approved_hosts=("www.demandstar.com", "api.demandstar.com"),
)
DEMANDSTAR_PROFILES = {
    profile.profile_key: profile
    for profile in (BUTLER_COUNTY, LYNN_HAVEN, WILL_COUNTY, RAMSEY_COUNTY, FIXTURE_PROFILE)
}


@dataclass(frozen=True, slots=True)
class DemandStarQuery(ConnectorQuery):
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
class DemandStarHealth:
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
    async def post(self, url: str, *, json: Mapping[str, Any]) -> httpx.Response: ...
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


def detect_access_boundary(text: str) -> DemandStarAccessState:
    value = re.sub(r"\s+", " ", text).casefold()
    for state, terms in (
        (DemandStarAccessState.PAYMENT_REQUIRED, ("payment required", "document fee", "checkout")),
        (
            DemandStarAccessState.SUBSCRIPTION_REQUIRED,
            ("subscription required", "purchase a subscription", "paid membership"),
        ),
        (
            DemandStarAccessState.REGISTRATION_REQUIRED,
            ("registration required", "create a supplier account", "register to download"),
        ),
        (
            DemandStarAccessState.LOGIN_REQUIRED,
            ("login required", "sign in to continue", "supplier login"),
        ),
        (DemandStarAccessState.RESTRICTED, ("access denied", "not authorized")),
        (DemandStarAccessState.UNAVAILABLE, ("temporarily unavailable", "scheduled maintenance")),
    ):
        if any(term in value for term in terms):
            return state
    return DemandStarAccessState.PUBLIC


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


class EunaOpenBidsDemandStarConnector(BaseConnector):
    platform_family = CANONICAL_FAMILY
    jurisdictions = ("configurable",)
    public_read_only = True
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        profile: DemandStarProfile = FIXTURE_PROFILE,
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
        self._access = DemandStarAccessState.UNKNOWN

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self):
        return DemandStarHealth(
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
            if isinstance(query, DemandStarQuery)
            else DemandStarQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if self.profile.profile_status in {"migrated", "legacy", "unavailable"}:
            raise DemandStarAccessError(
                DemandStarAccessState.MIGRATED
                if self.profile.profile_status != "unavailable"
                else DemandStarAccessState.UNAVAILABLE
            )
        if not self._configuration_valid():
            raise DemandStarError("invalid or unsafe DemandStar profile")
        if self.profile.api_base_url and self.profile.organization_id:
            for item in await self._discover_api(q):
                yield item
            return
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
            if boundary is not DemandStarAccessState.PUBLIC:
                raise DemandStarAccessError(boundary)
            items, links = parse_page(response.text)
            if not items:
                if page == 1 and not re.search(
                    r"no (?:open )?(?:opportunities|solicitations)|data-openbids-list",
                    response.text,
                    re.I,
                ):
                    raise DemandStarAccessError(DemandStarAccessState.CHANGED_MARKUP)
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
                elif boundary is not DemandStarAccessState.PUBLIC:
                    item.raw_payload["detail_access_state"] = boundary.value
                else:
                    item.raw_payload["detail_access_state"] = "changed_markup"
            yield item
            maximum -= 1
            if maximum <= 0:
                break

    async def _discover_api(self, query: DemandStarQuery) -> list[RawOpportunity]:
        """Replay only the anonymous agency-scoped API contracts observed in reviewed HARs."""
        base = self.profile.api_base_url or ""
        response = await self._get(
            f"{base}/search", params={"id": self.profile.organization_id or ""}
        )
        payload = self._json_payload(response)
        rows = payload.get("result", [])
        if not isinstance(rows, list):
            raise DemandStarAccessError(DemandStarAccessState.CHANGED_MARKUP)
        maximum = min(
            query.maximum_results or query.limit,
            self.profile.maximum_results,
            query.limit,
        )
        result: list[RawOpportunity] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            bid_id = str(row.get("bidId") or "").strip()
            title = str(row.get("bidName") or "").strip()
            if not bid_id or not title:
                continue
            data: dict[str, Any] = {
                "id": bid_id,
                "title": title,
                "agency": row.get("agency") or self.profile.agency_name,
                "solicitationNumber": row.get("bidIdentifier"),
                "status": row.get("status") or row.get("statusType"),
                "postedDate": row.get("broadCastDate"),
                "dueDate": row.get("dueDate"),
                "documents": [],
                "openbids_search": row,
            }
            if query.include_details:
                summary = self._json_payload(
                    await self._post(f"{base}/summary", {"bidId": int(bid_id)})
                ).get("result", {})
                documents = self._json_payload(
                    await self._post(f"{base}/documents", {"bidId": int(bid_id)})
                ).get("result", [])
                commodities = self._json_payload(
                    await self._post(
                        f"{base}/commodityByType", {"bidId": int(bid_id), "type": "Bid"}
                    )
                ).get("result", [])
                planholders: list[dict[str, Any]] = []
                legal: dict[str, Any] = {}
                if self.profile.public_planholders:
                    value = self._json_payload(
                        await self._post(f"{base}/planholders", {"bidId": int(bid_id)})
                    ).get("result", [])
                    if isinstance(value, list):
                        planholders = [x for x in value if isinstance(x, dict)]
                if self.profile.public_legal:
                    value = self._json_payload(
                        await self._post(f"{base}/legal", {"bidId": int(bid_id)})
                    ).get("result", {})
                    if isinstance(value, dict):
                        legal = value
                if isinstance(summary, dict):
                    data.update(
                        {
                            "title": summary.get("bidName") or data["title"],
                            "agency": summary.get("agencyName") or data["agency"],
                            "solicitationNumber": summary.get("bidNumber")
                            or summary.get("bidIdentifier")
                            or data["solicitationNumber"],
                            "description": summary.get("scopeOfWork"),
                            "status": summary.get("bidExternalStatus")
                            or summary.get("bidStatusText")
                            or data["status"],
                            "postedDate": summary.get("broadcastDate") or data["postedDate"],
                            "dueDate": summary.get("dueDate") or data["dueDate"],
                            "questionDate": summary.get("questionDate"),
                            "opportunityType": summary.get("bidTypeDescription")
                            or summary.get("bidType"),
                            "department": summary.get("departmentName"),
                            "buyerName": summary.get("bidWriter"),
                            "timezone": summary.get("tzfn") or summary.get("tzn"),
                            "statusNarrative": summary.get("bidStatusText"),
                            "openbids_summary": summary,
                        }
                    )
                if isinstance(documents, list):
                    data["documents"] = [self._api_document(x) for x in documents if isinstance(x, dict)]
                if isinstance(commodities, list):
                    data["categories"] = [
                        str(x.get("commodityDescription") or x.get("commodityCategory") or "").strip()
                        for x in commodities
                        if isinstance(x, dict)
                        and (x.get("commodityDescription") or x.get("commodityCategory"))
                    ]
                data["public_planholders"] = planholders
                data["openbids_legal"] = legal
                if legal:
                    data["buyer_contact"] = {
                        "name": " ".join(
                            str(legal.get(key) or "").strip()
                            for key in ("firstName", "lastName")
                        ).strip()
                        or data.get("buyerName"),
                        "title": legal.get("jobTitle"),
                        "phone": legal.get("phoneNumber") or legal.get("memberPhoneNumber"),
                    }
            item = self._normalize(data, bid_id)
            if not self._matches(item, query):
                continue
            result.append(item)
            if len(result) >= maximum:
                break
        return result

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise DemandStarAccessError(DemandStarAccessState.CHANGED_MARKUP) from exc
        if not isinstance(value, dict):
            raise DemandStarAccessError(DemandStarAccessState.CHANGED_MARKUP)
        return value

    @staticmethod
    def _api_document(value: Mapping[str, Any]) -> dict[str, Any]:
        path = str(value.get("path") or "").strip()
        return {
            "id": str(value.get("bidDocID") or "") or None,
            "label": value.get("fileName") or value.get("originalFileName") or "Document",
            "filename": value.get("fileName") or value.get("originalFileName") or "document",
            "url": path or None,
            "mediaType": str(value.get("mimeType") or "").strip() or None,
            "category": EunaOpenBidsDemandStarConnector._category(str(value.get("type") or "")),
            "accessState": "public" if path else "registration_required",
            "direct": bool(path),
            "modifiedDate": value.get("modifiedDate"),
            "fileSize": value.get("fileSize"),
            "upstream": dict(value),
        }

    def _normalize(self, data, raw_id):
        url = str(data.get("url") or self.profile.detail_url(raw_id))
        safe = self._safe_url(url) or self.profile.detail_url(raw_id)
        docs = data.get("documents") if isinstance(data.get("documents"), list) else []
        source_id = f"{CANONICAL_FAMILY}:{self.profile.profile_key}:{raw_id}"
        posted = self._datetime(data.get("postedDate"), self.profile.timezone)
        due = self._datetime(data.get("dueDate"), self.profile.timezone)
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
        return await self._request("GET", url, params=params)

    async def _post(self, url: str, payload: Mapping[str, Any]):
        return await self._request("POST", url, payload=payload)

    async def _request(self, method: str, url: str, params=None, payload=None):
        if self._circuit_open():
            raise DemandStarError("profile circuit is open")
        safe = self._safe_url(url)
        if not safe:
            raise DemandStarError("unsafe URL")
        for attempt in range(self.profile.retries + 1):
            try:
                response = (
                    await self._transport.get(safe, params=params)
                    if method == "GET"
                    else await self._transport.post(safe, json=payload or {})
                )
                self._last_status = response.status_code
                if response.status_code in self._transient and attempt < self.profile.retries:
                    await self._sleep(self._backoff(attempt, response.headers.get("retry-after")))
                    continue
                if response.status_code in {401, 403}:
                    raise DemandStarAccessError(DemandStarAccessState.LOGIN_REQUIRED)
                response.raise_for_status()
                self._failures = 0
                self._access = DemandStarAccessState.PUBLIC
                return response
            except DemandStarAccessError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                self._failures += 1
                self._last_failure = self._now()
                self._last_error = type(exc).__name__
                self._access = DemandStarAccessState.TRANSIENT_ERROR
                if attempt >= self.profile.retries:
                    raise DemandStarError(str(exc)) from exc

    def _configuration_valid(self):
        return bool(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.profile.profile_key)
            and self.profile.supported_hostname.casefold() in PLATFORM_HOSTS
            and self._safe_url(self.profile.discovery_url)
            and self._safe_url(self.profile.detail_url("fixture"))
            and (not self.profile.api_base_url or self._safe_url(self.profile.api_base_url))
        )

    def _safe_url(self, value, document=False):
        try:
            parsed = urlparse(value)
            host = (parsed.hostname or "").casefold()
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if parsed.scheme != "https" or not host or (ip and (not ip.is_global)):
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
    def _datetime(value, timezone="UTC"):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo:
                return parsed
            return parsed.replace(tzinfo=ZoneInfo(timezone))
        except (ValueError, ZoneInfoNotFoundError):
            return None

    @staticmethod
    def _status(value):
        text = str(value or "").casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if "close" in text or "evaluation" in text:
            return OpportunityStatus.CLOSED
        if "open" in text or "active" in text:
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
