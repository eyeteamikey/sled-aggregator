"""Add normalized document extraction persistence.

Revision ID: 20260730_0004
Revises: 20260730_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0004"
down_revision: str = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("solicitation_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("document_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            sa.String(36),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parser_name", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("detected_format", sa.String(32), nullable=False),
        sa.Column("extraction_state", sa.String(32), nullable=False),
        sa.Column("ocr_state", sa.String(32), nullable=False),
        sa.Column("ocr_engine", sa.String(100)),
        sa.Column("ocr_engine_version", sa.String(100)),
        sa.Column("language", sa.String(32)),
        sa.Column("native_text_character_count", sa.Integer(), nullable=False),
        sa.Column("ocr_text_character_count", sa.Integer(), nullable=False),
        sa.Column("total_character_count", sa.Integer(), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False),
        sa.Column("table_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("error_classification", sa.String(64)),
        sa.Column("error_summary", sa.String(512)),
        sa.Column("extraction_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "artifact_id",
            "content_sha256",
            "parser_name",
            "parser_version",
            name="uq_extraction_identity",
        ),
    )
    for name, columns in (
        ("ix_extractions_document_current", ["document_id", "is_current"]),
        ("ix_extractions_opportunity", ["opportunity_id"]),
        ("ix_extractions_state", ["extraction_state"]),
        ("ix_extractions_ocr_state", ["ocr_state"]),
    ):
        op.create_index(name, "document_extractions", columns)
    op.create_table(
        "document_text_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "extraction_id",
            sa.String(36),
            sa.ForeignKey("document_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("sheet_name", sa.String(255)),
        sa.Column("archive_entry", sa.Text()),
        sa.Column("paragraph_index", sa.Integer()),
        sa.Column("table_index", sa.Integer()),
        sa.Column("row_start", sa.Integer()),
        sa.Column("row_end", sa.Integer()),
        sa.Column("column_start", sa.Integer()),
        sa.Column("column_end", sa.Integer()),
        sa.Column("block_type", sa.String(32), nullable=False),
        sa.Column("heading_level", sa.Integer()),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("character_start", sa.Integer(), nullable=False),
        sa.Column("character_end", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("ocr_confidence", sa.Integer()),
        sa.Column("source_location", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("extraction_id", "sequence", name="uq_block_sequence"),
    )
    op.create_index(
        "ix_blocks_page_sheet",
        "document_text_blocks",
        ["extraction_id", "page_number", "sheet_name"],
    )
    op.create_table(
        "document_tables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "extraction_id",
            sa.String(36),
            sa.ForeignKey("document_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("sheet_name", sa.String(255)),
        sa.Column("archive_entry", sa.Text()),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("structured_data", postgresql.JSONB(), nullable=False),
        sa.Column("flattened_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("extraction_id", "sequence", name="uq_table_sequence"),
    )


def downgrade() -> None:
    op.drop_table("document_tables")
    op.drop_index("ix_blocks_page_sheet", table_name="document_text_blocks")
    op.drop_table("document_text_blocks")
    for name in (
        "ix_extractions_ocr_state",
        "ix_extractions_state",
        "ix_extractions_opportunity",
        "ix_extractions_document_current",
    ):
        op.drop_index(name, table_name="document_extractions")
    op.drop_table("document_extractions")
