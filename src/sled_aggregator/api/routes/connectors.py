from fastapi import APIRouter

from sled_aggregator.connectors.registry import connector_registry

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("")
async def list_connectors() -> list[dict[str, object]]:
    return connector_registry.describe()
