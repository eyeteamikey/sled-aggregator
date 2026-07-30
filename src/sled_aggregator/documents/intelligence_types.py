from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

SCHEMA_VERSION = "1.0"


class SourceStatus(StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    INFERRED = "inferred"
    CONFLICTING = "conflicting"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class RequirementStrength(StrEnum):
    MANDATORY = "mandatory"
    PROHIBITED = "prohibited"
    CONDITIONAL = "conditional"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    INFORMATIONAL = "informational"
    UNCLEAR = "unclear"


class DocumentAuthority(StrEnum):
    PRIMARY = "primary_solicitation"
    REVISED = "revised_primary"
    ADDENDUM = "formal_addendum"
    AMENDMENT = "formal_amendment"
    QA = "official_questions_and_answers"
    ATTACHMENT = "supplemental_attachment"
    PRICING = "pricing_attachment"
    BID_FORM = "bid_form"
    NOTICE = "informational_notice"
    CANCELLATION = "cancellation_notice"
    INTENT = "intent_to_award"
    AWARD = "award_notice"
    UNKNOWN = "unofficial_or_unknown"


@dataclass(slots=True)
class Evidence:
    document_id: str
    artifact_id: str
    text_extraction_id: str
    text_block_id: str | None
    quote: str
    context: str
    evidence_hash: str
    page_number: int | None = None
    sheet_name: str | None = None
    archive_entry: str | None = None
    table_id: str | None = None
    table_index: int | None = None
    row_start: int | None = None
    column_start: int | None = None
    character_start: int | None = None
    character_end: int | None = None
    extraction_method: str = "native"
    ocr_confidence: int | None = None


@dataclass(slots=True)
class StructuredFact:
    canonical_field: str
    normalized_value: Any
    original_value: str
    value_type: str = "string"
    source_status: SourceStatus = SourceStatus.EXPLICIT
    confidence: str = "high"
    confidence_score: int = 90
    evidence: list[Evidence] = field(default_factory=list)
    effective_status: str = "candidate"
    category: str = "other"
    notes: str | None = None


@dataclass(slots=True)
class StructuredExtractionResult:
    opportunity_id: str
    document_id: str
    artifact_id: str
    text_extraction_id: str
    authority: DocumentAuthority
    extractor_name: str = "deterministic_solicitation"
    extractor_version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION
    configuration_fingerprint: str = ""
    facts: list[StructuredFact] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    requirements: list[dict[str, Any]] = field(default_factory=list)
    deliverables: list[dict[str, Any]] = field(default_factory=list)
    evaluation_factors: list[dict[str, Any]] = field(default_factory=list)
    contacts: list[dict[str, Any]] = field(default_factory=list)
    codes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    completeness: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    created_at: datetime | None = None
    completed_at: datetime | None = None


class StructuredExtractor(Protocol):
    extractor_name: str
    extractor_version: str
    schema_version: str
    supported_document_types: frozenset[str]

    def extract(self, **kwargs: Any) -> StructuredExtractionResult: ...
