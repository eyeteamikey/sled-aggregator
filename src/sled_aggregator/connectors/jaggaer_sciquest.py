"""Configurable, public GET-only JAGGAER/SciQuest event connector.

JAGGAER tenants differ substantially.  Routes and search capabilities therefore
live in :class:`JaggaerPortal`; this module does not call supplier APIs, submit
forms, or retrieve attachment bodies.
"""

import asyncio
import email.utils
import hashlib
import ipaddress
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import RawOpportunity, SourceRef


class JaggaerAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    CAPTCHA = "captcha"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    TRANSIENT_ERROR = "transient_error"


class JaggaerError(RuntimeError):
    pass


class JaggaerAccessError(JaggaerError):
    def __init__(self, state: JaggaerAccessState) -> None:
        self.state = state
        super().__init__(f"JAGGAER public access ended at {state.value}")


class JaggaerAvailabilityError(JaggaerError):
    pass


@dataclass(frozen=True, slots=True)
class JaggaerPortal:
    key: str
    display_name: str
    customer_org: str
    jurisdiction: str
    state_code: str
    public_router_base_url: str = "https://bids.sciquest.com/apps/Router/PublicEvent"
    discovery_url: str | None = None
    authoritative_bid_board_url: str | None = None
    owning_organization: str | None = None
    platform_variant: str = "JAGGAER ONE public event"
    default_tab: str | None = "PHX_NAV_SourcingAllOpps"
    event_number_parameter: str = "eventNumExact"
    headers: Mapping[str, str] = field(default_factory=dict)
    page_size: int = 25
    max_pages: int = 3
    max_results: int = 100
    request_timeout: float = 30
    max_retries: int = 2
    backoff_seconds: float = 0.5
    jitter_seconds: float = 0.25
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown: float = 60
    public_detail: bool = True
    discover_attachments: bool = True
    parser_strategy: str = "semantic-html"
    remote_keyword_search: bool = False
    enabled: bool = True
    verification_status: str = "fixture_verified"
    notes: tuple[str, ...] = ()
    allowed_document_hosts: tuple[str, ...] = ()

    @property
    def bid_board_url(self) -> str:
        return self.authoritative_bid_board_url or (
            f"{self.public_router_base_url}?{urlencode({'CustomerOrg': self.customer_org})}"
        )

    @property
    def search_url(self) -> str:
        return self.discovery_url or self.bid_board_url


UTAH_U3P = JaggaerPortal(
    "utah/u3p",
    "Utah Public Procurement Place (U3P)",
    "StateOfUtah",
    "Utah",
    "UT",
    notes=("Includes participating public entities; preserve the actual issuer.",),
)
WISCONSIN_SHOPUW = JaggaerPortal(
    "wisconsin/shopuw",
    "University of Wisconsin System ShopUW+ Public Bid Board",
    "UWisconsin",
    "Wisconsin",
    "WI",
    owning_organization="University of Wisconsin System",
    notes=("Scoped to UW System events, not statewide Wisconsin coverage.",),
)
GEORGIA_SOURCING = JaggaerPortal(
    "georgia/sourcing-director",
    "Georgia JAGGAER Sourcing Director",
    "Georgia",
    "Georgia",
    "GA",
    remote_keyword_search=True,
    notes=("Secondary to the Georgia Procurement Registry; not complete statewide coverage.",),
)
IOWA_IMPACS = JaggaerPortal(
    "iowa/impacs",
    "Iowa IMPACS JAGGAER Sourcing",
    "DASIowa",
    "Iowa",
    "IA",
    notes=("The State of Iowa public bid interface may be the authoritative upstream source.",),
)
JAGGAER_PORTALS = {p.key: p for p in (UTAH_U3P, WISCONSIN_SHOPUW, GEORGIA_SOURCING, IOWA_IMPACS)}


@dataclass(frozen=True, slots=True)
class JaggaerQuery(ConnectorQuery):
    keyword: str | None = None
    event_number: str | None = None
    status: str | None = None
    issuing_organization: str | None = None
    posted_from: date | None = None
    posted_to: date | None = None
    closing_from: date | None = None
    closing_to: date | None = None
    page_size: int | None = None
    max_pages: int | None = None
    max_results: int | None = None
    include_details: bool = True
    include_attachments: bool = True


class JaggaerTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class JaggaerHealth:
    available: bool
    access_state: JaggaerAccessState
    tenant: str
    platform: str
    platform_variant: str
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    last_error_class: str | None
    last_error_message: str | None
    discovery_supported: bool
    keyword_search_supported: bool
    detail_supported: bool
    document_discovery_supported: bool
    public_document_download_observed: bool
    login_required_observed: bool
    captcha_observed: bool
    parser_strategy: str
    configuration_valid: bool


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


class _PublicEventParser(HTMLParser):
    """Parse sanitized semantic markup without tenant-specific CSS selectors."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._record: dict[str, Any] | None = None
        self._depth = 0
        self._field: str | None = None
        self._section: str | None = None
        self._href: str | None = None
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        marker = values.get("data-event-id") or values.get("data-jaggaer-event")
        if marker is not None and self._record is None:
            self._record, self._depth = {"event_id": marker}, 1
        elif self._record is not None:
            self._depth += 1
        self._field = (values.get("data-field") or "").replace("-", "_") or None
        self._section = values.get("data-section") or self._section
        self._attrs, self._text = values, []
        if tag == "a":
            self._href = values.get("href")

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = _clean("".join(self._text))
        if self._record is not None:
            if self._field and text:
                if self._field in {"commodity", "category", "award_supplier"}:
                    self._record.setdefault(self._field + "s", []).append(text)
                else:
                    self._record[self._field] = text
            if tag == "a" and self._href:
                if self._field and self._field.endswith("_url"):
                    self._record[self._field] = self._href
                link = {
                    "title": text or "Document",
                    "url": self._href,
                    **{
                        k[5:].replace("-", "_"): v
                        for k, v in self._attrs.items()
                        if k.startswith("data-")
                    },
                }
                if self._section == "documents" or re.search(
                    r"\.(?:pdf|docx?|xlsx?|csv|zip)\b|addend|amend|q\s*&\s*a|award|tabulation|\b(?:rfp|rfq|ifb|itb|sow|pws)\b",
                    f"{text} {self._href}",
                    re.I,
                ):
                    self._record.setdefault("documents", []).append(link)
                elif not self._record.get("event_url"):
                    self._record["event_url"] = self._href
                self._href = None
            self._depth -= 1
            if self._depth == 0:
                self.records.append(self._record)
                self._record = None
        self._field, self._text = None, []
        if tag == "section":
            self._section = None


class JaggaerSciQuestConnector(BaseConnector):
    platform_family = "jaggaer/sciquest"
    jurisdictions = ("Utah", "Wisconsin", "Georgia", "Iowa")
    _transient = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
    _transient_query = frozenset({"timestamp", "time", "sessionid", "jsessionid", "navstate", "_"})

    def __init__(
        self,
        portal: JaggaerPortal = UTAH_U3P,
        *,
        transport: JaggaerTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.portal, self._sleep, self._random, self._now = portal, sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=portal.request_timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={
                "User-Agent": "TrustEST-SLED-Aggregator/0.1 (public read-only)",
                **portal.headers,
            },
        )
        self._owns_transport = transport is None
        self._failures = 0
        self._last_status = None
        self._last_failure = self._last_success = None
        self._last_error_class = self._last_error_message = None
        self._access = JaggaerAccessState.PUBLIC
        self._login_observed = self._captcha_observed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> JaggaerHealth:
        opened = self._circuit_open()
        return JaggaerHealth(
            not opened and self._failures == 0,
            self._access,
            self.portal.key,
            self.platform_family,
            self.portal.platform_variant,
            opened,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._last_error_class,
            self._last_error_message,
            self.portal.enabled,
            self.portal.remote_keyword_search,
            self.portal.public_detail,
            self.portal.discover_attachments,
            False,
            self._login_observed,
            self._captcha_observed,
            self.portal.parser_strategy,
            self._configuration_valid(),
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, JaggaerQuery)
            else JaggaerQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if q.jurisdiction and q.jurisdiction.casefold() not in {
            self.portal.jurisdiction.casefold(),
            self.portal.state_code.casefold(),
        }:
            return
        if not self.portal.enabled or not self._configuration_valid():
            raise JaggaerAccessError(JaggaerAccessState.UNSUPPORTED)
        if self._circuit_open():
            raise JaggaerAvailabilityError(f"{self.portal.key} circuit is open")
        page_size = min(q.page_size or self.portal.page_size, 100)
        max_pages = min(q.max_pages or self.portal.max_pages, 20)
        maximum = min(q.limit, q.max_results or self.portal.max_results, 1000)
        records: dict[str, dict[str, Any]] = {}
        pages: set[str] = set()
        try:
            for page in range(1, max_pages + 1):
                response = await self._request(
                    self.portal.search_url, self._params(q, page, page_size)
                )
                parsed = self._parse(response)
                fingerprint = hashlib.sha256(repr(parsed).encode()).hexdigest()
                if not parsed or fingerprint in pages:
                    break
                pages.add(fingerprint)
                for record in parsed:
                    identity = self._identity(record)
                    if identity:
                        records[identity] = self._merge(records.get(identity, {}), record)
                if len(parsed) < page_size:
                    break
            keyword = _clean(q.keyword or " ".join(q.keywords)).casefold()
            for identity, record in records.items():
                if (
                    keyword
                    and not self.portal.remote_keyword_search
                    and keyword not in repr(record).casefold()
                ):
                    continue
                if q.include_details and self.portal.public_detail:
                    detail = self._event_url(record, q.event_number)
                    if detail and detail != self.portal.search_url:
                        detail_records = self._parse(await self._request(detail))
                        if detail_records:
                            record = self._merge(record, detail_records[0])
                yield self._normalize(identity, record, q)
                maximum -= 1
                if maximum <= 0:
                    return
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _params(self, q: JaggaerQuery, page: int, page_size: int) -> dict[str, str]:
        values: dict[str, Any] = {
            "CustomerOrg": self.portal.customer_org,
            "tab": self.portal.default_tab,
            "page": page,
            "pageSize": page_size,
            "status": q.status,
            "issuingOrganization": q.issuing_organization,
            "postedFrom": q.posted_from,
            "postedTo": q.posted_to,
            "closingFrom": q.closing_from,
            "closingTo": q.closing_to,
        }
        if q.event_number:
            values[self.portal.event_number_parameter] = q.event_number
        keyword = q.keyword or " ".join(q.keywords)
        if keyword and self.portal.remote_keyword_search:
            values["keyword"] = keyword
        return {
            k: v.isoformat() if isinstance(v, date) else str(v)
            for k, v in values.items()
            if v not in (None, "")
        }

    async def _request(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        if not self._safe_url(url):
            raise JaggaerError("unsafe public URL")
        for attempt in range(self.portal.max_retries + 1):
            try:
                response = await self._transport.get(url, params=params)
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.portal.max_retries:
                    raise JaggaerAvailabilityError("JAGGAER public connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if not self._safe_url(str(response.url)):
                raise JaggaerError("unsafe redirect target")
            if response.status_code in self._transient:
                if attempt == self.portal.max_retries:
                    raise JaggaerAvailabilityError(f"JAGGAER unavailable ({response.status_code})")
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 404:
                raise JaggaerAccessError(JaggaerAccessState.NOT_FOUND)
            if response.status_code >= 400:
                raise JaggaerAccessError(JaggaerAccessState.RESTRICTED)
            state = self._detect_access(response)
            if state not in {JaggaerAccessState.PUBLIC, JaggaerAccessState.PUBLIC_METADATA_ONLY}:
                raise JaggaerAccessError(state)
            self._access, self._failures, self._last_failure = state, 0, None
            self._last_success = self._now()
            return response
        raise AssertionError("retry loop exhausted")

    def _parse(self, response: httpx.Response) -> list[dict[str, Any]]:
        content_type = response.headers.get("content-type", "").casefold()
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise JaggaerAccessError(JaggaerAccessState.MALFORMED) from exc
            records = payload.get("events") if isinstance(payload, dict) else payload
            if not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
                raise JaggaerAccessError(JaggaerAccessState.MALFORMED)
            return records
        if "html" not in content_type:
            raise JaggaerAccessError(JaggaerAccessState.MALFORMED)
        parser = _PublicEventParser()
        parser.feed(response.text)
        return parser.records

    def _detect_access(self, response: httpx.Response) -> JaggaerAccessState:
        text = response.text[:200_000].casefold()
        if re.search(r"captcha|access denied.*bot|cloudflare.*challenge", text):
            self._captcha_observed = True
            return JaggaerAccessState.CAPTCHA
        if re.search(r"supplier login|sign in to your account|username.*password", text):
            self._login_observed = True
            return JaggaerAccessState.LOGIN_REQUIRED
        if re.search(r"create (?:a |your )?(?:supplier )?account|supplier registration", text):
            return JaggaerAccessState.REGISTRATION_REQUIRED
        if re.search(r"scheduled maintenance|service unavailable", text):
            return JaggaerAccessState.UNAVAILABLE
        if re.search(r"<app-root[^>]*>\s*</app-root>|javascript (?:is )?required", text):
            return JaggaerAccessState.UNSUPPORTED
        # A response action can require registration while public event metadata remains public.
        if "respond now" in text and ("data-event-id" in text or "data-jaggaer-event" in text):
            return JaggaerAccessState.PUBLIC
        return JaggaerAccessState.PUBLIC

    def _normalize(self, identity: str, record: dict[str, Any], q: JaggaerQuery) -> RawOpportunity:
        title = _clean(record.get("title"))
        agency = _clean(
            record.get("issuing_organization") or record.get("organization") or record.get("agency")
        )
        if not title or not agency:
            raise JaggaerAccessError(JaggaerAccessState.MALFORMED)
        number = _clean(record.get("event_number") or record.get("solicitation_number")) or None
        url = self._event_url(record, number) or self.portal.bid_board_url
        payload = dict(record)
        payload["jaggaer_sciquest"] = {
            "tenant": self.portal.key,
            "customer_org": self.portal.customer_org,
            "platform_variant": self.portal.platform_variant,
            "access_state": self._access.value,
            "verification_status": self.portal.verification_status,
            "keyword_filtering": "remote" if self.portal.remote_keyword_search else "local",
            "retrieved_at": self._now().isoformat(),
            "authoritative_bid_board_url": self.portal.bid_board_url,
        }
        payload["documents"] = (
            self._documents(record, identity, url) if q.include_attachments else []
        )
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.portal.jurisdiction,
                source_id=identity,
                opportunity_url=url,
            ),
            title=title,
            agency=agency,
            description=_clean(record.get("description")) or None,
            solicitation_number=number,
            status=self._status(record.get("status")),
            posted_at=self._datetime(record.get("posted_date")),
            due_at=self._datetime(record.get("close_date") or record.get("response_deadline")),
            categories=self._dedupe_strings(
                [
                    *record.get("categories", []),
                    *record.get("commoditys", []),
                    *record.get("nigp_codes", []),
                    *record.get("unspsc_codes", []),
                ]
            ),
            raw_payload=payload,
        )

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
            filename = _clean(item.get("filename")) or urlparse(url).path.rsplit("/", 1)[-1]
            restricted = str(item.get("access", "")).casefold() in {"login_required", "restricted"}
            result.append(
                {
                    "document_title": title,
                    "displayed_filename": filename or None,
                    "media_type": item.get("media_type"),
                    "file_extension": filename.rsplit(".", 1)[-1].lower()
                    if "." in filename
                    else None,
                    "displayed_size": item.get("size"),
                    "document_category": self._document_category(title),
                    "posted_date": item.get("posted_date"),
                    "modified_date": item.get("modified_date"),
                    "addendum_or_amendment_number": item.get("number"),
                    "public_download_url": url,
                    "public_detail_page_url": parent,
                    "parent_event_id": identity,
                    "publicly_retrievable": not restricted,
                    "access_state": "login_required" if restricted else "public",
                    "captcha_present": False,
                    "raw_link_attributes": dict(item),
                }
            )
        return result

    def _identity(self, record: Mapping[str, Any]) -> str | None:
        stable = _clean(record.get("event_id"))
        number = _clean(record.get("event_number") or record.get("solicitation_number"))
        if stable:
            return f"{self.portal.key}:id:{stable}"
        if number:
            return f"{self.portal.key}:event:{number}"
        title, agency = (
            _clean(record.get("title")),
            _clean(record.get("issuing_organization") or record.get("agency")),
        )
        if title and agency:
            digest = hashlib.sha256(f"{self.portal.key}|{title}|{agency}".encode()).hexdigest()[:20]
            return f"{self.portal.key}:derived:{digest}"
        return None

    def _event_url(self, record: Mapping[str, Any], number: str | None = None) -> str | None:
        direct = self._safe_url(record.get("event_url"), self.portal.bid_board_url)
        if direct:
            return self._canonical_url(direct)
        number = number or _clean(record.get("event_number") or record.get("solicitation_number"))
        if not number:
            return None
        params = {
            "CustomerOrg": self.portal.customer_org,
            self.portal.event_number_parameter: number,
        }
        if self.portal.default_tab:
            params["tab"] = self.portal.default_tab
        return f"{self.portal.public_router_base_url}?{urlencode(params)}"

    def _safe_url(
        self, value: Any, base: str | None = None, *, document: bool = False
    ) -> str | None:
        if not value:
            return None
        parsed = urlparse(urljoin(base or self.portal.public_router_base_url, str(value).strip()))
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
        allowed = {
            (urlparse(self.portal.public_router_base_url).hostname or "").casefold(),
            *(h.casefold() for h in self.portal.allowed_document_hosts),
        }
        if host not in allowed or (document and host not in allowed):
            return None
        return urlunparse(parsed)

    def _canonical_url(self, url: str) -> str:
        parsed = urlparse(url)
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
                    parsed = email.utils.parsedate_to_datetime(retry_after)
                    return max(0, (parsed - self._now()).total_seconds())
                except (TypeError, ValueError):
                    pass
        return (
            self.portal.backoff_seconds * (2**attempt) + self.portal.jitter_seconds * self._random()
        )

    def _record_failure(self, exc: Exception) -> None:
        self._failures += 1
        self._last_failure = self._now()
        self._last_error_class = type(exc).__name__
        self._last_error_message = str(exc)[:200]
        if isinstance(exc, JaggaerAccessError):
            self._access = exc.state
        else:
            self._access = JaggaerAccessState.TRANSIENT_ERROR

    def _circuit_open(self) -> bool:
        if self._failures < self.portal.circuit_breaker_threshold or not self._last_failure:
            return False
        if (
            self._now() - self._last_failure
        ).total_seconds() >= self.portal.circuit_breaker_cooldown:
            self._failures = 0
            return False
        return True

    def _configuration_valid(self) -> bool:
        return bool(
            re.fullmatch(r"[A-Za-z0-9_.-]+", self.portal.customer_org)
            and self._safe_url(self.portal.search_url)
        )

    @staticmethod
    def _merge(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(old)
        result.update({k: v for k, v in new.items() if v not in (None, "", [])})
        result["documents"] = [*old.get("documents", []), *new.get("documents", [])]
        return result

    @staticmethod
    def _dedupe_strings(values: list[Any]) -> list[str]:
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
        if any(x in text for x in ("open", "posted", "active")):
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
    def _document_category(title: str) -> str:
        text = title.casefold()
        for pattern, category in (
            (r"addend", "addendum"),
            (r"amend", "amendment"),
            (r"q\s*&\s*a|questions", "questions_and_answers"),
            (r"award|intent", "award_notice"),
            (r"tabulation", "tabulation"),
            (r"pricing", "pricing"),
            (r"\bsow\b|scope", "scope"),
            (r"spec", "specifications"),
            (r"\b(?:rfp|rfq|ifb|itb|rfi)\b", "solicitation"),
        ):
            if re.search(pattern, text):
                return category
        return "other"
