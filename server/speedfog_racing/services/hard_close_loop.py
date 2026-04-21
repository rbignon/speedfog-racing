"""Background task that force-finishes races past their race_ends_at."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Caster, Participant, Race, RaceStatus
from speedfog_racing.services.race_lifecycle import finalize_race

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # seconds


async def close_expired_races(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[uuid.UUID]:
    """Transition any RUNNING race past race_ends_at to FINISHED.

    Returns the list of race ids that were finalized this tick.
    """
    now = datetime.now(UTC)
    affected: list[uuid.UUID] = []

    async with session_maker() as db:
        result = await db.execute(
            select(Race.id).where(
                Race.status == RaceStatus.RUNNING,
                Race.race_ends_at.isnot(None),
                Race.race_ends_at <= now,
            )
        )
        race_ids = [row[0] for row in result.all()]

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

            race.status = RaceStatus.FINISHED
            race.finished_at = datetime.now(UTC)
            await db.commit()

            await finalize_race(db, race, forced=True)
            affected.append(race_id)
            logger.info("Hard-closed race %s at %s", race_id, race.finished_at)

    return affected


async def hard_close_loop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodic loop that hard-closes expired races."""
    logger.info("Hard-close monitor started (poll=%ds)", POLL_INTERVAL)
    while True:
        try:
            await close_expired_races(session_maker)
        except Exception:
            logger.exception("Hard-close monitor error")
        await asyncio.sleep(POLL_INTERVAL)
