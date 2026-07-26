from copy import deepcopy

from sled_aggregator.domain.models import CanonicalOpportunity
from sled_aggregator.domain.repositories import UpsertResult


class InMemoryOpportunityRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], CanonicalOpportunity] = {}

    def list(self, *, limit: int = 100, offset: int = 0) -> list[CanonicalOpportunity]:
        items = sorted(
            self._items.values(),
            key=lambda item: (item.due_at is None, item.due_at, item.title),
        )
        return deepcopy(items[offset : offset + limit])

    def get_by_source(
        self, *, source_portal: str, source_record_id: str
    ) -> CanonicalOpportunity | None:
        value = self._items.get((source_portal, source_record_id))
        return deepcopy(value) if value else None

    def upsert(self, opportunity: CanonicalOpportunity) -> UpsertResult:
        key = (opportunity.source.platform_family, opportunity.source.source_id)
        created = key not in self._items
        self._items[key] = deepcopy(opportunity)
        return UpsertResult(opportunity=deepcopy(opportunity), created=created)

