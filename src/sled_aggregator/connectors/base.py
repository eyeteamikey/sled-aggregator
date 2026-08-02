from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sled_aggregator.domain.models import RawOpportunity


@dataclass(frozen=True, slots=True)
class ConnectorQuery:
    keywords: tuple[str, ...] = ()
    jurisdiction: str | None = None
    limit: int = 100


class BaseConnector(ABC):
    platform_family: str
    jurisdictions: tuple[str, ...] = ()
    public_read_only: bool = True
    # Set only after a fixture-backed adapter emits DocumentCandidate objects and
    # the normal collection path has been verified against the manifest queue.
    document_pipeline_compatible: bool = False

    @abstractmethod
    async def discover(self, query: ConnectorQuery) -> AsyncIterator[RawOpportunity]:
        """Yield public opportunity records without performing portal mutations."""
        if False:
            yield
