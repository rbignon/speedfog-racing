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
from speedfog_racing.services.layer_service import get_layer_for_node, get_tier_for_node
from speedfog_racing.websocket.schemas import (
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)
from speedfog_racing.websocket.training_manager import training_manager

AUTH_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 30.0
SEND_TIMEOUT = 5.0

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
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

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


async def _heartbeat_loop(websocket: WebSocket) -> None:
    ping_json = PingMessage().model_dump_json()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await asyncio.wait_for(websocket.send_text(ping_json), timeout=SEND_TIMEOUT)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


async def _send_initial_state(
    websocket: WebSocket, session: TrainingSession, *, locale: str = "en"
) -> None:
    """Send current training session state to spectator."""
    seed = session.seed

    current_zone = session.current_zone
    current_layer = 0
    tier = None
    if session.progress_nodes:
        if not current_zone:
            current_zone = session.progress_nodes[-1].get("node_id")
        if current_zone and seed and seed.graph_json:
            tier = get_tier_for_node(current_zone, seed.graph_json)
        for entry in session.progress_nodes:
            nid = entry.get("node_id")
            if nid and seed and seed.graph_json:
                layer = get_layer_for_node(nid, seed.graph_json)
                if layer > current_layer:
                    current_layer = layer

    # Finished sessions show total_layers so progress reads N/N
    if session.status == TrainingSessionStatus.FINISHED and seed:
        current_layer = seed.total_layers

    room = training_manager.get_room(session.id)

    # Map training status to participant status for frontend compatibility:
    # "active" → "playing" (MetroDagLive/Leaderboard expect "playing"/"finished")
    participant_status = (
        "playing" if session.status == TrainingSessionStatus.ACTIVE else session.status.value
    )

    participant = ParticipantInfo(
        id=str(session.id),
        twitch_username=session.user.twitch_username,
        twitch_display_name=session.user.twitch_display_name,
        status=participant_status,
        current_zone=current_zone,
        current_layer=current_layer,
        current_layer_tier=tier,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        color_index=0,
        mod_connected=room is not None and room.mod is not None,
        zone_history=session.progress_nodes,
    )

    graph_json = seed.graph_json if seed else None
    if graph_json is not None and locale != "en":
        graph_json = translate_graph_json(graph_json, locale)

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(session.id),
            name=f"Training {format_pool_display_name(seed.pool_name)}" if seed else "Training",
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
