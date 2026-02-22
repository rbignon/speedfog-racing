"""WebSocket handler for training mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.grace_service import resolve_zone_query
from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_start_node,
    get_tier_for_node,
)
from speedfog_racing.websocket.common import (
    MOD_AUTH_TIMEOUT,
    extract_event_ids,
    get_graces_mapping,
    heartbeat_loop,
    parse_zone_query_input,
    send_auth_error,
    send_error,
    send_zone_update,
)
from speedfog_racing.websocket.schemas import (
    AuthOkMessage,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    RaceStatusChangeMessage,
    SeedInfo,
    extract_spawn_items,
)
from speedfog_racing.websocket.training_manager import training_manager

logger = logging.getLogger(__name__)


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
            logger.warning(f"Training mod auth timeout: session={session_id}")
            await websocket.close(code=4001, reason="Auth timeout")
            return

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await send_auth_error(websocket, "Invalid JSON")
            return

        if auth_msg.get("type") != "auth" or "mod_token" not in auth_msg:
            await send_auth_error(websocket, "Invalid auth message")
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
                await send_auth_error(websocket, "Invalid mod token or session")
                return

            if session.status != TrainingSessionStatus.ACTIVE:
                await send_auth_error(websocket, "Solo session is not active")
                return

            if training_manager.is_mod_connected(session_id):
                await send_auth_error(websocket, "Already connected from another client")
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
                    await send_zone_update(
                        websocket,
                        last_node,
                        seed.graph_json,
                        session.progress_nodes or [],
                        mod_locale,
                    )

        # Register connection and notify spectators (mod already has auth_ok data)
        await training_manager.connect_mod(session_id, user_id, websocket)
        authenticated = True
        await _broadcast_participant_update(session, spectator_only=True)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from training mod (ignored): {e}")
                    continue

                msg_type = msg.get("type")

                if msg_type == "pong":
                    pass
                elif msg_type == "status_update":
                    await _handle_status_update(websocket, session_maker, session_id, msg)
                elif msg_type == "event_flag":
                    await _handle_event_flag(
                        websocket, session_maker, session_id, msg, locale=mod_locale
                    )
                elif msg_type == "zone_query":
                    await _handle_zone_query(
                        websocket, session_maker, session_id, msg, locale=mod_locale
                    )
                else:
                    logger.warning(f"Unknown message type from training mod: {msg_type}")
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


def build_training_participant_info(
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

    event_ids: list[int] = []
    finish_event_id: int | None = None
    if seed and seed.graph_json:
        event_ids, finish_event_id = extract_event_ids(seed.graph_json)

    # Extract gem items from care_package for runtime spawning by the mod
    spawn_items = extract_spawn_items(seed.graph_json) if seed and seed.graph_json else []

    message = AuthOkMessage(
        participant_id=str(session.id),
        race=RaceInfo(
            id=str(session.id),
            name=format_pool_display_name(seed.pool_name) if seed else "Solo",
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
        participants=[build_training_participant_info(session)],
    )
    await websocket.send_text(message.model_dump_json())


async def _handle_status_update(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Update IGT and death count."""
    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            if session:
                await send_error(websocket, "Solo session not active")
            return

        if isinstance(msg.get("igt_ms"), int):
            session.igt_ms = msg["igt_ms"]

        # Record start node on first status_update (mirrors race mode READY→PLAYING).
        # Must happen BEFORE death attribution so current_zone/progress_nodes exist.
        if not session.progress_nodes:
            seed = session.seed
            if seed and seed.graph_json:
                start_node = get_start_node(seed.graph_json)
                if start_node:
                    session.progress_nodes = [{"node_id": start_node, "igt_ms": 0}]
                    session.current_zone = start_node

        new_death_count = msg.get("death_count")
        if isinstance(new_death_count, int):
            delta = new_death_count - session.death_count
            if delta < 0:
                logger.warning(
                    "Negative death delta %d for training session %s (stored=%d, received=%d)",
                    delta,
                    session_id,
                    session.death_count,
                    new_death_count,
                )
            if delta > 0 and session.current_zone and session.progress_nodes:
                # Deep-copy entries so mutations don't affect the committed
                # state — SQLAlchemy compares new vs committed to detect dirt.
                history = [dict(e) for e in session.progress_nodes]
                for entry in history:
                    if entry.get("node_id") == session.current_zone:
                        entry["deaths"] = entry.get("deaths", 0) + delta
                        break
                session.progress_nodes = history
            session.death_count = new_death_count

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

    igt = msg.get("igt_ms", 0) if isinstance(msg.get("igt_ms"), int) else 0
    node_id = None
    seed_graph = None

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            if session:
                await send_error(websocket, "Solo session not active")
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
        is_revisit = any(e.get("node_id") == node_id for e in old_history)

        if is_revisit:
            # Already discovered — just update position (like zone_query)
            session.current_zone = node_id
            session.igt_ms = igt
            await db.commit()
        else:
            # New discovery — record in history
            session.igt_ms = igt
            session.current_zone = node_id
            session.progress_nodes = [*old_history, {"node_id": node_id, "igt_ms": igt}]
            await db.commit()

    # Broadcast to spectators (session is detached; expire_on_commit=False keeps attrs)
    if session:
        await _broadcast_participant_update(session)

    # Send zone_update to mod
    if node_id and seed_graph:
        await send_zone_update(websocket, node_id, seed_graph, session.progress_nodes or [], locale)


async def _handle_zone_query(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
    *,
    locale: str = "en",
) -> None:
    """Handle zone_query from mod (loading screen exit overlay update)."""
    zq = parse_zone_query_input(msg)
    if zq is None:
        return

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
            get_graces_mapping(),
            grace_entity_id=zq.grace_entity_id,
            map_id=zq.map_id,
            position=zq.position,
            play_region_id=zq.play_region_id,
            zone_history=session.progress_nodes,
        )
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for training session %s",
                zq.grace_entity_id,
                zq.map_id,
                session_id,
            )
            return

        session.current_zone = node_id
        await db.commit()

        progress = session.progress_nodes or []

    # Unicast zone_update to mod
    await send_zone_update(websocket, node_id, graph_json, progress, locale)

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

    info = build_training_participant_info(session, mod_connected=room.mod is not None)
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
