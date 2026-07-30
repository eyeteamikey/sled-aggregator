"""Configurable anonymous Euna Procurement/IonWave connector.

Only public GET routes configured on :class:`IonWavePortal` are used.  The
connector discovers attachment metadata; the document pipeline owns retrieval,
parsing, OCR, and structured extraction.
"""

import asyncio
import email.utils
import hashlib
import ipaddress
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef


class IonWaveAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    CAPTCHA = "captcha"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"
    JAVASCRIPT_ONLY = "javascript_only"
    UNSUPPORTED_SEARCH = "unsupported_search"
    TRANSIENT_ERROR = "transient_error"
    CHANGED_MARKUP = "changed_markup"
    MIGRATED = "migrated"
    BLOCKED = "blocked"


class IonWaveError(RuntimeError):
    pass


class IonWaveAccessError(IonWaveError):
    def __init__(self, state: IonWaveAccessState) -> None:
        self.state = state
        super().__init__(f"IonWave public access ended at {state.value}")


class IonWaveAvailabilityError(IonWaveError):
    pass


_ORGANIZATION_TYPES = frozenset(
    {
        "city",
        "town",
        "county",
        "state agency",
        "university",
        "university system",
        "university/state agency",
        "university/state institution",
        "community college",
        "school district",
        "transportation agency",
        "state transportation agency",
        "utility",
        "special district",
        "cooperative",
        "other public entity",
    }
)

IONWAVE_VARIANTS = frozenset(
    {
        "ionwave_classic_aspx",
        "ionwave_modern",
        "euna_branded_ionwave",
        "public_detail_only",
        "public_list_and_detail",
        "registration_required",
        "agency_upstream_fallback",
        "migrated_to_opengov",
        "migrated_to_bonfire",
        "legacy_archive_only",
        "configured_unknown",
    }
)


@dataclass(frozen=True, slots=True)
class IonWavePortal:
    portal_key: str
    tenant_slug: str
    display_name: str
    jurisdiction: str
    state_code: str
    organization_type: str
    owning_organization: str
    portal_hostname: str = ""
    public_portal_url: str | None = None
    sourcing_events_url: str | None = None
    current_events_url: str | None = None
    public_detail_template: str | None = None
    awarded_events_url: str | None = None
    closed_events_url: str | None = None
    login_url: str | None = None
    registration_url: str | None = None
    authoritative_agency_procurement_url: str | None = None
    platform_variant: str = "ionwave_classic_aspx"
    branding_variant: str = "ionwave"
    default_timezone: str = "UTC"
    source_type: str = "1"
    parser_strategy: str = "semantic-aspx"
    discovery_strategy: str = "bounded-get-only"
    pagination_strategy: str = "bounded-query-or-initial-list"
    keyword_search_support: str = "local"
    detail_enrichment_support: bool = True
    document_discovery_support: bool = True
    addenda_support: bool = True
    q_and_a_support: bool = True
    award_support: bool = True
    approved_hosts: tuple[str, ...] = ()
    approved_attachment_hosts: tuple[str, ...] = ()
    page_size: int = 25
    maximum_pages: int = 4
    maximum_results: int = 100
    request_timeout: float = 30
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    retry_jitter_seconds: float = 0.25
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown: float = 60
    enabled: bool = True
    verification_status: str = "configured_unverified"
    access_notes: str = "Access is classified per page and document."
    migration_notes: str = ""
    migration_target: str | None = None
    migration_cutoff: str | None = None
    production: bool = True

    @property
    def portal_url(self) -> str:
        return self.public_portal_url or f"https://{self.portal_hostname}/"

    @property
    def embed_list_url(self) -> str:
        return (
            self.sourcing_events_url
            or self.current_events_url
            or f"https://{self.portal_hostname}/SourcingEvents.aspx?SourceType={self.source_type}"
        )

    def opportunity_url(self, bid_id: str) -> str:
        template = (
            self.public_detail_template
            or f"https://{self.portal_hostname}/PublicDetail.aspx?bidID={{BID_ID}}&SourceType={self.source_type}"
        )
        return template.replace("{BID_ID}", bid_id)


