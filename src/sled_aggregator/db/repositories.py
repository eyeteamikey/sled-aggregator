from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sled_aggregator.db.models import OpportunityRecord
from sled_aggregator.domain.enums import OpportunityStatus
from sled_aggregator.domain.models import CanonicalOpportunity, SourceRef
from sled_aggregator.domain.repositories import UpsertResult


class SqlAlchemyOpportunityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, limit: int = 100, offset: int = 0) -> list[CanonicalOpportunity]:
        statement = (
            select(OpportunityRecord)
            .order_by(OpportunityRecord.due_at.asc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(row) for row in self.session.scalars(statement)]

    def get_by_source(
        self, *, source_portal: str, source_record_id: str
    ) -> CanonicalOpportunity | None:
        record = self.session.scalar(
            select(OpportunityRecord).where(
                OpportunityRecord.source_portal == source_portal,
                OpportunityRecord.source_record_id == source_record_id,
            )
        )
        return self._to_domain(record) if record else None

    def upsert(self, opportunity: CanonicalOpportunity) -> UpsertResult:
        source = opportunity.source
        record = self.session.scalar(
            select(OpportunityRecord).where(
                OpportunityRecord.source_portal == source.platform_family,
                OpportunityRecord.source_record_id == source.source_id,
            )
        )
        created = record is None
        now = datetime.now(UTC)
        if record is None:
            record = OpportunityRecord(
                first_seen_at=now,
                source_portal=source.platform_family,
                source_record_id=source.source_id,
                jurisdiction=source.jurisdiction,
                detail_url=str(source.opportunity_url),
                canonical_key=opportunity.canonical_key,
                title=opportunity.title,
                agency=opportunity.agency,
                status=opportunity.status.value,
                last_seen_at=opportunity.last_seen_at,
                normalized_at=opportunity.normalized_at,
            )
            self.session.add(record)

        record.canonical_key = opportunity.canonical_key
        record.jurisdiction = source.jurisdiction
        record.detail_url = str(source.opportunity_url)
        record.solicitation_number = opportunity.solicitation_number
        record.title = opportunity.title
        record.agency = opportunity.agency
        record.description = opportunity.description
        record.status = opportunity.status.value
        record.posted_at = opportunity.posted_at
        record.due_at = opportunity.due_at
        record.categories = opportunity.categories
        record.raw_payload = opportunity.raw_payload
        record.last_seen_at = opportunity.last_seen_at
        record.normalized_at = opportunity.normalized_at

        self.session.commit()
        self.session.refresh(record)
        return UpsertResult(opportunity=self._to_domain(record), created=created)

    @staticmethod
    def _to_domain(record: OpportunityRecord) -> CanonicalOpportunity:
        return CanonicalOpportunity(
            canonical_key=record.canonical_key,
            source=SourceRef(
                platform_family=record.source_portal,
                jurisdiction=record.jurisdiction,
                source_id=record.source_record_id,
                opportunity_url=record.detail_url,
            ),
            title=record.title,
            agency=record.agency,
            description=record.description,
            solicitation_number=record.solicitation_number,
            status=OpportunityStatus(record.status),
            posted_at=record.posted_at,
            due_at=record.due_at,
            categories=record.categories,
            raw_payload=record.raw_payload,
            last_seen_at=record.last_seen_at,
            normalized_at=record.normalized_at,
        )
