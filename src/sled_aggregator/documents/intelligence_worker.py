import argparse
import json
from datetime import UTC, datetime

from sqlalchemy import select

from sled_aggregator.config import get_settings
from sled_aggregator.db.models import DocumentExtractionRecord
from sled_aggregator.db.session import get_session_factory
from sled_aggregator.documents.intelligence_service import SolicitationIntelligenceService


def run_once(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    size = batch_size or settings.solicitation_intelligence_batch_size
    summary = {
        key: 0
        for key in (
            "claimed",
            "extracted",
            "reconciled",
            "reused",
            "completed_with_warnings",
            "conflicts",
            "retried",
            "failed",
            "quarantined",
            "lease_lost",
        )
    }
    if not settings.solicitation_intelligence_enabled:
        return summary
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(DocumentExtractionRecord)
                .where(
                    DocumentExtractionRecord.is_current.is_(True),
                    DocumentExtractionRecord.extraction_state.in_(
                        ("completed", "completed_with_warnings")
                    ),
                )
                .order_by(DocumentExtractionRecord.created_at, DocumentExtractionRecord.id)
                .limit(size)
            )
        )
        summary["claimed"] = len(rows)
        service = SolicitationIntelligenceService(session, settings)
        for extraction in rows:
            try:
                run, reused = service.extract(extraction, now=datetime.now(UTC))
                summary["reused" if reused else "extracted"] += 1
                summary["completed_with_warnings"] += int(run.state == "completed_with_warnings")
                summary["conflicts"] += run.conflict_count
            except (ValueError, TypeError):
                summary["failed"] += 1
        session.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract evidence-backed solicitation intelligence"
    )
    parser.add_argument("--once", action="store_true", help="process one bounded batch")
    parser.add_argument("--batch-size", type=int, help="bounded batch size (1-100)")
    args = parser.parse_args()
    if args.batch_size is not None and not 1 <= args.batch_size <= 100:
        parser.error("--batch-size must be between 1 and 100")
    print(json.dumps(run_once(args.batch_size), sort_keys=True))


if __name__ == "__main__":
    main()
