"""Anonymous GET-only Oracle Fusion Procurement REST connector."""

import asyncio
import email.utils
import hashlib
import ipaddress
import random
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import quote, urljoin, urlparse

import httpx

from sled_aggregator.connectors.base import BaseConnector, ConnectorQuery
from sled_aggregator.domain.enums import AccessState, OpportunityStatus
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef

FIELDS = (
    "AttachmentsCount,AuctionHeaderId,BuyerName,CloseDate,Negotiation,"
    "NegotiationStatus,NegotiationStatusCode,NegotiationTitle,NegotiationType,"
    "OpenDate,PostingDate,PreviewDate,ProcurementBUId,ProcurementBUName,"
    "PublishDate,Synopsis,TimeRemaining,TimeRemainingOrder"
)
SORT_FIELDS = frozenset({"CloseDate", "Negotiation", "OpenDate", "PostingDate", "PublishDate"})
STATUSES = frozenset({"ACTIVE", "AMENDED", "AWARDED", "CANCELLED", "CLOSED", "PREVIEW", "UPCOMING"})
TRANSIENT = frozenset({429, 502, 503, 504})
SIGNED_KEYS = re.compile(r"(?i)(XFND_(?:SIGNATURE|RANDOM|CERT_FP|SCHEME_ID)|token|signature)")


class GetTransport(Protocol):
    async def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class OracleFusionError(RuntimeError):
    """The configured public REST contract cannot safely be consumed."""


class OracleFusionAccessError(OracleFusionError):
    pass


