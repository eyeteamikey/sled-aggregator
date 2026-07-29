"""Bounded, anonymous Pennsylvania eMarketplace discovery.

This connector submits only the portal's public WebForms search form.  Hidden
state is obtained immediately before use and is never logged or persisted.
"""

import asyncio
import email.utils
import hashlib
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef

EASTERN = ZoneInfo("America/New_York")


class PennsylvaniaRecordType(StrEnum):
    SOLICITATION = "solicitation"
    UPCOMING_PROCUREMENT = "upcoming_procurement"


class PennsylvaniaAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_SESSION_REQUIRED = "public_session_required"
    EXTERNAL_PUBLIC = "external_public"
    EXTERNAL_ACCOUNT_REQUIRED = "external_account_required"
    SUPPLIER_PORTAL_REQUIRED = "supplier_portal_required"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    MFA_REQUIRED = "mfa_required"
    RESTRICTED = "restricted"
    CAPTCHA = "captcha"
    FORBIDDEN = "forbidden"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"
    EXPIRED_SESSION = "expired_session"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN = "unknown"


class PennsylvaniaError(RuntimeError):
    pass


class PennsylvaniaAccessError(PennsylvaniaError):
    def __init__(self, state: PennsylvaniaAccessState) -> None:
        self.state = state
        super().__init__(f"Pennsylvania eMarketplace access ended at {state.value}")


class PennsylvaniaAvailabilityError(PennsylvaniaError):
    pass


@dataclass(frozen=True, slots=True)
class PennsylvaniaEMarketplacePortal:
    base_url: str = "https://www.emarketplace.state.pa.us/"
    search_path: str = "Search.aspx"
    detail_path: str = "Solicitations.aspx"
    upcoming_path: str = "Procurement.aspx"
    upcoming_detail_path: str = "Procurement_Details.aspx"
    tabulation_path: str = "bidtabs.aspx"
    awards_path: str = "Awards.aspx"
    contracts_path: str = "Contracts.aspx"
    jurisdiction: str = "Pennsylvania"
    country_subdivision: str = "US-PA"
    source_system: str = "Pennsylvania eMarketplace"

    @property
    def search_url(self) -> str:
        return urljoin(self.base_url, self.search_path)


PENNSYLVANIA_EMARKETPLACE = PennsylvaniaEMarketplacePortal()


@dataclass(frozen=True, slots=True)
class PennsylvaniaEMarketplaceQuery(ConnectorQuery):
    keyword: str | None = None
    solicitation_number: str | None = None
    agency: str | None = None
    county: str | None = None
    statewide: bool = False
    multiple_counties: bool = False
    solicitation_type: str | None = None
    advertisement_types: tuple[str, ...] = ()
    small_business_only: bool = False
    sdb_vbe_goal_only: bool = False
    bid_open_date: date | str | None = None
    posted_since: date | str | None = None
    include_current: bool = True
    include_archived: bool = False
    page_size: int = 25
    max_pages: int = 5
    result_limit: int = 100
    include_details: bool = True
    include_documents: bool = True
    include_upcoming: bool = False
    include_post_award_links: bool = True

    def __post_init__(self) -> None:
        if min(self.page_size, self.max_pages, self.result_limit, self.limit) < 1:
            raise ValueError("query bounds must be positive")
        if not (self.include_current or self.include_archived or self.include_upcoming):
            raise ValueError("at least one search lane is required")


class AsyncWebFormsTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def post(self, url: str, *, data: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PennsylvaniaHealth:
    available: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    access_state: PennsylvaniaAccessState
    skipped_records: int


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


class _PAParser(HTMLParser):
    """Label/header-oriented parser tolerant of WebForms naming containers."""

    labels = {
        "solicitation number": "solicitation_number",
        "project number": "solicitation_number",
        "type": "solicitation_type",
        "solicitation type": "solicitation_type",
        "title": "title",
        "solicitation title": "title",
        "project title": "title",
        "description": "description",
        "agency": "agency",
        "department": "agency",
        "department responsible": "department",
        "county": "county",
        "amended date": "amended_date",
        "solicitation start date": "start_date",
        "solicitation due date": "due_date",
        "solicitation due time": "due_time",
        "bid opening date": "opening_date",
        "solicitation opening date": "opening_date",
        "solicitation opening time": "opening_time",
        "status": "status",
        "contact person": "contact_name",
        "first name": "contact_first_name",
        "last name": "contact_last_name",
        "phone number": "contact_phone",
        "email": "contact_email",
        "advertisement type": "advertisement_type",
        "date prepared": "date_prepared",
        "delivery location": "delivery_location",
        "duration": "duration",
        "opening location": "opening_location",
        "number of addenda": "number_of_addenda",
        "material/service/it": "classification",
        "proposed procurement method": "procurement_method",
    }

    def __init__(self) -> None:
        super().__init__()
        self.hidden: dict[str, str] = {}
        self.records: list[dict[str, Any]] = []
        self.headers: list[str] = []
        self._row: list[tuple[str, str | None]] | None = None
        self._cell: list[str] | None = None
        self._cell_href: str | None = None
        self._record: dict[str, Any] | None = None
        self._depth = 0
        self._field: str | None = None
        self._text: list[str] = []
        self._href: str | None = None
        self.form_action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self._text = []
        if tag == "form" and a.get("action"):
            self.form_action = a["action"]
        if tag == "input" and a.get("type", "").lower() == "hidden" and a.get("name"):
            self.hidden[str(a["name"])] = str(a.get("value") or "")
        if tag == "tr":
            self._row = []
        if tag in {"th", "td"} and self._row is not None:
            self._cell, self._cell_href = [], None
        if tag == "a" and a.get("href"):
            self._href = str(a["href"])
            if self._cell is not None:
                self._cell_href = self._href
        marker = a.get("data-pa-record") or a.get("data-procurement-id")
        if self._record is None and marker is not None:
            self._record = {
                k[5:].replace("-", "_"): v for k, v in a.items() if k.startswith("data-")
            }
            self._depth = 1
        elif self._record is not None:
            self._depth += 1
        if self._record is not None and a.get("data-field"):
            self._field = a["data-field"].replace("-", "_")

    def handle_data(self, data: str) -> None:
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = _clean("".join(self._text))
        if tag in {"th", "td"} and self._row is not None and self._cell is not None:
            self._row.append((_clean("".join(self._cell)), self._cell_href))
            self._cell = None
        if tag == "tr" and self._row is not None:
            values = self._row
            self._row = None
            if values and all(h is None for _, h in values) and not self.headers:
                self.headers = [_clean(x).casefold().rstrip(":") for x, _ in values]
            elif (
                self.headers
                and values
                and not re.search(
                    r"no (matching )?(records|results)", " ".join(x for x, _ in values), re.I
                )
            ):
                record: dict[str, Any] = {}
                for index, (value, href) in enumerate(values):
                    if index >= len(self.headers):
                        continue
                    field = self.labels.get(self.headers[index])
                    if field and value:
                        record[field] = value
                    if href:
                        record["url"] = href
                if record:
                    self.records.append(record)
        if self._record is not None:
            if self._field and text:
                self._record[self._field] = text
            if tag == "a" and self._href:
                item = {"title": text or "Link", "url": self._href}
                section = self._field or "related"
                if re.search(
                    r"\.pdf|\.docx?|\.xlsx?|\.csv|\.txt|\.zip|addend|flyer|tabulation|award|contract|supplier|jaggaer|ecms",
                    f"{text} {self._href}",
                    re.I,
                ):
                    item["section"] = section
                    self._record.setdefault("documents", []).append(item)
                else:
                    self._record.setdefault("url", self._href)
                self._href = None
            self._depth -= 1
            if self._depth == 0:
                self.records.append(self._record)
                self._record = None
        self._field = None
        self._text = []


class PennsylvaniaEMarketplaceConnector(BaseConnector):
    platform_family = "pennsylvania/emarketplace"
    jurisdictions = ("Pennsylvania",)
    _transient = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        portal: PennsylvaniaEMarketplacePortal = PENNSYLVANIA_EMARKETPLACE,
        *,
        transport: AsyncWebFormsTransport | None = None,
        max_retries: int = 3,
        timeout: float = 30,
        user_agent: str = "TrustEST-SLED-Aggregator/0.1 (public read-only)",
        concurrency: int = 3,
        backoff_seconds: float = 0.5,
        jitter_seconds: float = 0.25,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if min(concurrency, circuit_breaker_threshold) < 1:
            raise ValueError("limits must be positive")
        self.portal, self.max_retries = portal, max_retries
        self.backoff_seconds, self.jitter_seconds = backoff_seconds, jitter_seconds
        self.circuit_breaker_threshold, self.circuit_breaker_cooldown = (
            circuit_breaker_threshold,
            circuit_breaker_cooldown,
        )
        self._sleep, self._random, self._now = sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._owns_transport = transport is None
        self._semaphore = asyncio.Semaphore(concurrency)
        self._failures = 0
        self._last_status = None
        self._last_failure = None
        self._last_success = None
        self._access = PennsylvaniaAccessState.UNKNOWN
        self._skipped = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> PennsylvaniaHealth:
        opened = self._circuit_is_open()
        return PennsylvaniaHealth(
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
            if isinstance(query, PennsylvaniaEMarketplaceQuery)
            else PennsylvaniaEMarketplaceQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if q.jurisdiction and q.jurisdiction.casefold() not in {"pennsylvania", "pa", "us-pa"}:
            return
        if self._circuit_is_open():
            raise PennsylvaniaAvailabilityError("Pennsylvania eMarketplace circuit breaker is open")
        records: dict[str, dict[str, Any]] = {}
        lanes = [
            x
            for x, enabled in (
                ("current", q.include_current),
                ("archived", q.include_archived),
                ("upcoming", q.include_upcoming),
            )
            if enabled
        ]
        try:
            for lane in lanes:
                await self._collect_lane(q, lane, records)
            yielded = 0
            for identity, record in records.items():
                try:
                    if q.include_details and record.get("url"):
                        detail = self._parse(
                            await self._request(
                                "GET",
                                self._safe_url(record["url"], self.portal.base_url)
                                or self.portal.search_url,
                            )
                        ).records
                        if detail:
                            record = self._merge(record, detail[0])
                    yield self._normalize(identity, record, q)
                    yielded += 1
                    if yielded >= min(q.limit, q.result_limit):
                        return
                except (PennsylvaniaError, ValueError):
                    self._skipped += 1
        except Exception:
            self._record_failure()
            raise

    async def _collect_lane(
        self, q: PennsylvaniaEMarketplaceQuery, lane: str, records: dict[str, dict[str, Any]]
    ) -> None:
        url = (
            urljoin(self.portal.base_url, self.portal.upcoming_path)
            if lane == "upcoming"
            else self.portal.search_url
        )
        seen: set[str] = set()
        refreshed = False
        landing = self._parse(await self._request("GET", url))
        for page in range(1, q.max_pages + 1):
            form = self._form(q, lane, page, landing.hidden)
            response = await self._request("POST", urljoin(url, landing.form_action or url), form)
            state = self._detect_access(response)
            if state == PennsylvaniaAccessState.EXPIRED_SESSION and not refreshed:
                landing = self._parse(await self._request("GET", url))
                refreshed = True
                continue
            parsed = self._parse(response)
            fingerprint = hashlib.sha256(repr(parsed.records).encode()).hexdigest()
            if not parsed.records or fingerprint in seen:
                break
            seen.add(fingerprint)
            for record in parsed.records:
                record["search_lane"] = lane
                record["record_type"] = (
                    PennsylvaniaRecordType.UPCOMING_PROCUREMENT.value
                    if lane == "upcoming"
                    else PennsylvaniaRecordType.SOLICITATION.value
                )
                identity = self._identity(record)
                if identity:
                    records[identity] = self._merge(records.get(identity, {}), record)
                else:
                    self._skipped += 1
            landing = parsed
            if len(parsed.records) < q.page_size:
                break

    def _form(
        self, q: PennsylvaniaEMarketplaceQuery, lane: str, page: int, hidden: Mapping[str, str]
    ) -> dict[str, Any]:
        form = {k: v for k, v in hidden.items() if k.startswith("__")}
        form.update(
            {
                "ctl00$MainContent$txtSolicitationNumber": q.solicitation_number or "",
                "ctl00$MainContent$txtKeyword": q.keyword or " ".join(q.keywords),
                "ctl00$MainContent$ddlAgency": q.agency or "",
                "ctl00$MainContent$ddlCounty": q.county or "",
                "ctl00$MainContent$ddlSolicitationType": q.solicitation_type or "",
                "ctl00$MainContent$chkStatewide": "on" if q.statewide else "",
                "ctl00$MainContent$chkMultipleCounties": "on" if q.multiple_counties else "",
                "ctl00$MainContent$chkSmallBusiness": "on" if q.small_business_only else "",
                "ctl00$MainContent$chkSDBVBEGoal": "on" if q.sdb_vbe_goal_only else "",
                "ctl00$MainContent$txtBidOpenDate": self._date_text(q.bid_open_date),
                "ctl00$MainContent$txtPostedSince": self._date_text(q.posted_since),
                "ctl00$MainContent$ddlRecordsPerPage": str(q.page_size),
                "ctl00$MainContent$rblStatus": lane,
                "ctl00$MainContent$chkAdvertisementType": list(q.advertisement_types),
                "__EVENTTARGET": "ctl00$MainContent$gvResults"
                if page > 1
                else "ctl00$MainContent$btnSearch",
                "__EVENTARGUMENT": f"Page${page}" if page > 1 else "",
            }
        )
        return form

    async def _request(
        self, method: str, url: str, data: Mapping[str, Any] | None = None
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                async with self._semaphore:
                    response = await (
                        self._transport.post(url, data=data or {})
                        if method == "POST"
                        else self._transport.get(url, params=None)
                    )
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.max_retries:
                    raise PennsylvaniaAvailabilityError(
                        "Pennsylvania eMarketplace connection failed"
                    ) from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if response.status_code in self._transient:
                self._access = PennsylvaniaAccessState.UNAVAILABLE
                if attempt == self.max_retries:
                    raise PennsylvaniaAvailabilityError(
                        f"Pennsylvania eMarketplace unavailable ({response.status_code})"
                    )
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 403:
                self._access = PennsylvaniaAccessState.FORBIDDEN
                raise PennsylvaniaAccessError(self._access)
            if response.status_code >= 400:
                raise PennsylvaniaError(
                    f"Pennsylvania eMarketplace returned HTTP {response.status_code}"
                )
            state = self._detect_access(response)
            if state not in {
                PennsylvaniaAccessState.PUBLIC,
                PennsylvaniaAccessState.EXPIRED_SESSION,
            }:
                self._access = state
                raise PennsylvaniaAccessError(state)
            self._failures = 0
            self._last_failure = None
            self._last_success = self._now()
            self._access = state
            return response
        raise AssertionError("retry loop exhausted")

    def _parse(self, response: httpx.Response) -> _PAParser:
        if "html" not in response.headers.get("content-type", "text/html").casefold():
            raise PennsylvaniaError("unexpected content type")
        parser = _PAParser()
        parser.feed(response.text)
        return parser

    def _normalize(
        self, identity: str, r: dict[str, Any], q: PennsylvaniaEMarketplaceQuery
    ) -> RawOpportunity:
        title, agency = _clean(r.get("title")), _clean(r.get("agency") or r.get("department"))
        if not title or not agency:
            raise PennsylvaniaError("title and agency are required")
        upcoming = r.get("record_type") == PennsylvaniaRecordType.UPCOMING_PROCUREMENT.value
        url = self._safe_url(r.get("url"), self.portal.base_url) or self.portal.search_url
        solicitation = _clean(r.get("solicitation_number")) or None
        payload = dict(r)
        payload["pennsylvania_emarketplace"] = {
            "sid": self._sid(r),
            "normalized_solicitation_number": re.sub(
                r"[^a-z0-9]", "", (solicitation or "").casefold()
            )
            or None,
            "search_lane": r.get("search_lane"),
            "record_type": r.get("record_type"),
            "source_status": _clean(r.get("status")) or None,
            "country_subdivision": self.portal.country_subdivision,
            "source_system": self.portal.source_system,
            "last_seen_at": self._now().isoformat(),
            "date_authority_note": (
                "advertisement dates preserved; solicitation documents may control"
            ),
            "absence_policy": "reconcile_archive; retain_last_known; absence_is_not_deletion",
        }
        payload["document_links"] = self._documents(r, identity, url) if q.include_documents else []
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
            solicitation_number=solicitation,
            status=OpportunityStatus.FORECAST if upcoming else self._status(r.get("status")),
            posted_at=self._datetime(r.get("start_date")),
            due_at=None if upcoming else self._datetime(r.get("due_date"), r.get("due_time")),
            categories=[
                x
                for x in (
                    _clean(r.get("solicitation_type")),
                    _clean(r.get("advertisement_type")),
                    _clean(r.get("classification")),
                )
                if x
            ],
            raw_payload=payload,
        )

    def _documents(self, r: Mapping[str, Any], identity: str, parent: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for d in r.get("documents", []) if isinstance(r.get("documents"), list) else []:
            url = self._safe_url(d.get("url"), parent) if isinstance(d, dict) else None
            if not url or url in seen:
                continue
            seen.add(url)
            title = _clean(d.get("title")) or "Document"
            host = (urlparse(url).hostname or "").casefold()
            own = host.endswith("emarketplace.state.pa.us")
            state, classification = (
                (PennsylvaniaAccessState.PUBLIC.value, "internal")
                if own
                else (PennsylvaniaAccessState.EXTERNAL_PUBLIC.value, "external")
            )
            if "supplier" in host or "pasupplierportal" in url.casefold():
                state = PennsylvaniaAccessState.SUPPLIER_PORTAL_REQUIRED.value
            elif "jaggaer" in host:
                state = PennsylvaniaAccessState.EXTERNAL_ACCOUNT_REQUIRED.value
            category = (
                "addendum"
                if re.search(r"addend|amend|flyer", title, re.I)
                else "tabulation"
                if "tab" in title.casefold()
                else "award_notice"
                if "award" in title.casefold()
                else "contract_reference"
                if "contract" in title.casefold()
                else "solicitation"
            )
            filename = urlparse(url).path.rsplit("/", 1)[-1]
            out.append(
                {
                    "displayed_title": title,
                    "displayed_filename": filename or None,
                    "source_url": url,
                    "source_section": d.get("section"),
                    "apparent_file_type": filename.rsplit(".", 1)[-1].lower()
                    if "." in filename
                    else None,
                    "document_category": category,
                    "addendum_or_version": self._version(title),
                    "posted_or_amended_date": d.get("posted"),
                    "access_state": state,
                    "parent_opportunity_id": identity,
                    "parent_opportunity_url": parent,
                    "classification": "external_system"
                    if "ecms" in url.casefold()
                    else classification,
                    "retrieval_eligible": state in {"public", "external_public"},
                }
            )
        return out

    @staticmethod
    def _merge(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(old)
        result.update({k: v for k, v in new.items() if v not in (None, "", [])})
        result["documents"] = list(
            {
                d.get("url"): d
                for d in [*old.get("documents", []), *new.get("documents", [])]
                if isinstance(d, dict)
            }.values()
        )
        return result

    @staticmethod
    def _sid(r: Mapping[str, Any]) -> str | None:
        query = parse_qs(urlparse(str(r.get("url") or "")).query)
        return next((query[k][0] for k in ("SID", "sid", "id") if query.get(k)), None) or (
            _clean(r.get("pa_record")) or None
        )

    def _identity(self, r: Mapping[str, Any]) -> str | None:
        sid = self._sid(r)
        if sid:
            return ("upcoming:" if r.get("record_type") == "upcoming_procurement" else "sid:") + sid
        number, agency = _clean(r.get("solicitation_number")), _clean(r.get("agency"))
        return (
            f"solicitation:{agency.casefold()}:{number.casefold()}" if number and agency else None
        )

    @staticmethod
    def _safe_url(value: Any, base: str) -> str | None:
        if not value:
            return None
        url = urljoin(base, str(value).strip())
        p = urlparse(url)
        return url if p.scheme in {"http", "https"} and p.hostname else None

    @staticmethod
    def _status(value: Any) -> OpportunityStatus:
        text = _clean(value).casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if text in {"closed", "archived"}:
            return OpportunityStatus.CLOSED
        if text in {"open", "extended", "amended"}:
            return OpportunityStatus.OPEN
        return OpportunityStatus.UNKNOWN

    @staticmethod
    def _datetime(day: Any, clock: Any = None) -> datetime | None:
        text = _clean(day)
        if not text:
            return None
        combined = f"{text} {_clean(clock)}".strip()
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(combined, fmt)
                return parsed.replace(tzinfo=EASTERN) if clock or fmt != "%m/%d/%Y" else None
            except ValueError:
                pass
        return None

    @staticmethod
    def _date_text(value: date | str | None) -> str:
        return value.strftime("%m/%d/%Y") if isinstance(value, date) else _clean(value)

    @staticmethod
    def _version(title: str) -> str | None:
        match = re.search(r"(?:addendum|amendment)\s*#?\s*([\w.-]+)", title, re.I)
        return match.group(1) if match else None

    def _detect_access(self, response: httpx.Response) -> PennsylvaniaAccessState:
        text, url = response.text.casefold(), str(response.url).casefold()
        checks = (
            (PennsylvaniaAccessState.CAPTCHA, ("captcha", "recaptcha")),
            (
                PennsylvaniaAccessState.MFA_REQUIRED,
                ("verification code", "passcode", "multi-factor"),
            ),
            (
                PennsylvaniaAccessState.REGISTRATION_REQUIRED,
                ("supplier registration", "create an account"),
            ),
            (
                PennsylvaniaAccessState.LOGIN_REQUIRED,
                ("supplier login", "please sign in", "user name and password"),
            ),
            (PennsylvaniaAccessState.MAINTENANCE, ("scheduled maintenance",)),
            (
                PennsylvaniaAccessState.EXPIRED_SESSION,
                ("invalid postback", "validation of viewstate", "session has expired"),
            ),
            (PennsylvaniaAccessState.RESTRICTED, ("access denied", "not authorized")),
        )
        for state, markers in checks:
            if any(x in text for x in markers):
                return state
        if "login" in url:
            return PennsylvaniaAccessState.LOGIN_REQUIRED
        if not text.strip() or re.search(r"<title>\s*(error|server error)\s*</title>", text):
            return PennsylvaniaAccessState.MALFORMED_RESPONSE
        return PennsylvaniaAccessState.PUBLIC

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
