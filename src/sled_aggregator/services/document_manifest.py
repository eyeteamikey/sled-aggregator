"""Transactional manifest ingestion and PostgreSQL-backed retrieval queue."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from sled_aggregator.db.models import DocumentRetrievalJobRecord, SolicitationDocumentRecord
from sled_aggregator.domain.enums import AccessState, DocumentEligibility, RetrievalState
from sled_aggregator.domain.models import DocumentCandidate
from sled_aggregator.services.document_classifier import DocumentClassifier
from sled_aggregator.services.document_state import transition
from sled_aggregator.services.document_urls import UnsafeDocumentUrl, canonicalize_document_url


class InvalidLease(ValueError):
    pass


class DocumentManifestService:
    """Upsert candidates and queue them in one caller-controlled transaction."""

    def __init__(self, session: Session, *, max_attempts: int = 5, default_priority: int = 50) -> None:
        self.session, self.max_attempts, self.default_priority = session, max_attempts, default_priority
        self.classifier = DocumentClassifier()

    def upsert(self, *, candidate: DocumentCandidate, connector: str, tenant: str = "default", jurisdiction: str = "unknown", now: datetime | None = None) -> tuple[SolicitationDocumentRecord, bool]:
        now = now or datetime.now(UTC)
        classification = self.classifier.classify(candidate)
        try:
            canonical_url = canonicalize_document_url(str(candidate.source_document_url))
        except UnsafeDocumentUrl:
            canonical_url = None
        identity_material = candidate.source_document_id or canonical_url or f"{candidate.filename}|{candidate.label}|{candidate.category}"
        identity_key = sha256(f"{connector}|{tenant}|{candidate.opportunity_id}|{identity_material}".encode()).hexdigest()
        record = self.session.scalar(select(SolicitationDocumentRecord).where(SolicitationDocumentRecord.opportunity_id == candidate.opportunity_id, SolicitationDocumentRecord.identity_key == identity_key))
        created = record is None
        filename = PurePosixPath(candidate.filename).name
        public = candidate.access_state is AccessState.PUBLIC and candidate.publicly_retrievable is not False
        if record is None:
            record = SolicitationDocumentRecord(id=str(uuid4()), opportunity_id=candidate.opportunity_id, identity_key=identity_key, first_discovered_at=now, created_at=now)
            self.session.add(record)
        record.source_document_id = candidate.source_document_id
        record.tenant, record.connector, record.jurisdiction = tenant, connector, jurisdiction
        record.document_type, record.document_category = classification.role.value, candidate.category
        record.title, record.displayed_filename, record.normalized_filename = candidate.label, filename, filename.casefold()
        record.file_extension = PurePosixPath(filename).suffix.lower().lstrip(".") or None
        record.declared_media_type = candidate.mime_type
        record.likely_solicitation_document = classification.eligibility is DocumentEligibility.INCLUDE
        record.eligibility_reason = "; ".join(classification.rationale)
        record.classification_confidence = round(classification.score * 100)
        record.source_url, record.canonical_source_url = str(candidate.source_document_url), canonical_url
        record.authoritative_opportunity_url = str(candidate.source_opportunity_url)
        record.source_detail_url = str(candidate.source_detail_url) if candidate.source_detail_url else None
        record.referring_page_url = str(candidate.referring_page_url) if candidate.referring_page_url else None
        record.original_link_text = candidate.label
        record.source_metadata = {**(record.source_metadata or {}), **candidate.raw_metadata}
        record.access_state = candidate.access_state.value
        record.requires_login = candidate.access_state is AccessState.LOGIN_REQUIRED
        record.captcha_observed = candidate.access_state is AccessState.CAPTCHA
        record.publicly_retrievable = public and canonical_url is not None
        record.last_discovered_at, record.source_posted_at, record.source_modified_at = now, candidate.posted_at, candidate.modified_at
        record.logical_document_key = sha256(f"{candidate.opportunity_id}|{candidate.category}|{filename.casefold()}".encode()).hexdigest()[:32]
        record.version_label, record.version_number = candidate.version_label, candidate.version_number
        record.addendum_number, record.amendment_number = candidate.addendum_number, candidate.amendment_number
        record.relationship_type = "related"
        record.is_current, record.is_operationally_required = True, classification.role.value in {"addendum", "amendment", "questions_and_answers"}
        record.extracted_text_available, record.updated_at = False, now
        self.session.flush()
        if record.likely_solicitation_document and record.publicly_retrievable:
            self.enqueue(record, now=now)
        return record, created

    def enqueue(self, document: SolicitationDocumentRecord, *, priority: int | None = None, now: datetime | None = None) -> DocumentRetrievalJobRecord:
        now = now or datetime.now(UTC)
        job = self.session.scalar(select(DocumentRetrievalJobRecord).where(DocumentRetrievalJobRecord.document_id == document.id))
        if job:
            return job
        job = DocumentRetrievalJobRecord(id=str(uuid4()), document_id=document.id, retrieval_state=RetrievalState.QUEUED.value, priority=self.default_priority if priority is None else priority, attempt_count=0, max_attempts=self.max_attempts, next_attempt_at=now, created_at=now, updated_at=now)
        self.session.add(job)
        self.session.flush()
        return job


class DocumentQueueService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def claim_statement(now: datetime, limit: int = 1) -> Select[tuple[DocumentRetrievalJobRecord]]:
        return (select(DocumentRetrievalJobRecord).where(DocumentRetrievalJobRecord.retrieval_state == RetrievalState.QUEUED.value, DocumentRetrievalJobRecord.next_attempt_at <= now).order_by(DocumentRetrievalJobRecord.priority.desc(), DocumentRetrievalJobRecord.next_attempt_at, DocumentRetrievalJobRecord.created_at, DocumentRetrievalJobRecord.id).limit(limit).with_for_update(skip_locked=True))

    def claim(self, owner: str, *, now: datetime, lease_seconds: int, limit: int = 1) -> list[DocumentRetrievalJobRecord]:
        jobs = list(self.session.scalars(self.claim_statement(now, limit)))
        for job in jobs:
            job.retrieval_state = transition(RetrievalState(job.retrieval_state), RetrievalState.LEASED).value
            job.lease_owner, job.lease_token = owner, str(uuid4())
            job.lease_expires_at, job.updated_at = now + timedelta(seconds=lease_seconds), now
        self.session.flush()
        return jobs

    def recover_expired(self, *, now: datetime) -> int:
        jobs = list(self.session.scalars(select(DocumentRetrievalJobRecord).where(DocumentRetrievalJobRecord.retrieval_state == RetrievalState.LEASED.value, DocumentRetrievalJobRecord.lease_expires_at <= now).with_for_update(skip_locked=True)))
        for job in jobs:
            job.retrieval_state = transition(RetrievalState.LEASED, RetrievalState.QUEUED).value
            job.lease_owner = job.lease_token = job.lease_expires_at = None
        return len(jobs)

    def complete(self, job: DocumentRetrievalJobRecord, *, owner: str, token: str, now: datetime) -> None:
        if job.lease_owner != owner or job.lease_token != token or not job.lease_expires_at or job.lease_expires_at <= now:
            raise InvalidLease("active lease owner and token are required")
        transition(RetrievalState(job.retrieval_state), RetrievalState.DOWNLOADING)
        job.retrieval_state, job.retrieved_at = RetrievalState.DOWNLOADED.value, now
        job.lease_owner = job.lease_token = job.lease_expires_at = None

    def retry(self, job: DocumentRetrievalJobRecord, *, now: datetime, base_seconds: int, max_seconds: int) -> None:
        if job.attempt_count >= job.max_attempts:
            job.retrieval_state = RetrievalState.QUARANTINED.value
            return
        job.attempt_count += 1
        delay = min(max_seconds, base_seconds * (2 ** (job.attempt_count - 1)))
        job.retrieval_state, job.next_attempt_at = RetrievalState.QUEUED.value, now + timedelta(seconds=delay)
        job.lease_owner = job.lease_token = job.lease_expires_at = None

    def stats(self) -> dict[str, int]:
        return dict(self.session.execute(select(DocumentRetrievalJobRecord.retrieval_state, func.count()).group_by(DocumentRetrievalJobRecord.retrieval_state)).all())
