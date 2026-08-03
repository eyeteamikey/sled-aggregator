"""Anonymous, bounded connector for Rhode Island RIVIP External solicitations.

Only the configured public search form may be posted.  The navigator rejects
unknown controls and refreshes ASP.NET state from every response; state is
never retained in normalized records or logs.
"""

import hashlib
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

CANONICAL_FAMILY = "rhode-island/rivip-external"
ALIASES = (
    "ri-rivip-external",
    "rhode-island-rivip",
    "rivip-external",
    "ri-external-solicitations",
    "rhode-island-external-solicitations",
)
STATE_FIELDS = frozenset({"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"})
SEARCH_FIELDS = frozenset(
    {
        "entity",
        "group",
        "bid_number",
        "status",
        "keyword",
        "start_date",
        "end_date",
        "posted_date",
        "closing_date",
        "search",
    }
)
EVENT_TARGETS = frozenset({"results$pager"})


class RIVIPError(RuntimeError):
    pass


class RIVIPAccessError(RIVIPError):
    def __init__(self, state: str):
        self.state = state
        super().__init__(f"RIVIP public access boundary: {state}")


@dataclass(frozen=True, slots=True)
class RIVIPProfile:
    profile_key: str = "rhode-island-external"
    jurisdiction: str = "Rhode Island"
    state: str = "RI"
    system_name: str = "RIVIP External Solicitations"
    landing_url: str = "https://www.purchasing.ri.gov/"
    search_url: str = "https://www.purchasing.ri.gov/RIVIP/ExternalBids.aspx"
    detail_url_pattern: str = (
        "https://www.purchasing.ri.gov/RIVIP/ViewExternalBid.aspx?BidNum={external_bid_id}"
    )
    document_url_pattern: str = "https://www.purchasing.ri.gov/RIVIP/ExternalBids/{path}"
    legacy_repository_url: str = "https://www.purchasing.ri.gov/bidding/ExternalBidSearch.aspx"
    approved_hostname: str = "www.purchasing.ri.gov"
    approved_document_hosts: tuple[str, ...] = ("www.purchasing.ri.gov", "purchasing.ri.gov")
    default_entity_filter: str | None = None
    default_status: str = "active"
    maximum_pages: int = 5
    maximum_results: int = 100
    maximum_form_submissions: int = 5
    request_timeout: float = 15
    markup_variant: str = "rivip_external_webforms_v1"
    source_state: str = "active"
    verification_status: str = "fixture_verified"
    verification_timestamp: datetime | None = None
    verification_notes: str = "Sanitized deterministic fixtures; live availability is not implied."
    replacement_platform: str | None = None
    replacement_url: str | None = None

    def __post_init__(self):
        if self.source_state not in {
            "active",
            "legacy",
            "migrated",
            "dual_published",
            "configured_unverified",
            "unavailable",
        }:
            raise ValueError("invalid source state")
        if not (
            1 <= self.maximum_pages <= 20
            and 1 <= self.maximum_results <= 1000
            and 1 <= self.maximum_form_submissions <= 20
        ):
            raise ValueError("invalid collection bounds")
        for value in (
            self.landing_url,
            self.search_url,
            self.detail_url_pattern,
            self.legacy_repository_url,
        ):
            if urlparse(value).hostname != self.approved_hostname:
                raise ValueError("profile URL is outside the approved hostname")


FIXTURE_PROFILE = RIVIPProfile()


@dataclass(frozen=True, slots=True)
class RIVIPQuery(ConnectorQuery):
    entity: str | None = None
    group: str | None = None
    solicitation_number: str | None = None
    status: str | None = None
    keyword: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    posted_date: date | None = None
    closing_date: date | None = None
    maximum_pages: int | None = None
    maximum_results: int | None = None
    include_details: bool = True


