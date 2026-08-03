import asyncio
import email.utils
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef

SEARCH_URL = "https://webprocure.proactiscloud.com/wp-full-text-search/search/sols"
PUBLIC_HOST = "webprocure.proactiscloud.com"


@dataclass(frozen=True, slots=True)
class WebProcurePortal:
    profile_key: str
    jurisdiction: str
    jurisdiction_code: str
    name: str
    customer_id: int
    owner_oid: int = -1

    def __post_init__(self) -> None:
        if not self.profile_key or len(self.jurisdiction_code) != 2 or self.customer_id < 1:
            raise ValueError("WebProcure profiles require a key, jurisdiction code, and customer ID")

    @property
    def bid_board_url(self) -> str:
        return (
            "https://webprocure.proactiscloud.com/wp-web-public/#/bidboard/search"
            f"?customerid={self.customer_id}&oid={self.owner_oid}"
        )


CONNECTICUT = WebProcurePortal("connecticut/ctsource", "Connecticut", "CT", "CTsource", 51)
MISSOURI = WebProcurePortal(
    "missouri/legacy-webprocure", "Missouri", "MO", "Missouri WebProcure legacy bid board", 38
)
RHODE_ISLAND = WebProcurePortal(
    "rhode-island/ocean-state-procures", "Rhode Island", "RI", "Ocean State Procures", 46, 120002
)
PORTALS = (CONNECTICUT, MISSOURI, RHODE_ISLAND)


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...

    async def aclose(self) -> None: ...


class WebProcureError(RuntimeError):
    """A WebProcure response cannot safely be consumed."""


class WebProcureAvailabilityError(WebProcureError):
    """The public endpoint is temporarily unavailable."""


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None


