from sled_aggregator.domain.models import CanonicalOpportunity, RawOpportunity
from sled_aggregator.domain.repositories import OpportunityRepository, UpsertResult
from sled_aggregator.services.normalizer import OpportunityNormalizer


class OpportunityService:
    def __init__(
        self,
        repository: OpportunityRepository,
        normalizer: OpportunityNormalizer | None = None,
    ) -> None:
        self.repository = repository
        self.normalizer = normalizer or OpportunityNormalizer()

    def ingest(self, raw: RawOpportunity) -> UpsertResult:
        return self.repository.upsert(self.normalizer.normalize(raw))

    def list(self, *, limit: int = 100, offset: int = 0) -> list[CanonicalOpportunity]:
        return self.repository.list(limit=limit, offset=offset)
