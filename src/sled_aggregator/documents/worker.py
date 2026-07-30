"""One-shot safe document downloader: ``python -m sled_aggregator.documents.worker --once``."""

import argparse
import asyncio
import logging
import random
import socket
from collections import Counter
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sled_aggregator.config import Settings, get_settings
from sled_aggregator.db.models import (
    DocumentArtifactRecord,
    DocumentDownloadAttemptRecord,
    DocumentRetrievalJobRecord,
    SolicitationDocumentRecord,
)
from sled_aggregator.db.session import get_session_factory
from sled_aggregator.documents.fetcher import PublicDocumentFetcher
from sled_aggregator.documents.policy import DownloadPolicy
from sled_aggregator.documents.storage import DocumentStorage, LocalDocumentStorage
from sled_aggregator.documents.types import DownloadFailure, FailureKind
from sled_aggregator.domain.enums import AccessState, RetrievalState
from sled_aggregator.services.document_manifest import DocumentQueueService, InvalidLease

logger = logging.getLogger(__name__)


class DocumentDownloadWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        fetcher: PublicDocumentFetcher,
        storage: DocumentStorage,
        settings: Settings,
        *,
        owner: str | None = None,
        clock=lambda: datetime.now(UTC),
        randomness=random.random,
    ) -> None:
        self.factory, self.fetcher, self.storage, self.settings = (
            factory,
            fetcher,
            storage,
            settings,
        )
        self.owner = owner or f"{socket.gethostname()}-{uuid4()}"
        self.clock, self.randomness = clock, randomness

    async def run_once(self, batch_size: int | None = None) -> dict[str, int]:
        summary: Counter[str] = Counter()
        with self.factory() as session:
            jobs = DocumentQueueService(session).claim(
                self.owner,
                now=self.clock(),
                lease_seconds=self.settings.document_queue_lease_seconds,
                limit=min(batch_size or self.settings.document_download_batch_size, 100),
            )
            session.commit()
            job_ids = [job.id for job in jobs]
        summary["claimed"] = len(job_ids)
        for job_id in job_ids:
            try:
                outcome = await self._process(job_id)
            except InvalidLease:
                outcome = "lease_lost"
            except Exception:
                logger.exception("document download job failed", extra={"job_id": job_id})
                outcome = "failed"
            summary[outcome] += 1
        return dict(summary)

    async def _process(self, job_id: str) -> str:
        with self.factory() as session:
            job = session.get(DocumentRetrievalJobRecord, job_id)
            if job is None:
                return "skipped"
            document = session.get(SolicitationDocumentRecord, job.document_id)
            now, token = self.clock(), job.lease_token or ""
            queue = DocumentQueueService(session)
            queue.validate_lease(job, owner=self.owner, token=token, now=now)
            if not document or not self._eligible(document, job):
                queue.terminal(
                    job, owner=self.owner, token=token, now=now, state=RetrievalState.QUARANTINED
                )
                session.commit()
                return "skipped"
            latest = session.scalar(
                select(DocumentArtifactRecord)
                .where(DocumentArtifactRecord.document_id == document.id)
                .order_by(DocumentArtifactRecord.retrieved_at.desc())
                .limit(1)
            )
            attempt = DocumentDownloadAttemptRecord(
                id=str(uuid4()),
                document_id=document.id,
                queue_job_id=job.id,
                attempt_number=job.attempt_count + 1,
                started_at=now,
                original_host=(urlsplit(document.source_url).hostname or "")[:255],
                redirect_count=0,
                bytes_received=0,
            )
            session.add(attempt)
            session.commit()
        try:
            result = await self.fetcher.fetch(
                document.source_url,
                etag=latest.etag if latest else None,
                last_modified=latest.last_modified if latest else None,
                allow_html=document.declared_media_type == "text/html",
            )
            with self.factory() as session:
                job = session.get(DocumentRetrievalJobRecord, job_id)
                document = session.get(SolicitationDocumentRecord, job.document_id) if job else None
                attempt = session.get(DocumentDownloadAttemptRecord, attempt.id)
                queue = DocumentQueueService(session)
                if not job or not document or not attempt:
                    raise InvalidLease("download records disappeared")
                now = self.clock()
                queue.validate_lease(job, owner=self.owner, token=token, now=now)
                if result.unchanged:
                    if latest:
                        current = session.get(DocumentArtifactRecord, latest.id)
                        if current:
                            current.last_checked_at = now
                    job.retrieval_state, job.retrieved_at = RetrievalState.UNCHANGED.value, now
                    job.lease_owner = job.lease_token = job.lease_expires_at = None
                    attempt.outcome, attempt.completed_at, attempt.http_status = (
                        "unchanged",
                        now,
                        304,
                    )
                    session.commit()
                    return "unchanged"
                assert result.metadata and result.temporary_path
                existing = session.scalar(
                    select(DocumentArtifactRecord).where(
                        DocumentArtifactRecord.document_id == document.id,
                        DocumentArtifactRecord.content_sha256 == result.metadata.sha256,
                    )
                )
                key = self.storage.generate_key(
                    document.jurisdiction,
                    document.opportunity_id,
                    document.id,
                    result.metadata.sha256,
                )
                self.storage.commit(
                    result.temporary_path,
                    key,
                    size=result.metadata.length,
                    sha256=result.metadata.sha256,
                )
                artifact = existing or DocumentArtifactRecord(
                    id=str(uuid4()),
                    document_id=document.id,
                    content_sha256=result.metadata.sha256,
                    content_length=result.metadata.length,
                    storage_provider="local",
                    storage_key=key,
                    final_url=result.final_url,
                    declared_media_type=result.metadata.declared_media_type,
                    detected_media_type=result.metadata.detected_media_type,
                    displayed_filename=result.metadata.filename,
                    etag=result.metadata.etag,
                    last_modified=result.metadata.last_modified,
                    retrieved_at=now,
                    last_checked_at=now,
                )
                if not existing:
                    session.add(artifact)
                else:
                    artifact.last_checked_at = now
                unchanged = (
                    existing is not None or document.content_sha256 == result.metadata.sha256
                )
                document.content_sha256, document.content_length = (
                    result.metadata.sha256,
                    result.metadata.length,
                )
                document.storage_provider, document.storage_key = "local", key
                document.final_url, document.detected_media_type = (
                    result.final_url,
                    result.metadata.detected_media_type,
                )
                document.downloaded_media_type, document.original_filename = (
                    result.metadata.detected_media_type,
                    result.metadata.filename,
                )
                attempt.outcome, attempt.completed_at, attempt.http_status = (
                    ("unchanged" if unchanged else "downloaded"),
                    now,
                    result.status_code,
                )
                attempt.final_host, attempt.redirect_count = (
                    (urlsplit(result.final_url).hostname or "")[:255],
                    len(result.redirects),
                )
                attempt.bytes_received, attempt.declared_media_type = (
                    result.metadata.length,
                    result.metadata.declared_media_type,
                )
                attempt.detected_media_type, attempt.artifact_id = (
                    result.metadata.detected_media_type,
                    artifact.id,
                )
                if unchanged:
                    job.retrieval_state, job.retrieved_at = RetrievalState.UNCHANGED.value, now
                    job.lease_owner = job.lease_token = job.lease_expires_at = None
                else:
                    queue.complete(job, owner=self.owner, token=token, now=now)
                session.commit()
                return "unchanged" if unchanged else "downloaded"
        except DownloadFailure as failure:
            return self._record_failure(job_id, attempt.id, token, failure)

    def _record_failure(
        self, job_id: str, attempt_id: str, token: str, failure: DownloadFailure
    ) -> str:
        transient = failure.kind is FailureKind.TRANSIENT
        mapping = {
            FailureKind.LOGIN_REQUIRED: RetrievalState.LOGIN_REQUIRED,
            FailureKind.REGISTRATION_REQUIRED: RetrievalState.REGISTRATION_REQUIRED,
            FailureKind.CAPTCHA: RetrievalState.CAPTCHA,
            FailureKind.RESTRICTED: RetrievalState.RESTRICTED,
            FailureKind.NOT_FOUND: RetrievalState.NOT_FOUND,
        }
        with self.factory() as session:
            job, attempt = (
                session.get(DocumentRetrievalJobRecord, job_id),
                session.get(DocumentDownloadAttemptRecord, attempt_id),
            )
            if not job or not attempt:
                raise InvalidLease("download records disappeared")
            now = self.clock()
            queue = DocumentQueueService(session)
            queue.validate_lease(job, owner=self.owner, token=token, now=now)
            attempt.completed_at, attempt.http_status = now, failure.status_code
            attempt.error_classification, attempt.error_summary = (
                failure.kind.value,
                str(failure)[:512],
            )
            if transient and job.attempt_count + 1 < min(
                job.max_attempts, self.settings.document_download_max_attempts
            ):
                queue.retry(
                    job,
                    now=now,
                    base_seconds=self.settings.document_download_retry_base_seconds,
                    max_seconds=self.settings.document_download_retry_max_seconds,
                )
                if failure.retry_after is not None:
                    job.next_attempt_at = now + timedelta(
                        seconds=min(
                            failure.retry_after, self.settings.document_download_retry_max_seconds
                        )
                    )
                attempt.outcome, attempt.retry_scheduled_at = "retried", job.next_attempt_at
                outcome = "retried"
            else:
                state = mapping.get(failure.kind, RetrievalState.QUARANTINED)
                queue.terminal(job, owner=self.owner, token=token, now=now, state=state)
                attempt.outcome = state.value
                outcome = state.value
            session.commit()
            return outcome

    @staticmethod
    def _eligible(document: SolicitationDocumentRecord, job: DocumentRetrievalJobRecord) -> bool:
        return (
            document.publicly_retrievable
            and document.likely_solicitation_document
            and document.is_current
            and document.access_state == AccessState.PUBLIC.value
            and job.retrieval_state == RetrievalState.LEASED.value
            and job.attempt_count < job.max_attempts
        )


