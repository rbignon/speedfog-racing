"""Race lifecycle helpers (auto-finish, abandon)."""

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import ParticipantStatus, Race, RaceStatus

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

    result = await db.execute(
        update(Race)
        .where(
            Race.id == race.id,
            Race.status == RaceStatus.RUNNING,
            Race.version == race.version,
        )
        .values(status=RaceStatus.FINISHED, version=race.version + 1)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        logger.warning("Race %s already transitioned (concurrent update)", race.id)
        await db.commit()
        return False

    race.status = RaceStatus.FINISHED
    race.version += 1
    await db.commit()
    return True
