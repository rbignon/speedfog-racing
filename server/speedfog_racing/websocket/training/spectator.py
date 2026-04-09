"""WebSocket handler for training session spectators (the player's web view)."""

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.auth import get_user_by_token
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.i18n import translate_graph_json
from speedfog_racing.websocket.handler import BaseSpectatorHandler
from speedfog_racing.websocket.schemas import (
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)
from speedfog_racing.websocket.training.manager import training_manager
from speedfog_racing.websocket.training.mod import build_training_participant_info

logger = logging.getLogger(__name__)


class TrainingSpectatorHandler(BaseSpectatorHandler):
    """Spectator WebSocket handler for training session connections."""

    AUTH_TIMEOUT = 5.0

    def __init__(
        self,
        websocket: WebSocket,
        session_id: uuid.UUID,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, session_id, session_maker)
        self._spectator_id: uuid.UUID | None = None
        self._user_id: uuid.UUID | None = None

    async def _auth_and_setup(self) -> bool:
        # Wait AUTH_TIMEOUT for auth message
        try:
            auth_data = await asyncio.wait_for(
                self.websocket.receive_text(), timeout=self.AUTH_TIMEOUT
            )
        except TimeoutError:
            await self.websocket.close(code=4001, reason="Auth timeout")
            return False

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await self.websocket.close(code=4003, reason="Invalid JSON")
            return False

        if auth_msg.get("type") != "auth":
            await self.websocket.close(code=4003, reason="Invalid auth")
            return False

        # Optional token -> get_user_by_token -> user_id, locale
        token = auth_msg.get("token")
        async with self.session_maker() as db:
            if isinstance(token, str) and token:
                user = await get_user_by_token(db, token)
                if user:
                    self._user_id = user.id
                    if user.locale:
                        self.locale = user.locale

            # Load session
            result = await db.execute(
                select(TrainingSession)
                .options(
                    selectinload(TrainingSession.user),
                    selectinload(TrainingSession.seed),
                )
                .where(TrainingSession.id == self.entity_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                await self.websocket.close(code=4004, reason="Session not found")
                return False

            await _send_initial_state(self.websocket, session, locale=self.locale)

        self._spectator_id = self._user_id or uuid.uuid4()
        return True

    async def _register(self) -> None:
        assert isinstance(self.entity_id, uuid.UUID)
        assert self._spectator_id is not None
        await training_manager.connect_spectator(
            self.entity_id,
            self._spectator_id,
            self.websocket,
        )

    async def _unregister(self) -> None:
        assert isinstance(self.entity_id, uuid.UUID)
        await training_manager.disconnect_spectator(self.entity_id, self.websocket)


async def handle_training_spectator_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle spectator WebSocket for a training session.

    Accepts both authenticated and anonymous spectators.
    """
    handler = TrainingSpectatorHandler(websocket, session_id, session_maker)
    await handler.run()


async def _send_initial_state(
    websocket: WebSocket, session: TrainingSession, *, locale: str = "en"
) -> None:
    """Send current training session state to spectator."""
    seed = session.seed
    room = training_manager.get_room(session.id)
    mod_connected = room is not None and room.mod is not None
    participant = build_training_participant_info(
        session, mod_connected=mod_connected, include_zone_history=True
    )

    graph_json = seed.graph_json if seed else None
    if graph_json is not None and locale != "en":
        graph_json = translate_graph_json(graph_json, locale)

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(session.id),
            name=format_pool_display_name(seed.pool_name) if seed else "Solo",
            status="running"
            if session.status == TrainingSessionStatus.ACTIVE
            else session.status.value,
            started_at=session.created_at.isoformat() if session.created_at else None,
        ),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=graph_json,
            total_nodes=seed.graph_json.get("total_nodes") if seed and seed.graph_json else None,
            total_paths=seed.graph_json.get("total_paths") if seed and seed.graph_json else None,
        ),
        participants=[participant],
    )
    await websocket.send_text(message.model_dump_json())
