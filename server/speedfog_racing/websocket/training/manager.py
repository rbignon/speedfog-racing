"""Connection management for training sessions."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

SEND_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


@dataclass
class TrainingModConnection:
    websocket: WebSocket
    user_id: uuid.UUID
    mod_version: str | None = None


@dataclass
class TrainingSpectatorConnection:
    websocket: WebSocket
    user_id: uuid.UUID
    # Unique id for O(1) removal from TrainingRoom.spectators dict.
    connection_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class TrainingRoom:
    """A training session room with at most one mod and multiple spectators."""

    session_id: uuid.UUID
    mod: TrainingModConnection | None = None
    # connection_id -> connection (dict for O(1) removal during broadcasts)
    spectators: dict[uuid.UUID, TrainingSpectatorConnection] = field(default_factory=dict)

    async def broadcast_to_spectators(self, message: str) -> None:
        """Send message to all connected spectators concurrently with timeout."""
        if not self.spectators:
            return

        snapshot = list(self.spectators.values())

        async def _send(
            conn: TrainingSpectatorConnection,
        ) -> TrainingSpectatorConnection | None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                return conn
            return None

        results = await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in results:
            if conn is not None:
                self.spectators.pop(conn.connection_id, None)

    async def broadcast_to_mod(self, message: str) -> None:
        """Send message to mod if connected."""
        conn = self.mod
        if conn is None:
            return
        try:
            await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
        except Exception:
            logger.warning(f"Failed to send to mod for session {self.session_id}")
            try:
                await conn.websocket.close()
            except Exception:
                pass
            # Only clear if still the current connection (may have been replaced)
            if self.mod is conn:
                self.mod = None

    async def broadcast_to_all(self, message: str) -> None:
        """Send message to mod and all spectators."""
        await asyncio.gather(
            self.broadcast_to_mod(message),
            self.broadcast_to_spectators(message),
        )


class TrainingConnectionManager:
    """Manages training session WebSocket connections."""

    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, TrainingRoom] = {}

    def get_or_create_room(self, session_id: uuid.UUID) -> TrainingRoom:
        if session_id not in self.rooms:
            self.rooms[session_id] = TrainingRoom(session_id=session_id)
        return self.rooms[session_id]

    def get_room(self, session_id: uuid.UUID) -> TrainingRoom | None:
        return self.rooms.get(session_id)

    async def connect_mod(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
        mod_version: str | None = None,
    ) -> None:
        """Register a mod connection, replacing any existing one.

        If a previous connection exists (likely a ghost after a network drop),
        it is closed with code 4000 so the old handler's receive loop exits.
        """
        room = self.get_or_create_room(session_id)
        existing = room.mod
        room.mod = TrainingModConnection(
            websocket=websocket, user_id=user_id, mod_version=mod_version
        )
        if existing is not None:
            logger.info(f"Mod replaced for training session {session_id}")
            try:
                await existing.websocket.close(code=4000, reason="replaced by new connection")
            except Exception:
                logger.debug(
                    "Failed to close replaced training mod connection: session=%s",
                    session_id,
                )
        else:
            logger.info(f"Mod connected to training session {session_id}")

    async def disconnect_mod(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if room:
            # Only remove if the disconnecting websocket is the current one
            # (a new mod may have already replaced it via connect_mod)
            if room.mod is not None and room.mod.websocket is websocket:
                room.mod = None
                logger.info(f"Mod disconnected from training session {session_id}")
            else:
                logger.debug(f"Stale mod disconnect ignored for training session {session_id}")
            if room.mod is None and not room.spectators:
                del self.rooms[session_id]

    async def connect_spectator(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
    ) -> None:
        room = self.get_or_create_room(session_id)
        conn = TrainingSpectatorConnection(websocket=websocket, user_id=user_id)
        room.spectators[conn.connection_id] = conn
        logger.info(f"Spectator connected to training session {session_id}")

    async def disconnect_spectator(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if room:
            # Find matching connection by websocket identity, then O(1) pop.
            # Training sessions have few spectators, so the linear scan is fine.
            for conn in list(room.spectators.values()):
                if conn.websocket is websocket:
                    room.spectators.pop(conn.connection_id, None)
                    logger.info(f"Spectator disconnected from training session {session_id}")
                    break
            if room.mod is None and not room.spectators:
                del self.rooms[session_id]

    def is_mod_connected(self, session_id: uuid.UUID) -> bool:
        room = self.rooms.get(session_id)
        return room is not None and room.mod is not None

    def get_mod_version(self, session_id: uuid.UUID) -> str | None:
        """Release version reported by the connected mod, if any."""
        room = self.rooms.get(session_id)
        return room.mod.mod_version if room and room.mod else None


training_manager = TrainingConnectionManager()
