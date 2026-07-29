from dataclasses import dataclass
from typing import Protocol

from sled_aggregator.domain.models import CanonicalOpportunity


@dataclass(frozen=True, slots=True)
class UpsertResult:
    opportunity: CanonicalOpportunity
    created: bool


class OpportunityRepository(Protocol):
    def list(self, *, limit: int = 100, offset: int = 0) -> list[CanonicalOpportunity]: ...

    def get_by_source(
        self, *, source_portal: str, source_record_id: str
    ) -> CanonicalOpportunity | None: ...

    def upsert(self, opportunity: CanonicalOpportunity) -> UpsertResult: ...