def _safe_https(url: str, hosts: frozenset[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or host not in hosts:
        raise ValueError("URL must be credential-free HTTPS on an approved host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("private or special-purpose hosts are forbidden")


@dataclass(frozen=True, slots=True)
class OracleFusionProfile:
    key: str
    organization: str
    jurisdiction: str
    public_portal_url: str
    api_host: str
    rest_resource_root: str
    procurement_bu_id: str
    approved_api_hosts: frozenset[str]
    approved_document_hosts: frozenset[str]
    page_size: int = 25
    maximum_pages: int = 20
    maximum_results: int = 500
    retry_count: int = 3
    backoff_seconds: float = 0.25
    jitter_seconds: float = 0.1
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 60.0

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", self.key):
            raise ValueError("invalid profile key")
        if not self.organization.strip() or not re.fullmatch(r"[A-Z]{2}", self.jurisdiction):
            raise ValueError("organization and two-letter jurisdiction are required")
        if not self.procurement_bu_id.isdigit() or not self.api_host:
            raise ValueError("numeric procurement BU ID and API host are required")
        api_hosts = frozenset(h.lower() for h in self.approved_api_hosts)
        doc_hosts = frozenset(h.lower() for h in self.approved_document_hosts)
        if self.api_host.lower() not in api_hosts:
            raise ValueError("API host must be approved")
        object.__setattr__(self, "approved_api_hosts", api_hosts)
        object.__setattr__(self, "approved_document_hosts", doc_hosts)
        _safe_https(self.public_portal_url, api_hosts | doc_hosts)
        _safe_https(self.rest_resource_root, api_hosts)
        root = urlparse(self.rest_resource_root)
        if root.hostname != self.api_host.lower() or not root.path.endswith(
            "/supplierNegotiationAbstracts"
        ):
            raise ValueError("REST root must target the configured host and collection")
        if not (1 <= self.page_size <= 100 and 1 <= self.maximum_pages <= 100):
            raise ValueError("page bounds are invalid")
        if not (1 <= self.maximum_results <= 10_000 and 0 <= self.retry_count <= 8):
            raise ValueError("result or retry bounds are invalid")
        if min(self.backoff_seconds, self.jitter_seconds, self.circuit_breaker_cooldown) < 0:
            raise ValueError("timing values cannot be negative")
        if self.circuit_breaker_threshold < 1:
            raise ValueError("circuit threshold must be positive")

    @property
    def release_identifier(self) -> str:
        path = urlparse(self.rest_resource_root).path
        return path.rsplit("/supplierNegotiationAbstracts", 1)[0].rsplit("/rest/", 1)[-1]


DETROIT = OracleFusionProfile(
    key="mi-detroit-oracle-fusion",
    organization="City of Detroit",
    jurisdiction="MI",
    public_portal_url="https://ebkk.fa.us8.oraclecloud.com/fscmUI/faces/NegotiationAbstracts?prcBuId=300000007775375",
    api_host="ebkk.fa.us8.oraclecloud.com",
    rest_resource_root="https://ebkk.fa.us8.oraclecloud.com/fscmRestApi/rest/rv:ddf69fe5-0d44-4b34-b551-ddb6e54beb31/en/11.13.18.05:9/supplierNegotiationAbstracts",
    procurement_bu_id="300000007775375",
    approved_api_hosts=frozenset({"ebkk.fa.us8.oraclecloud.com"}),
    approved_document_hosts=frozenset({"ebkk.fa.us8.oraclecloud.com"}),
)
PROFILES = (DETROIT,)


@dataclass(frozen=True, slots=True)
class OracleFusionQuery(ConnectorQuery):
    negotiation_number: str | None = None
    status: str | None = None
    posted_from: date | None = None
    posted_to: date | None = None
    open_from: date | None = None
    open_to: date | None = None
    sort_field: str = "PostingDate"
    sort_direction: str = "desc"


@dataclass(frozen=True, slots=True)
class OracleFusionHealth:
    available: bool
    configuration_valid: bool
    circuit_open: bool
    consecutive_failures: int
    last_status_code: int | None
    last_failure_at: datetime | None
    last_success_at: datetime | None
    access_classification: str
    release_path_incompatible: bool


class OracleFusionRestConnector(BaseConnector):
    platform_family = "oracle/fusion-rest"
    jurisdictions = ("Michigan",)
    public_read_only = True

    def __init__(
        self, profile: OracleFusionProfile = DETROIT, transport: GetTransport | None = None
    ) -> None:
        self.profile = profile
        self._client = transport or httpx.AsyncClient(
            follow_redirects=False, headers={"Accept": "application/json"}
        )
        self._owns_client = transport is None
        self._failures = 0
        self._opened_at: datetime | None = None
        self._last_status: int | None = None
        self._last_failure: datetime | None = None
        self._last_success: datetime | None = None
        self._classification = "public-anonymous-get"
        self._incompatible = False

    async def __aenter__(self) -> "OracleFusionRestConnector":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def health_snapshot(self) -> OracleFusionHealth:
        now = datetime.now(UTC)
        circuit = bool(
            self._opened_at
            and (now - self._opened_at).total_seconds() < self.profile.circuit_breaker_cooldown
        )
        return OracleFusionHealth(
            not circuit and not self._incompatible,
            True,
            circuit,
            self._failures,
            self._last_status,
            self._last_failure,
            self._last_success,
            self._classification,
            self._incompatible,
        )

    @staticmethod
    def _literal(value: str, *, maximum: int = 200) -> str:
        if not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid Oracle filter literal")
        return "'" + value.replace("'", "''") + "'"

    def query_params(
        self, query: OracleFusionQuery, *, offset: int = 0, limit: int | None = None
    ) -> dict[str, str | int]:
        size = self.profile.page_size if limit is None else limit
        if offset < 0 or size <= 0 or size > self.profile.page_size or query.limit < 0:
            raise ValueError("invalid pagination bounds")
        if query.jurisdiction and query.jurisdiction.upper() not in {"MI", "MICHIGAN"}:
            raise ValueError("query jurisdiction does not match profile")
        if query.sort_field not in SORT_FIELDS or query.sort_direction not in {"asc", "desc"}:
            raise ValueError("unsupported sort")
        clauses: list[str] = []
        if len(query.keywords) > 5:
            raise ValueError("at most five keywords are supported")
        for keyword in query.keywords:
            literal = self._literal(keyword, maximum=100)
            clauses.append(
                f"(NegotiationTitle LIKE {literal} OR NegotiationType LIKE {literal} OR Negotiation LIKE {literal})"
            )
        if query.negotiation_number:
            clauses.append(f"Negotiation={self._literal(query.negotiation_number, maximum=100)}")
        if query.status:
            status = query.status.upper()
            if status not in STATUSES:
                raise ValueError("unsupported status")
            clauses.append(f"NegotiationStatusCode={self._literal(status)}")
        for field, operator, value in (
            ("PostingDate", ">=", query.posted_from),
            ("PostingDate", "<=", query.posted_to),
            ("OpenDate", ">=", query.open_from),
            ("OpenDate", "<=", query.open_to),
        ):
            if value:
                clauses.append(f"{field}{operator}{self._literal(value.isoformat())}")
        params: dict[str, str | int] = {
            "finder": f"RowFinderByBU;ProcurementBUId={self.profile.procurement_bu_id}",
            "orderBy": f"{query.sort_field}:{query.sort_direction}",
            "fields": FIELDS,
            "limit": size,
            "offset": offset,
        }
        if clauses:
            params["q"] = ";".join(clauses)
        return params

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        value = response.headers.get("Retry-After") if response else None
        if value:
            try:
                return max(0.0, min(float(value), 60.0))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(value)
                return max(0.0, min((parsed - datetime.now(UTC)).total_seconds(), 60.0))
        return self.profile.backoff_seconds * 2**attempt + random.uniform(
            0, self.profile.jitter_seconds
        )

    async def _get_json(self, url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _safe_https(url, self.profile.approved_api_hosts | self.profile.approved_document_hosts)
        health = self.health_snapshot()
        if health.circuit_open:
            raise OracleFusionAccessError("circuit breaker is open")
        response: httpx.Response | None = None
        for attempt in range(self.profile.retry_count + 1):
            try:
                response = await self._client.get(url, params=params)
                self._last_status = response.status_code
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location", "")
                    try:
                        _safe_https(
                            urljoin(url, location),
                            self.profile.approved_api_hosts | self.profile.approved_document_hosts,
                        )
                    except ValueError as exc:
                        return self._fail("unsafe redirect", exc)
                    return self._fail("unexpected redirect")
                if response.status_code in TRANSIENT and attempt < self.profile.retry_count:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue
                if response.status_code in {404, 410}:
                    self._incompatible = True
                    self._classification = "release-path-incompatible"
                    return self._fail("configured Oracle release path is incompatible")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                text = response.text
                lower = text.lower()
                if "json" not in content_type or "<html" in lower:
                    self._classification = "login-or-non-json" if "login" in lower else "non-json"
                    return self._fail("Oracle response was not JSON")
                if "captcha" in lower:
                    self._classification = "captcha"
                    return self._fail("CAPTCHA access boundary")
                try:
                    payload = response.json()
                except ValueError as exc:
                    return self._fail("malformed Oracle JSON", exc)
                if not isinstance(payload, dict):
                    return self._fail("incompatible Oracle JSON shape")
                self._failures = 0
                self._opened_at = None
                self._last_success = datetime.now(UTC)
                self._classification = "public-anonymous-get"
                return payload
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt < self.profile.retry_count and (
                    not response or response.status_code in TRANSIENT
                ):
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue
                return self._fail("Oracle transport unavailable", exc)
        return self._fail("Oracle transport unavailable")

    def _fail(self, message: str, cause: Exception | None = None) -> Any:
        self._failures += 1
        self._last_failure = datetime.now(UTC)
        if self._failures >= self.profile.circuit_breaker_threshold:
            self._opened_at = self._last_failure
        raise OracleFusionAccessError(message) from cause

    @staticmethod
    def _envelope(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        items = payload.get("items")
        if not isinstance(items, list) or not isinstance(payload.get("hasMore"), bool):
            raise OracleFusionAccessError("incompatible Oracle collection envelope")
        if any(not isinstance(item, dict) for item in items):
            raise OracleFusionAccessError("invalid Oracle collection item")
        return items, payload["hasMore"]

    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        oracle_query = (
            query
            if isinstance(query, OracleFusionQuery)
            else OracleFusionQuery(
                keywords=query.keywords, jurisdiction=query.jurisdiction, limit=query.limit
            )
        )
        wanted = min(oracle_query.limit, self.profile.maximum_results)
        if wanted <= 0:
            return
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        seen_offsets: set[int] = set()
        offset = 0
        for _ in range(self.profile.maximum_pages):
            if offset in seen_offsets:
                raise OracleFusionError("repeated pagination offset")
            seen_offsets.add(offset)
            payload = await self._get_json(
                self.profile.rest_resource_root,
                self.query_params(
                    oracle_query,
                    offset=offset,
                    limit=min(self.profile.page_size, wanted - len(seen_ids)),
                ),
            )
            items, has_more = self._envelope(payload)
            fingerprint = hashlib.sha256(repr(items).encode()).hexdigest()
            if fingerprint in seen_pages:
                raise OracleFusionError("repeated Oracle page")
            seen_pages.add(fingerprint)
            useful = 0
            for item in items:
                opportunity = self.normalize(item)
                if opportunity is None:
                    continue
                key = str(item["AuctionHeaderId"])
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                useful += 1
                yield opportunity
                if len(seen_ids) >= wanted:
                    return
            if not has_more or not items or useful == 0:
                return
            offset += self.profile.page_size

    def normalize(self, item: Mapping[str, Any]) -> RawOpportunity | None:
        auction = str(item.get("AuctionHeaderId") or "").strip()
        title = str(item.get("NegotiationTitle") or "").strip()
        if (
            not auction
            or not title
            or str(item.get("ProcurementBUId")) != self.profile.procurement_bu_id
        ):
            return None
        raw = self._sanitize(dict(item))
        raw.update(
            {
                "source_organization": self.profile.organization,
                "connector_variant": self.platform_family,
                "api_release_identifier": self.profile.release_identifier,
                "evidence_access": "public-anonymous-get",
            }
        )
        return RawOpportunity(
            source=SourceRef(
                platform_family=self.platform_family,
                jurisdiction=self.profile.jurisdiction,
                source_id=f"{self.platform_family}:{self.profile.key}:{auction}",
                opportunity_url=self.profile.public_portal_url,
            ),
            title=title,
            agency=str(item.get("ProcurementBUName") or self.profile.organization),
            description=item.get("Synopsis"),
            solicitation_number=item.get("Negotiation"),
            status=self._status(str(item.get("NegotiationStatusCode") or "")),
            posted_at=self._date(item.get("PostingDate") or item.get("PublishDate")),
            due_at=self._date(item.get("CloseDate")),
            categories=[str(item["NegotiationType"])] if item.get("NegotiationType") else [],
            raw_payload=raw,
        )

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _status(value: str) -> OpportunityStatus:
        return {
            "ACTIVE": OpportunityStatus.OPEN,
            "AMENDED": OpportunityStatus.OPEN,
            "PREVIEW": OpportunityStatus.FORECAST,
            "UPCOMING": OpportunityStatus.FORECAST,
            "AWARDED": OpportunityStatus.AWARDED,
            "CANCELLED": OpportunityStatus.CANCELLED,
            "CLOSED": OpportunityStatus.CLOSED,
        }.get(value.upper(), OpportunityStatus.UNKNOWN)

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("[REDACTED]" if SIGNED_KEYS.search(k) else cls._sanitize(v))
                for k, v in value.items()
                if k != "FileUrl"
            }
        if isinstance(value, list):
            return [cls._sanitize(v) for v in value]
        return value

    def child_url(self, auction_id: str, child: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(auction_id)) or child not in {
            "attachments",
            "supplierNegotiationAmendments",
        }:
            raise ValueError("unsafe child route")
        return f"{self.profile.rest_resource_root}/{quote(str(auction_id))},{self.profile.procurement_bu_id}/child/{child}"

    async def attachments(self, opportunity: RawOpportunity) -> list[DocumentCandidate]:
        auction = opportunity.raw_payload["AuctionHeaderId"]
        payload = await self._get_json(
            self.child_url(str(auction), "attachments"),
            {"limit": self.profile.page_size, "offset": 0},
        )
        items, _ = self._envelope(payload)
        result = []
        for item in items:
            key = str(item.get("AttachmentId") or item.get("AttachedDocumentId") or "")
            filename = str(item.get("FileName") or item.get("Title") or "document")
            if not key or re.search(
                r"login|register|submit response|bid submission", filename, re.I
            ):
                continue
            url = f"{self.child_url(str(auction), 'attachments')}/{quote(key, safe='')}/enclosure/FileContents"
            category = self._document_category(
                filename
                + " "
                + str(item.get("Title") or "")
                + " "
                + str(item.get("Description") or "")
            )
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=url,
                    source_opportunity_url=self.profile.public_portal_url,
                    filename=filename,
                    label=item.get("Title"),
                    mime_type=item.get("DatatypeCode"),
                    access_state=AccessState.PUBLIC,
                    source_document_id=key,
                    category=category,
                    publicly_retrievable=True,
                    raw_metadata=self._sanitize(dict(item)),
                )
            )
        return result

    @staticmethod
    def _document_category(text: str) -> str:
        for pattern, category in (
            (r"addend|amend", "addendum"),
            (r"question|q&a", "questions_and_answers"),
            (r"statement of work|\bsow\b|\bpws\b", "sow"),
            (r"pricing|price sheet", "pricing"),
            (r"form|template", "required_form"),
            (r"solicitation|\brfp\b|\brfq\b|\bitb\b", "solicitation"),
        ):
            if re.search(pattern, text, re.I):
                return category
        return "other"

    async def amendments(self, opportunity: RawOpportunity) -> list[dict[str, Any]]:
        auction = str(opportunity.raw_payload["AuctionHeaderId"])
        payload = await self._get_json(
            self.child_url(auction, "supplierNegotiationAmendments"),
            {"limit": self.profile.page_size, "offset": 0},
        )
        items, _ = self._envelope(payload)
        return [
            {
                "parent_auction_header_id": auction,
                "amendment_number": i.get("AmendmentNumber"),
                "document_number": i.get("DocumentNumber"),
                "publication_date": i.get("PublishDate"),
                "description": i.get("AmendmentDescription") or i.get("Synopsis"),
                "source_provenance": {
                    "connector": self.platform_family,
                    "profile": self.profile.key,
                },
                "raw_metadata": self._sanitize(i),
            }
            for i in items
        ]