class WebProcureConnector(BaseConnector):
    """GET-only connector for WebProcure/PROACTIS public solicitation search."""

    platform_family = "webprocure/proactis"
    jurisdictions = tuple(portal.jurisdiction for portal in PORTALS)
    _transient_statuses = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: WebProcurePortal = CONNECTICUT,
        *,
        transport: AsyncGetTransport | None = None,
        page_size: int = 25,
        max_pages: int = 10,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        jitter_seconds: float = 0.25,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        for name, value in (("page_size", page_size), ("max_pages", max_pages)):
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if max_retries < 0 or circuit_breaker_threshold < 1 or circuit_breaker_cooldown < 0:
            raise ValueError("retry and circuit-breaker settings must be non-negative")
        self.portal = portal
        self.page_size = page_size
        self.max_pages = max_pages
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.jitter_seconds = jitter_seconds
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self._sleep = sleep
        self._random = random_value
        self._now = now
        self._transport = transport or httpx.AsyncClient(
            timeout=30, headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1"}
        )
        self._owns_transport = transport is None
        self._consecutive_failures = 0
        self._last_status_code: int | None = None
        self._last_failure_at: datetime | None = None

    @property
    def health(self) -> ConnectorHealth:
        open_ = self._circuit_is_open()
        return ConnectorHealth(
            available=self._consecutive_failures == 0 and not open_,
            circuit_open=open_,
            consecutive_failures=self._consecutive_failures,
            last_status_code=self._last_status_code,
            last_failure_at=self._last_failure_at,
        )

    async def __aenter__(self) -> "WebProcureConnector":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        if query.limit < 1:
            return
        if (
            query.jurisdiction
            and query.jurisdiction.casefold()
            not in {self.portal.jurisdiction.casefold(), self.portal.jurisdiction_code.casefold()}
        ):
            return
        if self._circuit_is_open():
            raise WebProcureAvailabilityError("WebProcure circuit breaker is open")

        seen: set[str] = set()
        yielded = 0
        search_term = " ".join(query.keywords).strip() or "*"
        try:
            for page in range(self.max_pages):
                payload = await self._request(
                    {
                        "customerid": self.portal.customer_id,
                        "q": search_term,
                        "from": page * self.page_size,
                        "sort": "r",
                        "f": "",
                        "oids": self.portal.owner_oid,
                    }
                )
                records = self._records(payload)
                for record in records:
                    item = self._normalize(record)
                    if item.source.source_id in seen:
                        continue
                    seen.add(item.source.source_id)
                    yield item
                    yielded += 1
                    if yielded >= query.limit:
                        return
                if len(records) < self.page_size:
                    return
        except Exception:
            self._record_failed_run()
            raise

    async def _request(self, params: Mapping[str, Any]) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._transport.get(SEARCH_URL, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise WebProcureAvailabilityError("WebProcure connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status_code = response.status_code
            if response.status_code in self._transient_statuses:
                if attempt == self.max_retries:
                    raise WebProcureAvailabilityError(
                        f"WebProcure temporarily unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise WebProcureError(f"WebProcure returned HTTP {response.status_code}") from exc
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                raise WebProcureError("WebProcure returned a non-JSON response")
            try:
                payload = response.json()
            except ValueError as exc:
                raise WebProcureError("WebProcure returned malformed JSON") from exc
            self._consecutive_failures = 0
            self._last_failure_at = None
            return payload
        raise AssertionError("retry loop exhausted")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_seconds * (2**attempt) + self.jitter_seconds * self._random()
        if retry_after:
            try:
                retry_delay = max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                retry_delay = max(0.0, (parsed - self._now()).total_seconds())
            delay = max(delay, retry_delay)
        return delay

    def _record_failed_run(self) -> None:
        self._consecutive_failures += 1
        self._last_failure_at = self._now()

    def _circuit_is_open(self) -> bool:
        if self._consecutive_failures < self.circuit_breaker_threshold or not self._last_failure_at:
            return False
        return self._now() < self._last_failure_at + timedelta(
            seconds=self.circuit_breaker_cooldown
        )

    @staticmethod
    def _records(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise WebProcureError("WebProcure response must be a JSON object")
        records: Any = payload.get("results", payload.get("solicitations", payload.get("hits")))
        if isinstance(records, dict):
            records = records.get("hits")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise WebProcureError("WebProcure response has an invalid results shape")
        return records

    def _normalize(self, record: dict[str, Any]) -> RawOpportunity:
        source = record.get("_source") if isinstance(record.get("_source"), dict) else record
        source_id = self._first(source, "id", "solicitationId", "bidId", "bidid", "solId")
        title = self._first(source, "title", "solicitationTitle", "bidTitle", "descriptionShort")
        if not source_id or not title:
            raise WebProcureError("WebProcure record requires source ID and title")
        agency = self._first(source, "agency", "organizationName", "department", "buyerName")
        direct_url = self._first(source, "url", "detailUrl", "solicitationUrl", "publicUrl")
        opportunity_url = self.portal.bid_board_url
        if direct_url and self._safe_public_url(str(direct_url)):
            opportunity_url = str(direct_url).strip()
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=str(source_id).strip(),
                opportunity_url=opportunity_url,
            ),
            title=str(title),
            agency=str(agency or self.portal.name),
            description=self._optional(source, "description", "solicitationDescription", "summary"),
            solicitation_number=self._optional(
                source, "solicitationNumber", "bidNumber", "solicitationNo", "number"
            ),
            status=self._status(self._optional(source, "status", "solicitationStatus")),
            posted_at=self._date(source, "postedDate", "publishDate", "createdDate"),
            due_at=self._date(source, "dueDate", "closeDate", "responseDeadline"),
            categories=self._categories(source),
            raw_payload=record,
        )

    @staticmethod
    def _safe_public_url(url: str) -> bool:
        parsed = urlsplit(url.strip())
        return bool(
            parsed.scheme == "https"
            and parsed.hostname == PUBLIC_HOST
            and not parsed.username
            and not parsed.password
        )

    @staticmethod
    def _first(record: Mapping[str, Any], *names: str) -> Any:
        return next((record[name] for name in names if record.get(name) not in (None, "")), None)

    @classmethod
    def _optional(cls, record: Mapping[str, Any], *names: str) -> str | None:
        value = cls._first(record, *names)
        return str(value) if value is not None else None

    @classmethod
    def _date(cls, record: Mapping[str, Any], *names: str) -> datetime | None:
        value = cls._first(record, *names)
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise WebProcureError(f"invalid WebProcure date: {value}") from exc

    @classmethod
    def _categories(cls, record: Mapping[str, Any]) -> list[str]:
        value = cls._first(record, "categories", "category", "commodityCodes", "nigpCodes")
        if value is None:
            return []
        if isinstance(value, list):
            return [
                str(item.get("name", item.get("code", "")) if isinstance(item, dict) else item)
                for item in value
                if item
            ]
        return [str(value)]

    @staticmethod
    def _status(value: str | None) -> OpportunityStatus:
        text = (value or "").casefold()
        for status, terms in {
            OpportunityStatus.OPEN: ("open", "active", "published"),
            OpportunityStatus.CLOSED: ("closed", "expired"),
            OpportunityStatus.AWARDED: ("awarded",),
            OpportunityStatus.CANCELLED: ("cancelled", "canceled"),
            OpportunityStatus.FORECAST: ("forecast", "planned"),
        }.items():
            if any(term in text for term in terms):
                return status
        return OpportunityStatus.UNKNOWN
