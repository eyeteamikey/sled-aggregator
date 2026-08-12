"""Public, read-only connector for the Periscope S2G/BuySpeed family."""

import asyncio
import email.utils
import html
import json
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef

ResponseStrategy = Literal["json", "html", "hybrid", "fallback"]


@dataclass(frozen=True, slots=True)
class PeriscopePortal:
    """Everything that may vary between BuySpeed deployments."""

    jurisdiction: str
    jurisdiction_code: str
    name: str
    base_url: str
    search_url: str
    platform_variant: str
    response_strategy: ResponseStrategy = "fallback"
    detail_url_template: str | None = None
    page_parameter: str = "page"
    page_size_parameter: str = "pageSize"
    keyword_parameter: str = "q"
    page_starts_at: int = 1
    default_headers: Mapping[str, str] = field(default_factory=dict)
    field_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    date_formats: tuple[str, ...] = ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d")
    session_init_url: str | None = None
    document_session_required: bool = False
    production_verified: bool = False
    profile_key: str | None = None

    @property
    def bid_board_url(self) -> str:
        return self.search_url


# Public entry points are authoritative; endpoint/parser behavior remains deliberately
# conservative and fixture-tested until anonymous production discovery is verified.
ILLINOIS = PeriscopePortal(
    "Illinois",
    "IL",
    "BidBuy",
    "https://www.bidbuy.illinois.gov/",
    "https://www.bidbuy.illinois.gov/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="illinois/bidbuy",
)
MASSACHUSETTS = PeriscopePortal(
    "Massachusetts",
    "MA",
    "COMMBUYS",
    "https://www.commbuys.com/",
    "https://www.commbuys.com/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="massachusetts/commbuys",
)
NEVADA = PeriscopePortal(
    "Nevada",
    "NV",
    "NevadaEPro",
    "https://nevadaepro.com/",
    "https://nevadaepro.com/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="nevada/nevadaepro",
)
NEW_JERSEY = PeriscopePortal(
    "New Jersey",
    "NJ",
    "NJSTART",
    "https://www.njstart.gov/",
    "https://www.njstart.gov/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="new-jersey/njstart",
)
OREGON = PeriscopePortal(
    "Oregon",
    "OR",
    "OregonBuys",
    "https://oregonbuys.gov/",
    "https://oregonbuys.gov/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="oregon/oregonbuys",
)
US_VIRGIN_ISLANDS = PeriscopePortal(
    "U.S. Virgin Islands",
    "VI",
    "GVIBUY",
    "https://gvibuy.com/",
    "https://gvibuy.com/bso/view/search/external/advancedSearchBid.xhtml",
    "BuySpeed Online",
    response_strategy="html",
    profile_key="us-virgin-islands/gvibuy",
)
PORTALS = (ILLINOIS, MASSACHUSETTS, NEVADA, NEW_JERSEY, OREGON, US_VIRGIN_ISLANDS)


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class AsyncBidBuyTransport(AsyncGetTransport, Protocol):
    async def post(self, url: str, *, data: Mapping[str, Any]) -> httpx.Response: ...


class PeriscopeError(RuntimeError):
    """A response cannot safely be consumed."""


class PeriscopeAvailabilityError(PeriscopeError):
    """The public endpoint is temporarily unavailable."""


class PeriscopeRestrictedError(PeriscopeError):
    """Anonymous access ended at an authentication or challenge boundary."""


_INPUT_VALUE = re.compile(
    r'<input\b[^>]*\bname=["\'](?P<name>[^"\']+)["\'][^>]*\bvalue=["\'](?P<value>[^"\']*)',
    re.I,
)
_TAG = re.compile(r"<[^>]+>")


def extract_bidbuy_tokens(page: str) -> tuple[str, str]:
    """Extract ephemeral anonymous JSF tokens without persisting them."""
    values = {match["name"]: html.unescape(match["value"]) for match in _INPUT_VALUE.finditer(page)}
    csrf = values.get("_csrf")
    view_state = values.get("javax.faces.ViewState")
    if not csrf:
        raise PeriscopeError("BidBuy anonymous page is missing CSRF state")
    if not view_state:
        raise PeriscopeError("BidBuy anonymous page is missing JSF ViewState")
    return csrf, view_state


