"""WebSocket connection manager for race rooms."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from speedfog_racing.models import Participant
from speedfog_racing.services.layer_service import get_tier_for_node
from speedfog_racing.websocket.schemas import (
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PlayerUpdateMessage,
    RaceStatusChangeMessage,
    SpectatorCountMessage,
)

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5.0  # seconds before a send is considered failed


@dataclass
class ModConnection:
    """A connected mod client."""

    websocket: WebSocket
    participant_id: uuid.UUID
    user_id: uuid.UUID
    locale: str = "en"


@dataclass
class SpectatorConnection:
    """A connected spectator client."""

    websocket: WebSocket
    user_id: uuid.UUID | None = None
    locale: str = "en"


@dataclass
class RaceRoom:
    """A room for a specific race with mod and spectator connections."""

    race_id: uuid.UUID
    # participant_id -> connection
    mods: dict[uuid.UUID, ModConnection] = field(default_factory=dict)
    spectators: list[SpectatorConnection] = field(default_factory=list)

    async def broadcast_to_mods(self, message: str) -> None:
        """Send message to all connected mods concurrently with timeout."""
        if not self.mods:
            return

        # Snapshot to avoid issues with concurrent dict modification
        snapshot = dict(self.mods)

        async def _send(participant_id: uuid.UUID, conn: ModConnection) -> uuid.UUID | None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                return participant_id
            return None

        results = await asyncio.gather(*(_send(pid, conn) for pid, conn in snapshot.items()))
        for pid in results:
            if pid is not None:
                self.mods.pop(pid, None)

    async def broadcast_to_spectators(self, message: str) -> None:
        """Send message to all connected spectators concurrently with timeout."""
        if not self.spectators:
            return

        # Snapshot to avoid issues with concurrent list modification.
        # During the gather, connect_spectator/disconnect_spectator can
        # modify self.spectators; index-based removal would then pop the
        # wrong connection, silently orphaning innocent spectators.
        snapshot = list(self.spectators)

        async def _send(conn: SpectatorConnection) -> SpectatorConnection | None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                return conn
            return None

        results = await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in results:
            if conn is not None:
                try:
                    self.spectators.remove(conn)
                except ValueError:
                    pass  # Already removed by disconnect handler

    async def broadcast_to_all(self, message: str) -> None:
        """Send message to all connections (mods + spectators) concurrently."""
        await asyncio.gather(
            self.broadcast_to_mods(message),
            self.broadcast_to_spectators(message),
        )


class ConnectionManager:
    """Manages all WebSocket connections across races."""

    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, RaceRoom] = {}

    def get_or_create_room(self, race_id: uuid.UUID) -> RaceRoom:
        """Get or create a room for a race."""
        if race_id not in self.rooms:
            self.rooms[race_id] = RaceRoom(race_id=race_id)
        return self.rooms[race_id]

    def get_room(self, race_id: uuid.UUID) -> RaceRoom | None:
        """Get a room if it exists."""
        return self.rooms.get(race_id)

    async def connect_mod(
        self,
        race_id: uuid.UUID,
        participant_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
        locale: str = "en",
    ) -> None:
        """Register a mod connection."""
        room = self.get_or_create_room(race_id)
        room.mods[participant_id] = ModConnection(
            websocket=websocket,
            participant_id=participant_id,
            user_id=user_id,
            locale=locale,
        )
        logger.info(f"Mod connected: race={race_id}, participant={participant_id}")

    async def disconnect_mod(self, race_id: uuid.UUID, participant_id: uuid.UUID) -> None:
        """Remove a mod connection."""
        room = self.get_room(race_id)
        if room:
            room.mods.pop(participant_id, None)
            logger.info(f"Mod disconnected: race={race_id}, participant={participant_id}")
            if not room.mods and not room.spectators:
                self.rooms.pop(race_id, None)

    async def connect_spectator(self, race_id: uuid.UUID, conn: SpectatorConnection) -> None:
        """Register a spectator connection."""
        room = self.get_or_create_room(race_id)
        room.spectators.append(conn)
        logger.info(f"Spectator connected: race={race_id}")
        await self._broadcast_spectator_count(room)

    async def disconnect_spectator(self, race_id: uuid.UUID, conn: SpectatorConnection) -> None:
        """Remove a spectator connection."""
        room = self.get_room(race_id)
        if room:
            try:
                room.spectators.remove(conn)
            except ValueError:
                pass
            logger.info(f"Spectator disconnected: race={race_id}")
            await self._broadcast_spectator_count(room)
            if not room.mods and not room.spectators:
                self.rooms.pop(race_id, None)

    async def close_room(self, race_id: uuid.UUID, code: int = 1000, reason: str = "") -> None:
        """Close all WebSocket connections in a room and remove it."""
        room = self.rooms.pop(race_id, None)
        if not room:
            return

        for mod_conn in room.mods.values():
            try:
                await mod_conn.websocket.close(code=code, reason=reason)
            except Exception:
                pass

        for spec_conn in room.spectators:
            try:
                await spec_conn.websocket.close(code=code, reason=reason)
            except Exception:
                pass

        logger.info(f"Closed room: race={race_id}")

    def is_mod_connected(self, race_id: uuid.UUID, participant_id: uuid.UUID) -> bool:
        """Check if a mod is connected."""
        room = self.get_room(race_id)
        return room is not None and participant_id in room.mods

    async def broadcast_leaderboard(
        self,
        race_id: uuid.UUID,
        participants: list[Participant],
        *,
        graph_json: dict[str, Any] | None = None,
    ) -> None:
        """Broadcast leaderboard update to all connections in a room."""
        room = self.get_room(race_id)
        if not room:
            return

        sorted_participants = sort_leaderboard(participants)
        connected_ids = set(room.mods.keys())
        participant_infos = [
            participant_to_info(
                p,
                connected_ids=connected_ids,
                graph_json=graph_json,
            )
            for p in sorted_participants
        ]

        message = LeaderboardUpdateMessage(participants=participant_infos)
        await room.broadcast_to_all(message.model_dump_json())

    async def broadcast_player_update(
        self,
        race_id: uuid.UUID,
        participant: Participant,
        *,
        graph_json: dict[str, Any] | None = None,
    ) -> None:
        """Broadcast a single player update to spectators."""
        room = self.get_room(race_id)
        if not room:
            return

        connected_ids = set(room.mods.keys())
        message = PlayerUpdateMessage(
            player=participant_to_info(
                participant, connected_ids=connected_ids, graph_json=graph_json
            )
        )
        await room.broadcast_to_spectators(message.model_dump_json())

    async def _broadcast_spectator_count(self, room: RaceRoom) -> None:
        """Broadcast spectator count to all spectators in a room."""
        msg = SpectatorCountMessage(count=len(room.spectators))
        await room.broadcast_to_spectators(msg.model_dump_json())

    async def broadcast_race_status(
        self,
        race_id: uuid.UUID,
        status: str,
        started_at: str | None = None,
    ) -> None:
        """Broadcast race status change to all connections."""
        room = self.get_room(race_id)
        if not room:
            return

        message = RaceStatusChangeMessage(status=status, started_at=started_at)
        await room.broadcast_to_all(message.model_dump_json())


def participant_to_info(
    participant: Participant,
    *,
    connected_ids: set[uuid.UUID] | None = None,
    graph_json: dict[str, Any] | None = None,
) -> ParticipantInfo:
    """Convert a Participant model to ParticipantInfo schema."""
    # Compute tier on the fly from current_zone + graph_json
    tier: int | None = None
    if graph_json and participant.current_zone:
        tier = get_tier_for_node(participant.current_zone, graph_json)

    return ParticipantInfo(
        id=str(participant.id),
        twitch_username=participant.user.twitch_username,
        twitch_display_name=participant.user.twitch_display_name,
        status=participant.status.value,
        current_zone=participant.current_zone,
        current_layer=participant.current_layer,
        current_layer_tier=tier,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
        color_index=participant.color_index,
        mod_connected=participant.id in connected_ids if connected_ids else False,
        zone_history=participant.zone_history,
    )


def sort_leaderboard(participants: list[Participant]) -> list[Participant]:
    """Sort participants for leaderboard display.

    Priority:
    1. Finished players first, sorted by IGT (lowest first)
    2. Playing players by layer (highest first), then IGT (lowest first)
    3. Ready players
    4. Registered players
    5. Abandoned (DNF) players last, sorted by layer (highest first), then IGT (lowest first)
    """
    status_priority = {
        "finished": 0,
        "playing": 1,
        "ready": 2,
        "registered": 3,
        "abandoned": 4,
    }

    def sort_key(p: Participant) -> tuple[int, int, int]:
        status = p.status.value
        priority = status_priority.get(status, 99)

        if status == "finished":
            return (priority, p.igt_ms, 0)
        elif status in ("playing", "abandoned"):
            return (priority, -p.current_layer, p.igt_ms)
        else:
            return (priority, 0, 0)

    return sorted(participants, key=sort_key)


# Global connection manager instance
manager = ConnectionManager()
