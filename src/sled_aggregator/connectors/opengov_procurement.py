"""Anonymous OpenGov Procurement (formerly ProcureNow) connector.

The request contract is limited to routes observed on the public Ocean County
and Alameda County portals on 2026-08-24. Document download is not attempted:
the public UI requires login before invoking its download endpoint, while detail
responses contain short-lived signed URLs that must never be retained.
"""

import asyncio
import email.utils
import html
import ipaddress
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef


class OpenGovAccessState(StrEnum):
    PUBLIC = "public"
    PUBLIC_METADATA_ONLY = "public_metadata_only"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    CAPTCHA = "captcha"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"
    UNSUPPORTED_SEARCH = "unsupported_search"
    TRANSIENT_ERROR = "transient_error"


class OpenGovError(RuntimeError):
    pass


class OpenGovAccessError(OpenGovError):
    def __init__(self, state: OpenGovAccessState) -> None:
        self.state = state
        super().__init__(f"OpenGov public access ended at {state.value}")


class OpenGovAvailabilityError(OpenGovError):
    pass


_ORGANIZATION_TYPES = frozenset(
    {
        "state", "county", "city", "town", "transit authority", "fire district",
        "school district", "university", "utility", "special district", "cooperative",
    }
)
_SORT_FIELDS = frozenset({"title", "status", "releaseProjectDate", "proposalDeadline"})
_SORT_DIRECTIONS = frozenset({"ASC", "DESC"})


@dataclass(frozen=True, slots=True)
class OpenGovPortal:
    tenant_key: str
    tenant_slug: str
    display_name: str
    jurisdiction: str
    state_code: str
    organization_type: str
    owning_organization: str
    portal_base_url: str = "https://procurement.opengov.com"
    api_base_url: str = "https://api.procurement.opengov.com/api/v1"
    default_timezone: str = "UTC"
    page_size: int = 10
    maximum_pages: int = 10
    maximum_results: int = 100
    request_timeout: float = 30
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    retry_jitter_seconds: float = 0.25
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown: float = 60
    enabled: bool = True
    verification_status: str = "unverified_profile"
    notes: tuple[str, ...] = ()
    production: bool = True

    @property
    def portal_url(self) -> str:
        return f"{self.portal_base_url}/portal/{self.tenant_slug}"

    @property
    def public_projects_url(self) -> str:
        return f"{self.api_base_url}/government/{self.tenant_slug}/project/public"

    @property
    def government_url(self) -> str:
        return f"{self.api_base_url}/government/{self.tenant_slug}"

    def project_api_url(self, project_id: str) -> str:
        return f"{self.api_base_url}/project/{project_id}"

    def question_api_url(self, project_id: str) -> str:
        return f"{self.project_api_url(project_id)}/question"

    def project_url(self, project_id: str) -> str:
        return f"{self.portal_url}/projects/{project_id}"


OCEAN_COUNTY = OpenGovPortal(
    "ocean-county-nj", "oceancounty", "Ocean County, New Jersey", "New Jersey", "NJ",
    "county", "County of Ocean", default_timezone="America/New_York",
    verification_status="live_validated_2026-08-24",
    notes=(
        "Anonymous listing, filters, pagination, detail, Q&A, and attachment metadata validated.",
        "Downloads require login; related contracts were browser-visible but the API returned 401 without browser session state.",
    ),
)
ALAMEDA_COUNTY = OpenGovPortal(
    "alameda-county-ca", "acgov", "Alameda County, California", "California", "CA",
    "county", "County of Alameda", default_timezone="America/Los_Angeles",
    verification_status="live_validated_2026-08-24",
    notes=(
        "Anonymous listing, filters, pagination, detail, Q&A, and attachment metadata validated.",
        "Document download requires login.",
    ),
)