class Transport(Protocol):
    async def get(self, url: str) -> httpx.Response: ...
    async def post(self, url: str, *, data: Mapping[str, str]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden: dict[str, str] = {}
        self.rows: list[dict[str, str]] = []
        self.docs: list[dict[str, str]] = []
        self.fields: dict[str, str] = {}
        self.next_target: str | None = None
        self.marker = False
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == "rivip-external-results" or a.get("id") == "rivip-external-detail":
            self.marker = True
        if (
            tag == "input"
            and a.get("type", "").lower() == "hidden"
            and a.get("name") in STATE_FIELDS
        ):
            self.hidden[a["name"]] = a.get("value", "")
        if tag == "article" and a.get("data-external-bid-id"):
            self.rows.append(
                {k.removeprefix("data-"): v for k, v in a.items() if k.startswith("data-")}
            )
        if tag == "meta" and a.get("name", "").startswith("rivip:"):
            self.fields[a["name"][6:]] = a.get("content", "")
        if tag == "a" and a.get("data-next-event"):
            self.next_target = a["data-next-event"]
        if tag == "a" and a.get("data-document-kind"):
            self.docs.append(
                {k.removeprefix("data-"): v for k, v in a.items() if k.startswith("data-")}
                | {"href": a.get("href", "")}
            )

    def handle_data(self, data):
        self.text.append(data)


def parse_page(html: str) -> _Parser:
    parser = _Parser()
    try:
        parser.feed(html)
    except Exception as exc:
        raise RIVIPAccessError("changed_markup") from exc
    return parser


def detect_boundary(html: str) -> str | None:
    value = re.sub(r"\s+", " ", html).casefold()
    for state, terms in (
        ("captcha_required", ("captcha", "g-recaptcha", "hcaptcha")),
        ("login_required", ("agency login", "sign in to continue", "password")),
        ("registration_required", ("vendor registration required",)),
        ("migrated", ("has moved to rhodybuy", "has moved to bidnet")),
        ("unavailable", ("session has expired", "service unavailable")),
    ):
        if any(term in value for term in terms):
            return state
    if "validation of viewstate mac failed" in value or "invalid viewstate" in value:
        return "expired_view_state"
    if "invalid postback or callback argument" in value:
        return "invalid_event_validation"
    return None


class PublicWebFormsNavigator:
    """Allowlisted anonymous search/pagination POST navigator."""

    def __init__(self, profile: RIVIPProfile, transport: Transport):
        self.profile, self.transport = profile, transport
        self.state: dict[str, str] = {}
        self.submissions = 0
        self._events: set[str] = set()

    def refresh(self, html: str) -> _Parser:
        boundary = detect_boundary(html)
        if boundary:
            raise RIVIPAccessError(boundary)
        page = parse_page(html)
        if not page.marker:
            raise RIVIPAccessError("changed_markup")
        if not STATE_FIELDS.issubset(page.hidden):
            raise RIVIPAccessError("changed_markup")
        self.state = page.hidden
        return page

    async def initialize(self) -> _Parser:
        return self.refresh((await self.transport.get(self.profile.search_url)).text)

    async def submit(self, fields: Mapping[str, str], *, event_target: str = "") -> _Parser:
        if urlparse(self.profile.search_url).hostname != self.profile.approved_hostname:
            raise RIVIPError("non-public POST rejected")
        if set(fields) - SEARCH_FIELDS:
            raise RIVIPError("unknown public search control")
        if event_target and event_target not in EVENT_TARGETS:
            raise RIVIPError("unknown event target")
        fingerprint = f"{event_target}:{fields.get('__EVENTARGUMENT', '')}"
        if event_target and fingerprint in self._events:
            raise RIVIPError("pagination cycle")
        if self.submissions >= self.profile.maximum_form_submissions:
            raise RIVIPError("maximum form submissions reached")
        self._events.add(fingerprint)
        self.submissions += 1
        payload = (
            dict(self.state) | dict(fields) | {"__EVENTTARGET": event_target, "__EVENTARGUMENT": ""}
        )
        response = await self.transport.post(self.profile.search_url, data=payload)
        return self.refresh(response.text)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def sanitize_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" .")
    return value[:180] or "document"


def _status(value: str) -> OpportunityStatus:
    return {
        "active": OpportunityStatus.OPEN,
        "open": OpportunityStatus.OPEN,
        "awarded": OpportunityStatus.AWARDED,
        "cancelled": OpportunityStatus.CANCELLED,
        "closed": OpportunityStatus.CLOSED,
    }.get(value.casefold(), OpportunityStatus.UNKNOWN)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


