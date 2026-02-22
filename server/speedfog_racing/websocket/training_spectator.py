"""WebSocket handler for training session spectators (the player's web view)."""

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.auth import get_user_by_token
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.i18n import translate_graph_json
from speedfog_racing.websocket.common import heartbeat_loop
from speedfog_racing.websocket.schemas import (
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)
from speedfog_racing.websocket.training_manager import training_manager
from speedfog_racing.websocket.training_mod import build_training_participant_info

AUTH_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


async def handle_training_spectator_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle spectator WebSocket for a training session.

    Accepts both authenticated and anonymous spectators.
    """
    await websocket.accept()

    # Read locale from query param (e.g. ?locale=fr)
    locale = websocket.query_params.get("locale", "en")

    spectator_id = None

    try:
        # Wait for auth message (token is optional for anonymous access)
        try:
            auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT)
        except TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await websocket.close(code=4003, reason="Invalid JSON")
            return

        if auth_msg.get("type") != "auth":
            await websocket.close(code=4003, reason="Invalid auth")
            return

        # Token is optional — anonymous spectators don't send one
        token = auth_msg.get("token")
        user_id = None

        async with session_maker() as db:
            if isinstance(token, str) and token:
                user = await get_user_by_token(db, token)
                if user:
                    user_id = user.id
                    # Prefer user's DB locale over query param
                    if user.locale:
                        locale = user.locale

            # Load session (no ownership check — public read-only)
            result = await db.execute(
                select(TrainingSession)
                .options(
                    selectinload(TrainingSession.user),
                    selectinload(TrainingSession.seed),
                )
                .where(TrainingSession.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                await websocket.close(code=4004, reason="Session not found")
                return

            # Send initial state
            await _send_initial_state(websocket, session, locale=locale)

        # Register connection — use user_id if authenticated, else random UUID
        spectator_id = user_id or uuid.uuid4()
        await training_manager.connect_spectator(session_id, spectator_id, websocket)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            # Spectators only listen
            while True:
                await websocket.receive_text()
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Training spectator disconnected: session={session_id}")
    except Exception:
        logger.exception(f"Training spectator error: session={session_id}")
    finally:
        if spectator_id:
            await training_manager.disconnect_spectator(session_id, websocket)


async def _send_initial_state(
    websocket: WebSocket, session: TrainingSession, *, locale: str = "en"
) -> None:
    """Send current training session state to spectator."""
    seed = session.seed
    room = training_manager.get_room(session.id)
    mod_connected = room is not None and room.mod is not None
    participant = build_training_participant_info(session, mod_connected=mod_connected)

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
