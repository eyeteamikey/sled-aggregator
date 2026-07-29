"""Virginia eVA public-board connector.

Only anonymous public GET navigation is implemented.  Account, response, and
challenge workflows are deliberately represented as access states, never automated.
"""

import asyncio
import email.utils
import json
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef


class EVAAccessState(StrEnum):
    PUBLIC_NO_LOGIN = "public_no_login"
    PUBLIC_SESSION_REQUIRED = "public_session_required"
    FREE_ACCOUNT_REQUIRED = "free_account_required"
    LOGIN_REQUIRED = "login_required"
    RESTRICTED = "restricted"
    CAPTCHA_BLOCKED = "captcha_blocked"
    FORBIDDEN = "forbidden"
    ROBOTS_RESTRICTED = "robots_restricted"
    MAINTENANCE = "maintenance"
    SESSION_EXPIRED = "session_expired"
    UNAVAILABLE = "unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN = "unknown"


class EVAPublicSession(StrEnum):
    NOT_STARTED = "not_started"
    ANONYMOUS = "anonymous"
    REQUIRED = "public_session_required"
    EXPIRED = "session_expired"


class EVANoticeType(StrEnum):
    IFB = "ifb"
    RFP = "rfp"
    RFQ = "rfq"
    RFI = "rfi"
    QUICK_QUOTE = "quick_quote"
    UNSEALED_BID = "unsealed_bid"
    SOLE_SOURCE = "sole_source"
    EMERGENCY = "emergency"
    AWARD = "award_notice"
    CANCELLATION = "cancellation"
    AMENDMENT = "amendment"
    NOTICE_ONLY = "notice_only"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class EVAPortal:
    identifier: str = "virginia-eva"
    name: str = "Virginia eVA"
    jurisdiction: str = "Virginia"
    base_url: str = "https://mvendor.cgieva.com/Vendor/public/"
    search_path: str = "PublicSearch.jsp"
    board_path: str = "AllOpportunities.jsp"
    detail_variants: tuple[str, ...] = ("IVDetailsV2.jsp", "IVDetails.jsp")
    anonymous_session_required: bool = True

    @property
    def search_url(self) -> str:
        return urljoin(self.base_url, self.search_path)

    @property
    def board_url(self) -> str:
        return urljoin(self.base_url, self.board_path)


VIRGINIA_EVA = EVAPortal()


@dataclass(frozen=True, slots=True)
class EVAQuery(ConnectorQuery):
    solicitation_number: str | None = None
    lot_id: str | None = None
    agency_name: str | None = None
    status: str | None = "Open"
    notice_type: str | None = None
    issue_from: str | None = None
    issue_to: str | None = None
    closing_from: str | None = None
    closing_to: str | None = None
    nigp_code: str | None = None
    locality: str | None = None


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class EVAError(RuntimeError):
    pass


class EVAAccessError(EVAError):
    def __init__(self, state: EVAAccessState) -> None:
        self.state = state
        super().__init__(f"eVA public access ended at {state.value}")


class EVAAvailabilityError(EVAError):
    pass


@dataclass(frozen=True, slots=True)
class EVAHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    access_state: EVAAccessState
    public_session_state: EVAPublicSession
    active_detail_variant: str | None
    portal_identifier: str
    skipped_records: int


