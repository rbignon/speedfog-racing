"""Seed pools API routes (public, with optional auth enrichment)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.models import User
from speedfog_racing.schemas import PoolConfig
from speedfog_racing.services import get_pool_config, get_pool_stats
from speedfog_racing.services.training_service import get_played_seed_counts

router = APIRouter()


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    played_by_user: int | None = None
    pool_config: PoolConfig | None = None


@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
    pool_type: str | None = Query(None, alias="type"),
    user: User | None = Depends(get_current_user_optional),
) -> dict[str, PoolStats]:
    """Get availability statistics for seed pools.

    Optional filter: ?type=race or ?type=training
    If authenticated, includes played_by_user count for training pools.
    """
    stats = await get_pool_stats(db)

    played_counts: dict[str, int] = {}
    if user:
        played_counts = await get_played_seed_counts(db, user.id)

    result: dict[str, PoolStats] = {}
    for name, counts in stats.items():
        raw_config = get_pool_config(name)
        # Filter by type if requested
        if pool_type and raw_config:
            if raw_config.get("type", "race") != pool_type:
                continue
        elif pool_type and not raw_config:
            if pool_type != "race":
                continue

        is_training = raw_config and raw_config.get("type") == "training"
        result[name] = PoolStats(
            available=counts.get("available", 0),
            consumed=counts.get("consumed", 0),
            played_by_user=played_counts.get(name) if user and is_training else None,
            pool_config=PoolConfig(**raw_config) if raw_config else None,
        )

    return result
