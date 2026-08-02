from collections.abc import Iterable
from typing import Protocol

from sled_aggregator.domain.models import CanonicalOpportunity, DocumentCandidate, RawOpportunity
from sled_aggregator.domain.repositories import OpportunityRepository, UpsertResult
from sled_aggregator.services.normalizer import OpportunityNormalizer


class DocumentIngestor(Protocol):
    def ingest(self, opportunity: CanonicalOpportunity, candidates: Iterable[DocumentCandidate]): ...


class OpportunityService:
    def __init__(
        self,
        repository: OpportunityRepository,
        normalizer: OpportunityNormalizer | None = None,
        document_ingestor: DocumentIngestor | None = None,
    ) -> None:
        self.repository = repository
        self.normalizer = normalizer or OpportunityNormalizer()
        self.document_ingestor = document_ingestor

    def ingest(
        self, raw: RawOpportunity, *, document_candidates: Iterable[DocumentCandidate] = ()
    ) -> UpsertResult:
        result = self.repository.upsert(self.normalizer.normalize(raw))
        if self.document_ingestor is not None:
            self.document_ingestor.ingest(result.opportunity, document_candidates)
        return result

    def list(self, *, limit: int = 100, offset: int = 0) -> list[CanonicalOpportunity]:
        return self.repository.list(limit=limit, offset=offset)
