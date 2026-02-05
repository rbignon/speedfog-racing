"""Seed pools API routes (public)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.database import get_db
from speedfog_racing.services import get_pool_stats

router = APIRouter()


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int


@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
) -> dict[str, PoolStats]:
    """Get availability statistics for all seed pools.

    Public endpoint for race creation form.
    """
    stats = await get_pool_stats(db)
    return {name: PoolStats(**counts) for name, counts in stats.items()}
