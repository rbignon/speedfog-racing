"""Training session management service."""

import logging
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import (
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.services.pool_service import get_pool
from speedfog_racing.services.seed_service import SpeedrunFloorError, draw_speedrun_seed
from speedfog_racing.services.set_seed_service import (
    SeedLookupError,
    resolve_seed,
    seed_replayability,
)

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


SpeedrunStartErrorCode = Literal[
    "active_session",
    "unfinished_limit",
    "unknown_pool",
    "no_fresh_seed",
    "unknown_seed",
    "ambiguous_seed",
    "not_replayable",
]


class SpeedrunStartError(Exception):
    """A ranked solo run could not start; ``code`` says why (the API maps it)."""

    def __init__(self, code: SpeedrunStartErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: SpeedrunStartErrorCode = code
        self.message = message


async def _require_no_active_session(db: AsyncSession, user_id: uuid.UUID) -> None:
    # SAFETY: same TOCTOU window as the practice flow (rate-limited, single user).
    active = await db.execute(
        select(TrainingSession.id).where(
            TrainingSession.user_id == user_id,
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
        )
    )
    if active.first() is not None:
        raise SpeedrunStartError("active_session", "You already have an active solo session")


async def _require_under_unfinished_limit(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> None:
    """Refuse a Speedrun solo start when the player has too many unfinished
    Speedrun sessions in the window (finished runs never count)."""
    limit = settings.speedrun_solo_unfinished_limit
    if limit <= 0:
        return
    now = now or datetime.now(UTC)
    hours = settings.speedrun_solo_unfinished_window_hours
    window = timedelta(hours=hours)
    result = await db.execute(
        select(TrainingSession.created_at)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.mode == RunMode.SPEEDRUN,
            TrainingSession.status != TrainingSessionStatus.FINISHED,
            TrainingSession.created_at >= now - window,
        )
        .order_by(TrainingSession.created_at)
    )
    created = list(result.scalars())
    count = len(created)
    if count < limit:
        return
    # The session whose leaving the window brings the count under the limit.
    frees_up = created[count - limit]
    if frees_up.tzinfo is None:  # SQLite drops the zone; stored values are UTC
        frees_up = frees_up.replace(tzinfo=UTC)
    minutes = max(1, -((now - (frees_up + window)) // timedelta(minutes=1)))
    hours_left, minutes_left = divmod(minutes, 60)
    wait = f"{hours_left} h {minutes_left} min" if hours_left else f"{minutes_left} min"
    unit = "hour" if hours == 1 else "hours"
    raise SpeedrunStartError(
        "unfinished_limit",
        f"You have {count} unfinished Random Seed runs in the last {hours} {unit} "
        f"(the limit is {limit}). Finish a run, or try again in {wait}.",
    )


async def _add_ranked_session(
    db: AsyncSession, user_id: uuid.UUID, seed: Seed, mode: RunMode
) -> TrainingSession:
    created = TrainingSession(user_id=user_id, seed_id=seed.id, mode=mode)
    db.add(created)
    await db.flush()
    result = await db.execute(
        select(TrainingSession)
        .options(selectinload(TrainingSession.user), selectinload(TrainingSession.seed))
        .where(TrainingSession.id == created.id)
    )
    return result.scalar_one()


async def create_speedrun_session(
    db: AsyncSession, user_id: uuid.UUID, pool_name: str
) -> TrainingSession:
    """Start a Speedrun-mode solo run on a fresh seed of a race pool.

    The seed is CONSUMED now and never released, even if the session is
    cancelled, so a player cannot fish for a seed by cancelling.

    Raises:
        SpeedrunStartError: ``active_session``, ``unfinished_limit``, ``unknown_pool``
            (missing, disabled or training pool) or ``no_fresh_seed`` (pool at its floor).
    """
    await _require_no_active_session(db, user_id)
    await _require_under_unfinished_limit(db, user_id)
    pool = await get_pool(db, pool_name)
    if pool is None or not pool.enabled or (pool.config or {}).get("type", "race") == "training":
        raise SpeedrunStartError("unknown_pool", "Unknown pool")
    try:
        seed = await draw_speedrun_seed(db, pool_name)
    except SpeedrunFloorError as error:
        raise SpeedrunStartError("no_fresh_seed", str(error)) from error
    seed.status = SeedStatus.CONSUMED
    session = await _add_ranked_session(db, user_id, seed, RunMode.SPEEDRUN)
    logger.info(f"Created speedrun session {session.id} for user {user_id} on {seed.seed_number}")
    return session


async def create_set_seed_session(
    db: AsyncSession, user_id: uuid.UUID, seed_text: str
) -> TrainingSession:
    """Start a Set Seed solo run on a known, replayable seed (consumes nothing).

    Raises:
        SpeedrunStartError: ``active_session``, ``unknown_seed``,
            ``ambiguous_seed`` or ``not_replayable`` (the reason as message).
    """
    await _require_no_active_session(db, user_id)
    try:
        seed = await resolve_seed(db, seed_text)
    except SeedLookupError as error:
        if error.kind == "ambiguous":
            raise SpeedrunStartError("ambiguous_seed", "Ambiguous seed ID") from error
        raise SpeedrunStartError("unknown_seed", "Unknown seed") from error
    replayability = await seed_replayability(db, seed)
    if not replayability.replayable:
        raise SpeedrunStartError("not_replayable", replayability.reason or "Not replayable")
    session = await _add_ranked_session(db, user_id, seed, RunMode.SET_SEED)
    logger.info(f"Created set seed session {session.id} for user {user_id} on {seed.seed_number}")
    return session


async def abandon_active_session(
    db: AsyncSession, session: TrainingSession, *, now: datetime
) -> bool:
    """End a session the player gives up: ABANDONED with progress, CANCELLED
    without. One conditional UPDATE, so a finish or an expiry committed since
    the session was read stands. False when it was no longer ACTIVE. The
    caller commits; ``session`` is not updated in memory."""
    result = await db.execute(
        update(TrainingSession)
        .where(
            TrainingSession.id == session.id,
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
        )
        .values(
            status=(
                TrainingSessionStatus.ABANDONED
                if session.zone_history
                else TrainingSessionStatus.CANCELLED
            ),
            finished_at=now,
        )
        .returning(TrainingSession.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def reset_set_seed_session(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """Clear the attempt of an ACTIVE Set Seed run so the player replays it on
    the pack already installed (same id, same mod token). One conditional
    UPDATE, so a finish committed since the run was read stands. The cheat
    detections, an admin invalidation and the live notification stamp belong
    to the run and stay. False when it was no longer an ACTIVE Set Seed run.
    The caller commits."""
    result = await db.execute(
        update(TrainingSession)
        .where(
            TrainingSession.id == session_id,
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
            TrainingSession.mode == RunMode.SET_SEED,
        )
        .values(
            igt_ms=0,
            death_count=0,
            zone_history=None,
            current_zone=None,
            last_igt_change_at=None,
        )
        .returning(TrainingSession.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def expire_speedrun_sessions(db: AsyncSession, *, now: datetime) -> list[uuid.UUID]:
    """Abandon ACTIVE Speedrun-mode sessions older than the TTL.

    A blind session left ACTIVE would hide its seed page forever. The seed
    stays CONSUMED and the zone history is kept. Set Seed and normal sessions
    never expire. Returns the abandoned session ids; the caller broadcasts.
    """
    cutoff = now - timedelta(hours=settings.speedrun_session_ttl_hours)
    # One conditional UPDATE: a session that finishes meanwhile is not overwritten.
    result = await db.execute(
        update(TrainingSession)
        .where(
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
            TrainingSession.mode == RunMode.SPEEDRUN,
            TrainingSession.created_at < cutoff,
        )
        .values(status=TrainingSessionStatus.ABANDONED, finished_at=now)
        .returning(TrainingSession.id)
        .execution_options(synchronize_session=False)
    )
    expired = list(result.scalars())
    await db.commit()
    for session_id in expired:
        logger.info(f"Expired speedrun session {session_id}")
    return expired
