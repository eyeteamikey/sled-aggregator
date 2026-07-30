from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sled_aggregator.db.models import (
    OpportunityRecord,
    SolicitationChangeRecord,
    SolicitationCodeRecord,
    SolicitationConflictRecord,
    SolicitationContactRecord,
    SolicitationDeliverableRecord,
    SolicitationDocumentRecord,
    SolicitationEvaluationFactorRecord,
    SolicitationEvidenceRecord,
    SolicitationFactRecord,
    SolicitationRequirementRecord,
    SolicitationSnapshotRecord,
)


class StructuredExportService:
    export_schema_version = "1.0"

    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self, opportunity_id: str, *, generated_at: datetime | None = None) -> dict[str, Any]:
        opportunity = self.session.get(OpportunityRecord, opportunity_id)
        if opportunity is None:
            raise LookupError(opportunity_id)
        facts = list(
            self.session.scalars(
                select(SolicitationFactRecord)
                .where(SolicitationFactRecord.opportunity_id == opportunity_id)
                .order_by(SolicitationFactRecord.canonical_field, SolicitationFactRecord.id)
            )
        )
        evidence = {
            f.id: list(
                self.session.scalars(
                    select(SolicitationEvidenceRecord)
                    .where(SolicitationEvidenceRecord.fact_id == f.id)
                    .order_by(SolicitationEvidenceRecord.id)
                )
            )
            for f in facts
        }

        def rows(model, *order):
            return list(
                self.session.scalars(
                    select(model).where(model.opportunity_id == opportunity_id).order_by(*order)
                )
            )

        serialized_facts = [
            {
                "id": f.id,
                "canonical_field": f.canonical_field,
                "category": f.category,
                "value": f.normalized_value,
                "original_value": f.original_value,
                "source_status": f.source_status,
                "confidence": f.confidence,
                "effective_status": f.effective_status,
                "conflict_group": f.conflict_group,
                "evidence": [
                    {
                        "id": e.id,
                        "document_id": e.document_id,
                        "text_extraction_id": e.text_extraction_id,
                        "text_block_id": e.text_block_id,
                        "source_location": e.source_location,
                        "quote": e.bounded_quote,
                        "evidence_hash": e.evidence_hash,
                        "ocr_confidence": e.ocr_confidence,
                    }
                    for e in evidence[f.id]
                ],
            }
            for f in facts
        ]
        return {
            "export_schema_version": self.export_schema_version,
            "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
            "opportunity_identity": {
                "id": opportunity.id,
                "solicitation_number": opportunity.solicitation_number,
                "title": opportunity.title,
                "jurisdiction": opportunity.jurisdiction,
                "authoritative_url": opportunity.detail_url,
            },
            "effective_snapshot": self._latest_snapshot(opportunity_id),
            "structured_facts": serialized_facts,
            "deadlines": [f for f in serialized_facts if f["category"] == "dates"],
            "contacts": [
                self._public(c)
                for c in rows(
                    SolicitationContactRecord,
                    SolicitationContactRecord.role,
                    SolicitationContactRecord.id,
                )
            ],
            "requirements": [
                self._public(x)
                for x in rows(
                    SolicitationRequirementRecord,
                    SolicitationRequirementRecord.category,
                    SolicitationRequirementRecord.id,
                )
            ],
            "deliverables": [
                self._public(x)
                for x in rows(SolicitationDeliverableRecord, SolicitationDeliverableRecord.id)
            ],
            "evaluation_criteria": [
                self._public(x)
                for x in rows(
                    SolicitationEvaluationFactorRecord, SolicitationEvaluationFactorRecord.sequence
                )
            ],
            "codes": [
                self._public(x)
                for x in rows(
                    SolicitationCodeRecord,
                    SolicitationCodeRecord.code_system,
                    SolicitationCodeRecord.code,
                )
            ],
            "documents": [
                {
                    "id": d.id,
                    "title": d.title,
                    "document_type": d.document_type,
                    "source_url": d.source_url,
                    "version_label": d.version_label,
                    "is_current": d.is_current,
                }
                for d in rows(
                    SolicitationDocumentRecord,
                    SolicitationDocumentRecord.first_discovered_at,
                    SolicitationDocumentRecord.id,
                )
            ],
            "unresolved_conflicts": [
                self._public(x)
                for x in rows(SolicitationConflictRecord, SolicitationConflictRecord.created_at)
            ],
            "change_ledger": [
                self._public(x)
                for x in rows(
                    SolicitationChangeRecord,
                    SolicitationChangeRecord.created_at,
                    SolicitationChangeRecord.id,
                )
            ],
        }

    def _latest_snapshot(self, opportunity_id: str) -> dict[str, Any] | None:
        item = self.session.scalar(
            select(SolicitationSnapshotRecord).where(
                SolicitationSnapshotRecord.opportunity_id == opportunity_id,
                SolicitationSnapshotRecord.is_current.is_(True),
            )
        )
        return None if item is None else item.snapshot_data

    @staticmethod
    def _public(record: Any) -> dict[str, Any]:
        excluded = {"configuration_fingerprint", "storage_key", "lease_token", "lease_owner"}
        return {
            c.name: getattr(record, c.name)
            for c in record.__table__.columns
            if c.name not in excluded
        }
