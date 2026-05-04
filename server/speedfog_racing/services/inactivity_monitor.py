"""Background task to auto-abandon inactive or no-show participants."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.discord import fire_race_finished_notifications
from speedfog_racing.models import ChatChannel, Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.websocket.schemas import persist_system_chat

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = timedelta(minutes=30)
POLL_INTERVAL = 60  # seconds


async def abandon_inactive_participants(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[list[uuid.UUID], set[uuid.UUID]]:
    """Find and abandon inactive participants in running races.

    Two branches:
    - PLAYING with stale IGT (older than INACTIVITY_TIMEOUT).
    - No-show REGISTERED/READY: gated on race_duration_minutes IS NULL
      (hard-close handles sweeping otherwise). Cutoff is per-participant
      via ``max(Race.started_at, Participant.created_at) < cutoff``,
      expressed as two ANDed conditions, so neither a late-joiner nor an
      early registrant gets abandoned spuriously at race start.

    Returns (race_ids with abandonments, participant_ids that were just
    abandoned). Caller is responsible for the auto-finish check and
    broadcasts.
    """
    cutoff = datetime.now(UTC) - INACTIVITY_TIMEOUT
    affected_race_ids: list[uuid.UUID] = []
    abandoned_participant_ids: set[uuid.UUID] = set()

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
                    # Never connected (still REGISTERED/READY after race started).
                    # Skipped when race_duration_minutes is set: hard_close_loop
                    # will move non-terminal participants to ABANDONED at the
                    # deadline via finalize_race.
                    Participant.status.in_([ParticipantStatus.REGISTERED, ParticipantStatus.READY])
                    & Race.race_duration_minutes.is_(None)
                    & Race.started_at.isnot(None)
                    & (Race.started_at < cutoff)
                    & (Participant.created_at < cutoff),
                ),
            )
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
            abandoned_participant_ids.add(p.id)
            if p.race_id not in affected_race_ids:
                affected_race_ids.append(p.race_id)

        if stale_participants:
            await db.commit()

    return affected_race_ids, abandoned_participant_ids


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
            affected, abandoned_ids = await abandon_inactive_participants(session_maker)
            if affected:
                from speedfog_racing.websocket.race.manager import manager
                from speedfog_racing.websocket.race.spectator import broadcast_race_state_update

                for race_id in affected:
                    # One session per affected race: load Race with the full
                    # option chain (participants+users, casters, seed), run
                    # the auto-finish check, then broadcast.
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
                        if race is None:
                            continue

                        if race.status == RaceStatus.RUNNING:
                            await check_race_auto_finish(db, race)

                        room = manager.get_room(race_id)
                        if room:
                            for p in race.participants:
                                if p.status == ParticipantStatus.ABANDONED:
                                    room.set_participant_status(
                                        p.user_id, ParticipantStatus.ABANDONED
                                    )

                        # Persist "abandoned due to inactivity" messages for
                        # newly abandoned participants (persist unconditionally
                        # so history replays on reconnect; broadcast only if a
                        # room exists).
                        abandon_messages: list[str] = []
                        for p in race.participants:
                            if p.id in abandoned_ids:
                                display = p.user.twitch_display_name or p.user.twitch_username
                                abandon_msg = (
                                    f"{display} abandoned the daily seed due to inactivity."
                                    if race.daily_date is not None
                                    else f"{display} has abandoned the race due to inactivity."
                                )
                                sys_json = await persist_system_chat(
                                    db,
                                    race_id,
                                    ChatChannel.PUBLIC,
                                    abandon_msg,
                                )
                                abandon_messages.append(sys_json)

                        finish_public_json: str | None = None
                        if race.status == RaceStatus.FINISHED:
                            finished_msg = (
                                "The daily seed is over."
                                if race.daily_date is not None
                                else "The race has finished."
                            )
                            finish_public_json = await persist_system_chat(
                                db, race_id, ChatChannel.PUBLIC, finished_msg
                            )
                        await db.commit()

                        if room:
                            for sys_json in abandon_messages:
                                await room.broadcast_chat_public(sys_json, race)

                        graph_json = race.seed.graph_json if race.seed else None
                        await manager.broadcast_leaderboard(
                            race_id, race.participants, graph_json=graph_json
                        )
                        await broadcast_race_state_update(race_id, race)
                        if race.status == RaceStatus.FINISHED:
                            await manager.broadcast_race_status(race_id, "finished")
                            if room and finish_public_json is not None:
                                await room.broadcast_chat_public(finish_public_json, race)
                            fire_race_finished_notifications(race)
        except Exception:
            logger.exception("Inactivity monitor error")

        await asyncio.sleep(POLL_INTERVAL)
