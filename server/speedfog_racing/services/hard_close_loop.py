"""Background task that force-finishes races past their race_duration_minutes."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Caster, Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.race_lifecycle import finalize_race

logger = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds


def _deadline_reached(started_at: datetime | None, duration_min: int | None, now: datetime) -> bool:
    if started_at is None or duration_min is None:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return started_at + timedelta(minutes=duration_min) <= now


async def close_expired_races(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[uuid.UUID]:
    """Transition any RUNNING race past ``started_at + race_duration_minutes`` to FINISHED.

    Returns the list of race ids that were finalized this tick.
    """
    now = datetime.now(UTC)
    affected: list[uuid.UUID] = []

    # SQL pre-filter on non-null duration fields; the datetime arithmetic
    # (started_at + duration <= now) is applied in Python since it's
    # dialect-specific (Postgres supports interval math, SQLite used in tests
    # does not). Row volume here is bounded by concurrent RUNNING races.
    async with session_maker() as db:
        result = await db.execute(
            select(Race.id, Race.started_at, Race.race_duration_minutes).where(
                Race.status == RaceStatus.RUNNING,
                Race.started_at.isnot(None),
                Race.race_duration_minutes.isnot(None),
            )
        )
        race_ids = [
            row_id
            for row_id, started_at, duration in result.all()
            if _deadline_reached(started_at, duration, now)
        ]

    for race_id in race_ids:
        async with session_maker() as db:
            race = (
                await db.execute(
                    select(Race)
                    .where(Race.id == race_id)
                    .options(
                        selectinload(Race.participants).selectinload(Participant.user),
                        selectinload(Race.casters).selectinload(Caster.user),
                        selectinload(Race.seed),
                    )
                )
            ).scalar_one_or_none()

            if race is None or race.status != RaceStatus.RUNNING:
                continue

            # Optimistic locking: another worker (e.g. /finish endpoint or
            # check_race_auto_finish) may transition this race concurrently.
            # Filter on version so only one caller wins; if we lose, skip.
            now_ts = datetime.now(UTC)
            current_version = race.version
            result = await db.execute(
                update(Race)
                .where(
                    Race.id == race_id,
                    Race.status == RaceStatus.RUNNING,
                    Race.version == current_version,
                )
                .values(
                    status=RaceStatus.FINISHED,
                    version=current_version + 1,
                    finished_at=now_ts,
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                logger.info("Hard-close skipped race %s (concurrently transitioned)", race_id)
                await db.commit()
                continue

            # Sync the in-memory object so finalize_race sees a consistent
            # post-transition snapshot (matches the race_lifecycle pattern).
            race.status = RaceStatus.FINISHED
            race.version = current_version + 1
            race.finished_at = now_ts
            await db.commit()

            await finalize_race(db, race, forced=True)
            affected.append(race_id)
            logger.info("Hard-closed race %s at %s", race_id, race.finished_at)

    return affected


async def close_late_join_done_races(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[uuid.UUID]:
    """Finalize RUNNING races where the late-join window has elapsed and
    every participant is already in a terminal status.

    ``check_race_auto_finish`` holds off the transition during the late-join
    window so a late-joiner can still enter even when the currently
    registered field has all finished. Once the window has elapsed, this
    function performs the deferred close.
    """
    now = datetime.now(UTC)
    candidate_ids: list[uuid.UUID] = []
    affected: list[uuid.UUID] = []

    async with session_maker() as db:
        result = await db.execute(
            select(Race.id, Race.started_at, Race.late_join_window_minutes).where(
                Race.status == RaceStatus.RUNNING,
                Race.started_at.isnot(None),
                Race.late_join_window_minutes.isnot(None),
            )
        )
        candidate_ids = [
            row_id
            for row_id, started_at, window in result.all()
            if _deadline_reached(started_at, window, now)
        ]

    for race_id in candidate_ids:
        async with session_maker() as db:
            race = (
                await db.execute(
                    select(Race)
                    .where(Race.id == race_id)
                    .options(
                        selectinload(Race.participants).selectinload(Participant.user),
                        selectinload(Race.casters).selectinload(Caster.user),
                        selectinload(Race.seed),
                    )
                )
            ).scalar_one_or_none()

            if race is None or race.status != RaceStatus.RUNNING:
                continue

            all_done = all(
                p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
                for p in race.participants
            )
            if not all_done:
                continue

            now_ts = datetime.now(UTC)
            current_version = race.version
            result = await db.execute(
                update(Race)
                .where(
                    Race.id == race_id,
                    Race.status == RaceStatus.RUNNING,
                    Race.version == current_version,
                )
                .values(
                    status=RaceStatus.FINISHED,
                    version=current_version + 1,
                    finished_at=now_ts,
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                logger.info("Late-join close skipped race %s (concurrently transitioned)", race_id)
                await db.commit()
                continue

            race.status = RaceStatus.FINISHED
            race.version = current_version + 1
            race.finished_at = now_ts
            await db.commit()

            await finalize_race(db, race, forced=False)
            affected.append(race_id)
            logger.info(
                "Late-join window elapsed, finalized race %s at %s", race_id, race.finished_at
            )

    return affected


async def hard_close_loop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodic loop that hard-closes expired races."""
    logger.info("Hard-close monitor started (poll=%ds)", POLL_INTERVAL)
    while True:
        try:
            await close_expired_races(session_maker)
            await close_late_join_done_races(session_maker)
        except Exception:
            logger.exception("Hard-close monitor error")
        await asyncio.sleep(POLL_INTERVAL)
