"""Public, bounded CGI Advantage Vendor Self-Service discovery.

Deployments are deliberately configuration-driven: routes and verified public
capabilities are tenant facts, not assumptions inferred from CGI branding.
The connector never enters registration, authentication, or response flows.
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
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef


class CGIAdvantageVSSVariant(StrEnum):
    ADVANTAGE4 = "Advantage4"
    ALT_SELF_SERVICE = "AltSelfService"
    LINK_ONLY = "link-only"


class CGIAdvantageVSSAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_GUEST = "public_guest"
    PUBLIC_SESSION_REQUIRED = "public_session_required"
    EXTERNAL_PUBLIC = "external_public"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    VERIFICATION_REQUIRED = "verification_required"
    INVITED_VENDOR_ONLY = "invited_vendor_only"
    RESTRICTED = "restricted"
    ATTACHMENT_RESTRICTED = "attachment_restricted"
    RESPONSE_LOGIN_REQUIRED = "response_login_required"
    CAPTCHA = "captcha"
    FORBIDDEN = "forbidden"
    SCHEDULED_UNAVAILABLE = "scheduled_unavailable"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"
    EXPIRED_SESSION = "expired_session"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN = "unknown"


class CGIAdvantageVSSRecordType(StrEnum):
    SOLICITATION = "solicitation"
    GRANT = "grant"
    CONTRACT = "contract"
    NOTICE = "notice"
    UNKNOWN = "unknown"


class CGIAdvantageVSSError(RuntimeError):
    pass


class CGIAdvantageVSSAccessError(CGIAdvantageVSSError):
    def __init__(self, state: CGIAdvantageVSSAccessState) -> None:
        self.state = state
        super().__init__(f"CGI Advantage VSS access ended at {state.value}")


class CGIAdvantageVSSAvailabilityError(CGIAdvantageVSSError):
    pass


@dataclass(frozen=True, slots=True)
class CGIAdvantageVSSPortal:
    key: str
    jurisdiction: str
    country_subdivision: str
    source_system: str
    base_url: str
    variant: CGIAdvantageVSSVariant
    timezone: str
    landing_route: str = ""
    guest_route: str | None = None
    search_route: str | None = None
    detail_template: str | None = None
    response_strategy: str = "html"
    public_search_verified: bool = False
    public_detail_verified: bool = False
    public_attachments_verified: bool = False
    public_awards_verified: bool = False
    public_contracts_verified: bool = False
    guest_bootstrap_required: bool = False
    anonymous_session_required: bool = False
    validation_level: str = "configured_unverified"
    last_validation_date: date | None = None
    known_restrictions: tuple[str, ...] = ()
    availability_schedule: str | None = None
    enabled: bool = False
    allowed_attachment_hosts: tuple[str, ...] = ()

    @property
    def landing_url(self) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", self.landing_route)

    @property
    def search_url(self) -> str:
        return urljoin(self.landing_url.rstrip("/") + "/", self.search_route or "")


MAINE_VSS = CGIAdvantageVSSPortal(
    key="maine/vss",
    jurisdiction="Maine",
    country_subdivision="US-ME",
    source_system="Maine CGI Advantage VSS",
    base_url="https://mevss.hostams.com/PRDVSS1X1/",
    landing_route="AltSelfService",
    guest_route="AltSelfService/Guest",
    search_route="SolicitationSearch",
    variant=CGIAdvantageVSSVariant.ALT_SELF_SERVICE,
    timezone="America/New_York",
    response_strategy="guest-session-html",
    guest_bootstrap_required=True,
    anonymous_session_required=True,
    validation_level="fixture_verified",
    known_restrictions=("RFP coverage begins with records published October 1, 2025",),
    enabled=True,
)
MICHIGAN_SIGMA_VSS = CGIAdvantageVSSPortal(
    key="michigan/sigma-vss",
    jurisdiction="Michigan",
    country_subdivision="US-MI",
    source_system="Michigan SIGMA VSS",
    base_url="https://sigma.michigan.gov/PRDVSS1X1/",
    landing_route="Advantage4",
    search_route="SolicitationSearch",
    detail_template="Advantage4?solicitation_number={solicitation_number}",
    variant=CGIAdvantageVSSVariant.ADVANTAGE4,
    timezone="America/Detroit",
    validation_level="configured_unverified",
)
COLORADO_VSS = CGIAdvantageVSSPortal(
    key="colorado/vss",
    jurisdiction="Colorado",
    country_subdivision="US-CO",
    source_system="ColoradoVSS",
    base_url="https://prd.co.cgiadvantage.com/PRDVSS1X1/",
    landing_route="Advantage4",
    search_route="SolicitationSearch",
    variant=CGIAdvantageVSSVariant.ADVANTAGE4,
    timezone="America/Denver",
    validation_level="configured_unverified",
    availability_schedule="Jurisdiction-published availability and maintenance windows apply",
)
CGI_ADVANTAGE_VSS_PORTALS = {
    portal.key: portal for portal in (MAINE_VSS, MICHIGAN_SIGMA_VSS, COLORADO_VSS)
}


@dataclass(frozen=True, slots=True)
class CGIAdvantageVSSQuery(ConnectorQuery):
    keyword: str | None = None
    solicitation_number: str | None = None
    solicitation_type: str | None = None
    status: str | None = None
    department: str | None = None
    agency: str | None = None
    buyer: str | None = None
    commodity_code: str | None = None
    commodity_description: str | None = None
    published_from: date | None = None
    published_to: date | None = None
    closing_from: date | None = None
    closing_to: date | None = None
    record_scope: str = "open"
    page_size: int = 25
    max_pages: int = 3
    result_limit: int = 100
    include_details: bool = True
    include_attachments: bool = True
    include_commodity_lines: bool = True
    include_instructions: bool = True
    include_awards: bool = False

    def __post_init__(self) -> None:
        if min(self.limit, self.page_size, self.max_pages, self.result_limit) < 1:
            raise ValueError("query bounds must be positive")
        if self.page_size > 100 or self.max_pages > 20 or self.result_limit > 1000:
            raise ValueError("query exceeds safe CGI VSS bounds")


class AsyncVSSTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def post(self, url: str, *, data: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CGIAdvantageVSSHealth:
    tenant_key: str
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    access_state: CGIAdvantageVSSAccessState
    skipped_records: int


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


class _VSSParser(HTMLParser):
    """Semantic/data-attribute parser used by both supported HTML variants."""

    labels = {
        "solicitation number": "solicitation_number",
        "solicitation type": "solicitation_type",
        "title": "title",
        "description": "description",
        "status": "status",
        "department": "department",
        "agency": "agency",
        "organization": "organization",
        "buyer": "buyer",
        "buyer email": "buyer_email",
        "buyer phone": "buyer_phone",
        "published date": "published_date",
        "issue date": "published_date",
        "opening date": "opening_date",
        "closing date": "closing_date",
        "closing time": "closing_time",
        "delivery location": "delivery_location",
    }

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.guest_action: str | None = None
        self._record: dict[str, Any] | None = None
        self._depth = 0
        self._field: str | None = None
        self._section: str | None = None
        self._text: list[str] = []
        self._href: str | None = None
        self._attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self._attrs = a
        self._text = []
        marker = a.get("data-vss-record") or a.get("data-solicitation-id")
        if marker is not None and self._record is None:
            self._record = {"internal_id": marker}
            self._depth = 1
        elif self._record is not None:
            self._depth += 1
        if a.get("data-field"):
            self._field = str(a["data-field"]).replace("-", "_")
        if a.get("data-section"):
            self._section = str(a["data-section"]).replace("-", "_")
        if tag == "a" and a.get("href"):
            self._href = str(a["href"])
        if tag in {"a", "button"} and re.search(
            r"guest|public access", f"{a.get('id', '')} {a.get('class', '')}", re.I
        ):
            self.guest_action = str(a.get("href") or a.get("formaction") or "")

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = _clean("".join(self._text))
        if self._record is not None:
            if self._field and text:
                if self._field in {"commodity_line", "award", "contract"}:
                    self._record.setdefault(self._field + "s", []).append(
                        {
                            "text": text,
                            **{k[5:]: v for k, v in self._attrs.items() if k.startswith("data-")},
                        }
                    )
                else:
                    self._record[self._field] = text
            if tag == "a" and self._href:
                link = {"title": text or "Link", "url": self._href, "section": self._section}
                if self._section == "attachments" or re.search(
                    r"\.pdf|\.docx?|\.xlsx?|\.csv|\.zip|addend|award|questions|\b(?:sow|pws)\b",
                    f"{text} {self._href}",
                    re.I,
                ):
                    self._record.setdefault("attachments", []).append(link)
                elif self._section == "contracts":
                    self._record.setdefault("contracts", []).append(link)
                elif not self._record.get("url"):
                    self._record["url"] = self._href
                self._href = None
            self._depth -= 1
            if self._depth == 0:
                self.records.append(self._record)
                self._record = None
        elif tag in {"a", "button"} and re.search(r"continue as guest|public access", text, re.I):
            self.guest_action = self._href or self.guest_action or ""
            self._href = None
        self._field = None
        self._text = []


class CGIAdvantageVSSConnector(BaseConnector):
    platform_family = "cgi/advantage-vss"
    jurisdictions = ("Maine", "Michigan", "Colorado")
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: CGIAdvantageVSSPortal = MAINE_VSS,
        *,
        transport: AsyncVSSTransport | None = None,
        max_retries: int = 2,
        timeout: float = 30,
        user_agent: str = "TrustEST-SLED-Aggregator/0.1 (public read-only)",
        concurrency: int = 2,
        backoff_seconds: float = 0.5,
        jitter_seconds: float = 0.25,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 60,
        max_response_bytes: int = 5_000_000,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if min(concurrency, circuit_breaker_threshold, max_response_bytes) < 1:
            raise ValueError("limits must be positive")
        self.portal, self.max_retries = portal, max_retries
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown, self.max_response_bytes = (
            circuit_breaker_cooldown,
            max_response_bytes,
        )
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._owns_transport = transport is None
        self._semaphore = asyncio.Semaphore(concurrency)
        self._guest_ready = False
        self._failures = 0
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._access = CGIAdvantageVSSAccessState.UNKNOWN
        self._skipped = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> CGIAdvantageVSSHealth:
        opened = self._circuit_is_open()
        return CGIAdvantageVSSHealth(
            self.portal.key,
            not opened and self._failures == 0,
            opened,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._access,
            self._skipped,
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, CGIAdvantageVSSQuery)
            else CGIAdvantageVSSQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if q.jurisdiction and q.jurisdiction.casefold() not in {
            self.portal.jurisdiction.casefold(),
            self.portal.country_subdivision.casefold(),
        }:
            return
        if not self.portal.enabled or not self.portal.public_search_verified:
            raise CGIAdvantageVSSAccessError(CGIAdvantageVSSAccessState.RESTRICTED)
        if self._circuit_is_open():
            raise CGIAdvantageVSSAvailabilityError(f"{self.portal.key} circuit breaker is open")
        try:
            if self.portal.guest_bootstrap_required and not self._guest_ready:
                await self._bootstrap_guest()
            records: dict[str, dict[str, Any]] = {}
            seen_pages: set[str] = set()
            refreshed = False
            page = 1
            while page <= q.max_pages:
                response = await self._request(
                    "GET", self.portal.search_url, params=self._params(q, page)
                )
                state = self._detect_access(response)
                if state == CGIAdvantageVSSAccessState.EXPIRED_SESSION and not refreshed:
                    self._guest_ready = False
                    await self._bootstrap_guest()
                    refreshed = True
                    continue
                parsed = self._parse(response)
                fingerprint = hashlib.sha256(repr(parsed.records).encode()).hexdigest()
                if not parsed.records or fingerprint in seen_pages:
                    break
                seen_pages.add(fingerprint)
                for record in parsed.records:
                    identity = self._identity(record)
                    if identity:
                        records[identity] = self._merge(records.get(identity, {}), record)
                    else:
                        self._skipped += 1
                if len(parsed.records) < q.page_size:
                    break
                page += 1
            yielded = 0
            for identity, record in records.items():
                try:
                    if q.include_details and self.portal.public_detail_verified:
                        detail_url = self._detail_url(record)
                        if detail_url:
                            details = self._parse(await self._request("GET", detail_url)).records
                            if details:
                                record = self._merge(record, details[0])
                    yield self._normalize(identity, record, q)
                    yielded += 1
                    if yielded >= min(q.limit, q.result_limit):
                        return
                except (CGIAdvantageVSSError, ValueError):
                    self._skipped += 1
        except Exception:
            self._record_failure()
            raise

    async def _bootstrap_guest(self) -> None:
        landing = await self._request("GET", self.portal.landing_url, allow_expired=True)
        parser = self._parse(landing)
        route = parser.guest_action or self.portal.guest_route
        if route is None:
            self._access = CGIAdvantageVSSAccessState.UNKNOWN
            raise CGIAdvantageVSSAccessError(CGIAdvantageVSSAccessState.UNKNOWN)
        response = await self._request("GET", self._safe_url(route, self.portal.landing_url) or "")
        state = self._detect_access(response)
        if state not in {
            CGIAdvantageVSSAccessState.PUBLIC,
            CGIAdvantageVSSAccessState.PUBLIC_GUEST,
        }:
            raise CGIAdvantageVSSAccessError(state)
        self._guest_ready = True
        self._access = CGIAdvantageVSSAccessState.PUBLIC_GUEST

    def _params(self, q: CGIAdvantageVSSQuery, page: int) -> dict[str, str]:
        # These neutral names are emitted only for a preset whose route/capability was verified.
        values = {
            "keyword": q.keyword or " ".join(q.keywords),
            "solicitation_number": q.solicitation_number,
            "solicitation_type": q.solicitation_type,
            "status": q.status,
            "department": q.department,
            "agency": q.agency,
            "buyer": q.buyer,
            "commodity_code": q.commodity_code,
            "commodity_description": q.commodity_description,
            "published_from": q.published_from,
            "published_to": q.published_to,
            "closing_from": q.closing_from,
            "closing_to": q.closing_to,
            "scope": q.record_scope,
            "page": page,
            "page_size": q.page_size,
        }
        return {
            k: v.isoformat() if isinstance(v, date) else str(v)
            for k, v in values.items()
            if v not in (None, "")
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        allow_expired: bool = False,
    ) -> httpx.Response:
        if not self._safe_url(url, self.portal.base_url):
            raise CGIAdvantageVSSError("unsafe request URL")
        for attempt in range(self.max_retries + 1):
            try:
                async with self._semaphore:
                    response = await (
                        self._transport.post(url, data=data or {})
                        if method == "POST"
                        else self._transport.get(url, params=params)
                    )
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise CGIAdvantageVSSAvailabilityError("CGI VSS connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if len(response.content) > self.max_response_bytes:
                raise CGIAdvantageVSSError("CGI VSS response exceeds configured bound")
            if response.status_code in self._transient:
                self._access = CGIAdvantageVSSAccessState.UNAVAILABLE
                if attempt == self.max_retries:
                    raise CGIAdvantageVSSAvailabilityError(
                        f"CGI VSS unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access = CGIAdvantageVSSAccessState.FORBIDDEN
                raise CGIAdvantageVSSAccessError(self._access)
            if response.status_code >= 400:
                raise CGIAdvantageVSSError(f"CGI VSS returned HTTP {response.status_code}")
            state = self._detect_access(response)
            if state == CGIAdvantageVSSAccessState.EXPIRED_SESSION and allow_expired:
                return response
            if state not in {
                CGIAdvantageVSSAccessState.PUBLIC,
                CGIAdvantageVSSAccessState.PUBLIC_GUEST,
                CGIAdvantageVSSAccessState.EXPIRED_SESSION,
            }:
                self._access = state
                raise CGIAdvantageVSSAccessError(state)
            self._failures = 0
            self._last_failure = None
            self._last_success = self._now()
            self._access = state
            return response
        raise AssertionError("retry loop exhausted")

    def _parse(self, response: httpx.Response) -> _VSSParser:
        if "html" not in response.headers.get("content-type", "text/html").casefold():
            raise CGIAdvantageVSSError("unexpected CGI VSS content type")
        parser = _VSSParser()
        parser.feed(response.text)
        return parser

    def _normalize(
        self, identity: str, r: dict[str, Any], q: CGIAdvantageVSSQuery
    ) -> RawOpportunity:
        title = _clean(r.get("title"))
        agency = _clean(r.get("agency") or r.get("department") or r.get("organization"))
        number = _clean(r.get("solicitation_number"))
        if not title or not agency or not number:
            raise CGIAdvantageVSSError("CGI VSS record lacks required identity or display fields")
        url = self._detail_url(r) or self.portal.search_url
        payload = dict(r)
        payload["cgi_advantage_vss"] = {
            "tenant_key": self.portal.key,
            "country_subdivision": self.portal.country_subdivision,
            "source_system": self.portal.source_system,
            "platform_variant": self.portal.variant.value,
            "public_route": url,
            "guest_session_required": self.portal.anonymous_session_required,
            "solicitation_number": number,
            "internal_source_id": _clean(r.get("internal_id")) or None,
            "round_or_version": self._suffix(number),
            "source_status": _clean(r.get("status")) or None,
            "original_dates": {
                k: r.get(k)
                for k in (
                    "published_date",
                    "opening_date",
                    "closing_date",
                    "closing_time",
                    "award_date",
                )
                if r.get(k)
            },
            "access_state": self._access.value,
            "validation_level": self.portal.validation_level,
            "last_seen_at": self._now().isoformat(),
            "absence_policy": "retain_last_known; absence_is_not_deletion",
        }
        payload["commodity_lines"] = (
            self._dedupe(r.get("commodity_lines", [])) if q.include_commodity_lines else []
        )
        payload["attachments"] = self._documents(r, identity, url) if q.include_attachments else []
        payload["solicitation_instructions"] = (
            r.get("instructions") if q.include_instructions else None
        )
        payload["award_metadata"] = r.get("awards", []) if q.include_awards else []
        payload["contract_references"] = self._contracts(r, identity, url)
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=identity,
                opportunity_url=url,
            ),
            title=title,
            agency=agency,
            description=_clean(r.get("description")) or None,
            solicitation_number=number,
            status=self._status(r.get("status")),
            posted_at=self._datetime(r.get("published_date")),
            due_at=self._datetime(r.get("closing_date"), r.get("closing_time")),
            categories=[x for x in (_clean(r.get("solicitation_type")),) if x],
            raw_payload=payload,
        )

    def _documents(self, r: Mapping[str, Any], identity: str, parent: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for item in r.get("attachments", []) if isinstance(r.get("attachments"), list) else []:
            if not isinstance(item, dict):
                continue
            url = self._safe_url(item.get("url"), parent, attachment=True)
            if not url or url in seen:
                continue
            seen.add(url)
            title = _clean(item.get("title")) or "Document"
            filename = urlparse(url).path.rsplit("/", 1)[-1]
            own = (urlparse(url).hostname or "").casefold() == (
                urlparse(self.portal.base_url).hostname or ""
            ).casefold()
            category = self._document_category(title)
            out.append(
                {
                    "displayed_filename": filename or None,
                    "displayed_title": title,
                    "source_url": url,
                    "document_category": category,
                    "apparent_file_type": filename.rsplit(".", 1)[-1].lower()
                    if "." in filename
                    else None,
                    "displayed_file_size": item.get("size"),
                    "posted_date": item.get("posted"),
                    "modified_date": item.get("modified"),
                    "version_or_amendment": self._suffix(title),
                    "attachment_id": item.get("attachment_id"),
                    "parent_solicitation_number": r.get("solicitation_number"),
                    "parent_source_id": identity,
                    "parent_opportunity_url": parent,
                    "access_state": "public_session_required"
                    if self.portal.anonymous_session_required
                    else ("public" if own else "external_public"),
                    "anonymous_session_required": self.portal.anonymous_session_required,
                    "retrieval_eligible": self.portal.public_attachments_verified,
                    "tenant_source": self.portal.key,
                    "classification": "internal" if own else "external",
                    "text_extracted": False,
                    "ocr_performed": False,
                }
            )
        return out

    def _contracts(self, r: Mapping[str, Any], identity: str, parent: str) -> list[dict[str, Any]]:
        out = []
        for item in r.get("contracts", []) if isinstance(r.get("contracts"), list) else []:
            if isinstance(item, dict) and (
                url := self._safe_url(item.get("url"), parent, attachment=True)
            ):
                out.append(
                    {
                        "title": _clean(item.get("title")),
                        "source_url": url,
                        "parent_source_id": identity,
                        "access_state": "public"
                        if self.portal.public_contracts_verified
                        else "restricted",
                    }
                )
        return out

    def _detail_url(self, r: Mapping[str, Any]) -> str | None:
        if r.get("url"):
            return self._safe_url(r["url"], self.portal.landing_url)
        number = _clean(r.get("solicitation_number"))
        if number and self.portal.detail_template:
            route = self.portal.detail_template.format(solicitation_number=number)
            parsed = urlparse(urljoin(self.portal.base_url, route))
            query = parse_qs(parsed.query)
            query["solicitation_number"] = [number]
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        return None

    def _identity(self, r: Mapping[str, Any]) -> str | None:
        internal = _clean(r.get("internal_id"))
        number = _clean(r.get("solicitation_number"))
        if internal:
            return f"{self.portal.key}:id:{internal}"
        return f"{self.portal.key}:solicitation:{number}" if number else None

    @staticmethod
    def _merge(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(old)
        result.update({k: v for k, v in new.items() if v not in (None, "", [])})
        for key in ("attachments", "commodity_lines", "awards", "contracts"):
            result[key] = CGIAdvantageVSSConnector._dedupe([*old.get(key, []), *new.get(key, [])])
        return result

    @staticmethod
    def _dedupe(items: Any) -> list[Any]:
        if not isinstance(items, list):
            return []
        out, seen = [], set()
        for item in items:
            marker = repr(sorted(item.items())) if isinstance(item, dict) else repr(item)
            if marker not in seen:
                seen.add(marker)
                out.append(item)
        return out

    def _safe_url(self, value: Any, base: str, *, attachment: bool = False) -> str | None:
        if not value:
            return None
        url = urljoin(base, str(value).strip())
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        host = parsed.hostname.casefold().rstrip(".")
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return None
        except ValueError:
            if host in {"localhost", "metadata.google.internal"} or host.endswith(
                (".local", ".internal", ".localhost")
            ):
                return None
        if attachment:
            origin = (urlparse(self.portal.base_url).hostname or "").casefold()
            allowed = {origin, *(x.casefold() for x in self.portal.allowed_attachment_hosts)}
            if host not in allowed:
                return None
        return url

    def _datetime(self, day: Any, clock: Any = None) -> datetime | None:
        day_text, clock_text = _clean(day), _clean(clock)
        if not day_text or (not clock_text and not re.search(r"\d:\d", day_text)):
            return None
        combined = f"{day_text} {clock_text}".strip()
        for fmt in (
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %H:%M",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(combined, fmt).replace(
                    tzinfo=ZoneInfo(self.portal.timezone)
                )
            except ValueError:
                pass
        return None

    @staticmethod
    def _status(value: Any) -> OpportunityStatus:
        text = _clean(value).casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if text == "awarded":
            return OpportunityStatus.AWARDED
        if text in {"closed", "archived", "no award"}:
            return OpportunityStatus.CLOSED
        if text in {"published", "open", "amended", "reopened"}:
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _suffix(value: str) -> str | None:
        match = re.search(
            r"(?:-|\b(?:amendment|addendum|version)\s*#?)([A-Za-z0-9.]+)$", value, re.I
        )
        return match.group(1) if match else None

    @staticmethod
    def _document_category(title: str) -> str:
        text = title.casefold()
        if re.search(r"questions|\bq&a\b", text):
            return "questions_and_answers"
        if "addend" in text or "amend" in text:
            return "addendum"
        if "award" in text:
            return "award_notice"
        if re.search(r"\bpws\b|performance work", text):
            return "pws"
        if re.search(r"\bsow\b|statement of work", text):
            return "sow"
        if "price" in text or "cost proposal" in text:
            return "pricing"
        return "solicitation"

    def _detect_access(self, response: httpx.Response) -> CGIAdvantageVSSAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        checks = (
            (CGIAdvantageVSSAccessState.CAPTCHA, ("captcha", "recaptcha")),
            (
                CGIAdvantageVSSAccessState.VERIFICATION_REQUIRED,
                ("verification code", "one-time passcode", "sms verification"),
            ),
            (
                CGIAdvantageVSSAccessState.REGISTRATION_REQUIRED,
                ("vendor registration required", "create a vendor account"),
            ),
            (
                CGIAdvantageVSSAccessState.INVITED_VENDOR_ONLY,
                ("invited vendors only", "invitation required"),
            ),
            (
                CGIAdvantageVSSAccessState.MAINTENANCE,
                ("scheduled maintenance", "maintenance in progress"),
            ),
            (
                CGIAdvantageVSSAccessState.SCHEDULED_UNAVAILABLE,
                ("outside normal operating hours", "scheduled unavailable"),
            ),
            (
                CGIAdvantageVSSAccessState.EXPIRED_SESSION,
                ("session has expired", "session expired"),
            ),
            (CGIAdvantageVSSAccessState.RESTRICTED, ("access denied", "not authorized")),
            (
                CGIAdvantageVSSAccessState.LOGIN_REQUIRED,
                ("please sign in", "username and password", "vendor login"),
            ),
        )
        for state, markers in checks:
            if any(marker in text for marker in markers):
                return state
        if any(marker in url for marker in ("okta", "sso", "login")):
            return CGIAdvantageVSSAccessState.LOGIN_REQUIRED
        if not text.strip() or ("<app-root" in text and "data-vss-record" not in text):
            return CGIAdvantageVSSAccessState.MALFORMED_RESPONSE
        if "continue as guest" in text or "public access" in text:
            return CGIAdvantageVSSAccessState.PUBLIC_GUEST
        return CGIAdvantageVSSAccessState.PUBLIC

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_seconds * 2**attempt + self.jitter_seconds * self._random()
        if retry_after:
            try:
                retry = max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry = max(
                        0.0,
                        (
                            email.utils.parsedate_to_datetime(retry_after) - self._now()
                        ).total_seconds(),
                    )
                except (TypeError, ValueError):
                    retry = 0.0
            delay = max(delay, retry)
        return delay

    def _record_failure(self) -> None:
        self._failures += 1
        self._last_failure = self._now()

    def _circuit_is_open(self) -> bool:
        if self._failures < self.circuit_breaker_threshold or not self._last_failure:
            return False
        if (self._now() - self._last_failure).total_seconds() >= self.circuit_breaker_cooldown:
            self._failures = 0
            return False
        return True
