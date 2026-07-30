"""Bounded extraction worker: ``python -m sled_aggregator.documents.extraction_worker --once``."""

import argparse
from collections import Counter

from sqlalchemy import exists, select

from sled_aggregator.config import get_settings
from sled_aggregator.db.models import DocumentArtifactRecord, DocumentExtractionRecord
from sled_aggregator.db.session import get_session_factory
from sled_aggregator.documents.extraction_service import DocumentExtractionService
from sled_aggregator.documents.extraction_types import ExtractionFailure
from sled_aggregator.documents.storage import LocalDocumentStorage


def run_once(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    summary: Counter[str] = Counter()
    with get_session_factory()() as session:
        artifacts = list(
            session.scalars(
                select(DocumentArtifactRecord)
                .where(
                    ~exists().where(
                        DocumentExtractionRecord.artifact_id == DocumentArtifactRecord.id
                    )
                )
                .order_by(DocumentArtifactRecord.retrieved_at, DocumentArtifactRecord.id)
                .limit(batch_size or settings.document_extraction_batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        service = DocumentExtractionService(
            session, LocalDocumentStorage(settings.document_storage_root), settings
        )
        summary["claimed"] = len(artifacts)
        for artifact in artifacts:
            try:
                service.extract(artifact)
                session.commit()
                summary["completed"] += 1
            except ExtractionFailure as failure:
                session.rollback()
                summary[failure.state.value] += 1
            except Exception:
                session.rollback()
                summary["failed"] += 1
    return dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract safely downloaded solicitation artifacts")
    parser.add_argument("--once", action="store_true", help="process one bounded batch and exit")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--ocr-health", action="store_true", help="report optional OCR availability"
    )
    args = parser.parse_args()
    if args.ocr_health:
        from sled_aggregator.documents.ocr import TesseractOcrProvider

        provider = TesseractOcrProvider()
        print({"available": provider.available, "version": provider.version})
    else:
        print(run_once(args.batch_size))


if __name__ == "__main__":
    main()
