"""Race lifecycle helpers (auto-finish, abandon)."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.stats_service import (
    recompute_traits_for_race_async,
    update_elo_ratings,
)

logger = logging.getLogger(__name__)


async def check_race_auto_finish(db: AsyncSession, race: Race) -> bool:
    """Transition race to FINISHED if all participants are FINISHED or ABANDONED.

    Uses optimistic locking (version column) to handle concurrent updates.
    Returns True if the race was transitioned.

    Requires: race.participants must be eagerly loaded.
    """
    all_done = all(
        p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
        for p in race.participants
    )
    if not all_done:
        return False

    now = datetime.now(UTC)
    result = await db.execute(
        update(Race)
        .where(
            Race.id == race.id,
            Race.status == RaceStatus.RUNNING,
            Race.version == race.version,
        )
        .values(status=RaceStatus.FINISHED, version=race.version + 1, finished_at=now)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        logger.warning("Race %s already transitioned (concurrent update)", race.id)
        await db.commit()
        return False

    race.status = RaceStatus.FINISHED
    race.version += 1
    race.finished_at = now
    await db.commit()

    logger.info("Race %s auto-finished (all participants done)", race.id)

    await update_elo_ratings(race.id, db)
    # Trait recomputation rescans each finisher's full race history, so
    # run it in the background to keep the request/tick responsive.
    task = asyncio.create_task(recompute_traits_for_race_async(race.id))
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    return True


async def finalize_race(
    db: AsyncSession,
    race: Race,
    *,
    forced: bool = False,
) -> None:
    """End-of-race pipeline shared by manual force-finish and hard-close loop.

    Caller must have loaded race with participants and casters, and must have
    already transitioned race.status to FINISHED (with finished_at set) and
    committed the transition.

    finalize_race then:
    - marks remaining PLAYING participants as ABANDONED
    - posts the public chat "race has finished" message
    - clears is_playing on spectator connections
    - triggers ELO update and trait recomputation (background)
    - broadcasts race_state + race_status + chat
    - fires Discord notifications
    """
    import asyncio as _asyncio

    from speedfog_racing.discord import fire_race_finished_notifications
    from speedfog_racing.models import ChatChannel, ParticipantStatus, RaceStatus
    from speedfog_racing.services.stats_service import (
        recompute_traits_for_race_async,
        update_elo_ratings,
    )
    from speedfog_racing.websocket.race.manager import manager
    from speedfog_racing.websocket.race.spectator import broadcast_race_state_update
    from speedfog_racing.websocket.schemas import persist_system_chat

    assert race.status == RaceStatus.FINISHED, "finalize_race: race must be FINISHED already"

    for p in race.participants:
        if p.status == ParticipantStatus.PLAYING:
            p.status = ParticipantStatus.ABANDONED

    finished_public_json = await persist_system_chat(
        db, race.id, ChatChannel.PUBLIC, "The race has finished."
    )
    await db.commit()

    room = manager.get_room(race.id)
    if room:
        room.clear_all_playing()

    await update_elo_ratings(race.id, db)

    task = _asyncio.create_task(recompute_traits_for_race_async(race.id))
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    await broadcast_race_state_update(race.id, race)
    await manager.broadcast_race_status(race.id, "finished")
    if room:
        await room.broadcast_chat_public(finished_public_json)

    fire_race_finished_notifications(race, forced=forced)
