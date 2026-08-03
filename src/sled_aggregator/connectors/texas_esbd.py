"""Public, read-only Texas Electronic State Business Daily connector.

The official browser is implemented by Texas SmartBuy.  This adapter performs
only bounded anonymous GET searches and detail retrieval; it never enters the
catalog, supplier registration, authentication, cart, or response workflows.
"""

import asyncio
import email.utils
import hashlib
import json
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

CENTRAL = ZoneInfo("America/Chicago")


class ESBDAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_SESSION_REQUIRED = "public_session_required"
    EXTERNAL_PUBLIC = "external_public"
    EXTERNAL_ACCOUNT_REQUIRED = "external_account_required"
    LOGIN_REQUIRED = "login_required"
    RESTRICTED = "restricted"
    CAPTCHA = "captcha"
    FORBIDDEN = "forbidden"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ESBDError(RuntimeError):
    pass


class ESBDAccessError(ESBDError):
    def __init__(self, state: ESBDAccessState) -> None:
        self.state = state
        super().__init__(f"Texas ESBD public access ended at {state.value}")


class ESBDAvailabilityError(ESBDError):
    pass


@dataclass(frozen=True, slots=True)
class ESBDPortal:
    base_url: str = "https://www.txsmartbuy.gov/"
    search_path: str = "esbd"
    detail_path: str = "esbd/solicitation/"
    jurisdiction: str = "Texas"
    country_subdivision: str = "US-TX"
    source_system: str = "Texas Electronic State Business Daily"

    @property
    def search_url(self) -> str:
        return urljoin(self.base_url, self.search_path)


TEXAS_ESBD = ESBDPortal()


@dataclass(frozen=True, slots=True)
class ESBDQuery(ConnectorQuery):
    solicitation_id: str | None = None
    agency_name: str | None = None
    agency_number: str | None = None
    status: str | None = None
    nigp_class: str | None = None
    nigp_item: str | None = None
    posted_from: str | None = None
    posted_to: str | None = None
    response_from: str | None = None
    response_to: str | None = None


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ESBDHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    access_state: ESBDAccessState
    skipped_records: int


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


class _ESBDParser(HTMLParser):
    """Parse label-oriented ESBD markup without relying on presentation classes."""

    fields = {
        "solicitation id": "solicitation_id",
        "solicitation number": "solicitation_id",
        "agency": "agency_name",
        "agency name": "agency_name",
        "agency number": "agency_number",
        "member number": "agency_number",
        "status": "status",
        "posting date": "posting_date",
        "response due date": "response_due",
        "response deadline": "response_due",
        "award date": "award_date",
        "last modified": "last_modified",
        "estimated value": "estimated_value",
        "estimated quantity": "estimated_quantity",
        "estimated needed date": "estimated_needed_date",
        "nigp class/item": "nigp",
        "nigp code": "nigp",
        "contact name": "contact_name",
        "contact email": "contact_email",
        "contact phone": "contact_phone",
        "contact address": "contact_address",
        "hub requirement": "hub_requirements",
        "hsp required": "hsp_requirement",
        "pre-bid conference": "pre_bid_conference",
        "description": "description",
        "award information": "award_information",
    }

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self._depth = 0
        self._field: str | None = None
        self._label: str | None = None
        self._tag = ""
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        is_record = "data-esbd-record" in values or "data-solicitation-id" in values
        if self.current is None and is_record:
            self.current = {
                key[5:].replace("-", "_"): value
                for key, value in values.items()
                if key.startswith("data-")
            }
            self._depth = 1
        elif self.current is not None:
            self._depth += 1
        self._tag, self._attrs, self._text = tag, values, []
        if self.current is not None:
            self._field = values.get("data-field") or self._field
        if tag == "a" and values.get("href"):
            self._href = str(values["href"])

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = _clean("".join(self._text))
        if self.current is not None:
            if self._tag in {"th", "dt", "label"} and text:
                self._label = text.casefold().rstrip(":")
            elif self._field and text:
                self.current[self._field.replace("-", "_")] = text
            elif self._tag in {"td", "dd", "span", "div"} and self._label and text:
                field = self.fields.get(self._label)
                if field:
                    self.current[field] = text
                self._label = None
            if tag == "a" and self._href:
                kind = (self._attrs.get("data-link-type") or "").casefold()
                item = {
                    "title": text or self._attrs.get("title") or "Document",
                    "url": self._href,
                    "access": self._attrs.get("data-access"),
                    "posted": self._attrs.get("data-posted"),
                    "version": self._attrs.get("data-version"),
                }
                if kind == "response":
                    self.current["external_response_url"] = self._href
                elif kind == "document" or re.search(
                    r"\.pdf|\.docx?|\.xlsx?|\.zip|addend|amend|award|scope|"
                    r"specification|bid form|hsp",
                    f"{text} {self._href}",
                    re.I,
                ):
                    self.current.setdefault("documents", []).append(item)
                else:
                    self.current.setdefault("url", self._href)
                self._href = None
            self._depth -= 1
            if self._depth == 0:
                self.records.append(self.current)
                self.current = None
        self._field, self._text = None, []


