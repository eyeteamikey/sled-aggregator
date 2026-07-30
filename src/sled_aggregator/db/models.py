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
        Index("ix_documents_logical_version", "opportunity_id", "logical_document_key", "version_number"),
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
    supersedes_document_id: Mapped[str | None] = mapped_column(ForeignKey("solicitation_documents.id"))
    superseded_by_document_id: Mapped[str | None] = mapped_column(ForeignKey("solicitation_documents.id"))
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
    document_id: Mapped[str] = mapped_column(ForeignKey("solicitation_documents.id", ondelete="CASCADE"), unique=True)
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
    document_id: Mapped[str] = mapped_column(ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False)
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
    document_id: Mapped[str] = mapped_column(ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False)
    queue_job_id: Mapped[str] = mapped_column(ForeignKey("document_retrieval_jobs.id", ondelete="CASCADE"), nullable=False)
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
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("document_artifacts.id", ondelete="SET NULL"))
