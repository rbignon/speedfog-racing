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
    asyncio.create_task(recompute_traits_for_race_async(race.id))

    return True