def _portal(
    key: str,
    tenant: str,
    name: str,
    jurisdiction: str,
    state: str,
    entity: str,
    organization: str,
    **kwargs: Any,
) -> IonWavePortal:
    host = f"{tenant}.ionwave.net"
    approved_hosts = kwargs.pop("approved_hosts", (host,))
    return IonWavePortal(
        key,
        tenant,
        name,
        jurisdiction,
        state,
        entity,
        organization,
        portal_hostname=host,
        approved_hosts=approved_hosts,
        **kwargs,
    )


PISD = _portal(
    "pisd",
    "pisd",
    "Plano ISD IonWave Procurement Portal",
    "Plano, Texas",
    "TX",
    "school district",
    "Plano Independent School District",
    authoritative_agency_procurement_url="https://www.pisd.edu/departments-66/purchasing-services/current-proposalsbids",
    default_timezone="America/Chicago",
    verification_status="fixture_verified",
    platform_variant="public_list_and_detail",
)
PROSPER_TX = _portal(
    "prospertx",
    "prospertx",
    "Town of Prosper IonWave Procurement Portal",
    "Prosper, Texas",
    "TX",
    "town",
    "Town of Prosper",
    authoritative_agency_procurement_url="https://www.prospertx.gov/325/Bid-Opportunities",
    default_timezone="America/Chicago",
    verification_status="fixture_verified",
    platform_variant="public_list_and_detail",
)
CLEMSON = _portal(
    "clemson",
    "clemson",
    "Clemson University IonWave Bidding Portal",
    "South Carolina",
    "SC",
    "university/state agency",
    "Clemson University",
    default_timezone="America/New_York",
    verification_status="configured_unverified",
)
UM_SYSTEM = _portal(
    "umsystembids",
    "umsystembids",
    "University of Missouri System Bid Portal",
    "Missouri",
    "MO",
    "university system",
    "University of Missouri System",
    default_timezone="America/Chicago",
    verification_status="configured_unverified",
)
CFB_PURCHASING = _portal(
    "cfbpurchasing",
    "cfbpurchasing",
    "Carrollton-Farmers Branch ISD Euna/IonWave Portal",
    "Carrollton-Farmers Branch, Texas",
    "TX",
    "school district",
    "Carrollton-Farmers Branch ISD",
    login_url="https://cfbpurchasing.ionwave.net/Login.aspx",
    registration_url="https://cfbpurchasing.ionwave.net/VendorRegistration/PreliminaryInfo.aspx",
    authoritative_agency_procurement_url="https://www.cfbisd.edu/departments/purchasing/procurement-opportunities",
    platform_variant="registration_required",
    branding_variant="euna_procurement",
    verification_status="registration_required",
    default_timezone="America/Chicago",
)
MT_SOURCE = _portal(
    "mtsource",
    "mtsource",
    "MTSU MT$ource IonWave Portal",
    "Tennessee",
    "TN",
    "university/state institution",
    "Middle Tennessee State University",
    login_url="https://mtsource.ionwave.net/Login.aspx",
    authoritative_agency_procurement_url="https://procurement.mtsu.edu/guidelines/",
    platform_variant="agency_upstream_fallback",
    verification_status="public_metadata_only",
    default_timezone="America/Chicago",
)
IOWA_DOT = _portal(
    "iowadotebid",
    "iowadotebid",
    "Iowa DOT IonWave Bid Portal",
    "Iowa",
    "IA",
    "state transportation agency",
    "Iowa Department of Transportation",
    authoritative_agency_procurement_url="https://bidopportunities.iowa.gov/",
    platform_variant="legacy_archive_only",
    verification_status="legacy_archive",
    migration_notes="State public bid site is authoritative; IonWave is historical/partially verified.",
    default_timezone="America/Chicago",
)
FIXTURE_ONLY = _portal(
    "fixture-only",
    "fixture-public",
    "Fixture-only configurable IonWave tenant",
    "Test Territory",
    "TT",
    "other public entity",
    "Fixture Public Entity",
    current_events_url="https://fixture-public.ionwave.net/CurrentSourcingEvents.aspx",
    production=False,
    verification_status="fixture_verified",
    platform_variant="ionwave_modern",
)
IONWAVE_PORTALS = {
    p.portal_key: p
    for p in (
        PISD,
        PROSPER_TX,
        CLEMSON,
        UM_SYSTEM,
        CFB_PURCHASING,
        MT_SOURCE,
        IOWA_DOT,
        FIXTURE_ONLY,
    )
}


