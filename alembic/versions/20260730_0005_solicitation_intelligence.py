"""Add structured solicitation intelligence and reconciliation.

Revision ID: 20260730_0005
Revises: 20260730_0004
"""

from collections.abc import Sequence

from alembic import op
from sled_aggregator.db.models import (
    SolicitationChangeRecord,
    SolicitationCodeRecord,
    SolicitationConflictRecord,
    SolicitationContactRecord,
    SolicitationDeliverableRecord,
    SolicitationEvaluationFactorRecord,
    SolicitationEvidenceRecord,
    SolicitationExtractionRunRecord,
    SolicitationFactRecord,
    SolicitationRequirementRecord,
    SolicitationSectionRecord,
    SolicitationSnapshotRecord,
)

revision: str = "20260730_0005"
down_revision: str = "20260730_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    SolicitationExtractionRunRecord.__table__,
    SolicitationSectionRecord.__table__,
    SolicitationFactRecord.__table__,
    SolicitationEvidenceRecord.__table__,
    SolicitationConflictRecord.__table__,
    SolicitationRequirementRecord.__table__,
    SolicitationDeliverableRecord.__table__,
    SolicitationEvaluationFactorRecord.__table__,
    SolicitationContactRecord.__table__,
    SolicitationCodeRecord.__table__,
    SolicitationChangeRecord.__table__,
    SolicitationSnapshotRecord.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=False)
