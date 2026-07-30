"""Add solicitation document manifest and durable retrieval queue.

Revision ID: 20260730_0002
Revises: 20260726_0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0002"
down_revision: str = "20260726_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solicitation_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("source_document_id", sa.String(255)), sa.Column("tenant", sa.String(100), nullable=False),
        sa.Column("connector", sa.String(100), nullable=False), sa.Column("jurisdiction", sa.String(100), nullable=False),
        sa.Column("issuing_organization", sa.Text()), sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("document_category", sa.String(255)), sa.Column("title", sa.Text()),
        sa.Column("displayed_filename", sa.Text(), nullable=False), sa.Column("normalized_filename", sa.Text(), nullable=False),
        sa.Column("file_extension", sa.String(16)), sa.Column("declared_media_type", sa.String(255)),
        sa.Column("detected_media_type", sa.String(255)), sa.Column("likely_solicitation_document", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.Text(), nullable=False), sa.Column("classification_confidence", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False), sa.Column("canonical_source_url", sa.Text()),
        sa.Column("authoritative_opportunity_url", sa.Text(), nullable=False), sa.Column("source_detail_url", sa.Text()),
        sa.Column("referring_page_url", sa.Text()), sa.Column("original_link_text", sa.Text()),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False), sa.Column("access_state", sa.String(32), nullable=False),
        sa.Column("requires_login", sa.Boolean(), nullable=False), sa.Column("captcha_observed", sa.Boolean(), nullable=False),
        sa.Column("publicly_retrievable", sa.Boolean(), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_posted_at", sa.DateTime(timezone=True)), sa.Column("source_modified_at", sa.DateTime(timezone=True)),
        sa.Column("logical_document_key", sa.String(255), nullable=False), sa.Column("version_label", sa.String(100)),
        sa.Column("version_number", sa.Integer()), sa.Column("revision_date", sa.DateTime(timezone=True)),
        sa.Column("supersedes_document_id", sa.String(36), sa.ForeignKey("solicitation_documents.id")),
        sa.Column("superseded_by_document_id", sa.String(36), sa.ForeignKey("solicitation_documents.id")),
        sa.Column("parent_document_id", sa.String(36), sa.ForeignKey("solicitation_documents.id")),
        sa.Column("relationship_type", sa.String(40), nullable=False), sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("is_operationally_required", sa.Boolean(), nullable=False), sa.Column("addendum_number", sa.String(50)),
        sa.Column("amendment_number", sa.String(50)), sa.Column("content_sha256", sa.String(64)),
        sa.Column("content_length", sa.Integer()), sa.Column("storage_key", sa.Text()), sa.Column("storage_provider", sa.String(50)),
        sa.Column("original_filename", sa.Text()), sa.Column("final_url", sa.Text()), sa.Column("downloaded_media_type", sa.String(255)),
        sa.Column("extracted_text_available", sa.Boolean(), nullable=False), sa.Column("extraction_state", sa.String(32)),
        sa.Column("ocr_state", sa.String(32)), sa.Column("structured_extraction_state", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("opportunity_id", "identity_key", name="uq_document_identity"),
    )
    for name, columns in (("ix_documents_opportunity_current", ["opportunity_id", "is_current"]), ("ix_documents_connector_tenant", ["connector", "tenant"]), ("ix_documents_source_id", ["connector", "tenant", "source_document_id"]), ("ix_documents_logical_version", ["opportunity_id", "logical_document_key", "version_number"]), ("ix_documents_content_hash", ["content_sha256"])):
        op.create_index(name, "solicitation_documents", columns)
    op.create_table(
        "document_retrieval_jobs", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("solicitation_documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("retrieval_state", sa.String(32), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True)), sa.Column("last_status_code", sa.Integer()),
        sa.Column("last_error_class", sa.String(255)), sa.Column("last_error_message", sa.Text()),
        sa.Column("lease_owner", sa.String(255)), sa.Column("lease_token", sa.String(36)), sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="ck_job_priority"),
        sa.CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_job_attempts"),
        sa.CheckConstraint("(lease_owner IS NULL) = (lease_expires_at IS NULL)", name="ck_job_lease"),
    )
    op.create_index("ix_jobs_claim", "document_retrieval_jobs", ["retrieval_state", "priority", "next_attempt_at"])
    op.create_index("ix_jobs_lease_expiration", "document_retrieval_jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_expiration", table_name="document_retrieval_jobs")
    op.drop_index("ix_jobs_claim", table_name="document_retrieval_jobs")
    op.drop_table("document_retrieval_jobs")
    for name in ("ix_documents_content_hash", "ix_documents_logical_version", "ix_documents_source_id", "ix_documents_connector_tenant", "ix_documents_opportunity_current"):
        op.drop_index(name, table_name="solicitation_documents")
    op.drop_table("solicitation_documents")
