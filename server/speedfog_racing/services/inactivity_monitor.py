"""Background task to auto-abandon inactive or no-show participants."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.discord import fire_race_finished_notifications
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.race_lifecycle import check_race_auto_finish

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = timedelta(minutes=15)
POLL_INTERVAL = 60  # seconds


async def abandon_inactive_participants(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[uuid.UUID]:
    """Find and abandon inactive participants in running races.

    Covers two cases:
    - PLAYING participants whose IGT hasn't changed in INACTIVITY_TIMEOUT
    - REGISTERED/READY participants who never connected after race started

    Returns list of race IDs that had abandonments (for broadcasting).
    """
    cutoff = datetime.now(UTC) - INACTIVITY_TIMEOUT
    affected_race_ids: list[uuid.UUID] = []

    async with session_maker() as db:
        result = await db.execute(
            select(Participant)
            .join(Race)
            .where(
                Race.status == RaceStatus.RUNNING,
                or_(
                    # PLAYING with stale IGT
                    (Participant.status == ParticipantStatus.PLAYING)
                    & Participant.last_igt_change_at.isnot(None)
                    & (Participant.last_igt_change_at < cutoff),
                    # Never connected (still REGISTERED/READY after race started)
                    Participant.status.in_([ParticipantStatus.REGISTERED, ParticipantStatus.READY])
                    & Race.started_at.isnot(None)
                    & (Race.started_at < cutoff),
                ),
            )
            .options(selectinload(Participant.race).selectinload(Race.participants))
        )
        stale_participants = result.scalars().unique().all()

        for p in stale_participants:
            reason = (
                f"last IGT change: {p.last_igt_change_at}"
                if p.status == ParticipantStatus.PLAYING
                else f"no-show after race start (status: {p.status.value})"
            )
            logger.info("Auto-abandoning participant %s (%s)", p.id, reason)
            p.status = ParticipantStatus.ABANDONED
            if p.race_id not in affected_race_ids:
                affected_race_ids.append(p.race_id)

        if stale_participants:
            await db.commit()

    # Check auto-finish for each affected race
    for race_id in list(affected_race_ids):
        async with session_maker() as db:
            race_query = (
                select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
            )
            race_result = await db.execute(race_query)
            race_obj = race_result.scalar_one_or_none()
            if isinstance(race_obj, Race) and race_obj.status == RaceStatus.RUNNING:
                await check_race_auto_finish(db, race_obj)

    return affected_race_ids


async def inactivity_monitor_loop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodic loop that checks for inactive participants."""
    logger.info(
        "Inactivity monitor started (timeout=%s, poll=%ds)",
        INACTIVITY_TIMEOUT,
        POLL_INTERVAL,
    )
    while True:
        try:
            affected = await abandon_inactive_participants(session_maker)
            if affected:
                from speedfog_racing.websocket.manager import manager
                from speedfog_racing.websocket.spectator import broadcast_race_state_update

                for race_id in affected:
                    async with session_maker() as db:
                        result = await db.execute(
                            select(Race)
                            .where(Race.id == race_id)
                            .options(
                                selectinload(Race.participants).selectinload(Participant.user),
                                selectinload(Race.casters),
                                selectinload(Race.seed),
                            )
                        )
                        race = result.scalar_one_or_none()
                        if race:
                            graph_json = race.seed.graph_json if race.seed else None
                            await manager.broadcast_leaderboard(
                                race_id, race.participants, graph_json=graph_json
                            )
                            await broadcast_race_state_update(race_id, race)
                            if race.status == RaceStatus.FINISHED:
                                await manager.broadcast_race_status(race_id, "finished")
                                fire_race_finished_notifications(race)
        except Exception:
            logger.exception("Inactivity monitor error")

        await asyncio.sleep(POLL_INTERVAL)
