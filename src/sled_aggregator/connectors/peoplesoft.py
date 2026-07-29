"""Oracle PeopleSoft public Strategic Sourcing connector.

The adapter deliberately models only anonymous, read-only navigation.  Form state is
kept in memory for the lifetime of a connector and is never copied into opportunities.
"""

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

PeopleSoftResponseStrategy = Literal["html", "json", "xml", "csv", "auto"]


class PeopleSoftSessionState(StrEnum):
    NOT_STARTED = "not-started"
    ANONYMOUS = "anonymous"
    FORM_READY = "form-ready"
    EXPIRED = "session-expired"


class PeopleSoftAccessState(StrEnum):
    PUBLIC = "public"
    ANONYMOUS_SESSION_REQUIRED = "anonymous-session-required"
    LOGIN_REQUIRED = "login-required"
    REGISTRATION_REQUIRED = "registration-required"
    RESTRICTED = "restricted"
    CAPTCHA_BLOCKED = "captcha-blocked"
    FORBIDDEN = "forbidden"
    MAINTENANCE = "maintenance"
    SESSION_EXPIRED = "session-expired"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PeopleSoftSourcingPortal:
    jurisdiction: str
    jurisdiction_code: str
    name: str
    public_system: str
    platform: str
    base_url: str
    search_url: str
    fallback_url: str
    response_strategy: PeopleSoftResponseStrategy = "html"
    landing_url: str | None = None
    detail_url_template: str | None = None
    page_parameter: str = "page"
    page_starts_at: int = 1
    keyword_parameter: str = "keyword"
    query_parameters: Mapping[str, str] = field(default_factory=dict)
    field_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_headers: Mapping[str, str] = field(default_factory=dict)
    date_formats: tuple[str, ...] = ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d")
    component_id: str | None = None
    page_id: str | None = None
    guest_context: str | None = None
    event_package_behavior: str = "metadata-only"
    public_attachment_behavior: str = "classify-only"
    unspsc_behavior: str = "source-table"
    service_area_behavior: str = "source-table"
    department_identifiers: Mapping[str, str] = field(default_factory=dict)
    anonymous_session_required: bool = True
    production_verified: bool = False


# Authoritative public entry points are stable; component/session navigation is
# intentionally configurable and fixture-verified rather than represented as a stable URL.
CAL_EPROCURE = PeopleSoftSourcingPortal(
    jurisdiction="California",
    jurisdiction_code="CA",
    name="Cal eProcure",
    public_system="California State Contracts Register",
    platform="Oracle PeopleSoft / FI$Cal",
    base_url="https://caleprocure.ca.gov/",
    search_url="https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx",
    fallback_url="https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx",
    landing_url="https://caleprocure.ca.gov/",
    response_strategy="html",
    guest_context="public event inquiry",
    production_verified=True,
)
PORTALS = (CAL_EPROCURE,)


@dataclass(frozen=True, slots=True)
class PeopleSoftQuery(ConnectorQuery):
    event_id: str | None = None
    event_name: str | None = None
    business_unit: str | None = None
    status: str | None = None
    published_from: str | None = None
    published_to: str | None = None
    end_from: str | None = None
    end_to: str | None = None
    unspsc: str | None = None
    service_area: str | None = None
    county: str | None = None
    historical: bool = False


class AsyncGetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class PeopleSoftError(RuntimeError):
    """A response cannot safely be interpreted as public sourcing data."""


class PeopleSoftAvailabilityError(PeopleSoftError):
    pass


class PeopleSoftAccessError(PeopleSoftError):
    def __init__(self, state: PeopleSoftAccessState) -> None:
        self.state = state
        super().__init__(f"PeopleSoft public access ended at: {state.value}")


@dataclass(frozen=True, slots=True)
class PeopleSoftHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    session_state: PeopleSoftSessionState
    access_state: PeopleSoftAccessState
    portal: str
    portal_identifier: str
    skipped_records: int


