import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from sled_aggregator.config import Settings
from sled_aggregator.db.models import (
    DocumentArtifactRecord,
    DocumentExtractionRecord,
    DocumentTableRecord,
    DocumentTextBlockRecord,
    OpportunityRecord,
    SolicitationCodeRecord,
    SolicitationContactRecord,
    SolicitationDeliverableRecord,
    SolicitationDocumentRecord,
    SolicitationEvaluationFactorRecord,
    SolicitationEvidenceRecord,
    SolicitationExtractionRunRecord,
    SolicitationFactRecord,
    SolicitationRequirementRecord,
    SolicitationSectionRecord,
)
from sled_aggregator.documents.intelligence import DeterministicSolicitationExtractor


class SolicitationIntelligenceService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    def extract(
        self, extraction: DocumentExtractionRecord, *, now: datetime | None = None
    ) -> tuple[SolicitationExtractionRunRecord, bool]:
        now = now or datetime.now(UTC)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "quote": self.settings.solicitation_intelligence_max_evidence_quote_chars,
                    "context": self.settings.solicitation_intelligence_context_window_chars,
                    "minimum": self.settings.solicitation_intelligence_min_confidence,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(SolicitationExtractionRunRecord).where(
                SolicitationExtractionRunRecord.text_extraction_id == extraction.id,
                SolicitationExtractionRunRecord.extractor_version == "1.0.0",
                SolicitationExtractionRunRecord.schema_version == "1.0",
                SolicitationExtractionRunRecord.configuration_fingerprint == fingerprint,
                SolicitationExtractionRunRecord.state.in_(("completed", "completed_with_warnings")),
            )
        )
        if existing:
            return existing, True
        document = self.session.get(SolicitationDocumentRecord, extraction.document_id)
        artifact = self.session.get(DocumentArtifactRecord, extraction.artifact_id)
        opportunity = self.session.get(OpportunityRecord, extraction.opportunity_id)
        if not all((document, artifact, opportunity)):
            raise ValueError("source extraction graph is incomplete")
        blocks = list(
            self.session.scalars(
                select(DocumentTextBlockRecord)
                .where(DocumentTextBlockRecord.extraction_id == extraction.id)
                .order_by(DocumentTextBlockRecord.sequence)
            )
        )
        tables = list(
            self.session.scalars(
                select(DocumentTableRecord)
                .where(DocumentTableRecord.extraction_id == extraction.id)
                .order_by(DocumentTableRecord.sequence)
            )
        )
        extractor = DeterministicSolicitationExtractor(
            self.settings.solicitation_intelligence_max_evidence_quote_chars,
            self.settings.solicitation_intelligence_context_window_chars,
        )
        result = extractor.extract(
            opportunity=opportunity,
            document=document,
            artifact=artifact,
            extraction=extraction,
            blocks=blocks,
            tables=tables,
            configuration_fingerprint=fingerprint,
        )
        run = SolicitationExtractionRunRecord(
            id=str(uuid4()),
            opportunity_id=opportunity.id,
            document_id=document.id,
            artifact_id=artifact.id,
            text_extraction_id=extraction.id,
            extractor_name=result.extractor_name,
            extractor_version=result.extractor_version,
            schema_version=result.schema_version,
            configuration_fingerprint=fingerprint,
            state=result.status,
            authority=result.authority.value,
            field_count=len(result.facts),
            evidence_count=sum(len(f.evidence) for f in result.facts),
            conflict_count=len(result.conflicts),
            warning_count=len(result.warnings),
            completeness=result.completeness,
            started_at=now,
            completed_at=now,
            created_at=now,
        )
        self.session.add(run)
        self.session.flush()
        for section in result.sections:
            self.session.add(
                SolicitationSectionRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    parent_section_id=None,
                    normalized_type=section["normalized_type"],
                    source_title=section["source_title"],
                    sequence=section["sequence"],
                    starting_block_id=section["starting_block_id"],
                    ending_block_id=section["ending_block_id"],
                    starting_page=section["starting_page"],
                    ending_page=section["ending_page"],
                    confidence=section["confidence"],
                )
            )
        for fact in result.facts[: self.settings.solicitation_intelligence_max_fields]:
            record = SolicitationFactRecord(
                id=str(uuid4()),
                extraction_run_id=run.id,
                opportunity_id=opportunity.id,
                canonical_field=fact.canonical_field,
                category=fact.category,
                value_type=fact.value_type,
                normalized_value={"value": fact.normalized_value},
                original_value=fact.original_value,
                source_status=fact.source_status.value,
                confidence=fact.confidence,
                confidence_score=fact.confidence_score,
                effective_status=fact.effective_status,
                notes=fact.notes,
                first_observed_at=now,
                last_observed_at=now,
                created_at=now,
                updated_at=now,
            )
            self.session.add(record)
            self.session.flush()
            for evidence in fact.evidence:
                self.session.add(
                    SolicitationEvidenceRecord(
                        id=str(uuid4()),
                        fact_id=record.id,
                        document_id=document.id,
                        artifact_id=artifact.id,
                        text_extraction_id=extraction.id,
                        text_block_id=evidence.text_block_id,
                        table_id=evidence.table_id,
                        source_location={
                            "page_number": evidence.page_number,
                            "sheet_name": evidence.sheet_name,
                            "archive_entry": evidence.archive_entry,
                            "table_index": evidence.table_index,
                            "row_start": evidence.row_start,
                            "column_start": evidence.column_start,
                            "character_start": evidence.character_start,
                            "character_end": evidence.character_end,
                        },
                        bounded_quote=evidence.quote,
                        bounded_context=evidence.context,
                        source_url=document.source_url,
                        evidence_hash=evidence.evidence_hash,
                        extraction_method=evidence.extraction_method,
                        ocr_confidence=evidence.ocr_confidence,
                        created_at=now,
                    )
                )
        self._persist_children(run, opportunity.id, result)
        document.structured_extraction_state = result.status
        self.session.flush()
        return run, False

    def _persist_children(self, run, opportunity_id, result) -> None:
        for item in result.requirements[: self.settings.solicitation_intelligence_max_requirements]:
            self.session.add(
                SolicitationRequirementRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    opportunity_id=opportunity_id,
                    normalized_text=item["normalized_text"],
                    original_text=item["original_text"],
                    strength=item["strength"],
                    category=item["category"],
                    effective_status=item["effective_status"],
                )
            )
        for item in result.deliverables[: self.settings.solicitation_intelligence_max_deliverables]:
            self.session.add(
                SolicitationDeliverableRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    opportunity_id=opportunity_id,
                    name=item["name"],
                    description=item["description"],
                    frequency=item["frequency"],
                    due_information=item["due_information"],
                )
            )
        for sequence, item in enumerate(
            result.evaluation_factors[
                : self.settings.solicitation_intelligence_max_evaluation_factors
            ]
        ):
            self.session.add(
                SolicitationEvaluationFactorRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    opportunity_id=opportunity_id,
                    name=item["name"],
                    weight=item["weight"],
                    points=item["points"],
                    qualitative_importance=item["qualitative_importance"],
                    pass_fail=item["pass_fail"],
                    sequence=sequence,
                )
            )
        for item in result.contacts[: self.settings.solicitation_intelligence_max_contacts]:
            self.session.add(
                SolicitationContactRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    opportunity_id=opportunity_id,
                    role=item["role"],
                    name=item["name"],
                    email=item["email"],
                    phone=item["phone"],
                )
            )
        for item in result.codes:
            self.session.add(
                SolicitationCodeRecord(
                    id=str(uuid4()),
                    extraction_run_id=run.id,
                    opportunity_id=opportunity_id,
                    code_system=item["system"],
                    code=item["code"],
                    description=item["description"],
                )
            )
