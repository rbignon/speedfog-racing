"""Twitch live status polling service."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_app_access_token
from speedfog_racing.config import settings
from speedfog_racing.models import Caster, Participant, Race, RaceStatus

if TYPE_CHECKING:
    from speedfog_racing.websocket.manager import ConnectionManager

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

    async def _collect_race_usernames(
        self, session: AsyncSession
    ) -> tuple[list[str], dict[uuid.UUID, set[str]]]:
        """Collect twitch_usernames from active races.

        Returns (all_usernames, {race_id: {usernames}}) for broadcast targeting.
        """
        result = await session.execute(
            select(Race)
            .where(Race.status.in_([RaceStatus.SETUP, RaceStatus.RUNNING]))
            .options(
                selectinload(Race.participants).selectinload(Participant.user),
                selectinload(Race.casters).selectinload(Caster.user),
            )
        )
        races = result.scalars().all()

        all_usernames: set[str] = set()
        race_usernames: dict[uuid.UUID, set[str]] = {}
        for race in races:
            names: set[str] = set()
            for p in race.participants:
                name = p.user.twitch_username.lower()
                names.add(name)
                all_usernames.add(name)
            for c in race.casters:
                name = c.user.twitch_username.lower()
                names.add(name)
                all_usernames.add(name)
            race_usernames[race.id] = names

        return sorted(all_usernames), race_usernames

    async def poll_once(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        ws_manager: ConnectionManager | None = None,
    ) -> None:
        """Run one polling cycle: collect usernames, check Twitch, update state.

        If ws_manager is provided and live statuses changed, broadcasts
        leaderboard_update to affected races.
        """
        async with session_maker() as session:
            all_usernames, race_usernames = await self._collect_race_usernames(session)

        if not all_usernames:
            self.live_usernames = set()
            return

        new_live = await self.check_live_status(all_usernames)
        old_live = self.live_usernames
        self.live_usernames = new_live

        # Broadcast to affected races if live status changed
        changed = (new_live - old_live) | (old_live - new_live)
        if changed and ws_manager:
            affected_race_ids = [
                race_id for race_id, names in race_usernames.items() if names & changed
            ]
            if affected_race_ids:
                await self._broadcast_live_changes(session_maker, ws_manager, affected_race_ids)

    async def _broadcast_live_changes(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        ws_manager: ConnectionManager,
        race_ids: list[uuid.UUID],
    ) -> None:
        """Broadcast leaderboard_update to races affected by live status changes."""
        async with session_maker() as session:
            result = await session.execute(
                select(Race)
                .where(Race.id.in_(race_ids))
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.seed),
                )
            )
            races = list(result.scalars().all())

        for race in races:
            graph = race.seed.graph_json if race.seed else None
            try:
                await ws_manager.broadcast_leaderboard(
                    race.id, list(race.participants), graph_json=graph
                )
            except Exception:
                logger.exception("Failed to broadcast live change for race %s", race.id)

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


async def twitch_live_poll_loop(
    session_maker: async_sessionmaker[AsyncSession],
    ws_manager: ConnectionManager | None = None,
) -> None:
    """Background loop that polls Twitch every POLL_INTERVAL seconds."""
    logger.info("Twitch live polling started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            await twitch_live_service.poll_once(session_maker, ws_manager=ws_manager)
            live_count = len(twitch_live_service.live_usernames)
            if live_count > 0:
                logger.debug("Twitch live: %d users online", live_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Twitch live poll error")
        await asyncio.sleep(POLL_INTERVAL)
