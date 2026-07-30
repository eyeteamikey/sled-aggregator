"""Add safe downloader artifacts and attempt audit.

Revision ID: 20260730_0003
Revises: 20260730_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260730_0003"
down_revision: str = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("solicitation_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("storage_provider", sa.String(50), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("declared_media_type", sa.String(255)),
        sa.Column("detected_media_type", sa.String(255), nullable=False),
        sa.Column("displayed_filename", sa.Text()),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "content_sha256", name="uq_artifact_document_hash"),
    )
    op.create_index(
        "ix_artifacts_document_retrieved", "document_artifacts", ["document_id", "retrieved_at"]
    )
    op.create_index("ix_artifacts_sha256", "document_artifacts", ["content_sha256"])
    op.create_table(
        "document_download_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("solicitation_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "queue_job_id",
            sa.String(36),
            sa.ForeignKey("document_retrieval_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(32)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("original_host", sa.String(255), nullable=False),
        sa.Column("final_host", sa.String(255)),
        sa.Column("redirect_count", sa.Integer(), nullable=False),
        sa.Column("bytes_received", sa.Integer(), nullable=False),
        sa.Column("declared_media_type", sa.String(255)),
        sa.Column("detected_media_type", sa.String(255)),
        sa.Column("error_classification", sa.String(64)),
        sa.Column("error_summary", sa.String(512)),
        sa.Column("retry_scheduled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("document_artifacts.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_attempts_document_started", "document_download_attempts", ["document_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_attempts_document_started", table_name="document_download_attempts")
    op.drop_table("document_download_attempts")
    op.drop_index("ix_artifacts_sha256", table_name="document_artifacts")
    op.drop_index("ix_artifacts_document_retrieved", table_name="document_artifacts")
    op.drop_table("document_artifacts")
