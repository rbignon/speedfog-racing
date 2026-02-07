"""Seed pools API routes (public)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.database import get_db
from speedfog_racing.services import get_pool_metadata, get_pool_stats

router = APIRouter()


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    estimated_duration: str | None = None
    description: str | None = None


@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
) -> dict[str, PoolStats]:
    """Get availability statistics for all seed pools.

    Public endpoint for race creation form.
    """
    stats = await get_pool_stats(db)
    metadata = get_pool_metadata(settings.seeds_pool_dir)

    result: dict[str, PoolStats] = {}
    # Merge DB stats with TOML metadata
    all_pools = set(stats.keys()) | set(metadata.keys())
    for name in all_pools:
        counts = stats.get(name, {"available": 0, "consumed": 0})
        meta = metadata.get(name, {})
        result[name] = PoolStats(
            available=counts.get("available", 0),
            consumed=counts.get("consumed", 0),
            estimated_duration=meta.get("estimated_duration"),
            description=meta.get("description"),
        )

    return result
