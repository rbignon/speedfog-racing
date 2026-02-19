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


@dataclass
class TrainingSpectatorConnection:
    websocket: WebSocket
    user_id: uuid.UUID


@dataclass
class TrainingRoom:
    """A training session room with at most one mod and multiple spectators."""

    session_id: uuid.UUID
    mod: TrainingModConnection | None = None
    spectators: list[TrainingSpectatorConnection] = field(default_factory=list)

    async def broadcast_to_spectators(self, message: str) -> None:
        """Send message to all connected spectators concurrently with timeout."""
        if not self.spectators:
            return

        snapshot = list(self.spectators)

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
                try:
                    self.spectators.remove(conn)
                except ValueError:
                    pass  # Already removed by disconnect handler

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
    ) -> None:
        room = self.get_or_create_room(session_id)
        room.mod = TrainingModConnection(websocket=websocket, user_id=user_id)
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
        room.spectators.append(TrainingSpectatorConnection(websocket=websocket, user_id=user_id))
        logger.info(f"Spectator connected to training session {session_id}")

    async def disconnect_spectator(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if room:
            # Remove matching connection by websocket identity
            for conn in room.spectators:
                if conn.websocket is websocket:
                    try:
                        room.spectators.remove(conn)
                    except ValueError:
                        pass
                    logger.info(f"Spectator disconnected from training session {session_id}")
                    break
            if room.mod is None and not room.spectators:
                del self.rooms[session_id]

    def is_mod_connected(self, session_id: uuid.UUID) -> bool:
        room = self.rooms.get(session_id)
        return room is not None and room.mod is not None


training_manager = TrainingConnectionManager()
