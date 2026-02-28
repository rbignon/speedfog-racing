"""Twitch live status polling service."""

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_app_access_token
from speedfog_racing.config import settings
from speedfog_racing.models import Caster, Participant, Race, RaceStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
BATCH_SIZE = 100  # Twitch API max per request


class TwitchLiveService:
    """Polls Twitch Helix API to detect live streams among race participants/casters."""

    def __init__(self) -> None:
        self.live_usernames: set[str] = set()

    async def check_live_status(self, usernames: list[str]) -> set[str]:
        """Query Twitch API for which usernames are currently live.

        Returns set of live usernames (lowercase).
        """
        if not usernames:
            return set()

        live: set[str] = set()
        token = await get_app_access_token()

        async with httpx.AsyncClient() as client:
            for i in range(0, len(usernames), BATCH_SIZE):
                batch = usernames[i : i + BATCH_SIZE]
                params = tuple(("user_login", name) for name in batch)
                try:
                    resp = await client.get(
                        "https://api.twitch.tv/helix/streams",
                        params=params,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Client-Id": settings.twitch_client_id,
                        },
                    )
                    if resp.status_code == 200:
                        for stream in resp.json().get("data", []):
                            if stream.get("type") == "live":
                                live.add(stream["user_login"].lower())
                    else:
                        logger.warning("Twitch streams API returned %d", resp.status_code)
                except Exception:
                    logger.exception("Failed to query Twitch streams API")

        return live

    async def _collect_usernames(self, session: AsyncSession) -> list[str]:
        """Collect all unique twitch_usernames from active races."""
        result = await session.execute(
            select(Race)
            .where(Race.status.in_([RaceStatus.SETUP, RaceStatus.RUNNING]))
            .options(
                selectinload(Race.participants).selectinload(Participant.user),
                selectinload(Race.casters).selectinload(Caster.user),
            )
        )
        races = result.scalars().all()

        usernames: set[str] = set()
        for race in races:
            for p in race.participants:
                usernames.add(p.user.twitch_username.lower())
            for c in race.casters:
                usernames.add(c.user.twitch_username.lower())

        return sorted(usernames)

    async def poll_once(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        """Run one polling cycle: collect usernames, check Twitch, update state."""
        async with session_maker() as session:
            usernames = await self._collect_usernames(session)

        if not usernames:
            self.live_usernames = set()
            return

        new_live = await self.check_live_status(usernames)
        self.live_usernames = new_live

    def is_live(self, twitch_username: str) -> bool:
        """Check if a username is currently live."""
        return twitch_username.lower() in self.live_usernames

    def stream_url(self, twitch_username: str) -> str | None:
        """Return stream URL if user is live, else None."""
        if self.is_live(twitch_username):
            return f"https://twitch.tv/{twitch_username}"
        return None


# Module-level singleton
twitch_live_service = TwitchLiveService()


async def twitch_live_poll_loop(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Background loop that polls Twitch every POLL_INTERVAL seconds."""
    logger.info("Twitch live polling started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            await twitch_live_service.poll_once(session_maker)
            live_count = len(twitch_live_service.live_usernames)
            if live_count > 0:
                logger.debug("Twitch live: %d users online", live_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Twitch live poll error")
        await asyncio.sleep(POLL_INTERVAL)