# Existing profiles remain available but are not promoted by this validation.
PHOENIX = OpenGovPortal("phoenix", "phoenix", "City of Phoenix, Arizona", "Arizona", "AZ", "city", "City of Phoenix", default_timezone="America/Phoenix")
SEATTLE = OpenGovPortal("seattle", "seattle", "City of Seattle, Washington", "Washington", "WA", "city", "City of Seattle", default_timezone="America/Los_Angeles")
CLEVELAND = OpenGovPortal("cleveland", "clevelandoh", "City of Cleveland, Ohio", "Ohio", "OH", "city", "City of Cleveland", default_timezone="America/New_York")
BRIDGEPORT = OpenGovPortal("bridgeport", "bridgeportct", "City of Bridgeport, Connecticut", "Connecticut", "CT", "city", "City of Bridgeport", default_timezone="America/New_York")
MOHAVE_COUNTY = OpenGovPortal("mohave-county", "mohavecounty", "Mohave County, Arizona", "Arizona", "AZ", "county", "Mohave County", default_timezone="America/Phoenix")
GALLUP = OpenGovPortal("gallup", "gallupnm", "City of Gallup, New Mexico", "New Mexico", "NM", "city", "City of Gallup", default_timezone="America/Denver")

OPENGOV_PORTALS = {
    p.tenant_key: p for p in (
        OCEAN_COUNTY, ALAMEDA_COUNTY, PHOENIX, SEATTLE, CLEVELAND, BRIDGEPORT,
        MOHAVE_COUNTY, GALLUP,
    )
}


@dataclass(frozen=True, slots=True)
class OpenGovQuery(ConnectorQuery):
    keyword: str | None = None
    project_id: str | None = None
    solicitation_number: str | None = None
    statuses: tuple[str, ...] = ()
    department_id: int | None = None
    category_ids: tuple[int, ...] = ()
    released_from: date | None = None
    released_to: date | None = None
    due_from: date | None = None
    due_to: date | None = None
    include_closed: bool = False
    include_awarded: bool = False
    include_details: bool = True
    include_documents: bool = True
    include_questions: bool = True
    sort_field: str = "proposalDeadline"
    sort_direction: str = "DESC"
    page_size: int | None = None
    maximum_pages: int | None = None
    maximum_results: int | None = None


class OpenGovTransport(Protocol):
    async def get(self, url: str) -> httpx.Response: ...
    async def post(self, url: str, *, json: Mapping[str, Any]) -> httpx.Response: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenGovHealth:
    available: bool
    access_state: OpenGovAccessState
    tenant: str
    platform: str
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    last_error_class: str | None
    discovery_supported: bool
    detail_supported: bool
    document_discovery_supported: bool
    document_download_supported: bool
    q_and_a_supported: bool
    contracts_api_access: str
    configuration_valid: bool


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _plain_text(value: Any) -> str:
    text = _clean(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))))
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