class TexasESBDConnector(BaseConnector):
    platform_family = "texas/esbd"
    jurisdictions = ("Texas",)
    document_pipeline_compatible = True
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: ESBDPortal = TEXAS_ESBD,
        *,
        transport: AsyncGetTransport | None = None,
        page_size: int = 25,
        max_pages: int = 10,
        max_results: int = 250,
        max_details: int = 50,
        max_retries: int = 3,
        timeout: float = 30,
        user_agent: str = "TrustEST-SLED-Aggregator/0.1 (public read-only)",
        concurrency: int = 4,
        backoff_seconds: float = 0.5,
        jitter_seconds: float = 0.25,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 60,
        fetch_details: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if min(page_size, max_pages, max_results, max_details, concurrency) < 1:
            raise ValueError("limits must be positive")
        self.portal = portal
        self.page_size, self.max_pages, self.max_results = page_size, max_pages, max_results
        self.max_details, self.max_retries, self.fetch_details = (
            max_details,
            max_retries,
            fetch_details,
        )
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._owns_transport = transport is None
        self._semaphore = asyncio.Semaphore(concurrency)
        self._failures = 0
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._access = ESBDAccessState.UNKNOWN
        self._skipped = 0

    async def __aenter__(self) -> "TexasESBDConnector":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> ESBDHealth:
        opened = self._circuit_is_open()
        return ESBDHealth(
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
        if query.limit < 1 or (
            query.jurisdiction and query.jurisdiction.casefold() not in {"texas", "tx", "us-tx"}
        ):
            return
        if self._circuit_is_open():
            raise ESBDAvailabilityError("Texas ESBD circuit breaker is open")
        pages: set[str] = set()
        records: dict[str, dict[str, Any]] = {}
        try:
            for page in range(1, self.max_pages + 1):
                response = await self._request(
                    self.portal.search_url, self._query_params(query, page)
                )
                parsed = self._records(response)
                fingerprint = hashlib.sha256(
                    json.dumps(parsed, sort_keys=True, default=str).encode()
                ).hexdigest()
                if not parsed or fingerprint in pages:
                    break
                pages.add(fingerprint)
                for record in parsed:
                    identity = self._identity(record)
                    if identity:
                        records[identity] = record
                    else:
                        self._skipped += 1
                if len(parsed) < self.page_size:
                    break
            yielded = details = 0
            for identity in sorted(records):
                record = records[identity]
                direct = self._safe_url(record.get("url"), self.portal.search_url)
                if self.fetch_details and direct and details < self.max_details:
                    detail_records = self._records(await self._request(direct, {}))
                    if detail_records:
                        detail_record = detail_records[0]
                        documents = [
                            *record.get("documents", []),
                            *detail_record.get("documents", []),
                        ]
                        record = {**record, **detail_record, "documents": documents}
                    details += 1
                try:
                    opportunity = self._normalize(identity, record)
                except (ESBDError, ValueError):
                    self._skipped += 1
                    continue
                yield opportunity
                yielded += 1
                if yielded >= min(query.limit, self.max_results):
                    return
        except Exception:
            self._record_failure()
            raise

    def _query_params(self, query: ConnectorQuery, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "pageSize": self.page_size,
            "keyword": " ".join(query.keywords).strip(),
        }
        if isinstance(query, ESBDQuery):
            for attr, key in (
                ("solicitation_id", "solicitationId"),
                ("agency_name", "agencyName"),
                ("agency_number", "agencyNumber"),
                ("status", "status"),
                ("posted_from", "postedFrom"),
                ("posted_to", "postedTo"),
                ("response_from", "responseFrom"),
                ("response_to", "responseTo"),
            ):
                if value := getattr(query, attr):
                    params[key] = value
            if query.nigp_class:
                params["nigpClass"] = self.normalize_nigp(query.nigp_class)
            if query.nigp_item:
                params["nigpItem"] = self.normalize_nigp(query.nigp_item)
        return params

    async def _request(self, url: str, params: Mapping[str, Any]) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                async with self._semaphore:
                    response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise ESBDAvailabilityError("Texas ESBD connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if response.status_code in self._transient:
                self._access = ESBDAccessState.UNAVAILABLE
                if attempt == self.max_retries:
                    raise ESBDAvailabilityError(f"Texas ESBD unavailable ({response.status_code})")
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access = ESBDAccessState.FORBIDDEN
                raise ESBDAccessError(self._access)
            if response.status_code >= 400:
                raise ESBDError(f"Texas ESBD returned HTTP {response.status_code}")
            state = self._detect_access(response)
            if state != ESBDAccessState.PUBLIC:
                self._access = state
                raise ESBDAccessError(state)
            self._failures, self._last_failure = 0, None
            self._last_success, self._access = self._now(), state
            return response
        raise AssertionError("retry loop exhausted")

    def _records(self, response: httpx.Response) -> list[dict[str, Any]]:
        if "html" not in response.headers.get("content-type", "text/html").casefold():
            raise ESBDError("unexpected Texas ESBD content type")
        parser = _ESBDParser()
        try:
            parser.feed(response.text)
        except (ValueError, AssertionError) as exc:
            raise ESBDError("malformed Texas ESBD HTML") from exc
        if not parser.records and not re.search(
            r"no (matching )?(solicitations|records|results)", response.text, re.I
        ):
            raise ESBDError("unexpected Texas ESBD response shape")
        return parser.records

    def _normalize(self, identity: str, record: dict[str, Any]) -> RawOpportunity:
        solicitation = self._optional(record.get("solicitation_id"))
        internal = self._internal_id(record)
        if not internal and not solicitation:
            raise ESBDError("ESBD identity is required")
        title = _clean(str(record.get("title") or ""))
        agency = _clean(str(record.get("agency_name") or ""))
        if not title or not agency:
            raise ESBDError("ESBD title and agency are required")
        opportunity_url = self._safe_url(record.get("url"), self.portal.search_url)
        if not opportunity_url and internal:
            opportunity_url = urljoin(self.portal.base_url, f"{self.portal.detail_path}{internal}")
        if not opportunity_url:
            opportunity_url = self.portal.search_url
        observed = self._now()
        payload = dict(record)
        payload["texas_esbd"] = {
            "internal_id": internal,
            "agency_number": self._optional(record.get("agency_number")),
            "solicitation_id": solicitation,
            "country_subdivision": self.portal.country_subdivision,
            "source_system": self.portal.source_system,
            "source_status": self._optional(record.get("status")),
            "last_seen_at": observed.isoformat(),
            "visibility_gap_policy": "retain_last_known; absence_is_not_deletion",
            "response_deadline_original": self._optional(record.get("response_due")),
            "response_time_inferred": False,
        }
        payload["document_links"] = self._documents(record, identity, opportunity_url)
        external = self._safe_url(record.get("external_response_url"), opportunity_url)
        if external:
            payload["external_response_url"] = external
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=identity,
                opportunity_url=opportunity_url,
            ),
            title=title,
            agency=agency,
            description=self._optional(record.get("description")),
            solicitation_number=solicitation,
            status=self._status(record.get("status")),
            posted_at=self._date(record.get("posting_date")),
            due_at=self._date(record.get("response_due")),
            categories=self._categories(record.get("nigp")),
            raw_payload=payload,
        )

    def _documents(
        self, record: dict[str, Any], identity: str, parent_url: str
    ) -> list[dict[str, Any]]:
        result = []
        seen: set[str] = set()
        for document in (
            record.get("documents", []) if isinstance(record.get("documents"), list) else []
        ):
            if not isinstance(document, dict):
                continue
            url = self._safe_url(document.get("url"), parent_url)
            if not url or url in seen:
                continue
            seen.add(url)
            parsed, title = urlparse(url), str(document.get("title") or "Document")
            internal = parsed.hostname == urlparse(self.portal.base_url).hostname
            access_text = f"{document.get('access', '')} {title} {url}".casefold()
            access = (
                ESBDAccessState.EXTERNAL_ACCOUNT_REQUIRED.value
                if not internal and re.search(r"account|login|register", access_text)
                else ESBDAccessState.EXTERNAL_PUBLIC.value
                if not internal
                else ESBDAccessState.PUBLIC.value
            )
            category = (
                "addendum"
                if re.search(r"addend|amend", title, re.I)
                else "award_notice"
                if re.search(r"award|intent", title, re.I)
                else "questions_answers"
                if re.search(r"question|answer|q&a", title, re.I)
                else "solicitation"
            )
            filename = parsed.path.rsplit("/", 1)[-1]
            result.append(
                {
                    "title": title,
                    "file_name": filename or None,
                    "apparent_file_type": filename.rsplit(".", 1)[-1].lower()
                    if "." in filename
                    else None,
                    "source_url": url,
                    "document_category": category,
                    "addendum_or_version": document.get("version"),
                    "posted_or_modified_date": document.get("posted"),
                    "access_state": access,
                    "parent_opportunity_id": identity,
                    "parent_opportunity_url": parent_url,
                    "internal_esbd_media": internal
                    and parsed.path.casefold().endswith("/core/media/media.nl"),
                    "external": not internal,
                }
            )
        return result

    def document_candidates(self, opportunity: RawOpportunity) -> list[DocumentCandidate]:
        """Adapt public ESBD media and preserve gated external links as metadata."""
        result: list[DocumentCandidate] = []
        seen: set[str] = set()
        for item in opportunity.raw_payload.get("document_links", []):
            if not isinstance(item, dict) or not item.get("source_url"):
                continue
            url = str(item["source_url"])
            if url in seen:
                continue
            seen.add(url)
            source_state = str(item.get("access_state") or "unknown")
            public = source_state in {
                ESBDAccessState.PUBLIC.value,
                ESBDAccessState.EXTERNAL_PUBLIC.value,
            }
            label = str(item.get("title") or item.get("file_name") or "document")
            version = item.get("addendum_or_version")
            match = re.search(r"\d+", str(version or ""))
            addendum = match.group() if item.get("document_category") == "addendum" and match else None
            parsed = urlparse(url)
            source_id = next(
                (parse_qs(parsed.query)[key][0] for key in ("id", "file", "h") if parse_qs(parsed.query).get(key)),
                None,
            )
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=url,
                    source_opportunity_url=opportunity.source.opportunity_url,
                    source_detail_url=opportunity.source.opportunity_url,
                    filename=re.sub(
                        r'[^A-Za-z0-9._ -]', "_", str(item.get("file_name") or label)
                    ),
                    label=label,
                    source_document_id=source_id,
                    category=item.get("document_category"),
                    access_state=AccessState.PUBLIC if public else AccessState.REGISTRATION_REQUIRED,
                    publicly_retrievable=public,
                    version_label=str(version) if version not in (None, "") else None,
                    version_number=int(match.group()) if match else None,
                    addendum_number=addendum,
                    posted_at=self._date(item.get("posted_or_modified_date")),
                    raw_metadata={
                        "source_access_state": source_state,
                        "internal_esbd_media": bool(item.get("internal_esbd_media")),
                        "authoritative_detail_url": str(opportunity.source.opportunity_url),
                    },
                )
            )
        return result

    @staticmethod
    def normalize_nigp(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z]", "", value)

    @staticmethod
    def _categories(value: Any) -> list[str]:
        return [_clean(x) for x in re.split(r"[,;\n]", str(value or "")) if _clean(x)]

    @staticmethod
    def _internal_id(record: Mapping[str, Any]) -> str | None:
        value = record.get("esbd_id") or record.get("record_id") or record.get("esbd_record")
        if not value and record.get("url"):
            query = parse_qs(urlparse(str(record["url"])).query)
            value = next((query[k][0] for k in ("id", "recordId", "esbdId") if query.get(k)), None)
            if not value:
                match = re.search(r"/solicitation/([^/?#]+)", str(record["url"]), re.I)
                value = match.group(1) if match else None
        return str(value).strip() if value else None

    def _identity(self, record: Mapping[str, Any]) -> str | None:
        internal = self._internal_id(record)
        if internal:
            return f"esbd:{internal}"
        solicitation = self._optional(record.get("solicitation_id"))
        agency = self._optional(record.get("agency_number"))
        return f"agency:{agency}:{solicitation}" if solicitation and agency else solicitation

    @staticmethod
    def _safe_url(value: Any, base: str) -> str | None:
        if not value:
            return None
        resolved = urljoin(base, str(value).strip())
        parsed = urlparse(resolved)
        return resolved if parsed.scheme in {"http", "https"} and parsed.hostname else None

    @staticmethod
    def _status(value: Any) -> OpportunityStatus:
        text = str(value or "").casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if "closed" in text:
            return OpportunityStatus.CLOSED
        if "pre-solicitation" in text:
            return OpportunityStatus.FORECAST
        if text in {"posted", "addendum posted"}:
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not value:
            return None
        text = _clean(str(value)).replace(" CT", "")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=CENTRAL)
        except ValueError:
            pass
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=CENTRAL)
            except ValueError:
                continue
        return None

    @staticmethod
    def _optional(value: Any) -> str | None:
        return _clean(str(value)) if value not in (None, "") else None

    def _detect_access(self, response: httpx.Response) -> ESBDAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        for state, markers in (
            (ESBDAccessState.CAPTCHA, ("captcha", "recaptcha", "bot challenge")),
            (ESBDAccessState.MAINTENANCE, ("scheduled maintenance", "down for maintenance")),
            (
                ESBDAccessState.LOGIN_REQUIRED,
                ("supplier login", "please sign in", "email address and password"),
            ),
            (ESBDAccessState.RESTRICTED, ("access denied", "not authorized")),
        ):
            if any(marker in text for marker in markers):
                return state
        if any(marker in url for marker in ("login", "signin", "authenticate")):
            return ESBDAccessState.LOGIN_REQUIRED
        if not text.strip() or re.search(r"<title>\s*(error|request failed)\s*</title>", text):
            return ESBDAccessState.UNKNOWN
        return ESBDAccessState.PUBLIC

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_seconds * 2**attempt + self.jitter_seconds * self._random()
        if retry_after:
            try:
                retry = max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                retry = max(0.0, (parsed - self._now()).total_seconds())
            delay = max(delay, retry)
        return delay

    def _record_failure(self) -> None:
        self._failures += 1
        self._last_failure = self._now()

    def _circuit_is_open(self) -> bool:
        return bool(
            self._failures >= self.circuit_breaker_threshold
            and self._last_failure
            and self._now() < self._last_failure + timedelta(seconds=self.circuit_breaker_cooldown)
        )