class _PeopleSoftHTMLParser(HTMLParser):
    """Tolerant parser for fixture/configured result and detail tables."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.hidden: dict[str, str] = {}
        self._record: dict[str, Any] | None = None
        self._field: str | None = None
        self._href: str | None = None
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "input" and values.get("type", "").casefold() == "hidden" and values.get("name"):
            self.hidden[str(values["name"])] = str(values.get("value") or "")
        if tag in {"tr", "article", "div"} and (
            classes.intersection({"event-row", "event", "ps-event", "opportunity"})
            or values.get("data-event-id")
        ):
            self._record = {
                k[5:].replace("-", "_"): v for k, v in values.items() if k.startswith("data-")
            }
        if self._record is not None:
            self._field = values.get("data-field") or next(
                (
                    name
                    for name in (
                        "event_id",
                        "title",
                        "department",
                        "business_unit",
                        "status",
                        "published",
                        "end",
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
            doc_words = (
                r"rfp|rfq|ifb|itb|rfi|package|spec|statement of work|pws|pricing|"
                r"bid form|addend|amend|questions|attachment|exhibit|insurance|certification"
            )
            if re.search(doc_words, text, re.I) or self._attrs.get("data-attachment-id"):
                self._record.setdefault("documents", []).append(
                    {
                        "title": text or "Attachment",
                        "url": self._href,
                        "attachment_id": self._attrs.get("data-attachment-id"),
                        "last_modified": self._attrs.get("data-last-modified"),
                        "access": self._attrs.get("data-access"),
                        "version": self._attrs.get("data-version"),
                        "superseded": self._attrs.get("data-superseded"),
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


class PeopleSoftSourcingConnector(BaseConnector):
    platform_family = "oracle/peoplesoft-sourcing"
    jurisdictions = ("California",)
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: PeopleSoftSourcingPortal = CAL_EPROCURE,
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
        self.portal, self.page_size, self.max_pages, self.max_results = (
            portal,
            page_size,
            max_pages,
            max_results,
        )
        self.max_retries, self.fetch_details = max_retries, fetch_details
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold, self.circuit_breaker_cooldown = (
            circuit_breaker_threshold,
            circuit_breaker_cooldown,
        )
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1", **portal.default_headers},
        )
        self._owns_transport = transport is None
        self._failures = 0
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._session = PeopleSoftSessionState.NOT_STARTED
        self._access = PeopleSoftAccessState.UNKNOWN
        self._form_state: dict[str, str] = {}
        self._skipped = 0

    @property
    def health(self) -> PeopleSoftHealth:
        opened = self._circuit_is_open()
        return PeopleSoftHealth(
            not opened and self._failures == 0,
            opened,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._session,
            self._access,
            self.portal.name,
            f"{self.portal.jurisdiction_code}:{self.portal.name}",
            self._skipped,
        )

    async def __aenter__(self) -> "PeopleSoftSourcingConnector":
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
            raise PeopleSoftAvailabilityError("PeopleSoft circuit breaker is open")
        seen: set[str] = set()
        fingerprints: set[str] = set()
        yielded = 0
        try:
            if self.portal.landing_url:
                landing = await self._request(self.portal.landing_url, {})
                parser = _PeopleSoftHTMLParser()
                parser.feed(landing.text)
                self._form_state = parser.hidden
                self._session = (
                    PeopleSoftSessionState.FORM_READY
                    if parser.hidden
                    else PeopleSoftSessionState.ANONYMOUS
                )
            for offset in range(self.max_pages):
                params = self._query_params(query, offset + self.portal.page_starts_at)
                response = await self._request(self.portal.search_url, params)
                records = self._records(response)
                fingerprint = json.dumps(records, sort_keys=True, default=str)
                if fingerprint in fingerprints:
                    return
                fingerprints.add(fingerprint)
                for record in records:
                    try:
                        item = await self._normalize(record)
                    except PeopleSoftError:
                        self._skipped += 1
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
            self._failures += 1
            self._last_failure = self._now()
            raise

    def _query_params(self, query: ConnectorQuery, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            self.portal.page_parameter: page,
            self.portal.keyword_parameter: " ".join(query.keywords).strip(),
        }
        if isinstance(query, PeopleSoftQuery):
            for name in (
                "event_id",
                "event_name",
                "business_unit",
                "status",
                "published_from",
                "published_to",
                "end_from",
                "end_to",
                "unspsc",
                "service_area",
                "county",
            ):
                value = getattr(query, name)
                if value:
                    params[self.portal.query_parameters.get(name, name)] = value
            params[self.portal.query_parameters.get("historical", "historical")] = str(
                query.historical
            ).lower()
        return params

    async def _request(self, url: str, params: Mapping[str, Any]) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise PeopleSoftAvailabilityError("PeopleSoft connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if response.status_code in self._transient:
                self._access = PeopleSoftAccessState.UNAVAILABLE
                if attempt == self.max_retries:
                    raise PeopleSoftAvailabilityError(
                        f"PeopleSoft temporarily unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access = PeopleSoftAccessState.FORBIDDEN
                raise PeopleSoftAccessError(self._access)
            if response.status_code >= 400:
                raise PeopleSoftError(f"PeopleSoft returned HTTP {response.status_code}")
            state = self._detect_access(response)
            if state not in {
                PeopleSoftAccessState.PUBLIC,
                PeopleSoftAccessState.ANONYMOUS_SESSION_REQUIRED,
            }:
                self._access = state
                if state == PeopleSoftAccessState.SESSION_EXPIRED:
                    self._session = PeopleSoftSessionState.EXPIRED
                raise PeopleSoftAccessError(state)
            self._failures = 0
            self._last_failure = None
            self._last_success = self._now()
            self._access = state
            return response
        raise AssertionError("retry loop exhausted")

    def _detect_access(self, response: httpx.Response) -> PeopleSoftAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        groups = (
            (PeopleSoftAccessState.CAPTCHA_BLOCKED, ("captcha", "recaptcha", "bot challenge")),
            (
                PeopleSoftAccessState.SESSION_EXPIRED,
                (
                    "session has expired",
                    "session expired",
                    "your peoplesoft connection has expired",
                ),
            ),
            (
                PeopleSoftAccessState.MAINTENANCE,
                ("scheduled maintenance", "temporarily down for maintenance"),
            ),
            (
                PeopleSoftAccessState.REGISTRATION_REQUIRED,
                ("supplier registration required", "register as a bidder"),
            ),
            (
                PeopleSoftAccessState.LOGIN_REQUIRED,
                ("sign in to peoplesoft", "user id", "password"),
            ),
            (
                PeopleSoftAccessState.RESTRICTED,
                ("not authorized", "permission denied", "you do not have access"),
            ),
        )
        for state, markers in groups:
            if any(marker in text for marker in markers):
                return state
        if any(marker in url for marker in ("login", "signin", "authenticate")):
            return PeopleSoftAccessState.LOGIN_REQUIRED
        return (
            PeopleSoftAccessState.ANONYMOUS_SESSION_REQUIRED
            if self.portal.anonymous_session_required
            else PeopleSoftAccessState.PUBLIC
        )

    def _records(self, response: httpx.Response) -> list[dict[str, Any]]:
        kind = self.portal.response_strategy
        content = response.headers.get("content-type", "").casefold()
        if kind == "auto":
            kind = (
                "json"
                if "json" in content
                else "xml"
                if "xml" in content
                else "csv"
                if "csv" in content
                else "html"
            )
        try:
            if kind == "json":
                payload = response.json()
                records = (
                    payload
                    if isinstance(payload, list)
                    else next(
                        (
                            payload[k]
                            for k in ("results", "events", "items", "rows")
                            if k in payload
                        ),
                        None,
                    )
                )
            elif kind == "csv":
                records = list(csv.DictReader(io.StringIO(response.text)))
            elif kind == "xml":
                records = [
                    {child.tag.split("}")[-1]: child.text for child in row}
                    for row in ET.fromstring(response.text).iter()
                    if row.tag.split("}")[-1].casefold() in {"event", "row", "item"}
                ]
            else:
                parser = _PeopleSoftHTMLParser()
                parser.feed(response.text)
                records = parser.records
        except (ValueError, csv.Error, ET.ParseError) as exc:
            raise PeopleSoftError("malformed PeopleSoft response") from exc
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            raise PeopleSoftError("unexpected PeopleSoft response shape")
        return records

    async def _normalize(self, record: dict[str, Any]) -> RawOpportunity:
        aliases = self.portal.field_aliases

        def first(name: str, defaults: tuple[str, ...]) -> Any:
            return next(
                (record[k] for k in aliases.get(name, defaults) if record.get(k) not in (None, "")),
                None,
            )

        event_id = first("event_id", ("event_id", "eventId", "Event ID", "id"))
        title = first("title", ("title", "event_name", "eventName", "Event Name"))
        unit = first(
            "business_unit", ("business_unit", "businessUnit", "Business Unit", "department")
        )
        if not event_id or not title:
            raise PeopleSoftError("event ID and title are required")
        direct = first("url", ("url", "detail_url", "detailUrl"))
        opportunity_url = (
            urljoin(self.portal.base_url, str(direct)) if direct else self.portal.fallback_url
        )
        if not direct and self.portal.detail_url_template:
            opportunity_url = urljoin(
                self.portal.base_url,
                self.portal.detail_url_template.format(event_id=event_id, business_unit=unit or ""),
            )
        if self.fetch_details and direct and not first("description", ("description", "summary")):
            detail = await self._request(opportunity_url, {})
            parsed = self._records(detail)
            if parsed:
                record = {**record, **parsed[0]}
        documents = self._documents(record, opportunity_url)
        payload = dict(record)
        payload["document_links"] = documents
        payload["peoplesoft"] = {
            "portal": self.portal.name,
            "public_system": self.portal.public_system,
            "platform": self.portal.platform,
            "event_round": first("round", ("event_round", "round", "Event Round")),
            "event_version": first("version", ("event_version", "version", "Event Version")),
            "session_required": self.portal.anonymous_session_required,
            "production_verified": self.portal.production_verified,
        }
        payload["stable_identity"] = {
            "jurisdiction": self.portal.jurisdiction_code,
            "business_unit": str(unit or "").strip(),
            "event_id": str(event_id).strip(),
        }
        source_id = ":".join(
            filter(
                None,
                (self.portal.jurisdiction_code, str(unit or "").strip(), str(event_id).strip()),
            )
        )
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=source_id,
                opportunity_url=opportunity_url,
            ),
            title=str(title),
            agency=str(
                first("agency", ("agency", "department", "Department")) or unit or self.portal.name
            ),
            description=self._optional(first("description", ("description", "summary"))),
            solicitation_number=str(event_id),
            status=self._status(
                self._optional(first("status", ("status", "event_status", "Event Status")))
            ),
            posted_at=self._date(
                first("posted", ("published", "published_date", "Published Date"))
            ),
            due_at=self._date(first("due", ("end", "end_date", "Event End Date"))),
            categories=self._list(first("categories", ("unspsc", "UNSPSC", "categories"))),
            raw_payload=payload,
        )

    def _documents(self, record: dict[str, Any], opportunity_url: str) -> list[dict[str, Any]]:
        result = []
        docs = record.get("documents", []) if isinstance(record.get("documents"), list) else []
        current = [
            d
            for d in docs
            if isinstance(d, dict)
            and str(d.get("superseded", "false")).casefold() not in {"true", "yes", "1"}
        ]
        for doc in current:
            if not doc.get("url"):
                continue
            url = urljoin(opportunity_url, str(doc["url"]))
            access = str(doc.get("access") or "").casefold()
            state = (
                "restricted"
                if re.search(r"login|register|restricted", access + " " + url, re.I)
                else (
                    "anonymous-session-required"
                    if self.portal.anonymous_session_required
                    else "public"
                )
            )
            result.append(
                {
                    "title": str(doc.get("title") or "Attachment"),
                    "apparent_file_type": url.rsplit(".", 1)[-1].split("?", 1)[0].lower()
                    if "." in url
                    else None,
                    "source_url": url,
                    "opportunity_url": opportunity_url,
                    "attachment_identifier": doc.get("attachment_id"),
                    "event_round_or_version": doc.get("version"),
                    "last_modified": doc.get("last_modified"),
                    "access_state": state,
                    "anonymous_session_required": self.portal.anonymous_session_required,
                }
            )
        return result

    def _date(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in self.portal.date_formats:
            try:
                return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

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

    @staticmethod
    def _optional(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [
                str(x.get("code", x.get("name", "")) if isinstance(x, dict) else x)
                for x in value
                if x
            ]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    @staticmethod
    def _status(value: str | None) -> OpportunityStatus:
        text = (value or "").casefold()
        for state, words in {
            OpportunityStatus.OPEN: ("open", "posted", "active"),
            OpportunityStatus.CLOSED: ("closed", "ended"),
            OpportunityStatus.AWARDED: ("award",),
            OpportunityStatus.CANCELLED: ("cancel",),
            OpportunityStatus.FORECAST: ("planned", "forecast"),
        }.items():
            if any(word in text for word in words):
                return state
        return OpportunityStatus.UNKNOWN
