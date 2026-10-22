"""Training session management service."""

import logging
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Seed, SeedStatus, TrainingSession, User

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

    # Pool exhausted for this user. Reset: pick from all available seeds.
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


@dataclass(frozen=True)
class PoolPlayProgress:
    """How far the users who played a training pool the most got through it.

    Counts follow ``get_played_seed_counts``: distinct AVAILABLE seeds a user
    opened a session on, so a regenerated pool starts back at zero.
    """

    max_played: int
    # Display names of every user at ``max_played``, sorted.
    top_players: tuple[str, ...]
    # Users who played every available seed: ``get_training_seed`` now hands
    # them seeds they have already seen.
    exhausted_users: int


async def get_pool_play_progress(db: AsyncSession) -> dict[str, PoolPlayProgress]:
    """Summarize per-user progress through each pool that has been played.

    Pools nobody has played (race pools included) are absent from the result.
    """
    totals = dict(
        (
            await db.execute(
                select(Seed.pool_name, func.count(Seed.id))
                .where(Seed.status == SeedStatus.AVAILABLE)
                .group_by(Seed.pool_name)
            )
        )
        .tuples()
        .all()
    )
    result = await db.execute(
        select(
            Seed.pool_name,
            User.twitch_username,
            User.twitch_display_name,
            func.count(TrainingSession.seed_id.distinct()),
        )
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .join(User, TrainingSession.user_id == User.id)
        .where(Seed.status == SeedStatus.AVAILABLE)
        .group_by(Seed.pool_name, User.id, User.twitch_username, User.twitch_display_name)
    )
    played_by_pool: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for pool_name, username, display_name, played in result.tuples():
        played_by_pool[pool_name].append((display_name or username, played))

    progress: dict[str, PoolPlayProgress] = {}
    for pool_name, players in played_by_pool.items():
        max_played = max(played for _, played in players)
        progress[pool_name] = PoolPlayProgress(
            max_played=max_played,
            top_players=tuple(
                sorted(
                    (name for name, played in players if played == max_played),
                    key=str.casefold,
                )
            ),
            exhausted_users=sum(1 for _, played in players if played >= totals[pool_name]),
        )
    return progress


async def create_training_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    pool_name: str,
) -> TrainingSession:
    """Create a new training session with a random seed.

    Raises:
        ValueError: If no seeds are available in the pool
    """
    seed = await get_training_seed(db, pool_name, user_id)
    if seed is None:
        raise ValueError(f"No available seeds in training mode '{pool_name}'")

    session = TrainingSession(
        user_id=user_id,
        seed_id=seed.id,
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
