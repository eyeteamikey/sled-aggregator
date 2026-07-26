from fastapi import APIRouter

from sled_aggregator.domain.models import CanonicalOpportunity, RawOpportunity
from sled_aggregator.services.normalizer import OpportunityNormalizer

router = APIRouter(prefix="/opportunities", tags=["opportunities"])
normalizer = OpportunityNormalizer()


@router.get("", response_model=list[CanonicalOpportunity])
async def list_opportunities() -> list[CanonicalOpportunity]:
    """Development seam until the persistence layer is added."""
    return []


@router.post("/normalize", response_model=CanonicalOpportunity)
async def normalize_opportunity(payload: RawOpportunity) -> CanonicalOpportunity:
    return normalizer.normalize(payload)

