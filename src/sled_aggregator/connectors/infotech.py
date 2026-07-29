"""Configurable public, GET-only Infotech Bid Express and BidX connector."""

import asyncio
import csv
import email.utils
import io
import json
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Literal, Protocol
from urllib.parse import urljoin

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef

ResponseStrategy = Literal["html", "json", "xml", "csv", "hybrid", "link-only"]


class InfotechPlatformVariant(StrEnum):
    BIDX_LEGACY = "bidx_legacy"
    BIDX_MODERN = "bidx_modern"
    BIDEXPRESS_GENERAL = "bidexpress_general"
    INFOTECH_EXPRESS = "infotech_express"
    UNKNOWN_CONFIGURABLE_VARIANT = "unknown_configurable_variant"


class InfotechAccessState(StrEnum):
    PUBLIC = "public"
    ANONYMOUS_SESSION_DEPENDENT = "anonymous-session-dependent"
    REGISTRATION_REQUIRED = "registration-required"
    LOGIN_REQUIRED = "login-required"
    SUBSCRIPTION_REQUIRED = "subscription-required"
    PAYMENT_REQUIRED = "payment-required"
    DIGITAL_ID_REQUIRED = "digital-id-required"
    CAPTCHA_BLOCKED = "captcha-blocked"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InfotechBidExpressPortal:
    agency_name: str
    jurisdiction: str
    platform_variant: InfotechPlatformVariant
    public_base_url: str
    listing_url: str | None = None
    agency_identifier: str | None = None
    response_strategy: ResponseStrategy = "link-only"
    detail_url_template: str | None = None
    document_behavior: str = "link-only"
    verification_status: str = "configured-only"
    access_state_notes: str = "Public directory link recorded; anonymous routes unverified."
    directory_url: str = "https://www.bidx.com/agency-directory"
    page_parameter: str = "page"
    page_size_parameter: str = "pageSize"
    keyword_parameter: str = "q"
    agency_parameter: str | None = None
    jurisdiction_parameter: str | None = None
    status_parameter: str | None = None
    letting_date_parameter: str | None = None
    page_starts_at: int = 1
    default_headers: Mapping[str, str] = field(default_factory=dict)
    field_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    date_formats: tuple[str, ...] = ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d")
    session_init_url: str | None = None
    document_session_required: bool = False
    fetch_details: bool = True

    @property
    def public_listing_or_fallback_url(self) -> str:
        return self.listing_url or self.directory_url or self.public_base_url

    @property
    def production_verified(self) -> bool:
        return self.verification_status == "live-verified"


# Directory-derived, configured-only state coverage. No agency identifiers or
# private endpoints are inferred. Each preset therefore safely falls back to the
# authoritative public family directory until an endpoint is separately verified.
_BIDX_STATES = (
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Idaho",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "South Carolina",
    "Tennessee",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
)


def _configured_agency(name: str, jurisdiction: str | None = None) -> InfotechBidExpressPortal:
    return InfotechBidExpressPortal(
        agency_name=name,
        jurisdiction=jurisdiction or name,
        platform_variant=InfotechPlatformVariant.BIDX_MODERN,
        public_base_url="https://www.bidx.com/",
    )


BIDX_AGENCIES = tuple(
    _configured_agency(f"{state} transportation agency", state) for state in _BIDX_STATES
) + (
    _configured_agency("Massachusetts Bay Transportation Authority", "Massachusetts"),
    _configured_agency("New Jersey Turnpike Authority", "New Jersey"),
    _configured_agency("New York State Thruway Authority", "New York"),
    _configured_agency("North Carolina DOT divisions", "North Carolina"),
)
DEFAULT_PORTAL = InfotechBidExpressPortal(
    agency_name="Infotech public agency directory",
    jurisdiction="United States",
    platform_variant=InfotechPlatformVariant.UNKNOWN_CONFIGURABLE_VARIANT,
    public_base_url="https://www.bidx.com/",
)
PORTALS = BIDX_AGENCIES


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class InfotechError(RuntimeError):
    """A response cannot safely be consumed."""


class InfotechAvailabilityError(InfotechError):
    """The configured public endpoint is temporarily unavailable."""


class InfotechRestrictedError(InfotechError):
    """Public navigation reached an access boundary."""


