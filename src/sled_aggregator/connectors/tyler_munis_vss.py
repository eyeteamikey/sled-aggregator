"""Public, anonymous Tyler Munis Vendor Self Service bid-board connector."""

import asyncio
import email.utils
import hashlib
import ipaddress
import random
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

TRANSIENT = frozenset({429, 502, 503, 504})
SENSITIVE_QUERY = frozenset({"token", "hash"})


class TylerMunisVssError(RuntimeError):
    """The public VSS contract could not be safely consumed."""


class TylerMunisVssAccessError(TylerMunisVssError):
    """Navigation reached an authentication or restricted boundary."""


class Transport(Protocol):
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...
    async def aclose(self) -> None: ...


def _safe_url(url: str, hosts: frozenset[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
        or host not in hosts
    ):
        raise ValueError("URL must be fragment-free HTTPS on an approved host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("private or special-purpose hosts are forbidden")


@dataclass(frozen=True, slots=True)
class TylerMunisVssProfile:
    key: str
    jurisdiction: str
    display_name: str
    base_url: str
    allowed_hosts: frozenset[str]
    root_path: str = "/vss/"
    selector_path: str = "Vendors/VBids/BidVersionSelector.aspx"
    search_path: str = "Vendors/VBids/Default.aspx"
    results_path: str = "Vendors/VBids/SearchResults.aspx"
    detail_path: str = "Vendors/VBids/Detail.aspx"
    document_path: str = "DocumentViewer.ashx"
    default_bid_type: str = "All"
    default_open_only: bool = True
    allow_blank_search: bool = False
    maximum_pages: int = 10
    maximum_results: int = 250
    timeout: float = 20
    retry_count: int = 2
    backoff_seconds: float = 0.25
    jitter_seconds: float = 0.1
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 60

    def __post_init__(self) -> None:
        hosts = frozenset(x.lower() for x in self.allowed_hosts)
        object.__setattr__(self, "allowed_hosts", hosts)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", self.key):
            raise ValueError("invalid source key")
        if not re.fullmatch(r"[A-Z]{2}", self.jurisdiction) or not self.display_name.strip():
            raise ValueError("display name and two-letter jurisdiction are required")
        _safe_url(self.base_url, hosts)
        if urlparse(self.base_url).hostname not in hosts or not self.base_url.endswith(
            self.root_path
        ):
            raise ValueError("base URL must use the configured VSS root")
        for path in (
            self.selector_path,
            self.search_path,
            self.results_path,
            self.detail_path,
            self.document_path,
        ):
            if path.startswith(("/", "//")) or ".." in path:
                raise ValueError("paths must remain beneath the VSS root")
        if not (1 <= self.maximum_pages <= 100 and 1 <= self.maximum_results <= 5000):
            raise ValueError("invalid discovery bounds")
        if (
            min(
                self.timeout,
                self.backoff_seconds,
                self.jitter_seconds,
                self.circuit_breaker_cooldown,
            )
            < 0
            or self.circuit_breaker_threshold < 1
        ):
            raise ValueError("invalid resilience configuration")

    def url(self, path: str) -> str:
        return urljoin(self.base_url, path)


SUMMIT = TylerMunisVssProfile(
    "oh-summit-county-tyler-munis-vss",
    "OH",
    "Summit County, Ohio",
    "https://summitcountyoh.munisselfservice.com/vss/",
    frozenset({"summitcountyoh.munisselfservice.com"}),
)
OPELIKA = TylerMunisVssProfile(
    "al-opelika-tyler-munis-vss",
    "AL",
    "City of Opelika, Alabama",
    "https://ss.opelika-al.gov/vss/",
    frozenset({"ss.opelika-al.gov"}),
)
PROFILES = (SUMMIT, OPELIKA)


@dataclass(frozen=True, slots=True)
class TylerMunisVssQuery(ConnectorQuery):
    bid_number: str | None = None
    bid_type: str | None = None
    open_only: bool | None = None


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden: dict[str, str] = {}
        self.controls: dict[str, str] = {}
        self.rows: list[dict[str, str]] = []
        self.documents: list[dict[str, str]] = []
        self.fields: dict[str, str] = {}
        self.next_event: tuple[str, str] | None = None
        self.page_events: dict[int, tuple[str, str]] = {}
        self._row: dict[str, str] | None = None
        self._text: list[str] = []
        self._field: str | None = None
        self._tables: list[str] = []
        self._live_cells: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._result_headers: list[str] = []
        self._document: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        if tag == "table":
            self._tables.append(a.get("id", ""))
        if tag == "tr" and self._tables:
            self._live_cells = []
        if tag in {"td", "th"} and self._live_cells is not None:
            self._cell = {"tag": tag, "text": [], "event": None}
            self._live_cells.append(self._cell)
        if tag in {"input", "select"} and a.get("name"):
            self.controls[a["name"]] = a.get("value", "")
            if a.get("type", "").lower() == "hidden":
                self.hidden[a["name"]] = a.get("value", "")
        if tag == "tr" and "data-bid-number" in a:
            self._row = {k[5:].replace("-", "_"): v for k, v in a.items() if k.startswith("data-")}
        if tag == "a":
            event = re.search(
                r"__doPostBack\('([^']+)','([^']*)'\)",
                " ".join((a.get("href", ""), a.get("onclick", ""))),
            )
            if self._cell is not None and event:
                self._cell["event"] = event.groups()
            if event and ("next" in a.get("class", "").lower() or a.get("rel") == "next"):
                self.next_event = event.group(1), event.group(2)
            if event:
                page = re.fullmatch(r"page:(?:\d+-\d+):(\d+)", event.group(2), re.I)
                if page:
                    self.page_events[int(page.group(1))] = event.group(1), event.group(2)
            if self._row is not None and event:
                self._row["detail_target"], self._row["detail_argument"] = event.groups()
            if "data-document-id" in a:
                item = {k[5:].replace("-", "_"): v for k, v in a.items() if k.startswith("data-")}
                item["url"] = a.get("href", "")
                self.documents.append(item)
            elif urlparse(a.get("href", "")).path.lower().endswith("documentviewer.ashx"):
                query = dict(parse_qsl(urlparse(a["href"]).query, keep_blank_values=True))
                self._document = {
                    "url": a["href"],
                    "document_id": query.get("documentId", query.get("id", "")),
                }
        if "data-field" in a:
            self._field, self._text = a["data-field"], []

    def handle_data(self, data: str) -> None:
        if self._field:
            self._text.append(data)
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._document is not None:
            self._document.setdefault("_text", "")
            self._document["_text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._document is not None:
            title = " ".join(self._document.pop("_text", "").split())
            self._document["title"] = title or "Document"
            self._document["filename"] = title or "document"
            self.documents.append(self._document)
            self._document = None
        if tag in {"td", "th"}:
            self._cell = None
        if tag == "tr" and self._live_cells is not None:
            self._consume_live_row(self._live_cells)
            self._live_cells = None
        if tag == "table" and self._tables:
            self._tables.pop()
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        if self._field:
            self.fields[self._field] = " ".join("".join(self._text).split())
            self._field = None

    def _consume_live_row(self, cells: list[dict[str, Any]]) -> None:
        values = [" ".join("".join(cell["text"]).split()) for cell in cells]
        if not values:
            return
        if all(cell["tag"] == "th" for cell in cells):
            self._result_headers = [value.casefold() for value in values]
            return
        if self._tables and self._tables[-1].endswith("MolGridView1") and self._result_headers:
            record: dict[str, str] = {}
            aliases = {
                "type": "bid_type",
                "number": "bid_number",
                "description": "title",
                "due by": "due_date",
                "opening": "opening_date",
                "status": "status",
            }
            for index, value in enumerate(values):
                if index < len(self._result_headers):
                    record[aliases.get(self._result_headers[index], self._result_headers[index])] = value
                event = cells[index].get("event")
                if event and event[0].lower().endswith("viewlink"):
                    record["detail_target"], record["detail_argument"] = event
            if record.get("bid_number") and record.get("title"):
                self.rows.append(record)
            return
        if len(values) >= 2 and values[0] and values[1]:
            key = re.sub(r"\W+", "_", values[0].casefold()).strip("_")
            if key:
                self.fields[key] = values[1]


def parse_page(html: str) -> _Parser:
    parser = _Parser()
    try:
        parser.feed(html)
    except Exception as exc:
        raise TylerMunisVssError("malformed HTML response") from exc
    return parser


def form_state(html: str, *, require_event_validation: bool = False) -> dict[str, str]:
    hidden = parse_page(html).hidden
    if not hidden.get("__VIEWSTATE"):
        raise TylerMunisVssError("required ASP.NET form state is absent")
    if require_event_validation and not hidden.get("__EVENTVALIDATION"):
        raise TylerMunisVssError("required ASP.NET event validation is absent")
    return hidden


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (k, "REDACTED" if k.lower() in SENSITIVE_QUERY else v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


class TylerMunisVssConnector(BaseConnector):
    platform_family = "tyler/munis-vss"
    jurisdictions = ("Ohio", "Alabama")
    public_read_only = True
    document_pipeline_compatible = True

    def __init__(
        self, profile: TylerMunisVssProfile = SUMMIT, transport: Transport | None = None
    ) -> None:
        self.profile = profile
        self._client = transport or httpx.AsyncClient(
            follow_redirects=False, timeout=profile.timeout
        )
        self._owns_client = transport is None
        self._failures = 0
        self._opened_at: datetime | None = None
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def health_snapshot(self) -> dict[str, Any]:
        circuit = bool(
            self._opened_at
            and (datetime.now(UTC) - self._opened_at).total_seconds()
            < self.profile.circuit_breaker_cooldown
        )
        return {
            "available": not circuit,
            "circuit_open": circuit,
            "consecutive_failures": self._failures,
            "last_status_code": self._last_status,
            "last_failure_at": self._last_failure,
            "last_success_at": self._last_success,
        }

    def _validate_response(self, response: httpx.Response, expected: str) -> None:
        self._last_status = response.status_code
        location = response.headers.get("location")
        if location:
            target = urljoin(str(response.url), location)
            try:
                _safe_url(target, self.profile.allowed_hosts)
            except ValueError as exc:
                raise TylerMunisVssAccessError("unsafe redirect") from exc
            low = urlparse(target).path.lower()
            if any(x in low for x in ("login", "portico", "vendorcheck", "register", "response")):
                raise TylerMunisVssAccessError("restricted authentication transition")
        ctype = response.headers.get("content-type", "").lower()
        if response.status_code == 200 and "text/html" not in ctype:
            raise TylerMunisVssError("public VSS operation returned unsupported content")
        low = response.text.lower()
        if (
            'type="password"' in low
            or 'name="password"' in low
            or "vendorcheck" in low
            or "sign in to your account" in low
        ):
            raise TylerMunisVssAccessError("restricted authentication page")
        if response.status_code == 200 and expected.lower() not in low:
            raise TylerMunisVssError("unexpected public VSS response shape")

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        _safe_url(url, self.profile.allowed_hosts)
        if self._opened_at and self.health_snapshot()["circuit_open"]:
            raise TylerMunisVssError("connector circuit is open")
        response = None
        for attempt in range(self.profile.retry_count + 1):
            try:
                response = await getattr(self._client, method)(url, **kwargs)
                if response.status_code not in TRANSIENT:
                    break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.profile.retry_count:
                    raise
            if attempt < self.profile.retry_count:
                delay = self.profile.backoff_seconds * 2**attempt + random.uniform(
                    0, self.profile.jitter_seconds
                )
                retry = response.headers.get("Retry-After") if response else None
                if retry:
                    try:
                        delay = min(float(retry), 60)
                    except ValueError:
                        delay = min(
                            max(
                                (
                                    email.utils.parsedate_to_datetime(retry) - datetime.now(UTC)
                                ).total_seconds(),
                                0,
                            ),
                            60,
                        )
                await asyncio.sleep(delay)
        assert response is not None
        if response.status_code >= 400:
            self._failures += 1
            self._last_failure = datetime.now(UTC)
            if self._failures >= self.profile.circuit_breaker_threshold:
                self._opened_at = self._last_failure
            response.raise_for_status()
        self._failures = 0
        self._opened_at = None
        self._last_success = datetime.now(UTC)
        return response

    @staticmethod
    def _control(controls: Mapping[str, str], suffix: str) -> str:
        matches = [name for name in controls if name.lower().endswith(suffix.lower())]
        if len(matches) != 1:
            raise TylerMunisVssError("required search control is absent or ambiguous")
        return matches[0]

    def search_form(self, html: str, query: TylerMunisVssQuery) -> dict[str, str]:
        if not query.keywords and not query.bid_number and not self.profile.allow_blank_search:
            raise ValueError("blank or wildcard search is disabled")
        page = parse_page(html)
        data = form_state(html)
        data[self._control(page.controls, "BidDescription")] = " ".join(query.keywords)
        data[self._control(page.controls, "BidNumber")] = query.bid_number or ""
        bid_type_control = next(
            (
                name
                for suffix in ("BidTypeDropBox", "BidType")
                for name in page.controls
                if name.lower().endswith(suffix.lower())
            ),
            None,
        )
        if not bid_type_control:
            raise TylerMunisVssError("required bid type control is absent")
        data[bid_type_control] = (
            query.bid_type or self.profile.default_bid_type
        )
        data[self._control(page.controls, "OpenBidsOnly")] = (
            "on" if query.open_only is not False else "off"
        )
        data[self._control(page.controls, "Search")] = "Search"
        return data

    def normalize(self, row: Mapping[str, str]) -> RawOpportunity:
        number, title = row.get("bid_number", "").strip(), row.get("title", "").strip()
        if not number or not title:
            raise TylerMunisVssError("result lacks required identity or title")
        status_text = row.get("status", "")
        status = (
            OpportunityStatus.OPEN if "open" in status_text.lower() else OpportunityStatus.UNKNOWN
        )
        payload = {k: v for k, v in row.items() if k not in {"detail_target", "detail_argument"}}
        payload["detail_navigation"] = {
            "target": row.get("detail_target", ""),
            "argument": row.get("detail_argument", ""),
        }
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.profile.jurisdiction,
                source_id=f"{self.profile.key}:{number}",
                opportunity_url=self.profile.url(self.profile.search_path),
            ),
            title=title,
            agency=self.profile.display_name,
            solicitation_number=number,
            status=status,
            due_at=self._date(row.get("due_date")),
            raw_payload=payload,
        )

    @staticmethod
    def _date(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=UTC)
            except ValueError:
                pass
        return None

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = query if isinstance(query, TylerMunisVssQuery) else TylerMunisVssQuery(**query.__dict__)
        response = await self._request("get", self.profile.url(self.profile.search_path))
        self._validate_response(response, "__VIEWSTATE")
        response = await self._request(
            "post",
            self.profile.url(self.profile.search_path),
            data=self.search_form(response.text, q),
        )
        if response.is_redirect:
            self._validate_response(response, self.profile.results_path)
            response = await self._request(
                "get", urljoin(str(response.url), response.headers["location"])
            )
        self._validate_response(response, "bid-results")
        seen: set[str] = set()
        fingerprints: set[str] = set()
        count = 0
        for page_index in range(self.profile.maximum_pages):
            page = parse_page(response.text)
            fingerprint = hashlib.sha256(
                "|".join(r.get("bid_number", "") for r in page.rows).encode()
            ).hexdigest()
            if fingerprint in fingerprints:
                break
            fingerprints.add(fingerprint)
            for row in page.rows:
                item = self.normalize(row)
                if item.source.source_id in seen:
                    continue
                seen.add(item.source.source_id)
                yield item
                count += 1
                if count >= min(query.limit, self.profile.maximum_results):
                    return
            next_event = page.page_events.get(page_index + 1) or page.next_event
            if not next_event:
                return
            state = form_state(response.text, require_event_validation=True)
            state["__EVENTTARGET"], state["__EVENTARGUMENT"] = next_event
            response = await self._request(
                "post", self.profile.url(self.profile.results_path), data=state
            )
            self._validate_response(response, "bid-results")

    async def detail(
        self, results_html: str, source_id: str
    ) -> tuple[dict[str, str], list[DocumentCandidate]]:
        page = parse_page(results_html)
        row = next((r for r in page.rows if r.get("bid_number") == source_id), None)
        if not row or not row.get("detail_target"):
            raise TylerMunisVssError("detail transition is unavailable")
        state = form_state(results_html, require_event_validation=True)
        state["__EVENTTARGET"], state["__EVENTARGUMENT"] = (
            row["detail_target"],
            row.get("detail_argument", ""),
        )
        response = await self._request(
            "post", self.profile.url(self.profile.results_path), data=state
        )
        if response.is_redirect:
            self._validate_response(response, self.profile.detail_path)
            response = await self._request(
                "get", urljoin(str(response.url), response.headers["location"])
            )
        self._validate_response(response, "bid-detail")
        detail = parse_page(response.text)
        docs = []
        for item in detail.documents:
            url = urljoin(str(response.url), item["url"])
            _safe_url(url, self.profile.allowed_hosts)
            if (
                urlparse(url).path.lower()
                != urlparse(self.profile.url(self.profile.document_path)).path.lower()
            ):
                raise TylerMunisVssError("unsupported document route")
            doc_id = item.get("document_id", "")
            stable = hashlib.sha256(
                f"{self.profile.key}|{source_id}|{doc_id}|{item.get('title', '')}|{item.get('category', 'attachment')}".encode()
            ).hexdigest()
            docs.append(
                DocumentCandidate(
                    opportunity_id=f"{self.profile.key}:{source_id}",
                    source_document_url=url,
                    source_opportunity_url=self.profile.url(self.profile.search_path),
                    filename=item.get("filename") or item.get("title", "document"),
                    label=item.get("title"),
                    mime_type=item.get("media_type") or self._document_mime(item.get("filename")),
                    category=item.get("category", "attachment"),
                    source_document_id=stable,
                    access_state=AccessState.PUBLIC,
                    publicly_retrievable=True,
                    raw_metadata={
                        "document_id": doc_id,
                        "retrieval_url": redact_url(url),
                        "ephemeral_url": True,
                    },
                )
            )
        return detail.fields, docs

    @staticmethod
    def _document_mime(filename: str | None) -> str | None:
        suffix = (filename or "").rsplit(".", 1)[-1].casefold()
        return {
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }.get(suffix)

    async def reacquire_document_url(
        self, results_html: str, source_id: str, stable_id: str
    ) -> str:
        _, docs = await self.detail(results_html, source_id)
        match = next((d for d in docs if d.source_document_id == stable_id), None)
        if not match:
            raise TylerMunisVssError("document is no longer publicly listed")
        return str(match.source_document_url)
