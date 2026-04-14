"""Pool lookup and admin toggle helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import Pool


async def list_pools(db: AsyncSession, *, include_disabled: bool = False) -> list[Pool]:
    """Return all pools, ordered by name.

    By default disabled pools are excluded so callers on the public surface
    don't have to filter client-side.
    """
    query = select(Pool).order_by(Pool.name)
    if not include_disabled:
        query = query.where(Pool.enabled.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_pool(db: AsyncSession, name: str) -> Pool | None:
    """Return the Pool with the given name, or ``None`` if it does not exist."""
    result = await db.execute(select(Pool).where(Pool.name == name))
    return result.scalar_one_or_none()


async def set_pool_enabled(db: AsyncSession, name: str, enabled: bool) -> Pool:
    """Flip the ``enabled`` flag on a pool.

    Raises:
        ValueError: If no pool with that name exists.
    """
    pool = await get_pool(db, name)
    if pool is None:
        raise ValueError(f"Pool '{name}' does not exist")
    pool.enabled = enabled
    await db.commit()
    await db.refresh(pool)
    return pool
