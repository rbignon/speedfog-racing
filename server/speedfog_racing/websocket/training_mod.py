"""WebSocket handler for training mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from starlette.websockets import WebSocketDisconnect

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.grace_service import load_graces_mapping, resolve_zone_query
from speedfog_racing.services.i18n import translate_zone_update
from speedfog_racing.services.layer_service import (
    compute_zone_update,
    get_layer_for_node,
    get_start_node,
    get_tier_for_node,
)
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    AuthOkMessage,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStartMessage,
    RaceStatusChangeMessage,
    SeedInfo,
    extract_spawn_items,
)
from speedfog_racing.websocket.training_manager import training_manager

MOD_AUTH_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 30.0
SEND_TIMEOUT = 5.0

logger = logging.getLogger(__name__)

_graces_mapping: dict[str, dict[str, Any]] | None = None


def _get_graces_mapping() -> dict[str, dict[str, Any]]:
    global _graces_mapping
    if _graces_mapping is None:
        _graces_mapping = load_graces_mapping()
    return _graces_mapping


def _load_options() -> list[Any]:
    return [
        selectinload(TrainingSession.user),
        selectinload(TrainingSession.seed),
    ]


async def _load_session(db: AsyncSession, session_id: uuid.UUID) -> TrainingSession | None:
    result = await db.execute(
        select(TrainingSession).options(*_load_options()).where(TrainingSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def handle_training_mod_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle mod WebSocket for a training session."""
    await websocket.accept()

    authenticated = False

    try:
        # Auth phase
        try:
            auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=MOD_AUTH_TIMEOUT)
        except TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await _send_auth_error(websocket, "Invalid JSON")
            return

        if auth_msg.get("type") != "auth" or "mod_token" not in auth_msg:
            await _send_auth_error(websocket, "Invalid auth message")
            return

        mod_token = auth_msg["mod_token"]

        async with session_maker() as db:
            # Find session by mod_token
            result = await db.execute(
                select(TrainingSession)
                .options(*_load_options())
                .where(
                    TrainingSession.id == session_id,
                    TrainingSession.mod_token == mod_token,
                )
            )
            session = result.scalar_one_or_none()

            if not session:
                await _send_auth_error(websocket, "Invalid mod token or session")
                return

            if session.status != TrainingSessionStatus.ACTIVE:
                await _send_auth_error(websocket, "Training session is not active")
                return

            if training_manager.is_mod_connected(session_id):
                await _send_auth_error(websocket, "Already connected from another client")
                return

            user_id = session.user_id
            mod_locale = session.user.locale or "en"

            # Send auth_ok
            await _send_auth_ok(websocket, session)

            # Send race_start immediately (training starts right away)
            await websocket.send_text(RaceStartMessage().model_dump_json())

            # Send initial zone_update if session has progress
            seed = session.seed
            if seed and seed.graph_json:
                last_node = None
                if session.progress_nodes:
                    last_node = session.progress_nodes[-1].get("node_id")
                if not last_node:
                    last_node = get_start_node(seed.graph_json)
                if last_node:
                    zone_update = compute_zone_update(
                        last_node,
                        seed.graph_json,
                        session.progress_nodes or [],
                    )
                    if zone_update:
                        zone_update = translate_zone_update(zone_update, mod_locale)
                        await websocket.send_text(json.dumps(zone_update))

        # Register connection and notify spectators (mod already has auth_ok data)
        await training_manager.connect_mod(session_id, user_id, websocket)
        authenticated = True
        await _broadcast_participant_update(session, spectator_only=True)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "pong":
                    pass
                elif msg_type == "status_update":
                    await _handle_status_update(session_maker, session_id, msg)
                elif msg_type == "event_flag":
                    await _handle_event_flag(
                        websocket, session_maker, session_id, msg, locale=mod_locale
                    )
                elif msg_type == "zone_query":
                    await _handle_zone_query(
                        websocket, session_maker, session_id, msg, locale=mod_locale
                    )
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Training mod disconnected: session={session_id}")
    except Exception:
        logger.exception(f"Training mod handler error: session={session_id}")
    finally:
        if authenticated:
            await training_manager.disconnect_mod(session_id, websocket)
            # Notify spectators that mod disconnected (mod is already gone)
            try:
                async with session_maker() as db:
                    disc_session = await _load_session(db, session_id)
                    if disc_session:
                        await _broadcast_participant_update(disc_session, spectator_only=True)
            except Exception:
                pass


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


