"""Training session management service."""

import logging
import random
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Seed, SeedStatus, TrainingSession

logger = logging.getLogger(__name__)


async def get_training_seed(
    db: AsyncSession,
    pool_name: str,
    user_id: uuid.UUID,
    *,
    allow_reset: bool = True,
) -> Seed | None:
    """Get a random training seed, excluding seeds already played by this user.

    Args:
        db: Database session
        pool_name: Training pool name (e.g., "training_standard")
        user_id: User to exclude played seeds for
        allow_reset: If True and all seeds played, reset and pick from all

    Returns:
        A random Seed, or None if pool is empty
    """
    # Subquery: seeds already played by this user in this pool
    played_subq = (
        select(TrainingSession.seed_id)
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            TrainingSession.user_id == user_id,
            Seed.pool_name == pool_name,
        )
    ).scalar_subquery()

    result = await db.execute(
        select(Seed).where(
            Seed.pool_name == pool_name,
            Seed.status == SeedStatus.AVAILABLE,
            Seed.id.not_in(played_subq),
        )
    )
    available = list(result.scalars().all())

    if available:
        return random.choice(available)

    if not allow_reset:
        return None

    # Pool exhausted for this user — reset: pick from all available seeds
    logger.info(f"User {user_id} exhausted training pool '{pool_name}', resetting")
    result = await db.execute(
        select(Seed).where(
            Seed.pool_name == pool_name,
            Seed.status == SeedStatus.AVAILABLE,
        )
    )
    all_seeds = list(result.scalars().all())
    return random.choice(all_seeds) if all_seeds else None


async def get_played_seed_counts(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, int]:
    """Count distinct seeds played by a user, grouped by pool.

    Returns:
        Dict mapping pool_name → number of distinct seeds played.
    """
    result = await db.execute(
        select(Seed.pool_name, func.count(TrainingSession.seed_id.distinct()))
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            TrainingSession.user_id == user_id,
            Seed.status == SeedStatus.AVAILABLE,
        )
        .group_by(Seed.pool_name)
    )
    return {pool_name: count for pool_name, count in result.all()}


async def create_training_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    pool_name: str,
    *,
    exclude_from_stats: bool = False,
) -> TrainingSession:
    """Create a new training session with a random seed.

    Raises:
        ValueError: If no seeds are available in the pool
    """
    seed = await get_training_seed(db, pool_name, user_id)
    if seed is None:
        raise ValueError(f"No available seeds in training pool '{pool_name}'")

    session = TrainingSession(
        user_id=user_id,
        seed_id=seed.id,
        exclude_from_stats=exclude_from_stats,
    )
    db.add(session)
    await db.flush()

    # Eagerly load relationships for the response
    result = await db.execute(
        select(TrainingSession)
        .options(selectinload(TrainingSession.user), selectinload(TrainingSession.seed))
        .where(TrainingSession.id == session.id)
    )
    session = result.scalar_one()

    logger.info(
        f"Created training session {session.id} for user {user_id} "
        f"with seed {seed.seed_number} from pool '{pool_name}'"
    )
    return session