async def _main(batch_size: int | None) -> None:
    settings = get_settings()
    if not settings.document_downloader_enabled:
        raise SystemExit("document downloader is disabled; set DOCUMENT_DOWNLOADER_ENABLED=true")
    timeout = httpx.Timeout(
        connect=settings.document_download_connect_timeout,
        read=settings.document_download_read_timeout,
        write=settings.document_download_write_timeout,
        pool=settings.document_download_pool_timeout,
    )
    policy = DownloadPolicy(
        allowed_hosts=settings.document_download_allowed_hosts,
        allowed_ports=settings.document_download_allowed_ports,
    )
    async with PublicDocumentFetcher(
        policy,
        temp_root=settings.document_download_temp_root,
        max_bytes=settings.document_download_max_bytes,
        chunk_bytes=settings.document_download_chunk_bytes,
        max_redirects=settings.document_download_max_redirects,
        timeout=timeout,
        user_agent=settings.document_download_user_agent,
    ) as fetcher:
        worker = DocumentDownloadWorker(
            get_session_factory(),
            fetcher,
            LocalDocumentStorage(settings.document_storage_root),
            settings,
        )
        print(await worker.run_once(batch_size))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public document downloader once")
    parser.add_argument("--once", action="store_true", help="process one bounded batch and exit")
    parser.add_argument("--batch-size", type=int, help="override the configured batch size")
    args = parser.parse_args()
    asyncio.run(_main(args.batch_size))


if __name__ == "__main__":
    main()