async def _send_auth_error(websocket: WebSocket, message: str) -> None:
    logger.warning(f"Training auth error: {message}")
    try:
        await websocket.send_text(AuthErrorMessage(message=message).model_dump_json())
        await websocket.close(code=4003, reason=message)
    except Exception:
        pass


def _build_participant_info(
    session: TrainingSession, *, mod_connected: bool = True
) -> ParticipantInfo:
    """Build ParticipantInfo from a training session, computing layer/tier from progress."""
    seed = session.seed

    current_layer = 0
    current_layer_tier: int | None = None
    current_zone = session.current_zone
    if session.progress_nodes and seed and seed.graph_json:
        for entry in session.progress_nodes:
            nid = entry.get("node_id")
            if nid:
                layer = get_layer_for_node(nid, seed.graph_json)
                if layer > current_layer:
                    current_layer = layer
        if not current_zone:
            current_zone = session.progress_nodes[-1].get("node_id")
        if current_zone:
            current_layer_tier = get_tier_for_node(current_zone, seed.graph_json)

    # Finished sessions show total_layers so progress reads N/N
    if session.status == TrainingSessionStatus.FINISHED and seed:
        current_layer = seed.total_layers

    # Map training status to participant status for frontend compatibility:
    # "active" → "playing" (MetroDagLive/Leaderboard expect "playing"/"finished")
    status = "playing" if session.status == TrainingSessionStatus.ACTIVE else session.status.value

    return ParticipantInfo(
        id=str(session.id),
        twitch_username=session.user.twitch_username,
        twitch_display_name=session.user.twitch_display_name,
        status=status,
        current_zone=current_zone,
        current_layer=current_layer,
        current_layer_tier=current_layer_tier,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        color_index=0,
        mod_connected=mod_connected,
        zone_history=session.progress_nodes,
    )


async def _send_auth_ok(websocket: WebSocket, session: TrainingSession) -> None:
    """Send auth_ok with training session info."""
    seed = session.seed

    finish_event_id: int | None = None
    event_ids: list[int] = []
    if seed and seed.graph_json:
        event_map = seed.graph_json.get("event_map", {})
        finish = seed.graph_json.get("finish_event")
        if isinstance(finish, int):
            finish_event_id = finish
        if event_map:
            event_ids = sorted(int(k) for k in event_map.keys())
            if finish_event_id is not None and finish_event_id not in event_ids:
                event_ids.append(finish_event_id)

    # Extract gem items from care_package for runtime spawning by the mod
    spawn_items = extract_spawn_items(seed.graph_json) if seed and seed.graph_json else []

    message = AuthOkMessage(
        participant_id=str(session.id),
        race=RaceInfo(
            id=str(session.id),
            name=f"Training {format_pool_display_name(seed.pool_name)}" if seed else "Training",
            status="running",
            started_at=session.created_at.isoformat() if session.created_at else None,
        ),
        seed=SeedInfo(
            seed_id=str(seed.id) if seed else None,
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,
            event_ids=event_ids,
            finish_event=finish_event_id,
            spawn_items=spawn_items,
        ),
        participants=[_build_participant_info(session)],
    )
    await websocket.send_text(message.model_dump_json())