@dataclass(frozen=True, slots=True)
class IonWaveQuery(ConnectorQuery):
    keyword: str | None = None
    bid_id: str | None = None
    solicitation_number: str | None = None
    statuses: tuple[str, ...] = ()
    department: str | None = None
    released_from: date | None = None
    released_to: date | None = None
    due_from: date | None = None
    due_to: date | None = None
    include_closed: bool = False
    include_awarded: bool = False
    include_details: bool = True
    include_documents: bool = True
    page_size: int | None = None
    maximum_pages: int | None = None
    maximum_results: int | None = None


class IonWaveTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class IonWaveHealth:
    available: bool
    access_state: IonWaveAccessState
    tenant: str
    platform: str
    platform_variant: str
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    last_error_class: str | None
    discovery_supported: bool
    keyword_search_supported: bool
    detail_supported: bool
    document_discovery_supported: bool
    contracts_supported: bool
    parser_strategy: str
    configuration_valid: bool
    branding_variant: str
    verification_status: str
    filtering: str
    upstream_fallback_available: bool
    addenda_supported: bool
    q_and_a_supported: bool
    awards_supported: bool
    jurisdiction: str = ""
    entity_type: str = ""
    public_download_observed: bool = False
    registration_required_download_observed: bool = False
    upstream_fallback: str | None = None
    migration_target: str | None = None
    legacy_archive: bool = False
    changed_markup: bool = False
    login_observed: bool = False
    captcha_observed: bool = False


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