@dataclass(frozen=True, slots=True)
class InfotechHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    platform_variant: InfotechPlatformVariant
    agency_identifier: str | None
    access_state: str
    skipped_records: int


class _OpportunityHTMLParser(HTMLParser):
    """Small tolerant parser for semantic cards and rearranged HTML tables."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._record: dict[str, Any] | None = None
        self._field: str | None = None
        self._href: str | None = None
        self._text: list[str] = []
        self._headers: list[str] = []
        self._cells: list[str] = []
        self._in_header = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag in {"tr", "article", "div"} and (
            tag == "tr"
            or classes.intersection(
                {"opportunity", "proposal", "solicitation", "letting-row", "bid-row"}
            )
        ):
            self._record = {k[5:]: v for k, v in values.items() if k.startswith("data-")}
            self._cells = []
        self._field = values.get("data-field") or next(
            (
                x
                for x in (
                    "id",
                    "title",
                    "agency",
                    "status",
                    "posted",
                    "due",
                    "letting_date",
                    "number",
                    "description",
                    "route",
                    "county",
                    "project_number",
                    "contract_number",
                )
                if x in classes
            ),
            None,
        )
        if tag == "th":
            self._in_header = True
        if tag == "a" and values.get("href"):
            self._href = values["href"]
        self._text = []

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._text).split())
        if tag == "th":
            if text:
                self._headers.append(self._key(text))
            self._in_header = False
        elif tag == "td" and self._record is not None:
            self._cells.append(text)
        if self._record is not None and self._field and text:
            self._record[self._field] = text
        if tag == "a" and self._href:
            if self._record is not None:
                if re.search(
                    r"proposal|plan|spec|addend|amend|notice|bid form|item list|rfp|rfq|ifb|"
                    r"sow|pws|bid tab|award",
                    text,
                    re.I,
                ):
                    self._record.setdefault("documents", []).append(
                        {"title": text, "url": self._href}
                    )
                else:
                    self._record.setdefault("url", self._href)
            self._href = None
        if tag in {"tr", "article", "div"} and self._record is not None:
            if self._cells and self._headers:
                self._record.update(dict(zip(self._headers, self._cells, strict=False)))
            if self._record:
                self.records.append(self._record)
            self._record = None
        self._field = None
        self._text = []

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


class InfotechBidExpressConnector(BaseConnector):
    platform_family = "infotech/bid-express"
    jurisdictions = _BIDX_STATES
    _transient_statuses = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: InfotechBidExpressPortal = DEFAULT_PORTAL,
        *,
        transport: AsyncGetTransport | None = None,
        page_size: int = 25,
        max_pages: int = 10,
        max_results: int = 250,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        jitter_seconds: float = 0.25,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 60,
        fetch_details: bool | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if min(page_size, max_pages, max_results, circuit_breaker_threshold) < 1:
            raise ValueError("page, result, and circuit limits must be positive")
        if max_retries < 0 or circuit_breaker_cooldown < 0:
            raise ValueError("retry and cooldown settings must be non-negative")
        self.portal, self.page_size, self.max_pages = portal, page_size, max_pages
        self.max_results, self.max_retries = max_results, max_retries
        self.fetch_details = portal.fetch_details if fetch_details is None else fetch_details
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1", **portal.default_headers},
        )
        self._owns_transport = transport is None
        self._consecutive_failures = 0
        self._last_status_code: int | None = None
        self._last_failure_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._access_state = InfotechAccessState.UNKNOWN.value
        self._skipped_records = 0

    @property
    def health(self) -> InfotechHealth:
        opened = self._circuit_is_open()
        return InfotechHealth(
            not opened and self._consecutive_failures == 0,
            opened,
            self._consecutive_failures,
            self._last_status_code,
            self._last_failure_at,
            self._last_success_at,
            self.portal.platform_variant,
            self.portal.agency_identifier,
            self._access_state,
            self._skipped_records,
        )

    async def __aenter__(self) -> "InfotechBidExpressConnector":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        if query.limit < 1 or (
            query.jurisdiction
            and query.jurisdiction.casefold()
            not in {self.portal.jurisdiction.casefold(), "us", "united states"}
        ):
            return
        if self._circuit_is_open():
            raise InfotechAvailabilityError("Infotech circuit breaker is open")
        if self.portal.response_strategy == "link-only" or not self.portal.listing_url:
            self._access_state = InfotechAccessState.UNKNOWN.value
            return
        seen: set[str] = set()
        fingerprints: set[str] = set()
        yielded = 0
        try:
            if self.portal.session_init_url:
                await self._request(self.portal.session_init_url, {})
            for offset in range(self.max_pages):
                params: dict[str, Any] = {
                    self.portal.page_parameter: offset + self.portal.page_starts_at,
                    self.portal.page_size_parameter: self.page_size,
                    self.portal.keyword_parameter: " ".join(query.keywords).strip() or "*",
                }
                if self.portal.agency_parameter and self.portal.agency_identifier:
                    params[self.portal.agency_parameter] = self.portal.agency_identifier
                if self.portal.jurisdiction_parameter and query.jurisdiction:
                    params[self.portal.jurisdiction_parameter] = query.jurisdiction
                response = await self._request(self.portal.listing_url, params)
                records = self._records(response)
                fingerprint = json.dumps(records, sort_keys=True, default=str)
                if fingerprint in fingerprints:
                    return
                fingerprints.add(fingerprint)
                for record in records:
                    try:
                        item = await self._normalize(record)
                    except (InfotechError, ValueError):
                        self._skipped_records += 1
                        continue
                    if item.source.source_id in seen:
                        continue
                    seen.add(item.source.source_id)
                    yield item
                    yielded += 1
                    if yielded >= min(query.limit, self.max_results):
                        return
                if len(records) < self.page_size:
                    return
        except Exception:
            self._consecutive_failures += 1
            self._last_failure_at = self._now()
            raise

    async def _request(self, url: str, params: Mapping[str, Any]) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    self._access_state = InfotechAccessState.UNAVAILABLE.value
                    raise InfotechAvailabilityError("Infotech connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status_code = response.status_code
            if response.status_code in self._transient_statuses:
                if attempt == self.max_retries:
                    self._access_state = InfotechAccessState.UNAVAILABLE.value
                    raise InfotechAvailabilityError(
                        f"Infotech unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access_state = InfotechAccessState.FORBIDDEN.value
                raise InfotechRestrictedError("anonymous access forbidden")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise InfotechError(f"Infotech returned HTTP {response.status_code}") from exc
            state = self._detect_access_state(response)
            if state != InfotechAccessState.PUBLIC:
                self._access_state = state.value
                if state == InfotechAccessState.UNAVAILABLE:
                    raise InfotechAvailabilityError("Infotech maintenance or error page returned")
                raise InfotechRestrictedError(f"Infotech access boundary: {state.value}")
            self._consecutive_failures = 0
            self._last_failure_at = None
            self._last_success_at = self._now()
            self._access_state = state.value
            return response
        raise AssertionError("retry loop exhausted")

    @staticmethod
    def _detect_access_state(response: httpx.Response) -> InfotechAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        # Restricted document labels inside a valid JSON listing are metadata, not
        # an access boundary for the listing itself. JSON error payloads without
        # recognizable result containers are rejected later by the parser.
        if "json" in response.headers.get("content-type", "").casefold():
            return InfotechAccessState.PUBLIC
        markers = (
            (
                InfotechAccessState.CAPTCHA_BLOCKED,
                ("captcha", "recaptcha", "bot challenge", "cloudflare challenge"),
            ),
            (InfotechAccessState.DIGITAL_ID_REQUIRED, ("digital id", "digital identity")),
            (
                InfotechAccessState.PAYMENT_REQUIRED,
                ("payment required", "purchase access", "credit card", "pay now"),
            ),
            (
                InfotechAccessState.SUBSCRIPTION_REQUIRED,
                ("subscription required", "subscribe to access", "membership required"),
            ),
            (
                InfotechAccessState.REGISTRATION_REQUIRED,
                ("registration required", "create an account", "vendor registration"),
            ),
            (
                InfotechAccessState.LOGIN_REQUIRED,
                ("sign in", "log in", "vendor login", "session expired"),
            ),
            (
                InfotechAccessState.UNAVAILABLE,
                ("maintenance", "temporarily unavailable", "generic error", "service unavailable"),
            ),
        )
        for state, words in markers:
            if any(word in text for word in words):
                return state
        if any(word in url for word in ("login", "signin", "authenticate")):
            return InfotechAccessState.LOGIN_REQUIRED
        if "payment" in url or "checkout" in url:
            return InfotechAccessState.PAYMENT_REQUIRED
        return InfotechAccessState.PUBLIC

    def _records(self, response: httpx.Response) -> list[dict[str, Any]]:
        strategy = self.portal.response_strategy
        content_type = response.headers.get("content-type", "").casefold()
        if strategy in {"json", "hybrid"} and ("json" in content_type or strategy == "json"):
            try:
                payload = response.json()
            except ValueError as exc:
                raise InfotechError("malformed Infotech JSON") from exc
            records: Any = payload
            if isinstance(payload, dict):
                records = next(
                    (
                        payload[k]
                        for k in (
                            "results",
                            "items",
                            "proposals",
                            "solicitations",
                            "lettings",
                            "data",
                        )
                        if k in payload
                    ),
                    None,
                )
                if isinstance(records, dict):
                    records = next(
                        (records[k] for k in ("items", "rows", "results") if k in records), None
                    )
        elif strategy == "xml" or (strategy == "hybrid" and "xml" in content_type):
            try:
                root = ET.fromstring(response.text)
            except ET.ParseError as exc:
                raise InfotechError("malformed Infotech XML") from exc
            nodes = (
                list(root.findall(".//opportunity"))
                + list(root.findall(".//proposal"))
                + list(root.findall(".//solicitation"))
            )
            records = [
                {child.tag.split("}")[-1]: child.text or "" for child in node} for node in nodes
            ]
        elif strategy == "csv" or (strategy == "hybrid" and "csv" in content_type):
            records = list(csv.DictReader(io.StringIO(response.text)))
        elif strategy in {"html", "hybrid"}:
            parser = _OpportunityHTMLParser()
            try:
                parser.feed(response.text)
            except Exception as exc:
                raise InfotechError("invalid Infotech HTML") from exc
            records = parser.records
        else:
            raise InfotechError("unsupported Infotech response strategy")
        if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
            raise InfotechError("invalid Infotech response shape")
        return records

    async def _normalize(self, record: dict[str, Any]) -> RawOpportunity:
        aliases = self.portal.field_aliases

        def first(name: str, defaults: tuple[str, ...]) -> Any:
            return next(
                (record[k] for k in aliases.get(name, defaults) if record.get(k) not in (None, "")),
                None,
            )

        source_id = first(
            "id",
            (
                "id",
                "proposalId",
                "proposal_id",
                "solicitationId",
                "projectNumber",
                "proposal",
                "number",
            ),
        )
        title = first(
            "title",
            (
                "title",
                "description",
                "proposalDescription",
                "projectDescription",
                "solicitationTitle",
            ),
        )
        if not source_id or not title:
            raise InfotechError("record requires source ID and title")
        agency_id = self.portal.agency_identifier or first(
            "agency_id", ("agencyId", "agency_id", "agencyCode")
        )
        stable_id = f"{agency_id}:{source_id}" if agency_id else str(source_id)
        direct = first("url", ("url", "detailUrl", "proposalUrl", "publicUrl"))
        if direct:
            opportunity_url = urljoin(self.portal.public_base_url, str(direct))
        elif self.portal.detail_url_template:
            opportunity_url = urljoin(
                self.portal.public_base_url,
                self.portal.detail_url_template.format(
                    source_id=source_id, agency_id=agency_id or ""
                ),
            )
        else:
            opportunity_url = self.portal.public_listing_or_fallback_url
        if self.fetch_details and direct and not first("description", ("description", "summary")):
            detail = await self._request(opportunity_url, {})
            parsed = self._records(detail) if self.portal.response_strategy == "hybrid" else []
            if parsed:
                record = {**record, **parsed[0]}
        documents = [
            self._document(d, opportunity_url)
            for d in record.get("documents", [])
            if isinstance(d, dict) and d.get("url")
        ]
        payload = dict(record)
        payload.update(
            {
                "document_links": documents,
                "portal": {
                    "agency_name": self.portal.agency_name,
                    "agency_identifier": self.portal.agency_identifier,
                    "jurisdiction": self.portal.jurisdiction,
                    "variant": self.portal.platform_variant.value,
                    "verification_status": self.portal.verification_status,
                    "fallback_url": self.portal.public_listing_or_fallback_url,
                },
            }
        )
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=stable_id,
                opportunity_url=opportunity_url,
            ),
            title=str(title),
            agency=str(
                first("agency", ("agency", "department", "organization")) or self.portal.agency_name
            ),
            description=self._optional(first("description", ("description", "summary", "scope"))),
            solicitation_number=self._optional(
                first("number", ("number", "proposal", "solicitationNumber", "contractNumber"))
            ),
            status=self._status(self._optional(first("status", ("status", "proposalStatus")))),
            posted_at=self._date(first("posted", ("posted", "postedDate", "advertisedDate"))),
            due_at=self._date(
                first(
                    "due", ("due", "dueDate", "bidOpeningDate", "responseDeadline", "lettingDate")
                )
            ),
            categories=self._list(
                first("categories", ("categories", "commodityCodes", "workTypes"))
            ),
            raw_payload=payload,
        )

    def _document(self, document: dict[str, Any], opportunity_url: str) -> dict[str, Any]:
        url = urljoin(opportunity_url, str(document["url"]))
        title = str(document.get("title") or document.get("label") or "Document")
        text = f"{title} {url}".casefold()
        state = (
            InfotechAccessState.ANONYMOUS_SESSION_DEPENDENT
            if self.portal.document_session_required
            else InfotechAccessState.PUBLIC
        )
        for detected, words in (
            (InfotechAccessState.DIGITAL_ID_REQUIRED, ("digital-id", "digital id")),
            (InfotechAccessState.PAYMENT_REQUIRED, ("payment", "purchase", "paywall")),
            (InfotechAccessState.SUBSCRIPTION_REQUIRED, ("subscription", "subscribe")),
            (InfotechAccessState.REGISTRATION_REQUIRED, ("register", "registration")),
            (InfotechAccessState.LOGIN_REQUIRED, ("login", "signin")),
        ):
            if any(x in text for x in words):
                state = detected
                break
        suffix = (
            url.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
            if "." in url.rsplit("/", 1)[-1]
            else None
        )
        return {
            "title": title,
            "url": url,
            "opportunity_url": opportunity_url,
            "apparent_file_type": suffix,
            "access_state": state.value,
            "anonymous_session_required": state == InfotechAccessState.ANONYMOUS_SESSION_DEPENDENT,
            "registration_required": state == InfotechAccessState.REGISTRATION_REQUIRED,
            "subscription_required": state == InfotechAccessState.SUBSCRIPTION_REQUIRED,
            "payment_required": state == InfotechAccessState.PAYMENT_REQUIRED,
            "login_required": state == InfotechAccessState.LOGIN_REQUIRED,
            "link_only": state != InfotechAccessState.PUBLIC,
        }

    def _date(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in self.portal.date_formats:
            try:
                return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        raise InfotechError(f"invalid Infotech date: {value}")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_seconds * 2**attempt + self.jitter_seconds * self._random()
        if retry_after:
            try:
                retry = max(0.0, float(retry_after))
            except (ValueError, TypeError, OverflowError):
                try:
                    parsed = email.utils.parsedate_to_datetime(retry_after)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    retry = max(0.0, (parsed - self._now()).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    retry = 0
            delay = max(delay, retry)
        return delay

    def _circuit_is_open(self) -> bool:
        return bool(
            self._consecutive_failures >= self.circuit_breaker_threshold
            and self._last_failure_at
            and self._now()
            < self._last_failure_at + timedelta(seconds=self.circuit_breaker_cooldown)
        )

    @staticmethod
    def _optional(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [
                str(x.get("name", x.get("code", "")) if isinstance(x, dict) else x)
                for x in value
                if x
            ]
        return [x.strip() for x in str(value).split(",") if x.strip()]

    @staticmethod
    def _status(value: str | None) -> OpportunityStatus:
        text = (value or "").casefold()
        for status, words in {
            OpportunityStatus.OPEN: ("open", "active", "advertised"),
            OpportunityStatus.CLOSED: ("closed", "expired"),
            OpportunityStatus.AWARDED: ("award",),
            OpportunityStatus.CANCELLED: ("cancel",),
            OpportunityStatus.FORECAST: ("forecast", "planned"),
        }.items():
            if any(word in text for word in words):
                return status
        return OpportunityStatus.UNKNOWN