class RIVIPExternalConnector(BaseConnector):
    platform_family = CANONICAL_FAMILY
    jurisdictions = ("Rhode Island",)
    document_pipeline_compatible = True
    public_read_only = True

    def __init__(
        self, profile: RIVIPProfile = FIXTURE_PROFILE, *, transport: Transport | None = None
    ):
        self.profile = profile
        self._owned = transport is None
        self._transport = transport or httpx.AsyncClient(
            timeout=profile.request_timeout, follow_redirects=False
        )

    async def aclose(self):
        if self._owned:
            await self._transport.aclose()

    def _fields(self, query: RIVIPQuery) -> dict[str, str]:
        values = {
            "entity": query.entity or self.profile.default_entity_filter or "",
            "group": query.group or "",
            "bid_number": query.solicitation_number or "",
            "status": query.status or self.profile.default_status,
            "keyword": query.keyword or "",
            "start_date": str(query.start_date or ""),
            "end_date": str(query.end_date or ""),
            "posted_date": str(query.posted_date or ""),
            "closing_date": str(query.closing_date or ""),
            "search": "Search",
        }
        if not any(
            (
                values["entity"],
                values["bid_number"],
                values["keyword"],
                values["start_date"],
                values["posted_date"],
                values["status"],
            )
        ):
            raise RIVIPError("an explicit bounded filter is required")
        return values

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = (
            query
            if isinstance(query, RIVIPQuery)
            else RIVIPQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        if self.profile.source_state in {"migrated", "unavailable"}:
            raise RIVIPAccessError(self.profile.source_state)
        nav = PublicWebFormsNavigator(self.profile, self._transport)
        await nav.initialize()
        page = await nav.submit(self._fields(q))
        seen, page_hashes = set(), set()
        max_pages = min(q.maximum_pages or self.profile.maximum_pages, self.profile.maximum_pages)
        max_results = min(q.maximum_results or q.limit, self.profile.maximum_results)
        for _ in range(max_pages):
            digest = hashlib.sha256(repr(page.rows).encode()).hexdigest()
            if digest in page_hashes:
                break
            page_hashes.add(digest)
            for row in page.rows:
                key = (_slug(row.get("entity", "")), row["external-bid-id"])
                if key in seen:
                    continue
                seen.add(key)
                detail_url = urljoin(self.profile.search_url, row.get("detail-url", ""))
                detail = None
                if q.include_details:
                    response = await self._transport.get(detail_url)
                    boundary = detect_boundary(response.text)
                    if boundary:
                        raise RIVIPAccessError(boundary)
                    detail = parse_page(response.text)
                    if not detail.marker:
                        raise RIVIPAccessError("changed_markup")
                yield self._normalize(row, detail, detail_url)
                if len(seen) >= max_results:
                    return
            if not page.next_target:
                return
            page = await nav.submit({}, event_target=page.next_target)

    def _normalize(self, row: dict[str, str], detail: _Parser | None, url: str) -> RawOpportunity:
        fields = dict(row) | (detail.fields if detail else {})
        entity = fields.get("entity", "").strip()
        bid_id = fields["external-bid-id"]
        if not entity or not fields.get("title") or not bid_id:
            raise RIVIPAccessError("changed_markup")
        source_id = f"{CANONICAL_FAMILY}:{_slug(entity)}:{bid_id}"
        raw = {
            "external_bid_id": bid_id,
            "entity": entity,
            "entity_id": fields.get("entity-id"),
            "entity_type": fields.get("entity-type", "other"),
            "solicitation_group": fields.get("group"),
            "procurement_type": fields.get("procurement-type"),
            "contact": fields.get("contact"),
            "instructions": fields.get("instructions"),
            "location": fields.get("location"),
            "available_date": fields.get("available-date"),
            "question_deadline": fields.get("question-deadline"),
            "award_date": fields.get("award-date"),
            "award_information": fields.get("award"),
            "source_state": fields.get("source-state", self.profile.source_state),
            "replacement_platform": fields.get("replacement-platform")
            or self.profile.replacement_platform,
            "replacement_url": fields.get("replacement-url") or self.profile.replacement_url,
            "verification_status": self.profile.verification_status,
            "access_state": fields.get("access-state", "public"),
            "canonical_detail_url": url,
            "original_discovery_url": self.profile.search_url,
            "collected_at": datetime.now(UTC).isoformat(),
            "source_provenance": {k: "public_detail" for k in fields},
        }
        if detail:
            raw["documents"] = detail.docs
        return RawOpportunity(
            source=SourceRef(
                platform_family=CANONICAL_FAMILY,
                jurisdiction=self.profile.jurisdiction,
                source_id=source_id,
                opportunity_url=url,
            ),
            title=fields["title"],
            agency=entity,
            description=fields.get("description"),
            solicitation_number=fields.get("solicitation-number"),
            status=_status(fields.get("status", "unknown")),
            posted_at=_dt(fields.get("posted-date")),
            due_at=_dt(fields.get("closing-date")),
            raw_payload=raw,
        )

    def document_candidates(self, opportunity: RawOpportunity) -> list[DocumentCandidate]:
        result, seen = [], set()
        for item in opportunity.raw_payload.get("documents", []):
            href = urljoin(str(opportunity.source.opportunity_url), item.get("href", ""))
            host = urlparse(href).hostname
            kind = item.get("document-kind", "other")
            access = item.get("access-state", "public")
            eligible = bool(
                href
                and host in self.profile.approved_document_hosts
                and access == "public"
                and kind != "public_bid_response"
            )
            if href in seen:
                continue
            seen.add(href)
            label = item.get("label", "document")
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=href,
                    source_opportunity_url=opportunity.source.opportunity_url,
                    source_detail_url=opportunity.source.opportunity_url,
                    filename=sanitize_filename(item.get("filename") or label),
                    label=label,
                    category=kind,
                    access_state=AccessState.PUBLIC
                    if eligible
                    else AccessState.EXTERNAL_RESPONSE_SYSTEM,
                    publicly_retrievable=eligible,
                    addendum_number=item.get("addendum-number"),
                    version_label=item.get("version"),
                    posted_at=_dt(item.get("posted-date")),
                    raw_metadata={
                        **{key: value for key, value in item.items() if key != "href"},
                        "authoritative_detail_url": str(opportunity.source.opportunity_url),
                    },
                )
            )
        return result