async def _handle_status_update(
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Update IGT and death count."""
    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            return

        session.igt_ms = msg.get("igt_ms", 0)
        session.death_count = msg.get("death_count", 0)

        # Record start node on first status_update (mirrors race mode READY→PLAYING)
        if not session.progress_nodes:
            seed = session.seed
            if seed and seed.graph_json:
                start_node = get_start_node(seed.graph_json)
                if start_node:
                    session.progress_nodes = [{"node_id": start_node, "igt_ms": 0}]
                    session.current_zone = start_node

        await db.commit()

    # Broadcast to spectators (session is detached from DB but all relationships
    # were eagerly loaded and expire_on_commit=False keeps attributes accessible)
    await _broadcast_participant_update(session)


async def _handle_event_flag(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
    *,
    locale: str = "en",
) -> None:
    """Handle fog gate traversal or boss kill event flag."""
    flag_id = msg.get("flag_id")
    if not isinstance(flag_id, int):
        return

    igt = msg.get("igt_ms", 0)
    node_id = None
    seed_graph = None

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            return

        seed = session.seed
        if not seed or not seed.graph_json:
            return

        seed_graph = seed.graph_json
        event_map = seed_graph.get("event_map", {})
        finish_event = seed_graph.get("finish_event")

        # Check finish first
        if flag_id == finish_event:
            session.igt_ms = igt
            session.status = TrainingSessionStatus.FINISHED
            session.finished_at = datetime.now(UTC)
            await db.commit()

            # Broadcast finish to spectators
            await _broadcast_participant_update(session)
            await _broadcast_status_change(session_id, "finished")
            return

        # Fog gate traversal
        node_id = event_map.get(str(flag_id))
        if node_id is None:
            logger.warning(f"Unknown event flag {flag_id} in training session {session_id}")
            return

        # Check not duplicate
        old_history = session.progress_nodes or []
        if any(e.get("node_id") == node_id for e in old_history):
            return

        # Record
        session.igt_ms = igt
        session.current_zone = node_id
        session.progress_nodes = [*old_history, {"node_id": node_id, "igt_ms": igt}]
        await db.commit()

    # Broadcast to spectators (session is detached; expire_on_commit=False keeps attrs)
    if session:
        await _broadcast_participant_update(session)

    # Send zone_update to mod
    if node_id and seed_graph:
        zone_update = compute_zone_update(node_id, seed_graph, session.progress_nodes or [])
        if zone_update:
            zone_update = translate_zone_update(zone_update, locale)
            try:
                await websocket.send_text(json.dumps(zone_update))
            except Exception:
                pass


async def _handle_zone_query(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
    *,
    locale: str = "en",
) -> None:
    """Handle zone_query from mod (loading screen exit overlay update)."""
    grace_entity_id = msg.get("grace_entity_id")
    if isinstance(grace_entity_id, int) and grace_entity_id != 0:
        pass  # valid
    else:
        grace_entity_id = None

    map_id_str = msg.get("map_id") if isinstance(msg.get("map_id"), str) else None

    if grace_entity_id is None and map_id_str is None:
        return

    # Extract optional fields for future disambiguation
    raw_pos = msg.get("position")
    position = tuple(raw_pos) if isinstance(raw_pos, list) and len(raw_pos) == 3 else None
    raw_pr = msg.get("play_region_id")
    play_region_id = raw_pr if isinstance(raw_pr, int) else None

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            return

        seed = session.seed
        if not seed or not seed.graph_json:
            return

        graph_json = seed.graph_json
        node_id = resolve_zone_query(
            graph_json,
            _get_graces_mapping(),
            grace_entity_id=grace_entity_id,
            map_id=map_id_str,
            position=position,
            play_region_id=play_region_id,
            zone_history=session.progress_nodes,
        )
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for training session %s",
                grace_entity_id,
                map_id_str,
                session_id,
            )
            return

        session.current_zone = node_id
        await db.commit()

        progress = session.progress_nodes or []

    # Unicast zone_update to mod
    zone_update = compute_zone_update(node_id, graph_json, progress)
    if zone_update:
        zone_update = translate_zone_update(zone_update, locale)
        try:
            await asyncio.wait_for(
                websocket.send_text(json.dumps(zone_update)), timeout=SEND_TIMEOUT
            )
        except Exception:
            logger.warning("Failed to send zone_update for training zone_query")

    # Broadcast to spectators so DAG view reflects current zone
    # (mod already got the unicast zone_update above)
    await _broadcast_participant_update(session, spectator_only=True)


async def _broadcast_participant_update(
    session: TrainingSession, *, spectator_only: bool = False
) -> None:
    """Send leaderboard_update (single participant) to room connections."""
    room = training_manager.get_room(session.id)
    if not room:
        return

    info = _build_participant_info(session, mod_connected=room.mod is not None)
    message = LeaderboardUpdateMessage(participants=[info])
    payload = message.model_dump_json()
    if spectator_only:
        await room.broadcast_to_spectators(payload)
    else:
        await room.broadcast_to_all(payload)


async def _broadcast_status_change(session_id: uuid.UUID, new_status: str) -> None:
    """Notify all connections of status change."""
    room = training_manager.get_room(session_id)
    if not room:
        return

    message = RaceStatusChangeMessage(status=new_status)
    await room.broadcast_to_all(message.model_dump_json())
