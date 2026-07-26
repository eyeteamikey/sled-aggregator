"""Create opportunities table.

Revision ID: 20260726_0001
Revises:
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("canonical_key", sa.String(length=64), nullable=False),
        sa.Column("source_portal", sa.String(length=100), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("jurisdiction", sa.String(length=100), nullable=False),
        sa.Column("detail_url", sa.Text(), nullable=False),
        sa.Column("solicitation_number", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("agency", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("categories", postgresql.JSONB(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key"),
        sa.UniqueConstraint(
            "source_portal",
            "source_record_id",
            name="uq_opportunities_source_portal_record",
        ),
    )
    op.create_index(
        "ix_opportunities_jurisdiction",
        "opportunities",
        ["jurisdiction"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_status_due_at",
        "opportunities",
        ["status", "due_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_opportunities_status_due_at", table_name="opportunities")
    op.drop_index("ix_opportunities_jurisdiction", table_name="opportunities")
    op.drop_table("opportunities")

