from fastapi import APIRouter

from sled_aggregator.api.routes import connectors, documents, intelligence, opportunities
from sled_aggregator.config import get_settings

settings = get_settings()
api_router = APIRouter(prefix=settings.api_prefix)
api_router.include_router(opportunities.router)
api_router.include_router(documents.router)
api_router.include_router(connectors.router)

api_router.include_router(intelligence.router)
