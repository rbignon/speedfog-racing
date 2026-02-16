"""Connection management for training sessions."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

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
    """A training session room with at most one mod and one spectator."""

    session_id: uuid.UUID
    mod: TrainingModConnection | None = None
    spectator: TrainingSpectatorConnection | None = None

    async def broadcast_to_spectator(self, message: str) -> None:
        """Send message to spectator if connected."""
        conn = self.spectator
        if conn is None:
            return
        try:
            await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
        except Exception:
            logger.warning(f"Failed to send to spectator for session {self.session_id}")
            try:
                await conn.websocket.close()
            except Exception:
                pass
            # Only clear if still the current connection (may have been replaced)
            if self.spectator is conn:
                self.spectator = None

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
        """Send message to both mod and spectator."""
        await asyncio.gather(
            self.broadcast_to_mod(message),
            self.broadcast_to_spectator(message),
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
            if room.mod is None and room.spectator is None:
                del self.rooms[session_id]

    async def connect_spectator(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
    ) -> None:
        room = self.get_or_create_room(session_id)
        # Close previous spectator if any
        if room.spectator:
            try:
                await room.spectator.websocket.close()
            except Exception:
                pass
        room.spectator = TrainingSpectatorConnection(websocket=websocket, user_id=user_id)
        logger.info(f"Spectator connected to training session {session_id}")

    async def disconnect_spectator(self, session_id: uuid.UUID, websocket: WebSocket) -> None:
        room = self.rooms.get(session_id)
        if room:
            # Only remove if the disconnecting websocket is the current one
            # (a new spectator may have already replaced it via connect_spectator)
            if room.spectator is not None and room.spectator.websocket is websocket:
                room.spectator = None
                logger.info(f"Spectator disconnected from training session {session_id}")
            else:
                logger.debug(
                    f"Stale spectator disconnect ignored for training session {session_id}"
                )
            if room.mod is None and room.spectator is None:
                del self.rooms[session_id]

    def is_mod_connected(self, session_id: uuid.UUID) -> bool:
        room = self.rooms.get(session_id)
        return room is not None and room.mod is not None


training_manager = TrainingConnectionManager()