class _IonWaveHTMLParser(HTMLParser):
    """Parse fixture-backed semantic HTML without tenant-specific selectors."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.zero_results = False
        self._record: dict[str, Any] | None = None
        self._depth = 0
        self._field: str | None = None
        self._section: str | None = None
        self._href: str | None = None
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        marker = (
            values.get("data-bid-id")
            or values.get("data-ionwave-bid")
            or values.get("data-opportunity-id")
        )
        if marker is not None and self._record is None:
            self._record, self._depth = {"bid_id": marker}, 1
        elif self._record is not None:
            self._depth += 1
        self._field = (values.get("data-field") or "").replace("-", "_") or None
        self._section = values.get("data-section") or self._section
        self._attrs, self._text = values, []
        if tag == "a":
            self._href = values.get("href")

    def handle_data(self, data: str) -> None:
        self._text.append(data)
        if re.search(
            r"\bno (?:sourcing )?(?:events|opportunities|results) (?:found|available)\b", data, re.I
        ):
            self.zero_results = True

    def handle_endtag(self, tag: str) -> None:
        text = _clean("".join(self._text))
        if self._record is not None:
            if self._field and text:
                if self._field in {"category", "contact", "notice", "question", "award"}:
                    self._record.setdefault(self._field + "s", []).append(text)
                else:
                    self._record[self._field] = text
            if tag == "a" and self._href:
                link = {
                    "title": text or "Document",
                    "url": self._href,
                    **{
                        k[5:].replace("-", "_"): v
                        for k, v in self._attrs.items()
                        if k.startswith("data-")
                    },
                }
                if self._section in {
                    "documents",
                    "attachments",
                    "addenda",
                    "notices",
                    "awards",
                } or re.search(
                    r"\.(?:pdf|docx?|xlsx?|csv|zip)\b|addend|amend|notice|q\s*&\s*a|award|tabulation|\b(?:rfp|rfq|ifb|itb)\b",
                    f"{text} {self._href}",
                    re.I,
                ):
                    self._record.setdefault("documents", []).append(link)
                elif self._field in {"upstream_url", "opportunity_url"}:
                    self._record[self._field] = self._href
                    if self._field == "opportunity_url" and text and not self._record.get("title"):
                        self._record["title"] = text
                elif not self._record.get("opportunity_url"):
                    self._record["opportunity_url"] = self._href
                self._href = None
            self._depth -= 1
            if self._depth == 0:
                self.records.append(self._record)
                self._record = None
        self._field, self._text = None, []
        if tag == "section":
            self._section = None


class IonWaveEventListParser(_IonWaveHTMLParser):
    """Semantic parser for bounded public event lists."""


class IonWavePublicDetailParser(_IonWaveHTMLParser):
    """Semantic parser for direct ``PublicDetail.aspx`` pages."""


class IonWaveDocumentParser(_IonWaveHTMLParser):
    """Discovers link metadata only; it never downloads documents."""


class IonWaveAddendaParser(IonWaveDocumentParser):
    pass


class IonWaveQuestionsParser(IonWaveDocumentParser):
    pass


class IonWaveAwardParser(IonWaveDocumentParser):
    pass


class IonWaveUpstreamParser(_IonWaveHTMLParser):
    """Parser for explicitly configured authoritative agency fixture pages."""


class IonWaveAccessClassifier:
    """Names the independently testable access-classification concern."""


class IonWaveMigrationClassifier:
    TARGETS = {"opengov": "opengov/procurement", "bonfire": "euna/bonfire"}

    @classmethod
    def classify(cls, text: str) -> str | None:
        folded = text.casefold()
        return next((target for marker, target in cls.TARGETS.items() if marker in folded), None)


class IonWaveNormalizer:
    """Names the canonical identity and URL normalization concern."""


class EunaIonWaveConnector(BaseConnector):
    platform_family = "euna/ionwave"
    jurisdictions = tuple(dict.fromkeys(p.jurisdiction for p in IONWAVE_PORTALS.values()))
    _transient_statuses = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
    _transient_query = frozenset(
        {
            "timestamp",
            "time",
            "sessionid",
            "_",
            "sort",
            "page",
            "pagesize",
            "row",
            "rowindex",
            "__viewstate",
            "__eventvalidation",
            "__eventtarget",
        }
    )

    def __init__(
        self,
        portal: IonWavePortal = PISD,
        *,
        transport: IonWaveTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.portal, self._sleep, self._random, self._now = portal, sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=portal.request_timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1 (public read-only)"},
        )
        self._owns_transport = transport is None
        self._failures = 0
        self._last_status = None
        self._last_failure = self._last_success = None
        self._last_error_class = None
        self._access = IonWaveAccessState.PUBLIC

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> IonWaveHealth:
        opened = self._circuit_open()
        return IonWaveHealth(
            not opened and self._failures == 0,
            self._access,
            self.portal.portal_key,
            self.platform_family,
            self.portal.platform_variant,
            opened,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._last_error_class,
            self.portal.enabled,
            self.portal.keyword_search_support != "unsupported",
            True,
            True,
            bool(self.portal.authoritative_agency_procurement_url),
            self.portal.parser_strategy,
            self._configuration_valid(),
            self.portal.branding_variant,
            self.portal.verification_status,
            self.portal.keyword_search_support,
            bool(self.portal.authoritative_agency_procurement_url),
            self.portal.addenda_support,
            self.portal.q_and_a_support,
            self.portal.award_support,
            jurisdiction=self.portal.jurisdiction,
            entity_type=self.portal.organization_type,
            public_download_observed=self.portal.verification_status == "live_public_verified",
            registration_required_download_observed=self.portal.verification_status
            == "registration_required",
            upstream_fallback=self.portal.authoritative_agency_procurement_url,
            migration_target=self.portal.migration_target,
            legacy_archive=self.portal.platform_variant == "legacy_archive_only",
            changed_markup=self._access == IonWaveAccessState.CHANGED_MARKUP,
            login_observed=self._access == IonWaveAccessState.LOGIN_REQUIRED,
            captcha_observed=self._access == IonWaveAccessState.CAPTCHA,
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, IonWaveQuery)
            else IonWaveQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if q.jurisdiction and q.jurisdiction.casefold() not in {
            self.portal.jurisdiction.casefold(),
            self.portal.state_code.casefold(),
        }:
            return
        if not self.portal.enabled or not self._configuration_valid():
            raise IonWaveAccessError(IonWaveAccessState.UNSUPPORTED_SEARCH)
        if self._circuit_open():
            raise IonWaveAvailabilityError(f"{self.portal.portal_key} circuit is open")
        if (q.keyword or q.keywords) and self.portal.keyword_search_support == "unsupported":
            raise IonWaveAccessError(IonWaveAccessState.UNSUPPORTED_SEARCH)
        page_size = min(q.page_size or self.portal.page_size, 100)
        max_pages = min(q.maximum_pages or self.portal.maximum_pages, 20)
        maximum = min(q.limit, q.maximum_results or self.portal.maximum_results, 1000)
        records: dict[str, dict[str, Any]] = {}
        fingerprints: set[str] = set()
        try:
            for page in range(1, max_pages + 1):
                parsed, zero = self._parse(
                    await self._request(
                        self.portal.embed_list_url, {"page": page, "pageSize": page_size}
                    )
                )
                if not parsed:
                    if zero or page > 1:
                        break
                    raise IonWaveAccessError(IonWaveAccessState.MALFORMED)
                fingerprint = hashlib.sha256(repr(parsed).encode()).hexdigest()
                if fingerprint in fingerprints:
                    break
                fingerprints.add(fingerprint)
                for record in parsed:
                    identity = self._identity(record)
                    if identity:
                        records[identity] = self._merge(records.get(identity, {}), record)
                if len(parsed) < page_size:
                    break
            for identity in sorted(records):
                record = records[identity]
                if not self._matches(record, q):
                    continue
                if q.include_details:
                    detail_url = self._opportunity_url(record)
                    if detail_url:
                        detailed, _ = self._parse(await self._request(detail_url))
                        if detailed:
                            record = self._merge(record, detailed[0])
                yield self._normalize(identity, record, q)
                maximum -= 1
                if maximum <= 0:
                    return
        except Exception as exc:
            self._record_failure(exc)
            raise

    async def _request(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        if not self._safe_url(url):
            raise IonWaveError("unsafe public URL")
        for attempt in range(self.portal.retry_attempts + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.portal.retry_attempts:
                    raise IonWaveAvailabilityError("IonWave public connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if not self._safe_url(str(response.url)):
                raise IonWaveError("unsafe redirect target")
            if response.status_code in self._transient_statuses:
                if attempt == self.portal.retry_attempts:
                    raise IonWaveAvailabilityError(f"IonWave unavailable ({response.status_code})")
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 404:
                raise IonWaveAccessError(IonWaveAccessState.NOT_FOUND)
            if response.status_code >= 400:
                raise IonWaveAccessError(IonWaveAccessState.RESTRICTED)
            state = self._detect_access(response)
            if state not in {IonWaveAccessState.PUBLIC, IonWaveAccessState.PUBLIC_METADATA_ONLY}:
                raise IonWaveAccessError(state)
            self._access, self._failures, self._last_failure = state, 0, None
            self._last_success = self._now()
            return response
        raise AssertionError("retry loop exhausted")

    def _parse(self, response: httpx.Response) -> tuple[list[dict[str, Any]], bool]:
        content_type = response.headers.get("content-type", "").casefold()
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise IonWaveAccessError(IonWaveAccessState.MALFORMED) from exc
            records = (
                payload.get("bids", payload.get("opportunities"))
                if isinstance(payload, dict)
                else payload
            )
            if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
                raise IonWaveAccessError(IonWaveAccessState.MALFORMED)
            return records, not records
        if "html" not in content_type:
            raise IonWaveAccessError(IonWaveAccessState.MALFORMED)
        parser = _IonWaveHTMLParser()
        parser.feed(response.text)
        return parser.records, parser.zero_results

    def _detect_access(self, response: httpx.Response) -> IonWaveAccessState:
        text = response.text[:200_000].casefold()
        if re.search(r"captcha|access denied.{0,30}bot|cloudflare.{0,30}challenge", text):
            return IonWaveAccessState.CAPTCHA
        if re.search(
            r"supplier login|sign in to your account|username.{0,50}password|session (?:has )?expired",
            text,
        ):
            return IonWaveAccessState.LOGIN_REQUIRED
        if re.search(r"scheduled maintenance|service unavailable", text):
            return IonWaveAccessState.UNAVAILABLE
        if response.url.host in {"supplier.eunasolutions.com", "vendor.goionwave.com"}:
            return IonWaveAccessState.MIGRATED
        if re.search(
            r"<app-root[^>]*>\s*</app-root>|<div[^>]+id=[\"']root[\"'][^>]*>\s*</div>.*javascript",
            text,
            re.S,
        ):
            return IonWaveAccessState.JAVASCRIPT_ONLY
        # Register/follow/respond calls-to-action may coexist with public metadata.
        if any(
            marker in text for marker in ("data-bid-id", "data-ionwave-bid", "data-opportunity-id")
        ):
            return IonWaveAccessState.PUBLIC
        if re.search(
            r"registration required|vendorregistration|create (?:a |your )?(?:supplier )?account",
            text,
        ):
            return IonWaveAccessState.REGISTRATION_REQUIRED
        return IonWaveAccessState.PUBLIC

    def _normalize(self, identity: str, record: dict[str, Any], q: IonWaveQuery) -> RawOpportunity:
        title = _clean(record.get("title") or record.get("opportunity_title"))
        agency = (
            _clean(record.get("agency") or record.get("organization"))
            or self.portal.owning_organization
        )
        if not title:
            raise IonWaveAccessError(IonWaveAccessState.MALFORMED)
        url = self._opportunity_url(record) or self.portal.portal_url
        payload = dict(record)
        payload["euna_ionwave"] = {
            "tenant_key": self.portal.portal_key,
            "tenant_slug": self.portal.tenant_slug,
            "platform_variant": self.portal.platform_variant,
            "access_state": self._access.value,
            "verification_status": self.portal.verification_status,
            "retrieved_at": self._now().isoformat(),
            "portal_url": self.portal.portal_url,
            "embed_list_url": self.portal.embed_list_url,
            "contracts_portal_url": self.portal.authoritative_agency_procurement_url,
            "record_type": "solicitation",
            "production_preset": self.portal.production,
        }
        payload["documents"] = self._documents(record, identity, url) if q.include_documents else []
        payload["source_provenance"] = {
            key: url
            for key in record
            if key not in {"documents"} and record.get(key) not in (None, "", [])
        }
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=identity,
                opportunity_url=cast(Any, url),
            ),
            title=title,
            agency=agency,
            description=_clean(record.get("description") or record.get("summary")) or None,
            solicitation_number=_clean(
                record.get("solicitation_number") or record.get("opportunity_number")
            )
            or None,
            status=self._status(record.get("status")),
            posted_at=self._datetime(record.get("release_date") or record.get("posted_date")),
            due_at=self._datetime(record.get("due_date") or record.get("response_deadline")),
            categories=self._dedupe([*record.get("categorys", []), *record.get("categories", [])]),
            raw_payload=payload,
        )

    def document_candidates(self, opportunity: RawOpportunity) -> list[DocumentCandidate]:
        """Convert discovery metadata into PR #12 manifest inputs without fetching bodies."""
        result = []
        for item in opportunity.raw_payload.get("documents", []):
            state = AccessState(item.get("access_state", AccessState.PUBLIC.value))
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=item["public_download_url"],
                    source_opportunity_url=opportunity.source.opportunity_url,
                    filename=item.get("displayed_filename") or "document",
                    label=item.get("document_title"),
                    mime_type=item.get("media_type"),
                    access_state=state,
                    source_document_id=item.get("source_document_id"),
                    category=item.get("document_category"),
                    source_detail_url=opportunity.source.opportunity_url,
                    referring_page_url=opportunity.source.opportunity_url,
                    publicly_retrievable=item.get("publicly_retrievable"),
                    raw_metadata=item,
                )
            )
        return result

    def _documents(
        self, record: Mapping[str, Any], identity: str, parent: str
    ) -> list[dict[str, Any]]:
        result, seen = [], set()
        for item in record.get("documents", []):
            if not isinstance(item, dict):
                continue
            url = self._safe_url(item.get("url"), parent, document=True)
            if not url or url in seen:
                continue
            seen.add(url)
            title = _clean(item.get("title")) or "Document"
            filename = (
                _clean(item.get("filename")) or urlparse(url).path.rsplit("/", 1)[-1] or "document"
            )
            access = str(item.get("access", "public")).casefold()
            restricted = access in {
                "login_required",
                "registration_required",
                "captcha",
                "restricted",
            }
            result.append(
                {
                    "document_title": title,
                    "displayed_filename": filename,
                    "media_type": item.get("media_type"),
                    "document_category": self._document_category(title),
                    "source_document_id": item.get("document_id"),
                    "posted_date": item.get("posted_date"),
                    "addendum_or_amendment_number": item.get("number"),
                    "public_download_url": url,
                    "public_detail_page_url": parent,
                    "parent_bid_id": identity,
                    "publicly_retrievable": not restricted,
                    "access_state": access if restricted else "public",
                    "raw_link_attributes": dict(item),
                }
            )
        return result

    def _matches(self, record: Mapping[str, Any], q: IonWaveQuery) -> bool:
        text = repr(record).casefold()
        keyword = _clean(q.keyword or " ".join(q.keywords)).casefold()
        if keyword and keyword not in text:
            return False
        if q.bid_id and _clean(record.get("bid_id")).casefold() != q.bid_id.casefold():
            return False
        number = _clean(record.get("solicitation_number") or record.get("opportunity_number"))
        if q.solicitation_number and number.casefold() != q.solicitation_number.casefold():
            return False
        status = _clean(record.get("status")).casefold()
        if q.statuses and status not in {x.casefold() for x in q.statuses}:
            return False
        if not q.include_closed and any(x in status for x in ("closed", "cancelled", "canceled")):
            return False
        if not q.include_awarded and "award" in status:
            return False
        if (
            q.department
            and q.department.casefold() not in _clean(record.get("department")).casefold()
        ):
            return False
        released = self._datetime(record.get("release_date") or record.get("posted_date"))
        due = self._datetime(record.get("due_date") or record.get("response_deadline"))
        return self._in_range(released, q.released_from, q.released_to) and self._in_range(
            due, q.due_from, q.due_to
        )

    def _identity(self, record: Mapping[str, Any]) -> str | None:
        bid_id = _clean(record.get("bid_id"))
        number = _clean(record.get("solicitation_number") or record.get("opportunity_number"))
        if bid_id:
            return f"ionwave:{self.portal.tenant_slug}:bid:{bid_id}"
        if number:
            normalized = re.sub(r"[^a-z0-9]+", "-", number.casefold()).strip("-")
            return f"ionwave:{self.portal.tenant_slug}:solicitation:{normalized}"
        title = _clean(record.get("title") or record.get("opportunity_title"))
        if title:
            digest = hashlib.sha256(f"{self.portal.tenant_slug}|{title}".encode()).hexdigest()[:20]
            return f"ionwave:{self.portal.tenant_slug}:fingerprint:{digest}"
        return None

    def _opportunity_url(self, record: Mapping[str, Any]) -> str | None:
        direct = self._safe_url(record.get("opportunity_url"), self.portal.portal_url)
        if direct:
            return self._canonical_url(direct)
        bid_id = _clean(record.get("bid_id"))
        return self.portal.opportunity_url(bid_id) if bid_id else None

    def _safe_url(
        self, value: Any, base: str | None = None, *, document: bool = False
    ) -> str | None:
        if not value:
            return None
        parsed = urlparse(urljoin(base or self.portal.portal_url, str(value).strip()))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname.casefold().rstrip(".")
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if host in {"localhost", "metadata.google.internal"} or host.endswith(
                (".local", ".internal", ".localhost")
            ):
                return None
        allowed = {h.casefold() for h in self.portal.approved_hosts}
        if document:
            allowed.update(h.casefold() for h in self.portal.approved_attachment_hosts)
        if host not in allowed:
            return None
        return urlunparse(parsed)

    def _configuration_valid(self) -> bool:
        expected_host = f"{self.portal.tenant_slug}.ionwave.net"
        return bool(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.portal.tenant_slug)
            and self.portal.portal_hostname.casefold() == expected_host
            and self.portal.organization_type in _ORGANIZATION_TYPES
            and self.portal.platform_variant in IONWAVE_VARIANTS
            and self._safe_url(self.portal.portal_url)
            and self._safe_url(self.portal.embed_list_url)
        )

    def _canonical_url(self, value: str) -> str:
        parsed = urlparse(value)
        query = [
            (k, v) for k, v in parse_qsl(parsed.query) if k.casefold() not in self._transient_query
        ]
        return urlunparse(parsed._replace(query=urlencode(query), fragment=""))

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
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
        return (
            self.portal.retry_backoff_seconds * (2**attempt)
            + self.portal.retry_jitter_seconds * self._random()
        )

    def _record_failure(self, exc: Exception) -> None:
        self._failures += 1
        self._last_failure = self._now()
        self._last_error_class = type(exc).__name__
        self._access = (
            exc.state if isinstance(exc, IonWaveAccessError) else IonWaveAccessState.TRANSIENT_ERROR
        )

    def _circuit_open(self) -> bool:
        if self._failures < self.portal.circuit_breaker_threshold or not self._last_failure:
            return False
        if (
            self._now() - self._last_failure
        ).total_seconds() >= self.portal.circuit_breaker_cooldown:
            self._failures = 0
            return False
        return True

    @staticmethod
    def _merge(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(old)
        result.update({k: v for k, v in new.items() if v not in (None, "", [])})
        result["documents"] = [*old.get("documents", []), *new.get("documents", [])]
        return result

    @staticmethod
    def _dedupe(values: list[Any]) -> list[str]:
        return list(dict.fromkeys(_clean(x) for x in values if _clean(x)))

    @staticmethod
    def _status(value: Any) -> OpportunityStatus:
        text = _clean(value).casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if any(x in text for x in ("closed", "expired")):
            return OpportunityStatus.CLOSED
        if any(x in text for x in ("open", "active", "posted")):
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        text = _clean(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _in_range(value: datetime | None, start: date | None, end: date | None) -> bool:
        return not (
            (start and (not value or value.date() < start))
            or (end and (not value or value.date() > end))
        )

    @staticmethod
    def _document_category(title: str) -> str:
        for pattern, category in (
            (r"addend", "addendum"),
            (r"amend", "amendment"),
            (r"q\s*&\s*a|questions", "questions_and_answers"),
            (r"award|intent", "award_notice"),
            (r"tabulation", "bid_tabulation"),
            (r"\b(?:rfp|rfq|ifb|itb|rfi)\b", "solicitation"),
        ):
            if re.search(pattern, title, re.I):
                return category
        return "other"
