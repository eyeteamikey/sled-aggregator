"""Bridge connector document candidates to the durable document pipeline.

This module deliberately performs no retrieval.  Collection commits manifest and
queue metadata; downloader workers remain the network boundary.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sled_aggregator.config import Settings
from sled_aggregator.db.models import DocumentRetrievalJobRecord, OpportunityRecord
from sled_aggregator.domain.enums import AccessState
from sled_aggregator.domain.models import CanonicalOpportunity, DocumentCandidate
from sled_aggregator.services.document_manifest import DocumentManifestService

PIPELINE_CONNECTORS = frozenset(
    {
        "georgia/gpr", "maryland/emma", "oracle/fusion-rest", "oracle/peoplesoft-sourcing",
        "pennsylvania/emarketplace", "tyler/munis-vss", "virginia/eva",
        "texas/esbd", "rhode-island/rivip-external",
    }
)


@dataclass(slots=True)
class DocumentIngestionSummary:
    opportunity_id: str
    candidates_received: int = 0
    manifests_created: int = 0
    manifests_updated: int = 0
    versions_superseded: int = 0
    retrieval_jobs_created: int = 0
    duplicates_skipped: int = 0
    restricted_documents_preserved: int = 0
    invalid_candidates_rejected: int = 0
    warnings: list[str] = field(default_factory=list)


def candidates_from_payload(opportunity: CanonicalOpportunity) -> list[DocumentCandidate]:
    """Adapt the verified Pennsylvania canonical payload contract.

    Oracle and Tyler already return ``DocumentCandidate`` instances from their
    detail methods.  Other connectors are intentionally not guessed here.
    """
    if opportunity.source.platform_family != "pennsylvania/emarketplace":
        return []
    rows = opportunity.raw_payload.get("document_links", [])
    result: list[DocumentCandidate] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        access = str(row.get("access_state", "unknown"))
        state = (
            AccessState.PUBLIC
            if access in {"public", "external_public"}
            else AccessState.REGISTRATION_REQUIRED
            if "account" in access or "supplier" in access
            else AccessState.UNKNOWN
        )
        url = row.get("source_url")
        if not url:
            continue
        filename = row.get("displayed_filename") or PurePosixPath(urlparse(str(url)).path).name
        try:
            result.append(
                DocumentCandidate(
                    opportunity_id=opportunity.source.source_id,
                    source_document_url=url,
                    source_opportunity_url=opportunity.source.opportunity_url,
                    filename=filename or "document",
                    label=row.get("displayed_title"),
                    category=row.get("document_category"),
                    access_state=state,
                    version_label=row.get("addendum_or_version"),
                    publicly_retrievable=bool(row.get("retrieval_eligible")),
                    raw_metadata={
                        "source_section": row.get("source_section"),
                        "classification": row.get("classification"),
                    },
                )
            )
        except ValidationError:
            continue
    return result


class DocumentOrchestrationService:
    """Idempotently persist candidates for an already-persisted opportunity."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.manifest = DocumentManifestService(
            session,
            max_attempts=self.settings.document_queue_max_attempts,
            default_priority=self.settings.document_queue_default_priority,
            auto_enqueue=self.settings.document_auto_enqueue_enabled,
        )

    def ingest(
        self,
        opportunity: CanonicalOpportunity,
        candidates: Iterable[DocumentCandidate],
        *,
        queued_in_collection: int = 0,
    ) -> DocumentIngestionSummary:
        parent = self.session.scalar(
            select(OpportunityRecord).where(
                OpportunityRecord.source_portal == opportunity.source.platform_family,
                OpportunityRecord.source_record_id == opportunity.source.source_id,
            )
        )
        if parent is None:
            raise ValueError("document parent opportunity must be persisted first")
        summary = DocumentIngestionSummary(opportunity_id=parent.id)
        values = list(candidates)
        summary.candidates_received = len(values)
        if not self.settings.document_manifest_enabled:
            summary.warnings.append("document ingestion disabled")
            return summary
        allowed = set(self.settings.document_allowed_categories)
        seen: set[tuple[str | None, str | None, int | None]] = set()
        for candidate in values[: self.settings.document_max_per_opportunity]:
            key = (candidate.source_document_id, candidate.version_label, candidate.version_number)
            if key in seen:
                summary.duplicates_skipped += 1
                continue
            seen.add(key)
            if candidate.opportunity_id != opportunity.source.source_id:
                summary.invalid_candidates_rejected += 1
                continue
            if allowed and candidate.category not in allowed:
                summary.invalid_candidates_rejected += 1
                continue
            candidate = candidate.model_copy(update={"opportunity_id": parent.id})
            before_jobs = self.session.query(DocumentRetrievalJobRecord).count()
            try:
                record, created = self.manifest.upsert(
                    candidate=candidate,
                    connector=opportunity.source.platform_family,
                    jurisdiction=opportunity.source.jurisdiction,
                    enqueue=(queued_in_collection + summary.retrieval_jobs_created)
                    < self.settings.document_max_queued_per_collection,
                )
            except (TypeError, ValueError) as exc:
                summary.invalid_candidates_rejected += 1
                summary.warnings.append(type(exc).__name__)
                continue
            summary.manifests_created += int(created)
            summary.manifests_updated += int(not created)
            summary.retrieval_jobs_created += int(
                self.session.query(DocumentRetrievalJobRecord).count() > before_jobs
            )
            if record.access_state != AccessState.PUBLIC.value:
                summary.restricted_documents_preserved += 1
        if len(values) > self.settings.document_max_per_opportunity:
            summary.warnings.append("per-opportunity document limit reached")
        return summary