class OpenGovProcurementConnector(BaseConnector):
    platform_family = "opengov/procurement"
    jurisdictions = tuple(dict.fromkeys(p.jurisdiction for p in OPENGOV_PORTALS.values()))
    document_pipeline_compatible = True
    _transient_statuses = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def __init__(
        self, portal: OpenGovPortal = OCEAN_COUNTY, *,
        transport: OpenGovTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.portal, self._sleep, self._random, self._now = portal, sleep, random_value, now
        self._transport = transport or httpx.AsyncClient(
            timeout=portal.request_timeout, follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={"User-Agent": "TrustEST-SLED-Aggregator/0.1 (public read-only)"},
        )
        self._owns_transport = transport is None
        self._failures = 0
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._last_error_class: str | None = None
        self._access = OpenGovAccessState.PUBLIC_METADATA_ONLY

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    @property
    def health(self) -> OpenGovHealth:
        opened = self._circuit_open()
        return OpenGovHealth(
            not opened and self._failures == 0, self._access, self.portal.tenant_key,
            self.platform_family, opened, self._failures, self._last_status,
            self._last_failure, self._last_success, self._last_error_class,
            True, True, True, False, True, "session_dependent_not_called",
            self._configuration_valid(),
        )

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        q = query if isinstance(query, OpenGovQuery) else OpenGovQuery(
            keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
        )
        if q.jurisdiction and q.jurisdiction.casefold() not in {
            self.portal.jurisdiction.casefold(), self.portal.state_code.casefold(),
        }:
            return
        if not self.portal.enabled or not self._configuration_valid():
            raise OpenGovAccessError(OpenGovAccessState.UNSUPPORTED_SEARCH)
        if self._circuit_open():
            raise OpenGovAvailabilityError(f"{self.portal.tenant_key} circuit is open")
        if q.sort_field not in _SORT_FIELDS or q.sort_direction not in _SORT_DIRECTIONS:
            raise OpenGovAccessError(OpenGovAccessState.UNSUPPORTED_SEARCH)
        page_size = min(max(q.page_size or self.portal.page_size, 1), 50)
        max_pages = min(max(q.maximum_pages or self.portal.maximum_pages, 1), 20)
        maximum = min(max(q.limit, 0), q.maximum_results or self.portal.maximum_results, 1000)
        if maximum == 0:
            return
        seen: set[str] = set()
        try:
            for page in range(1, max_pages + 1):
                # OpenGov's application client passes ``{data: query}`` to its
                # request helper, but the helper serializes ``query`` itself as
                # the HTTP JSON body.  Sending the helper-options envelope over
                # the wire is accepted with HTTP 200 but silently ignores every
                # filter, sort, limit, and page field.
                body = self._listing_request(q, page, page_size)
                payload = await self._request_json("POST", self.portal.public_projects_url, body)
                count, rows = self._listing_rows(payload)
                for listed in rows:
                    project_id = _clean(listed.get("id"))
                    if not project_id:
                        raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
                    identity = f"{self.portal.tenant_key}:project:{project_id}"
                    if identity in seen:
                        continue
                    seen.add(identity)
                    record = dict(listed)
                    questions: list[dict[str, Any]] = []
                    if q.include_details:
                        detail = await self._request_json("GET", self.portal.project_api_url(project_id))
                        if not isinstance(detail, dict) or _clean(detail.get("id")) != project_id:
                            raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
                        record.update(detail)
                        if q.include_questions and bool(record.get("qaEnabled")):
                            question_payload = await self._request_json("GET", self.portal.question_api_url(project_id))
                            if not isinstance(question_payload, list) or not all(isinstance(x, dict) for x in question_payload):
                                raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
                            questions = question_payload
                    if not self._matches_local_dates(record, q):
                        continue
                    item = self._normalize(identity, record, questions, q)
                    self._record_success()
                    yield item
                    maximum -= 1
                    if maximum <= 0:
                        return
                if not rows or page * page_size >= count:
                    break
            self._record_success()
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _listing_request(self, q: OpenGovQuery, page: int, limit: int) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        keyword = _clean(q.keyword or " ".join(q.keywords))
        if keyword:
            filters.append({"type": "title", "value": keyword})
        if q.solicitation_number:
            filters.append({"type": "financialId", "value": q.solicitation_number})
        if q.department_id is not None:
            filters.append({"type": "department_id", "value": q.department_id})
        if q.category_ids:
            filters.append({"type": "categories", "value": list(q.category_ids)})
        if q.statuses:
            if len(q.statuses) != 1:
                raise OpenGovAccessError(OpenGovAccessState.UNSUPPORTED_SEARCH)
            filters.append({"type": "status", "value": q.statuses[0].casefold()})
        elif not q.include_closed and not q.include_awarded:
            filters.append({"type": "status", "value": "open"})
        return {
            "filters": filters, "quickSearchQuery": None, "limit": limit, "page": page,
            "sortField": q.sort_field, "sortDirection": q.sort_direction,
        }

    @staticmethod
    def _listing_rows(payload: Any) -> tuple[int, list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
        count, rows = payload.get("count"), payload.get("rows")
        if not isinstance(count, int) or count < 0 or not isinstance(rows, list):
            raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
        if not all(isinstance(row, dict) for row in rows):
            raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
        return count, rows

    async def _request_json(self, method: str, url: str, payload: Mapping[str, Any] | None = None) -> Any:
        if not self._safe_url(url):
            raise OpenGovError("unsafe public URL")
        if method == "POST" and url != self.portal.public_projects_url:
            raise OpenGovError("unobserved OpenGov POST route")
        for attempt in range(self.portal.retry_attempts + 1):
            try:
                if method == "GET":
                    response = await self._transport.get(url)
                elif method == "POST" and payload is not None:
                    response = await self._transport.post(url, json=payload)
                else:
                    raise OpenGovError("unsupported request")
            except (httpx.TransportError, ConnectionError, OSError) as exc:
                if attempt == self.portal.retry_attempts:
                    raise OpenGovAvailabilityError("OpenGov public connection failed") from exc
                await self._sleep(self._backoff(attempt, None))
                continue
            self._last_status = response.status_code
            if not self._safe_url(str(response.url)):
                raise OpenGovError("unsafe redirect target")
            if response.status_code in self._transient_statuses:
                if attempt == self.portal.retry_attempts:
                    raise OpenGovAvailabilityError(f"OpenGov unavailable ({response.status_code})")
                await self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code == 404:
                raise OpenGovAccessError(OpenGovAccessState.NOT_FOUND)
            if response.status_code in {401, 403}:
                raise OpenGovAccessError(OpenGovAccessState.LOGIN_REQUIRED)
            if response.status_code >= 400:
                raise OpenGovAccessError(OpenGovAccessState.RESTRICTED)
            access = self._detect_access(response)
            if access not in {OpenGovAccessState.PUBLIC, OpenGovAccessState.PUBLIC_METADATA_ONLY}:
                raise OpenGovAccessError(access)
            try:
                return response.json()
            except ValueError as exc:
                raise OpenGovAccessError(OpenGovAccessState.MALFORMED) from exc
        raise OpenGovAvailabilityError("OpenGov retry loop exhausted")

    @staticmethod
    def _detect_access(response: httpx.Response) -> OpenGovAccessState:
        content_type = response.headers.get("content-type", "").casefold()
        text = response.text[:20_000].casefold()
        if any(x in text for x in ("recaptcha", "hcaptcha", "cf-chl-", "performing security verification", "verify you are human", "captcha")):
            return OpenGovAccessState.CAPTCHA
        if any(x in text for x in ("supplier login", "sign in to continue", "login required")):
            return OpenGovAccessState.LOGIN_REQUIRED
        if "json" not in content_type:
            return OpenGovAccessState.MALFORMED
        return OpenGovAccessState.PUBLIC_METADATA_ONLY

    def _normalize(self, identity: str, record: Mapping[str, Any], questions: list[dict[str, Any]], query: OpenGovQuery) -> RawOpportunity:
        project_id, title = _clean(record.get("id")), _clean(record.get("title"))
        government = record.get("government") if isinstance(record.get("government"), dict) else {}
        organization = government.get("organization") if isinstance(government.get("organization"), dict) else {}
        agency = _clean(organization.get("name") or self.portal.owning_organization)
        if not project_id or not title or not agency:
            raise OpenGovAccessError(OpenGovAccessState.MALFORMED)
        project_url = self.portal.project_url(project_id)
        documents = self._document_metadata(record, identity, project_url) if query.include_documents else []
        payload = {
            "project": {k: record.get(k) for k in (
                "id", "financialId", "title", "status", "closedSubstatus", "closeOutReason",
                "type", "releaseProjectDate", "postedAt", "proposalDeadline", "qaDeadline",
                "qaResponseDeadline", "contractorSelectedDate",
            ) if record.get(k) is not None},
            "department": self._safe_object(record.get("department"), ("id", "name")),
            "government": {"code": government.get("code"), "organization": {
                k: organization.get(k) for k in (
                    "name", "timezone", "website", "address", "city", "state", "zip"
                ) if organization.get(k) is not None}},
            "contacts": self._contacts(record),
            "vendors": self._vendors(record),
            "award": {
                "closed_substatus": record.get("closedSubstatus"),
                "contractor_selected_date": record.get("contractorSelectedDate"),
                "public_bid_result": bool(record.get("isPublicBidResult")),
                "public_bid_pricing_result": bool(record.get("isPublicBidPricingResult")),
            },
            "amendments": self._amendments(record, notice=False),
            "notices": self._amendments(record, notice=True),
            "questions": self._questions(questions),
            "documents": documents,
            "source_provenance": {
                "listing_request": self.portal.public_projects_url,
                "detail_request": self.portal.project_api_url(project_id),
                "question_request": self.portal.question_api_url(project_id),
                "opportunity_url": project_url,
                "attachment_parent_id": project_id,
                "document_download_access": "login_required",
            },
            "opengov_procurement": {
                "tenant_key": self.portal.tenant_key, "tenant_code": self.portal.tenant_slug,
                "verification_status": self.portal.verification_status,
                "production_preset": self.portal.production,
                "listing_contract": "POST government/{tenant}/project/public",
                "detail_contract": "GET project/{id}",
                "questions_contract": "GET project/{id}/question",
            },
        }
        categories = [_clean(x.get("code") or x.get("title") or x.get("name")) for x in record.get("categories", []) if isinstance(x, dict)]
        return RawOpportunity(
            source=SourceRef(platform_family=self.platform_family, jurisdiction=self.portal.jurisdiction, source_id=identity, opportunity_url=project_url),
            title=title, agency=agency, description=_plain_text(record.get("summary")) or None,
            solicitation_number=_clean(record.get("financialId")) or None,
            status=self._status(record.get("status"), record.get("closedSubstatus")),
            posted_at=self._datetime(record.get("releaseProjectDate") or record.get("postedAt")),
            due_at=self._datetime(record.get("proposalDeadline")),
            categories=list(dict.fromkeys(x for x in categories if x)), raw_payload=payload,
        )

    def document_candidates(self, opportunity: RawOpportunity) -> list[DocumentCandidate]:
        result = []
        for item in opportunity.raw_payload.get("documents", []):
            result.append(DocumentCandidate(
                opportunity_id=opportunity.source.source_id,
                source_document_url=item["public_detail_page_url"],
                source_opportunity_url=opportunity.source.opportunity_url,
                filename=item["displayed_filename"], label=item.get("document_title"),
                mime_type=item.get("media_type"), access_state=AccessState.LOGIN_REQUIRED,
                source_document_id=_clean(item.get("source_document_id")) or None,
                category=item.get("document_category"), source_detail_url=item["public_detail_page_url"],
                referring_page_url=opportunity.source.opportunity_url,
                posted_at=self._datetime(item.get("posted_date")),
                addendum_number=_clean(item.get("addendum_number")) or None,
                publicly_retrievable=False, raw_metadata=dict(item),
            ))
        return result

    def _document_metadata(self, record: Mapping[str, Any], identity: str, project_url: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def add(item: Any, category: str, *, number: Any = None, posted: Any = None) -> None:
            if not isinstance(item, dict):
                return
            document_id, filename = _clean(item.get("id")), self._filename(item)
            if not document_id or not filename:
                return
            result.append({
                "source_document_id": document_id,
                "document_title": _clean(item.get("title") or item.get("name") or filename),
                "displayed_filename": filename, "media_type": self._mime_type(item.get("fileExtension")),
                "document_category": category, "posted_date": posted or item.get("created_at"),
                "addendum_number": number, "parent_project_id": _clean(record.get("id")),
                "parent_opportunity_id": identity, "public_detail_page_url": project_url,
                "publicly_retrievable": False, "access_state": "login_required",
                "storage_metadata": {k: item.get(k) for k in (
                    "id", "filename", "name", "title", "fileExtension", "type"
                ) if item.get(k) is not None},
            })

        add(record.get("documentAttachment"), "solicitation")
        for item in record.get("attachments", []):
            add(item, self._document_category(_clean(item.get("title") or item.get("filename"))))
        for amendment in record.get("addendums", []):
            if not isinstance(amendment, dict):
                continue
            category = "notice" if amendment.get("isNotice") else "addendum"
            for item in amendment.get("attachments", []):
                add(item, category, number=amendment.get("number"), posted=amendment.get("releasedAt"))
        return list({x["source_document_id"]: x for x in result}.values())

    @staticmethod
    def _contacts(record: Mapping[str, Any]) -> list[dict[str, Any]]:
        contacts = []
        for prefix, role, hidden in (
            ("contact", "project_contact", bool(record.get("hideContact"))),
            ("procurement", "procurement_contact", bool(record.get("hideProcurementContact"))),
        ):
            if hidden:
                continue
            name = _clean(record.get(f"{prefix}DisplayName") or record.get(f"{prefix}FullName"))
            if name:
                contacts.append({
                    "role": role, "name": name, "title": _clean(record.get(f"{prefix}Title")) or None,
                    "email": _clean(record.get(f"{prefix}Email")) or None,
                    "phone": _clean(record.get(f"{prefix}PhoneComplete")) or None,
                })
        for amendment in record.get("addendums", []):
            user = amendment.get("user") if isinstance(amendment, dict) else None
            if not isinstance(user, dict):
                continue
            name = _clean(user.get("displayName") or user.get("fullName"))
            if name:
                contacts.append({
                    "role": "notice_or_addendum_author", "name": name,
                    "title": _clean(user.get("title")) or None,
                    "email": _clean(user.get("email")) or None,
                    "phone": _clean(user.get("phoneComplete")) or None,
                })
        return list({(x["role"], x["name"], x.get("email")): x for x in contacts}.values())

    @staticmethod
    def _vendors(record: Mapping[str, Any]) -> list[dict[str, Any]]:
        bids = record.get("bidResults")
        if not isinstance(bids, dict):
            return []
        result = []
        for proposal in bids.get("proposalsData", []):
            if isinstance(proposal, dict) and _clean(proposal.get("vendorName")):
                result.append({
                    "name": _clean(proposal.get("vendorName")),
                    "city": _clean(proposal.get("vendorCity")) or None,
                    "state": _clean(proposal.get("vendorState")) or None,
                    "result_type": "public_bid_result",
                })
        return list({x["name"].casefold(): x for x in result}.values())

    @staticmethod
    def _amendments(record: Mapping[str, Any], *, notice: bool) -> list[dict[str, Any]]:
        result = []
        for item in record.get("addendums", []):
            if isinstance(item, dict) and bool(item.get("isNotice")) == notice:
                result.append({k: item.get(k) for k in (
                    "id", "project_id", "number", "title", "description", "releasedAt", "status", "type"
                ) if item.get(k) is not None})
        return result

    @staticmethod
    def _questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for item in questions:
            comments = []
            for comment in item.get("questionComments", []):
                if not isinstance(comment, dict):
                    continue
                user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
                comments.append({
                    "id": comment.get("id"),
                    "description": comment.get("description"),
                    "created_at": comment.get("created_at"),
                    "is_vendor": bool(comment.get("isVendor")),
                    "responder": _clean(user.get("displayName") or user.get("fullName")) or None,
                })
            result.append({
                "id": item.get("id"), "project_id": item.get("project_id"),
                "number": item.get("number"), "subject": item.get("subject"),
                "status": item.get("status"), "is_answered": bool(item.get("isAnswered")),
                "released_at": item.get("releasedAt"), "comments": comments,
            })
        return result

    @staticmethod
    def _safe_object(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
        return {k: value.get(k) for k in keys if value.get(k) is not None} if isinstance(value, dict) else {}

    def _matches_local_dates(self, record: Mapping[str, Any], q: OpenGovQuery) -> bool:
        released = self._datetime(record.get("releaseProjectDate") or record.get("postedAt"))
        due = self._datetime(record.get("proposalDeadline"))
        return self._in_range(released, q.released_from, q.released_to) and self._in_range(due, q.due_from, q.due_to)

    @staticmethod
    def _status(value: Any, substatus: Any = None) -> OpportunityStatus:
        text = f"{_clean(value)} {_clean(substatus)}".casefold()
        if "cancel" in text:
            return OpportunityStatus.CANCELLED
        if "award" in text:
            return OpportunityStatus.AWARDED
        if "closed" in text:
            return OpportunityStatus.CLOSED
        if any(x in text for x in ("open", "active", "posted")):
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
    def _in_range(value: datetime | None, start: date | None, end: date | None) -> bool:
        return not ((start and (not value or value.date() < start)) or (end and (not value or value.date() > end)))

    @staticmethod
    def _filename(item: Mapping[str, Any]) -> str:
        value = _clean(item.get("filename") or item.get("name") or item.get("title")).replace("\\", "/")
        return PurePosixPath(value).name[:240]

    @staticmethod
    def _mime_type(extension: Any) -> str | None:
        return {
            "pdf": "application/pdf", "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "csv": "text/csv", "zip": "application/zip",
        }.get(_clean(extension).casefold().lstrip("."))

    @staticmethod
    def _document_category(title: str) -> str:
        for pattern, category in (
            (r"addend", "addendum"), (r"amend", "amendment"),
            (r"q\s*&\s*a|questions", "questions_and_answers"),
            (r"award|intent", "award_notice"), (r"tabulation", "bid_tabulation"),
            (r"\b(?:rfp|rfq|ifb|itb|rfi)\b", "solicitation"),
        ):
            if re.search(pattern, title, re.I):
                return category
        return "other"

    @staticmethod
    def _safe_url(value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.casefold().rstrip(".")
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if host.endswith((".local", ".internal", ".localhost")) or host == "localhost":
                return False
        return host in {"procurement.opengov.com", "api.procurement.opengov.com"}

    def _configuration_valid(self) -> bool:
        return bool(
            re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.portal.tenant_slug)
            and self.portal.organization_type in _ORGANIZATION_TYPES
            and self._safe_url(self.portal.portal_url)
            and self._safe_url(self.portal.public_projects_url)
        )

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(0, float(retry_after))
            except ValueError:
                try:
                    return max(0, (email.utils.parsedate_to_datetime(retry_after) - self._now()).total_seconds())
                except (TypeError, ValueError):
                    pass
        return self.portal.retry_backoff_seconds * (2**attempt) + self.portal.retry_jitter_seconds * self._random()

    def _record_success(self) -> None:
        self._failures = 0
        self._last_success = self._now()
        self._last_error_class = None
        self._access = OpenGovAccessState.PUBLIC_METADATA_ONLY

    def _record_failure(self, exc: Exception) -> None:
        self._failures += 1
        self._last_failure = self._now()
        self._last_error_class = type(exc).__name__
        self._access = exc.state if isinstance(exc, OpenGovAccessError) else OpenGovAccessState.TRANSIENT_ERROR

    def _circuit_open(self) -> bool:
        if self._failures < self.portal.circuit_breaker_threshold or not self._last_failure:
            return False
        if (self._now() - self._last_failure).total_seconds() >= self.portal.circuit_breaker_cooldown:
            self._failures = 0
            return False
        return True