class _EVAParser(HTMLParser):
    """Tolerant strategy for both observed detail variants and result rows."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._record: dict[str, Any] | None = None
        self._field: str | None = None
        self._href: str | None = None
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag in {"tr", "article", "div"} and (
            classes.intersection({"opportunity", "opportunity-row", "eva-opportunity", "detail"})
            or values.get("data-lot-id")
        ):
            self._record = {
                key[5:].replace("-", "_"): value
                for key, value in values.items()
                if key.startswith("data-")
            }
        if self._record is not None:
            self._field = values.get("data-field") or next(
                (
                    name
                    for name in (
                        "title",
                        "agency",
                        "status",
                        "notice_type",
                        "posted",
                        "due",
                        "solicitation_number",
                        "description",
                        "nigp",
                        "locality",
                    )
                    if name in classes
                ),
                None,
            )
        if tag == "a" and values.get("href"):
            self._href, self._attrs = str(values["href"]), values
        self._text = []

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._text).split())
        if self._record is not None and self._field and text:
            self._record[self._field] = text
        if tag == "a" and self._href and self._record is not None:
            if re.search(
                r"document|attachment|rfp|ifb|rfq|spec|scope|sow|pricing|form|exhibit|drawing|plan|addend|amend|question|award|cancel|justification",
                text,
                re.I,
            ) or self._attrs.get("data-document-id"):
                self._record.setdefault("documents", []).append(
                    {
                        "title": text or "Document",
                        "url": self._href,
                        "attachment_id": self._attrs.get("data-document-id"),
                        "access": self._attrs.get("data-access"),
                        "posted": self._attrs.get("data-posted"),
                        "round": self._attrs.get("data-round"),
                    }
                )
            else:
                self._record.setdefault("url", self._href)
            self._href, self._attrs = None, {}
        if tag in {"tr", "article", "div"} and self._record is not None:
            if self._record:
                self.records.append(self._record)
            self._record = None
        self._field, self._text = None, []


class EVAConnector(BaseConnector):
    platform_family = "virginia/eva"
    jurisdictions = ("Virginia",)
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: EVAPortal = VIRGINIA_EVA,
        *,
        transport: AsyncGetTransport | None = None,
        page_size: int = 25,
        max_pages: int = 10,
        max_results: int = 250,
        max_details: int = 50,
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
        if min(page_size, max_pages, max_results, max_details, circuit_breaker_threshold) < 1:
            raise ValueError("limits must be positive")
        self.portal, self.page_size, self.max_pages, self.max_results = (
            portal,
            page_size,
            max_pages,
            max_results,
        )
        self.max_details, self.max_retries, self.fetch_details = (
            max_details,
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
            follow_redirects=True,
            headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1 (public read-only)"},
        )
        self._owns_transport = transport is None
        self._failures = 0
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._access = EVAAccessState.UNKNOWN
        self._session = EVAPublicSession.NOT_STARTED
        self._variant: str | None = None
        self._skipped = 0

    @property
    def health(self) -> EVAHealth:
        opened = self._circuit_is_open()
        return EVAHealth(
            not opened and self._failures == 0,
            opened,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._access,
            self._session,
            self._variant,
            self.portal.identifier,
            self._skipped,
        )

    async def __aenter__(self) -> "EVAConnector":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    def board_url(self, *, status: str | None = None, agency_name: str | None = None) -> str:
        params = {
            key: value for key, value in (("status", status), ("agencyname", agency_name)) if value
        }
        return f"{self.portal.board_url}?{urlencode(params)}" if params else self.portal.board_url

    def detail_url(
        self, lot_id: str, round_number: int | str = 0, variant: str | None = None
    ) -> str:
        path = variant or self.portal.detail_variants[0]
        params = {
            "PageTitle": "SO Details",
            "rfp_id_lot": lot_id,
            "rfp_id_round": round_number,
        }
        return f"{urljoin(self.portal.base_url, path)}?{urlencode(params)}"

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        if query.limit < 1 or (
            query.jurisdiction and query.jurisdiction.casefold() not in {"virginia", "va"}
        ):
            return
        if self._circuit_is_open():
            raise EVAAvailabilityError("eVA circuit breaker is open")
        seen_pages: set[str] = set()
        by_lot: dict[str, list[dict[str, Any]]] = {}
        try:
            for page in range(1, self.max_pages + 1):
                params = self._query_params(query, page)
                response = await self._request(self.portal.board_url, params)
                records = self._records(response)
                fingerprint = json.dumps(records, sort_keys=True, default=str)
                if fingerprint in seen_pages or not records:
                    break
                seen_pages.add(fingerprint)
                for record in records:
                    identity = self._identity(record)
                    if identity:
                        by_lot.setdefault(identity, []).append(record)
                    else:
                        self._skipped += 1
                if len(records) < self.page_size:
                    break
            yielded = details = 0
            for lot, rounds in by_lot.items():
                record = max(rounds, key=lambda row: self._round(row))
                history = sorted({self._round(row) for row in rounds})
                direct = record.get("url")
                if self.fetch_details and direct and details < self.max_details:
                    detail_url = urljoin(self.portal.base_url, str(direct))
                    variant = (
                        "IVDetailsV2.jsp"
                        if "ivdetailsv2" in detail_url.casefold()
                        else "IVDetails.jsp"
                    )
                    detail = await self._request(detail_url, {})
                    parsed = self._records(detail)
                    if parsed:
                        record = {**record, **parsed[0]}
                    self._variant, details = variant, details + 1
                try:
                    item = self._normalize(lot, record, history)
                except EVAError:
                    self._skipped += 1
                    continue
                yield item
                yielded += 1
                if yielded >= min(query.limit, self.max_results):
                    return
        except Exception:
            self._failures += 1
            self._last_failure = self._now()
            raise

    def _query_params(self, query: ConnectorQuery, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "pagesize": self.page_size,
            "keyword": " ".join(query.keywords).strip(),
        }
        if isinstance(query, EVAQuery):
            for attr, key in (
                ("solicitation_number", "solicitation"),
                ("lot_id", "rfp_id_lot"),
                ("agency_name", "agencyname"),
                ("status", "status"),
                ("notice_type", "noticetype"),
                ("issue_from", "issuefrom"),
                ("issue_to", "issueto"),
                ("closing_from", "closingfrom"),
                ("closing_to", "closingto"),
                ("nigp_code", "nigp"),
                ("locality", "locality"),
            ):
                value = getattr(query, attr)
                if value:
                    params[key] = value
        return params

    async def _request(self, url: str, params: Mapping[str, Any]) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise EVAAvailabilityError("eVA connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if response.status_code in self._transient:
                self._access = EVAAccessState.UNAVAILABLE
                if attempt == self.max_retries:
                    raise EVAAvailabilityError(
                        f"eVA temporarily unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access = EVAAccessState.FORBIDDEN
                raise EVAAccessError(self._access)
            if response.status_code >= 400:
                raise EVAError(f"eVA returned HTTP {response.status_code}")
            state = self._detect_access(response)
            if state not in {
                EVAAccessState.PUBLIC_NO_LOGIN,
                EVAAccessState.PUBLIC_SESSION_REQUIRED,
            }:
                self._access = state
                if state == EVAAccessState.SESSION_EXPIRED:
                    self._session = EVAPublicSession.EXPIRED
                raise EVAAccessError(state)
            self._failures, self._last_failure, self._last_success, self._access = (
                0,
                None,
                self._now(),
                state,
            )
            self._session = (
                EVAPublicSession.REQUIRED
                if state == EVAAccessState.PUBLIC_SESSION_REQUIRED
                else EVAPublicSession.ANONYMOUS
            )
            return response
        raise AssertionError("retry loop exhausted")

    def _detect_access(self, response: httpx.Response) -> EVAAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        groups = (
            (EVAAccessState.CAPTCHA_BLOCKED, ("captcha", "recaptcha", "bot challenge")),
            (
                EVAAccessState.SESSION_EXPIRED,
                ("session expired", "session has expired", "invalid session"),
            ),
            (EVAAccessState.MAINTENANCE, ("scheduled maintenance", "down for maintenance")),
            (
                EVAAccessState.FREE_ACCOUNT_REQUIRED,
                ("vendor registration", "register as a vendor"),
            ),
            (
                EVAAccessState.LOGIN_REQUIRED,
                ("supplier login", "buyer login", "please log in", "electronic response login"),
            ),
            (EVAAccessState.RESTRICTED, ("unauthorized access", "access denied")),
        )
        for state, markers in groups:
            if any(marker in text for marker in markers):
                return state
        if any(marker in url for marker in ("login", "signin", "authenticate")):
            return EVAAccessState.LOGIN_REQUIRED
        if "javascript is required" in text and not re.search(r"data-lot-id|opportunity-row", text):
            return EVAAccessState.MALFORMED_RESPONSE
        return (
            EVAAccessState.PUBLIC_SESSION_REQUIRED
            if self.portal.anonymous_session_required
            else EVAAccessState.PUBLIC_NO_LOGIN
        )

    def _records(self, response: httpx.Response) -> list[dict[str, Any]]:
        if "html" not in response.headers.get("content-type", "text/html").casefold():
            self._access = EVAAccessState.MALFORMED_RESPONSE
            raise EVAError("unexpected eVA content type")
        parser = _EVAParser()
        try:
            parser.feed(response.text)
        except ValueError as exc:
            raise EVAError("malformed eVA response") from exc
        return parser.records

    def _normalize(self, lot: str, record: dict[str, Any], history: list[int]) -> RawOpportunity:
        title = str(record.get("title") or "").strip()
        if not title:
            raise EVAError("title is required")
        round_number = self._round(record)
        direct = str(record.get("url") or "")
        variant = "IVDetailsV2.jsp" if "ivdetailsv2" in direct.casefold() else "IVDetails.jsp"
        opportunity_url = (
            urljoin(self.portal.base_url, direct)
            if direct
            else self.detail_url(lot, round_number, variant)
        )
        payload = dict(record)
        payload["eva"] = {
            "lot_id": lot,
            "round": round_number,
            "round_history": history,
            "detail_variant": variant,
            "notice_type_normalized": self._notice_type(record.get("notice_type")).value,
            "authoritative": True,
        }
        payload["document_links"] = self._documents(record, opportunity_url, lot, round_number)
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=lot,
                opportunity_url=opportunity_url,
            ),
            title=title,
            agency=str(record.get("agency") or "Virginia eVA participating public body"),
            description=self._optional(record.get("description")),
            solicitation_number=self._optional(record.get("solicitation_number")),
            status=self._status(record.get("status")),
            posted_at=self._date(record.get("posted")),
            due_at=self._date(record.get("due")),
            categories=self._categories(record),
            raw_payload=payload,
        )

    def _documents(
        self, record: dict[str, Any], opportunity_url: str, lot: str, current_round: int
    ) -> list[dict[str, Any]]:
        result = []
        for doc in record.get("documents", []) if isinstance(record.get("documents"), list) else []:
            if not isinstance(doc, dict) or not doc.get("url"):
                continue
            title, url = (
                str(doc.get("title") or "Document"),
                urljoin(opportunity_url, str(doc["url"])),
            )
            access_text = f"{doc.get('access', '')} {url}".casefold()
            access = (
                "free_account_required"
                if re.search(r"register|account", access_text)
                else "login_required"
                if "login" in access_text
                else "public_session_required"
                if self.portal.anonymous_session_required
                else "public_no_login"
            )
            category = (
                "amendment"
                if re.search(r"addend|amend", title, re.I)
                else "award_notice"
                if re.search(r"award|intent", title, re.I)
                else "solicitation"
            )
            result.append(
                {
                    "title": title,
                    "file_name": urlparse(url).path.rsplit("/", 1)[-1],
                    "apparent_file_type": urlparse(url).path.rsplit(".", 1)[-1].lower()
                    if "." in urlparse(url).path
                    else None,
                    "source_url": url,
                    "opportunity_url": opportunity_url,
                    "attachment_identifier": doc.get("attachment_id"),
                    "lot_id": lot,
                    "round": int(doc.get("round") or current_round),
                    "document_category": category,
                    "posted_or_modified_date": doc.get("posted"),
                    "access_state": access,
                    "session_required": self.portal.anonymous_session_required,
                    "authoritative_source": True,
                }
            )
        return result

    @staticmethod
    def _identity(record: dict[str, Any]) -> str | None:
        lot = record.get("lot_id") or record.get("rfp_id_lot")
        if not lot and record.get("url"):
            lot = parse_qs(urlparse(str(record["url"])).query).get("rfp_id_lot", [None])[0]
        return str(lot).strip() if lot else None

    @staticmethod
    def _round(record: dict[str, Any]) -> int:
        value = record.get("round") or record.get("rfp_id_round")
        if value is None and record.get("url"):
            value = parse_qs(urlparse(str(record["url"])).query).get("rfp_id_round", [0])[0]
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _notice_type(value: Any) -> EVANoticeType:
        text = str(value or "").casefold()
        mappings = (
            (EVANoticeType.QUICK_QUOTE, ("quick quote",)),
            (EVANoticeType.UNSEALED_BID, ("unsealed",)),
            (EVANoticeType.SOLE_SOURCE, ("sole source",)),
            (EVANoticeType.EMERGENCY, ("emergency",)),
            (EVANoticeType.AWARD, ("award",)),
            (EVANoticeType.CANCELLATION, ("cancel",)),
            (EVANoticeType.AMENDMENT, ("amend", "addend")),
            (EVANoticeType.IFB, ("ifb", "invitation for bid", "sealed bid")),
            (EVANoticeType.RFP, ("rfp", "proposal", "ppea", "ppta")),
            (EVANoticeType.RFQ, ("rfq", "request for quote")),
            (EVANoticeType.RFI, ("rfi", "request for information")),
            (EVANoticeType.NOTICE_ONLY, ("notice", "future procurement")),
        )
        return next(
            (kind for kind, words in mappings if any(word in text for word in words)),
            EVANoticeType.OTHER,
        )

    @staticmethod
    def _status(value: Any) -> OpportunityStatus:
        text = str(value or "").casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if any(x in text for x in ("closed", "expired")):
            return OpportunityStatus.CLOSED
        if any(x in text for x in ("open", "active")):
            return OpportunityStatus.OPEN
        if any(x in text for x in ("future", "forecast")):
            return OpportunityStatus.FORECAST
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

    @staticmethod
    def _categories(record: dict[str, Any]) -> list[str]:
        return [
            part.strip()
            for part in str(record.get("nigp") or record.get("categories") or "").split(",")
            if part.strip()
        ]

    @staticmethod
    def _optional(value: Any) -> str | None:
        return str(value) if value not in (None, "") else None

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

    def _circuit_is_open(self) -> bool:
        return bool(
            self._failures >= self.circuit_breaker_threshold
            and self._last_failure
            and self._now() < self._last_failure + timedelta(seconds=self.circuit_breaker_cooldown)
        )
