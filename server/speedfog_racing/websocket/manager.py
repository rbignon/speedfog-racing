"""WebSocket connection manager for race rooms."""

import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from speedfog_racing.models import Participant
from speedfog_racing.websocket.schemas import (
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PlayerUpdateMessage,
    RaceStatusChangeMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class ModConnection:
    """A connected mod client."""

    websocket: WebSocket
    participant_id: uuid.UUID
    user_id: uuid.UUID


@dataclass
class SpectatorConnection:
    """A connected spectator client."""

    websocket: WebSocket
    user_id: uuid.UUID | None = None
    dag_access: bool = False


@dataclass
class RaceRoom:
    """A room for a specific race with mod and spectator connections."""

    race_id: uuid.UUID
    # participant_id -> connection
    mods: dict[uuid.UUID, ModConnection] = field(default_factory=dict)
    spectators: list[SpectatorConnection] = field(default_factory=list)

    async def broadcast_to_mods(self, message: str) -> None:
        """Send message to all connected mods."""
        disconnected = []
        for participant_id, conn in self.mods.items():
            try:
                await conn.websocket.send_text(message)
            except Exception:
                disconnected.append(participant_id)

        for participant_id in disconnected:
            self.mods.pop(participant_id, None)

    async def broadcast_to_spectators(self, message: str) -> None:
        """Send message to all connected spectators."""
        disconnected = []
        for i, conn in enumerate(self.spectators):
            try:
                await conn.websocket.send_text(message)
            except Exception:
                disconnected.append(i)

        for i in reversed(disconnected):
            self.spectators.pop(i)

    async def broadcast_to_all(self, message: str) -> None:
        """Send message to all connections (mods + spectators)."""
        await self.broadcast_to_mods(message)
        await self.broadcast_to_spectators(message)


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
    ) -> None:
        """Register a mod connection."""
        room = self.get_or_create_room(race_id)
        room.mods[participant_id] = ModConnection(
            websocket=websocket,
            participant_id=participant_id,
            user_id=user_id,
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

    async def disconnect_spectator(self, race_id: uuid.UUID, conn: SpectatorConnection) -> None:
        """Remove a spectator connection."""
        room = self.get_room(race_id)
        if room:
            try:
                room.spectators.remove(conn)
            except ValueError:
                pass
            logger.info(f"Spectator disconnected: race={race_id}")
            if not room.mods and not room.spectators:
                self.rooms.pop(race_id, None)

    def is_mod_connected(self, race_id: uuid.UUID, participant_id: uuid.UUID) -> bool:
        """Check if a mod is connected."""
        room = self.get_room(race_id)
        return room is not None and participant_id in room.mods

    async def broadcast_leaderboard(
        self, race_id: uuid.UUID, participants: list[Participant]
    ) -> None:
        """Broadcast leaderboard update to all connections in a room."""
        room = self.get_room(race_id)
        if not room:
            return

        sorted_participants = sort_leaderboard(participants)
        participant_infos = [participant_to_info(p) for p in sorted_participants]

        message = LeaderboardUpdateMessage(participants=participant_infos)
        await room.broadcast_to_all(message.model_dump_json())

    async def broadcast_player_update(self, race_id: uuid.UUID, participant: Participant) -> None:
        """Broadcast a single player update to spectators."""
        room = self.get_room(race_id)
        if not room:
            return

        message = PlayerUpdateMessage(player=participant_to_info(participant))
        await room.broadcast_to_spectators(message.model_dump_json())

    async def broadcast_race_status(self, race_id: uuid.UUID, status: str) -> None:
        """Broadcast race status change to all connections."""
        room = self.get_room(race_id)
        if not room:
            return

        message = RaceStatusChangeMessage(status=status)
        await room.broadcast_to_all(message.model_dump_json())


def participant_to_info(
    participant: Participant, *, include_history: bool = False
) -> ParticipantInfo:
    """Convert a Participant model to ParticipantInfo schema."""
    return ParticipantInfo(
        id=str(participant.id),
        twitch_username=participant.user.twitch_username,
        twitch_display_name=participant.user.twitch_display_name,
        status=participant.status.value,
        current_zone=participant.current_zone,
        current_layer=participant.current_layer,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
        color_index=participant.color_index,
        zone_history=participant.zone_history if include_history else None,
    )


def sort_leaderboard(participants: list[Participant]) -> list[Participant]:
    """Sort participants for leaderboard display.

    Priority:
    1. Finished players first, sorted by IGT (lowest first)
    2. Playing players by layer (highest first), then IGT (lowest first)
    3. Ready players
    4. Registered players
    5. Abandoned players last
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
        elif status == "playing":
            return (priority, -p.current_layer, p.igt_ms)
        else:
            return (priority, 0, 0)

    return sorted(participants, key=sort_key)


# Global connection manager instance
manager = ConnectionManager()