def build_bidbuy_search_form(csrf: str, view_state: str, keywords: tuple[str, ...]) -> dict[str, str]:
    if not csrf or not view_state:
        raise PeriscopeError("BidBuy search requires dynamic session tokens")
    return {
        "bidSearchForm": "bidSearchForm",
        "bidSearchForm:alternateId": "",
        "bidSearchForm:bidNbr": "",
        "bidSearchForm:buyer": "",
        "bidSearchForm:categoryCode": "",
        "bidSearchForm:classId": "",
        "bidSearchForm:classItemId": "",
        "bidSearchForm:departmentPrefix": "",
        "bidSearchForm:desc": " ".join(keywords).strip(),
        "bidSearchForm:itemDesc": "",
        "bidSearchForm:openingDateFrom_input": "",
        "bidSearchForm:openingDateTo_input": "",
        "bidSearchForm:organization": "",
        "bidSearchForm:status": "",
        "bidSearchForm:typeCode": "",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "@all",
        "javax.faces.partial.render": "advSearchResults",
        "javax.faces.source": "bidSearchForm",
        "_csrf": csrf,
        "javax.faces.ViewState": view_state,
    }


def build_bidbuy_pagination_form(
    csrf: str, view_state: str, *, first: int, rows: int
) -> dict[str, str]:
    if first < 0 or rows < 1:
        raise ValueError("BidBuy pagination bounds must be positive")
    return {
        "bidSearchResultsForm": "bidSearchResultsForm",
        "bidSearchResultsForm:bidResultId": "bidSearchResultsForm:bidResultId",
        "bidSearchResultsForm:bidResultId_first": str(first),
        "bidSearchResultsForm:bidResultId_rows": str(rows),
        "bidSearchResultsForm:bidResultId_pagination": "true",
        "bidSearchResultsForm:bidResultId_encodeFeature": "true",
        "bidSearchResultsForm:bidResultId_skipChildren": "true",
        "bidSearchResultsForm:bidResultId_reflowDD": "0",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "bidSearchResultsForm:bidResultId",
        "javax.faces.partial.render": "bidSearchResultsForm:bidResultId",
        "javax.faces.source": "bidSearchResultsForm:bidResultId",
        "_csrf": csrf,
        "javax.faces.ViewState": view_state,
    }


