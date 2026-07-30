from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sled_aggregator.db.base import Base


class OpportunityRecord(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint(
            "source_portal",
            "source_record_id",
            name="uq_opportunities_source_portal_record",
        ),
        Index("ix_opportunities_status_due_at", "status", "due_at"),
        Index("ix_opportunities_jurisdiction", "jurisdiction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    canonical_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_portal: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    detail_url: Mapped[str] = mapped_column(Text, nullable=False)
    solicitation_number: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    agency: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationDocumentRecord(Base):
    __tablename__ = "solicitation_documents"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "identity_key", name="uq_document_identity"),
        Index("ix_documents_opportunity_current", "opportunity_id", "is_current"),
        Index("ix_documents_connector_tenant", "connector", "tenant"),
        Index("ix_documents_source_id", "connector", "tenant", "source_document_id"),
        Index(
            "ix_documents_logical_version",
            "opportunity_id",
            "logical_document_key",
            "version_number",
        ),
        Index("ix_documents_content_hash", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"))
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(String(255))
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    connector: Mapped[str] = mapped_column(String(100), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    issuing_organization: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    document_category: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    displayed_filename: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_extension: Mapped[str | None] = mapped_column(String(16))
    declared_media_type: Mapped[str | None] = mapped_column(String(255))
    detected_media_type: Mapped[str | None] = mapped_column(String(255))
    likely_solicitation_document: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(Text, nullable=False)
    classification_confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_source_url: Mapped[str | None] = mapped_column(Text)
    authoritative_opportunity_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_detail_url: Mapped[str | None] = mapped_column(Text)
    referring_page_url: Mapped[str | None] = mapped_column(Text)
    original_link_text: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    access_state: Mapped[str] = mapped_column(String(32), nullable=False)
    requires_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    captcha_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publicly_retrievable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    logical_document_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(100))
    version_number: Mapped[int | None] = mapped_column(Integer)
    revision_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_documents.id")
    )
    superseded_by_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_documents.id")
    )
    parent_document_id: Mapped[str | None] = mapped_column(ForeignKey("solicitation_documents.id"))
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False, default="related")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_operationally_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    addendum_number: Mapped[str | None] = mapped_column(String(50))
    amendment_number: Mapped[str | None] = mapped_column(String(50))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    content_length: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str | None] = mapped_column(Text)
    storage_provider: Mapped[str | None] = mapped_column(String(50))
    original_filename: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    downloaded_media_type: Mapped[str | None] = mapped_column(String(255))
    extracted_text_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extraction_state: Mapped[str | None] = mapped_column(String(32))
    ocr_state: Mapped[str | None] = mapped_column(String(32))
    structured_extraction_state: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentRetrievalJobRecord(Base):
    __tablename__ = "document_retrieval_jobs"
    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_job_priority"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_job_attempts"),
        CheckConstraint("(lease_owner IS NULL) = (lease_expires_at IS NULL)", name="ck_job_lease"),
        Index("ix_jobs_claim", "retrieval_state", "priority", "next_attempt_at"),
        Index("ix_jobs_lease_expiration", "lease_expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), unique=True
    )
    retrieval_state: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error_class: Mapped[str | None] = mapped_column(String(255))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentArtifactRecord(Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint("document_id", "content_sha256", name="uq_artifact_document_hash"),
        Index("ix_artifacts_document_retrieved", "document_id", "retrieved_at"),
        Index("ix_artifacts_sha256", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    declared_media_type: Mapped[str | None] = mapped_column(String(255))
    detected_media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    displayed_filename: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentDownloadAttemptRecord(Base):
    __tablename__ = "document_download_attempts"
    __table_args__ = (Index("ix_attempts_document_started", "document_id", "started_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False
    )
    queue_job_id: Mapped[str] = mapped_column(
        ForeignKey("document_retrieval_jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer)
    original_host: Mapped[str] = mapped_column(String(255), nullable=False)
    final_host: Mapped[str | None] = mapped_column(String(255))
    redirect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    declared_media_type: Mapped[str | None] = mapped_column(String(255))
    detected_media_type: Mapped[str | None] = mapped_column(String(255))
    error_classification: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(String(512))
    retry_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="SET NULL")
    )


class DocumentExtractionRecord(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "content_sha256",
            "parser_name",
            "parser_version",
            name="uq_extraction_identity",
        ),
        Index("ix_extractions_document_current", "document_id", "is_current"),
        Index("ix_extractions_opportunity", "opportunity_id"),
        Index("ix_extractions_state", "extraction_state"),
        Index("ix_extractions_ocr_state", "ocr_state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_format: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_state: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_state: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(100))
    ocr_engine_version: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(32))
    native_text_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_text_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_classification: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(String(512))
    extraction_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentTextBlockRecord(Base):
    __tablename__ = "document_text_blocks"
    __table_args__ = (
        UniqueConstraint("extraction_id", "sequence", name="uq_block_sequence"),
        Index("ix_blocks_page_sheet", "extraction_id", "page_number", "sheet_name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_id: Mapped[str] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    archive_entry: Mapped[str | None] = mapped_column(Text)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    table_index: Mapped[int | None] = mapped_column(Integer)
    row_start: Mapped[int | None] = mapped_column(Integer)
    row_end: Mapped[int | None] = mapped_column(Integer)
    column_start: Mapped[int | None] = mapped_column(Integer)
    column_end: Mapped[int | None] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    character_start: Mapped[int] = mapped_column(Integer, nullable=False)
    character_end: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_confidence: Mapped[int | None] = mapped_column(Integer)
    source_location: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentTableRecord(Base):
    __tablename__ = "document_tables"
    __table_args__ = (UniqueConstraint("extraction_id", "sequence", name="uq_table_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_id: Mapped[str] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    archive_entry: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_data: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    flattened_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationExtractionRunRecord(Base):
    __tablename__ = "solicitation_extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "text_extraction_id",
            "extractor_name",
            "extractor_version",
            "schema_version",
            "configuration_fingerprint",
            name="uq_intelligence_run_identity",
        ),
        Index("ix_intelligence_runs_state", "state"),
        Index("ix_intelligence_runs_opportunity", "opportunity_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    text_extraction_id: Mapped[str] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    extractor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completeness: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationSectionRecord(Base):
    __tablename__ = "solicitation_sections"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "sequence", name="uq_intelligence_section_sequence"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    parent_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_sections.id", ondelete="SET NULL")
    )
    normalized_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_title: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    starting_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_text_blocks.id", ondelete="SET NULL")
    )
    ending_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_text_blocks.id", ondelete="SET NULL")
    )
    starting_page: Mapped[int | None] = mapped_column(Integer)
    ending_page: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)


class SolicitationFactRecord(Base):
    __tablename__ = "solicitation_facts"
    __table_args__ = (
        Index("ix_facts_opportunity_field", "opportunity_id", "canonical_field"),
        Index("ix_facts_effective", "opportunity_id", "effective_status"),
        Index("ix_facts_conflict", "conflict_group"),
        Index("ix_facts_date", "date_value"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    canonical_field: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    original_value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(3))
    date_value: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(String(64))
    source_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_status: Mapped[str] = mapped_column(String(32), nullable=False)
    conflict_group: Mapped[str | None] = mapped_column(String(64))
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_facts.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationEvidenceRecord(Base):
    __tablename__ = "solicitation_evidence"
    __table_args__ = (
        UniqueConstraint("fact_id", "evidence_hash", name="uq_fact_evidence_hash"),
        Index("ix_evidence_source", "document_id", "text_extraction_id", "text_block_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    fact_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_facts.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    text_extraction_id: Mapped[str] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False
    )
    text_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_text_blocks.id", ondelete="SET NULL")
    )
    table_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_tables.id", ondelete="SET NULL")
    )
    source_location: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    bounded_quote: Mapped[str] = mapped_column(Text, nullable=False)
    bounded_context: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_confidence: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationConflictRecord(Base):
    __tablename__ = "solicitation_conflicts"
    __table_args__ = (
        Index("ix_conflicts_opportunity_status", "opportunity_id", "resolution_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    conflict_group: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    canonical_field: Mapped[str] = mapped_column(String(100), nullable=False)
    competing_fact_ids: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    controlling_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_facts.id", ondelete="SET NULL")
    )
    resolution_explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationRequirementRecord(Base):
    __tablename__ = "solicitation_requirements"
    __table_args__ = (Index("ix_requirements_opportunity_category", "opportunity_id", "category"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    responsible_party: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str | None] = mapped_column(Text)
    due_phase: Mapped[str | None] = mapped_column(String(64))
    effective_status: Mapped[str] = mapped_column(String(32), nullable=False)
    conflict_group: Mapped[str | None] = mapped_column(String(64))


class SolicitationDeliverableRecord(Base):
    __tablename__ = "solicitation_deliverables"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(String(100))
    due_information: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(String(255))
    recipient: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text)


class SolicitationEvaluationFactorRecord(Base):
    __tablename__ = "solicitation_evaluation_factors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_factor_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_evaluation_factors.id", ondelete="SET NULL")
    )
    weight: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    qualitative_importance: Mapped[str | None] = mapped_column(Text)
    pass_fail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class SolicitationContactRecord(Base):
    __tablename__ = "solicitation_contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(100))


class SolicitationCodeRecord(Base):
    __tablename__ = "solicitation_codes"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "code_system", "code", name="uq_intelligence_code"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("solicitation_extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    code_system: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class SolicitationChangeRecord(Base):
    __tablename__ = "solicitation_changes"
    __table_args__ = (
        Index("ix_changes_opportunity_created", "opportunity_id", "created_at"),
        Index("ix_changes_field", "canonical_field"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    canonical_field: Mapped[str] = mapped_column(String(100), nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prior_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_facts.id", ondelete="SET NULL")
    )
    new_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_facts.id", ondelete="SET NULL")
    )
    prior_value: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    controlling_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolicitationSnapshotRecord(Base):
    __tablename__ = "solicitation_snapshots"
    __table_args__ = (
        Index("ix_snapshots_current", "opportunity_id", "is_current"),
        UniqueConstraint("opportunity_id", "content_fingerprint", name="uq_snapshot_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_extraction_ids: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    snapshot_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    latest_controlling_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("solicitation_documents.id", ondelete="SET NULL")
    )
    cancellation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    award_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
