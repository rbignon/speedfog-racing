"""Seed pools API routes (public)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.database import get_db
from speedfog_racing.schemas import PoolConfig
from speedfog_racing.services import get_pool_config, get_pool_stats

router = APIRouter()


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    pool_config: PoolConfig | None = None


@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
) -> dict[str, PoolStats]:
    """Get availability statistics for all seed pools.

    Public endpoint for race creation form.
    """
    stats = await get_pool_stats(db)

    result: dict[str, PoolStats] = {}
    for name, counts in stats.items():
        raw_config = get_pool_config(name)
        result[name] = PoolStats(
            available=counts.get("available", 0),
            consumed=counts.get("consumed", 0),
            pool_config=PoolConfig(**raw_config) if raw_config else None,
        )

    return result
