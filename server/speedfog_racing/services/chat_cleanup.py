"""Background task to clean up old chat messages."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from speedfog_racing.models import ChatMessage, Race, RaceStatus

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
RETENTION_HOURS = 24


async def cleanup_old_chat_messages(session_maker: async_sessionmaker[AsyncSession]) -> int:
    """Delete chat messages from races finished more than RETENTION_HOURS ago.

    Returns the number of deleted messages.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=RETENTION_HOURS)

    async with session_maker() as db:
        finished_race_ids = await db.execute(
            select(Race.id).where(
                Race.status == RaceStatus.FINISHED,
                Race.finished_at.is_not(None),
                Race.finished_at < cutoff,
            )
        )
        race_ids = [row[0] for row in finished_race_ids.fetchall()]

        if not race_ids:
            return 0

        result = await db.execute(delete(ChatMessage).where(ChatMessage.race_id.in_(race_ids)))
        count: int = result.rowcount  # type: ignore[attr-defined]
        await db.commit()

    return count


async def chat_cleanup_loop(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Periodically clean up old chat messages."""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            count = await cleanup_old_chat_messages(session_maker)
            if count > 0:
                logger.info("Cleaned up %d old chat messages", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in chat cleanup loop")