def parse_bidbuy_partial_response(payload: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PeriscopeError("BidBuy returned malformed JSF partial response") from exc
    if root.tag.rsplit("}", 1)[-1] != "partial-response":
        raise PeriscopeError("BidBuy response is not a JSF partial response")
    updates = {
        node.attrib.get("id", ""): node.text or ""
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "update"
    }
    view_state = next((value for key, value in updates.items() if "ViewState" in key), None)
    fragments = "\n".join(
        value for key, value in updates.items() if key in {"advSearchResults", "advancedSearchMainPanelContainer"}
    )
    headers = [
        _clean_html(value)
        for value in re.findall(r"<th\b[^>]*>(.*?)</th>", fragments, re.I | re.S)
    ]
    records: list[dict[str, Any]] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", fragments, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)
        if not cells:
            continue
        record = {
            _result_key(headers[index] if index < len(headers) else f"column_{index}"): _clean_html(cell)
            for index, cell in enumerate(cells)
        }
        link = re.search(r'href=["\']([^"\']*bidDetail\.sda[^"\']*)', row, re.I)
        if link:
            record["url"] = html.unescape(link.group(1))
            query = parse_qs(urlparse(record["url"]).query)
            record["id"] = (query.get("docId") or [record.get("number")])[0]
        record.setdefault("title", record.get("description"))
        if record.get("id") and record.get("title"):
            records.append(record)
    return records, view_state.strip() if view_state else None


def parse_content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    plain = re.search(r'filename=["\']?([^;"\']+)', value, re.I)
    candidate = encoded.group(1) if encoded else plain.group(1).strip() if plain else None
    if not candidate:
        return None
    from urllib.parse import unquote

    return unquote(candidate).replace("\\", "/").rsplit("/", 1)[-1]


_ATTACHMENT_FIELDS = frozenset(
    {"bidId", "currentPage", "destination", "docId", "downloadFileNbr", "fromQuote",
     "itemNbr", "mode", "parentUrl", "querySql"}
)


def build_bidbuy_attachment_form(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Construct only the observed anonymous read-only attachment contract."""
    form = {key: str(value) for key, value in metadata.items() if key in _ATTACHMENT_FIELDS}
    if not form.get("docId") or not form.get("downloadFileNbr"):
        raise PeriscopeError("BidBuy attachment requires document and file identifiers")
    return form


def parse_bidbuy_detail(payload: str, detail_url: str) -> dict[str, Any]:
    pairs: dict[str, str] = {}
    for label, value in re.findall(
        r"<(?:th|label)\b[^>]*>(.*?)</(?:th|label)>\s*<td\b[^>]*>(.*?)</td>",
        payload,
        re.I | re.S,
    ):
        key, cleaned = _clean_html(label).casefold(), _clean_html(value)
        if key and cleaned:
            pairs[key] = cleaned
    contacts = {
        key: value for key, value in pairs.items()
        if any(marker in key for marker in ("contact", "buyer", "email", "phone", "address"))
    }
    vendors = {
        key: value for key, value in pairs.items()
        if any(marker in key for marker in ("vendor", "bid holder", "plan holder"))
    }
    attachments: list[dict[str, Any]] = []
    for form_match in re.finditer(r"<form\b[^>]*>(.*?)</form>", payload, re.I | re.S):
        fields = {
            match["name"]: html.unescape(match["value"])
            for match in _INPUT_VALUE.finditer(form_match.group(1))
            if match["name"] in _ATTACHMENT_FIELDS
        }
        if fields.get("docId") and fields.get("downloadFileNbr"):
            label = _clean_html(form_match.group(1)) or "Attachment"
            attachments.append(
                {
                    "id": fields["downloadFileNbr"],
                    "label": label,
                    "filename": label,
                    "url": detail_url,
                    "method": "POST",
                    "request": build_bidbuy_attachment_form(fields),
                    "access_state": "session-dependent",
                }
            )
    result: dict[str, Any] = {
        "detail_fields": pairs,
        "public_contacts": contacts,
        "public_vendors": vendors,
        "documents": attachments,
    }
    for target, markers in {
        "agency": ("department", "organization"),
        "description": ("description",),
        "status": ("status",),
        "number": ("bid solicitation", "bid number"),
    }.items():
        value = next((v for k, v in pairs.items() if any(m in k for m in markers)), None)
        if value:
            result[target] = value
    return result


def _clean_html(value: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", value)).split())


def _result_key(label: str) -> str:
    text = label.casefold()
    for key, marker in (
        ("number", "solicitation"), ("agency", "organization"), ("buyer", "buyer"),
        ("description", "description"), ("due", "opening date"), ("vendors", "awarded vendor"),
        ("status", "status"), ("alternate_id", "alternate"), ("bid_holders", "holder"),
    ):
        if marker in text:
            return key
    return re.sub(r"\W+", "_", text).strip("_")


@dataclass(frozen=True, slots=True)
class PeriscopeHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    portal: str
    jurisdiction: str
    access_state: str
    skipped_records: int


class _BidBoardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.documents: list[dict[str, str]] = []
        self._record: dict[str, Any] | None = None
        self._field: str | None = None
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag in {"tr", "article", "div"} and classes.intersection(
            {"opportunity", "bid", "solicitation", "bid-row"}
        ):
            self._record = {k[5:]: v for k, v in values.items() if k.startswith("data-")}
        if self._record is not None:
            self._field = values.get("data-field") or next(
                (
                    name
                    for name in ("id", "title", "agency", "status", "posted", "due", "number")
                    if name in classes
                ),
                None,
            )
        if tag == "a" and values.get("href"):
            self._href = values["href"]
        self._text = []

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._text).split())
        if self._record is not None and self._field and text:
            self._record[self._field] = text
        if tag == "a" and self._href:
            target = self._record if self._record is not None else {}
            if re.search(r"rfp|rfq|ifb|itb|sow|pws|spec|amend|q.?a|pricing|document", text, re.I):
                target.setdefault("documents", []).append({"label": text, "url": self._href})
            elif self._record is not None:
                self._record.setdefault("url", self._href)
            self._href = None
        if tag in {"tr", "article", "div"} and self._record is not None:
            if self._record:
                self.records.append(self._record)
            self._record = None
        self._field = None
        self._text = []


class PeriscopeBuySpeedConnector(BaseConnector):
    """Configurable asynchronous GET-only discovery for public BuySpeed boards."""

    platform_family = "periscope/buyspeed"
    jurisdictions = tuple(portal.jurisdiction for portal in PORTALS)
    _transient_statuses = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: PeriscopePortal = ILLINOIS,
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
        fetch_details: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if min(page_size, max_pages, max_results, circuit_breaker_threshold) < 1:
            raise ValueError("page, result, and circuit limits must be positive")
        if max_retries < 0 or circuit_breaker_cooldown < 0:
            raise ValueError("retry and cooldown settings must be non-negative")
        self.portal, self.page_size, self.max_pages = portal, page_size, max_pages
        self.max_results, self.max_retries, self.fetch_details = (
            max_results,
            max_retries,
            fetch_details,
        )
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold, self.circuit_breaker_cooldown = (
            circuit_breaker_threshold,
            circuit_breaker_cooldown,
        )
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": "TrustEST-SLED-Aggregator/0.1",
                **portal.default_headers,
            },
            follow_redirects=True,
        )
        self._owns_transport = transport is None
        self._consecutive_failures = 0
        self._last_status_code: int | None = None
        self._last_failure_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._access_state = "unverified" if not portal.production_verified else "public"
        self._skipped_records = 0

    @property
    def health(self) -> PeriscopeHealth:
        opened = self._circuit_is_open()
        return PeriscopeHealth(
            self._consecutive_failures == 0 and not opened,
            opened,
            self._consecutive_failures,
            self._last_status_code,
            self._last_failure_at,
            self._last_success_at,
            self.portal.name,
            self.portal.jurisdiction,
            self._access_state,
            self._skipped_records,
        )

    async def __aenter__(self) -> "PeriscopeBuySpeedConnector":
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
            not in {self.portal.jurisdiction.casefold(), self.portal.jurisdiction_code.casefold()}
        ):
            return
        if self._circuit_is_open():
            raise PeriscopeAvailabilityError("Periscope circuit breaker is open")
        limit, seen, fingerprints = min(query.limit, self.max_results), set(), set()
        yielded = 0
        try:
            if self.portal.profile_key == "illinois/bidbuy":
                async for item in self._discover_bidbuy(query, limit):
                    yield item
                return
            if self.portal.response_strategy == "fallback":
                self._access_state = "unsupported"
                return
            if self.portal.session_init_url:
                await self._request(self.portal.session_init_url, {})
            for offset in range(self.max_pages):
                page = offset + self.portal.page_starts_at
                params = {
                    self.portal.keyword_parameter: " ".join(query.keywords).strip() or "*",
                    self.portal.page_parameter: page,
                    self.portal.page_size_parameter: self.page_size,
                }
                response = await self._request(self.portal.search_url, params)
                records = self._records(response)
                fingerprint = json.dumps(records, sort_keys=True, default=str)
                if fingerprint in fingerprints:
                    return
                fingerprints.add(fingerprint)
                for record in records:
                    try:
                        item = await self._normalize(record)
                    except PeriscopeError:
                        self._skipped_records += 1
                        continue
                    if item.source.source_id in seen:
                        continue
                    seen.add(item.source.source_id)
                    yield item
                    yielded += 1
                    if yielded >= limit:
                        return
                if len(records) < self.page_size:
                    return
        except Exception:
            self._consecutive_failures += 1
            self._last_failure_at = self._now()
            raise

    async def _discover_bidbuy(
        self, query: ConnectorQuery, limit: int
    ) -> AsyncIterator[RawOpportunity]:
        initial = await self._request(self.portal.search_url, {})
        csrf, view_state = extract_bidbuy_tokens(initial.text)
        response = await self._post(
            self.portal.search_url, build_bidbuy_search_form(csrf, view_state, query.keywords)
        )
        seen: set[str] = set()
        for page in range(self.max_pages):
            records, updated_state = parse_bidbuy_partial_response(response.text)
            if updated_state:
                view_state = updated_state
            new_records = 0
            for record in records:
                source_id = str(record.get("id", "")).strip()
                if not source_id or source_id in seen:
                    continue
                seen.add(source_id)
                new_records += 1
                if self.fetch_details and record.get("url"):
                    detail_url = urljoin(self.portal.base_url, str(record["url"]))
                    detail = await self._request(detail_url, {})
                    record = {**record, **parse_bidbuy_detail(detail.text, detail_url)}
                yield await self._normalize(record)
                if len(seen) >= limit:
                    return
            if not records or not new_records or len(records) < self.page_size:
                return
            response = await self._post(
                self.portal.search_url,
                build_bidbuy_pagination_form(
                    csrf, view_state, first=(page + 1) * self.page_size, rows=self.page_size
                ),
            )

    async def _post(self, url: str, data: Mapping[str, Any]) -> httpx.Response:
        post = getattr(self._transport, "post", None)
        if post is None:
            raise PeriscopeError("BidBuy transport must support evidence-backed POST requests")
        for attempt in range(self.max_retries + 1):
            try:
                response = await post(url, data=data)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise PeriscopeAvailabilityError("BidBuy connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code in self._transient_statuses and attempt < self.max_retries:
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            self._validate_response(response)
            return response
        raise PeriscopeAvailabilityError("BidBuy retry limit exhausted")

    async def _request(self, url: str, params: Mapping[str, Any]) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise PeriscopeAvailabilityError("Periscope connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status_code = response.status_code
            if response.status_code in self._transient_statuses:
                if attempt == self.max_retries:
                    raise PeriscopeAvailabilityError(
                        f"Periscope temporarily unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            self._validate_response(response)
            return response
        raise AssertionError("retry loop exhausted")

    def _validate_response(self, response: httpx.Response) -> None:
        self._last_status_code = response.status_code
        if response.status_code == 403:
            self._access_state = "restricted"
            raise PeriscopeRestrictedError("anonymous access forbidden")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PeriscopeError(f"Periscope returned HTTP {response.status_code}") from exc
        text = response.text.casefold()
        if any(
                marker in text
                for marker in (
                    "captcha",
                    "recaptcha",
                    "bot challenge",
                    "sign in",
                    "vendor login",
                    "session expired",
                )
        ):
            self._access_state = "restricted"
            raise PeriscopeRestrictedError("authentication or challenge page returned")
        if any(
                marker in str(response.url).casefold()
                for marker in ("login", "signin", "authenticate")
        ):
            self._access_state = "restricted"
            raise PeriscopeRestrictedError("redirected to authentication")
        self._consecutive_failures = 0
        self._last_failure_at = None
        self._last_success_at = self._now()
        self._access_state = "public"

    def _records(self, response: httpx.Response) -> list[dict[str, Any]]:
        strategy = self.portal.response_strategy
        if (
            strategy in {"json", "hybrid"}
            and "json" in response.headers.get("content-type", "").lower()
        ):
            try:
                payload = response.json()
            except ValueError as exc:
                raise PeriscopeError("Periscope returned malformed JSON") from exc
            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict):
                records = next(
                    (
                        payload[k]
                        for k in ("results", "items", "bids", "solicitations", "data")
                        if k in payload
                    ),
                    None,
                )
            else:
                records = None
            if isinstance(records, dict):
                records = next(
                    (records[k] for k in ("items", "results", "rows") if k in records), None
                )
            if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
                raise PeriscopeError("Periscope response has an invalid JSON shape")
            return records
        if strategy not in {"html", "hybrid"}:
            raise PeriscopeError("portal response strategy is not supported")
        parser = _BidBoardParser()
        try:
            parser.feed(response.text)
        except Exception as exc:
            raise PeriscopeError("Periscope returned invalid HTML") from exc
        return parser.records

    async def _normalize(self, record: dict[str, Any]) -> RawOpportunity:
        aliases = self.portal.field_aliases

        def first(name: str, defaults: tuple[str, ...]) -> Any:
            return next(
                (
                    record[key]
                    for key in aliases.get(name, defaults)
                    if record.get(key) not in (None, "")
                ),
                None,
            )

        source_id = first("id", ("id", "bidId", "bid_id", "solicitationId", "number", "bidNumber"))
        title = first("title", ("title", "description", "bidTitle", "solicitationTitle"))
        if not source_id or not title:
            raise PeriscopeError("record requires source ID and title")
        direct = first("url", ("url", "detailUrl", "publicUrl"))
        if direct:
            opportunity_url = urljoin(self.portal.base_url, str(direct))
        elif self.portal.detail_url_template:
            opportunity_url = urljoin(
                self.portal.base_url, self.portal.detail_url_template.format(source_id=source_id)
            )
        else:
            opportunity_url = self.portal.bid_board_url
        if self.fetch_details and direct and not first("description", ("description", "summary")):
            detail = await self._request(opportunity_url, {})
            parser = _BidBoardParser()
            parser.feed(detail.text)
            if parser.records:
                record = {**record, **parser.records[0]}
        documents = []
        for document in (
            record.get("documents", []) if isinstance(record.get("documents"), list) else []
        ):
            if not isinstance(document, dict) or not document.get("url"):
                continue
            url = urljoin(opportunity_url, str(document["url"]))
            label = str(document.get("label", "Document"))
            state = "session-dependent" if self.portal.document_session_required else "public"
            if re.search(r"login|captcha", url, re.I):
                state = "restricted"
            documents.append(
                {
                    "label": label,
                    "url": url,
                    "opportunity_url": opportunity_url,
                    "access_state": state,
                }
            )
        enriched = dict(record)
        enriched["document_links"] = documents
        enriched["portal"] = {
            "name": self.portal.name,
            "variant": self.portal.platform_variant,
            "production_verified": self.portal.production_verified,
        }
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=str(source_id).strip(),
                opportunity_url=opportunity_url,
            ),
            title=str(title),
            agency=str(
                first("agency", ("agency", "department", "organization", "buyer"))
                or self.portal.name
            ),
            description=self._optional(first("description", ("description", "summary"))),
            solicitation_number=self._optional(
                first("number", ("number", "bidNumber", "solicitationNumber"))
            ),
            status=self._status(self._optional(first("status", ("status", "bidStatus")))),
            posted_at=self._date(first("posted", ("posted", "postedDate", "publishDate"))),
            due_at=self._date(first("due", ("due", "dueDate", "closeDate", "responseDeadline"))),
            categories=self._list(
                first("categories", ("categories", "commodityCodes", "nigpCodes"))
            ),
            raw_payload=enriched,
        )

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
        raise PeriscopeError(f"invalid Periscope date: {value}")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_seconds * 2**attempt + self.jitter_seconds * self._random()
        if retry_after:
            try:
                retry = max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                retry = max(0.0, (parsed - self._now()).total_seconds())
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
        return [str(value)]

    @staticmethod
    def _status(value: str | None) -> OpportunityStatus:
        text = (value or "").casefold()
        for status, words in {
            OpportunityStatus.OPEN: ("open", "active", "published"),
            OpportunityStatus.CLOSED: ("closed", "expired"),
            OpportunityStatus.AWARDED: ("award",),
            OpportunityStatus.CANCELLED: ("cancel",),
            OpportunityStatus.FORECAST: ("forecast", "planned"),
        }.items():
            if any(word in text for word in words):
                return status
        return OpportunityStatus.UNKNOWN
