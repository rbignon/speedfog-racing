"""WebSocket handler for training mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.discord import send_training_live_notification
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.grace_service import resolve_zone_query
from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_start_node,
    get_tier_for_node,
)
from speedfog_racing.websocket.common import (
    MAX_FRESH_IGT_MS,
    MAX_ZONE_HISTORY,
    MOD_AUTH_TIMEOUT,
    MessageRateLimiter,
    attribute_deaths,
    clamp_death_count,
    clamp_igt,
    extract_event_ids,
    get_graces_mapping,
    heartbeat_loop,
    parse_zone_query_input,
    send_auth_error,
    send_error,
    send_event_flag_ack,
    send_zone_query_ack,
    send_zone_update,
)
from speedfog_racing.websocket.mod import is_shared_entrance_duplicate
from speedfog_racing.websocket.schemas import (
    AuthOkMessage,
    DeathCountsMessage,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    RaceStatusChangeMessage,
    SeedInfo,
    ZoneHistoryMessage,
    extract_spawn_items,
)
from speedfog_racing.websocket.training_manager import training_manager

logger = logging.getLogger(__name__)


def _aggregate_session_deaths(zone_history: list[dict[str, Any]] | None) -> dict[str, int]:
    """Aggregate deaths per node_id from a single session's zone_history."""
    counts: dict[str, int] = {}
    for entry in zone_history or []:
        deaths = entry.get("deaths", 0)
        if deaths > 0:
            node_id = entry.get("node_id")
            if node_id:
                counts[node_id] = counts.get(node_id, 0) + deaths
    return counts


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

            user_id = session.user_id
            mod_locale = session.user.locale or "en"

            # Send auth_ok
            await _send_auth_ok(websocket, session)

            # Send race_start immediately (training starts right away)
            await websocket.send_text(RaceStartMessage().model_dump_json())

            # Send initial zone_update only on reconnect (zone_history exists).
            # For new sessions, the zone_update arrives after the first valid
            # status_update + event_flag/zone_query cycle, avoiding premature
            # display before fresh-save validation passes.
            seed = session.seed
            if seed and seed.graph_json and session.zone_history:
                last_node = session.zone_history[-1].get("node_id")
                if last_node:
                    await send_zone_update(
                        websocket,
                        last_node,
                        seed.graph_json,
                        session.zone_history,
                        mod_locale,
                    )

                # Send current death counts on reconnect
                counts = _aggregate_session_deaths(session.zone_history)
                if counts:
                    logger.info(
                        "Sending death_counts on reconnect: training=%s, counts=%s",
                        session_id,
                        counts,
                    )
                    await websocket.send_text(DeathCountsMessage(counts=counts).model_dump_json())

        # Register connection and notify spectators (mod already has auth_ok data)
        await training_manager.connect_mod(session_id, user_id, websocket)
        authenticated = True
        await _broadcast_participant_update(session, spectator_only=True)

        # Fire-and-forget: notify Discord if player is live on Twitch.
        # Atomic DB check prevents duplicate notifications on server restart
        # (in-memory cooldown is lost, but discord_notified_at persists).
        # The timestamp is set optimistically before delivery confirmation;
        # if the notification fails (not live, webhook error), it won't retry.
        should_notify = session.discord_notified_at is None
        if should_notify:
            async with session_maker() as db:
                result = await db.execute(
                    update(TrainingSession)
                    .where(
                        TrainingSession.id == session_id,
                        TrainingSession.discord_notified_at.is_(None),
                    )
                    .values(discord_notified_at=datetime.now(UTC))
                )
                await db.commit()
                should_notify = result.rowcount > 0  # type: ignore[attr-defined]

        if should_notify:
            notif_task = asyncio.create_task(
                send_training_live_notification(
                    session_id=str(session.id),
                    user=session.user,
                    pool_name=session.seed.pool_name if session.seed else "training_standard",
                )
            )
            notif_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))
        rate_limiter = MessageRateLimiter()

        try:
            while True:
                data = await websocket.receive_text()

                if not rate_limiter.check():
                    logger.warning("Rate limit exceeded: training session=%s", session_id)
                    await websocket.close(code=4008, reason="Rate limit exceeded")
                    return

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
    session: TrainingSession,
    *,
    mod_connected: bool = True,
    include_zone_history: bool = False,
) -> ParticipantInfo:
    """Build ParticipantInfo from a training session, computing layer/tier from progress.

    zone_history is omitted by default (saves bandwidth in high-frequency
    leaderboard_update broadcasts). The spectator bootstrap (_send_initial_state)
    passes include_zone_history=True to seed the client's local store; subsequent
    changes arrive as zone_history snapshots.
    """
    seed = session.seed

    current_layer = 0
    current_layer_tier: int | None = None
    current_zone = session.current_zone
    if session.zone_history and seed and seed.graph_json:
        for entry in session.zone_history:
            nid = entry.get("node_id")
            if nid:
                layer = get_layer_for_node(nid, seed.graph_json)
                if layer > current_layer:
                    current_layer = layer
        if not current_zone:
            current_zone = session.zone_history[-1].get("node_id")
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
        zone_history=session.zone_history if include_zone_history else None,
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
    death_flags = seed.graph_json.get("death_flags", {}) if seed and seed.graph_json else {}
    items_spawned_flag = (
        seed.graph_json.get("items_spawned_flag") if seed and seed.graph_json else None
    )

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
            death_flags=death_flags,
            items_spawned_flag=items_spawned_flag,
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
    delta = 0
    history_changed = False
    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            if session:
                await send_error(websocket, "Solo session not active")
            return

        # Gate: reject stale saves on first initialization
        igt_ms_val = clamp_igt(msg.get("igt_ms"))
        if igt_ms_val is not None and not session.zone_history and igt_ms_val > MAX_FRESH_IGT_MS:
            logger.warning(
                "Rejected stale save: training=%s igt_ms=%d",
                session_id,
                igt_ms_val,
            )
            await send_error(websocket, "Please start a New Game")
            return

        if igt_ms_val is not None:
            session.igt_ms = igt_ms_val

        # Record start node on first status_update (mirrors race mode READY→PLAYING).
        # Must happen BEFORE death attribution so current_zone/zone_history exist.
        if not session.zone_history:
            seed = session.seed
            if seed and seed.graph_json:
                start_node = get_start_node(seed.graph_json)
                if start_node:
                    session.zone_history = [{"node_id": start_node, "igt_ms": 0, "type": "spawn"}]
                    session.current_zone = start_node
                    history_changed = True

        new_death_count = clamp_death_count(msg.get("death_count"))
        if new_death_count is not None:
            delta = new_death_count - session.death_count
            if delta < 0:
                logger.warning(
                    "Negative death delta %d for training session %s (stored=%d, received=%d)",
                    delta,
                    session_id,
                    session.death_count,
                    new_death_count,
                )
            if delta > 0 and session.current_zone and session.zone_history:
                new_history = attribute_deaths(session.zone_history, session.current_zone, delta)
                session.zone_history = new_history
                history_changed = True
            session.death_count = new_death_count

        await db.commit()

    # Broadcast to spectators (session is detached from DB but all relationships
    # were eagerly loaded and expire_on_commit=False keeps attributes accessible)
    await _broadcast_participant_update(session)

    if history_changed:
        await _broadcast_zone_history(session_id, session.zone_history or [])

    # Send death counts to mod when deaths are attributed
    if delta > 0:
        counts = _aggregate_session_deaths(session.zone_history)
        logger.info(
            "Sending death_counts: training=%s, counts=%s",
            session_id,
            counts,
        )
        await websocket.send_text(DeathCountsMessage(counts=counts).model_dump_json())


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
    raw_message_id = msg.get("message_id")
    message_id = raw_message_id if isinstance(raw_message_id, int) else None

    raw_igt = clamp_igt(msg.get("igt_ms"))
    igt = raw_igt if raw_igt is not None else 0
    node_id = None
    seed_graph = None

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            if session and message_id is not None:
                # ACK replayed event flags so the mod clears its in-flight set
                # (e.g. finish event committed but ACK lost before disconnect).
                await send_event_flag_ack(websocket, message_id)
            elif session:
                await send_error(websocket, "Solo session not active")
            return

        # Guard: zone_history must be initialized by the first valid status_update
        # before processing event flags. Without this, stale flags persisted in a
        # loaded save bypass the fresh-save IGT gate in _handle_status_update.
        if not session.zone_history:
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
            if message_id is not None:
                await send_event_flag_ack(websocket, message_id)

            # Broadcast finish to spectators
            await _broadcast_participant_update(session)
            await _broadcast_status_change(session_id, "finished")
            return

        # Fog gate traversal
        node_id = event_map.get(str(flag_id))
        if node_id is None:
            logger.warning(f"Unknown event flag {flag_id} in training session {session_id}")
            return

        # Always append to zone_history (including revisits/backtracks)
        old_history = session.zone_history or []

        if message_id is not None and any(
            entry.get("type", "fog") == "fog" and entry.get("message_id") == message_id
            for entry in old_history
        ):
            await send_event_flag_ack(websocket, message_id)
            return

        if is_shared_entrance_duplicate(old_history, node_id, igt):
            return

        if len(old_history) >= MAX_ZONE_HISTORY:
            logger.warning("zone_history cap reached for training session %s", session_id)
            return

        is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)

        session.igt_ms = igt
        session.current_zone = node_id
        new_entry = {"node_id": node_id, "igt_ms": igt, "type": "fog"}
        if message_id is not None:
            new_entry["message_id"] = message_id
        session.zone_history = [*old_history, new_entry]
        await db.commit()
        if message_id is not None:
            await send_event_flag_ack(websocket, message_id)

    # Broadcast to spectators (session is detached; expire_on_commit=False keeps attrs)
    if session:
        await _broadcast_participant_update(session)
        await _broadcast_zone_history(session_id, session.zone_history or [])

    # Send zone_update to mod
    if node_id and seed_graph:
        await send_zone_update(
            websocket,
            node_id,
            seed_graph,
            session.zone_history or [],
            locale,
            is_first_visit=is_first_visit,
        )


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

    message_id = zq.message_id
    history_changed = False

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        # Guard: same as _handle_event_flag, require zone_history initialization
        if not session.zone_history:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        seed = session.seed
        if not seed or not seed.graph_json:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        graph_json = seed.graph_json
        node_id = resolve_zone_query(
            graph_json,
            get_graces_mapping(),
            grace_entity_id=zq.grace_entity_id,
            map_id=zq.map_id,
            position=zq.position,
            play_region_id=zq.play_region_id,
            zone_history=session.zone_history,
        )
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for training session %s",
                zq.grace_entity_id,
                zq.map_id,
                session_id,
            )
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        # Record backtrack entry when the player moved to a different node
        # (death/teleport/quit-out, no event flag fired)
        is_first_visit = False
        if node_id != session.current_zone:
            logger.info(
                "zone_query backtrack: %s -> %s for training session %s",
                session.current_zone,
                node_id,
                session_id,
            )
            igt = zq.igt_ms if zq.igt_ms is not None else session.igt_ms
            old_history = session.zone_history or []

            if message_id is not None and any(
                entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                pass  # Dedup: already persisted, skip to zone_update
            elif len(old_history) >= MAX_ZONE_HISTORY:
                logger.warning("zone_history cap reached for training session %s", session_id)
            else:
                is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)
                session.igt_ms = igt
                new_entry: dict[str, Any] = {
                    "node_id": node_id,
                    "igt_ms": igt,
                    "type": "backtrack",
                }
                if message_id is not None:
                    new_entry["message_id"] = message_id
                session.zone_history = [*old_history, new_entry]
                history_changed = True

        session.current_zone = node_id
        await db.commit()

    # Unicast zone_update to mod
    await send_zone_update(
        websocket,
        node_id,
        graph_json,
        session.zone_history or [],
        locale,
        is_first_visit=is_first_visit,
        message_id=message_id,
    )

    # Broadcast to spectators so DAG view reflects current zone
    # (mod already got the unicast zone_update above)
    await _broadcast_participant_update(session, spectator_only=True)

    if history_changed:
        await _broadcast_zone_history(session_id, session.zone_history or [])


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


async def _broadcast_zone_history(session_id: uuid.UUID, history: list[dict[str, Any]]) -> None:
    """Broadcast a full zone_history snapshot to spectators only.

    Emitted whenever the server's view of the session's zone_history
    changes. Sending the full list is self-healing: a client that missed
    an earlier message still ends up with the correct state on the next
    emission. Mods are skipped: they do not consume zone_history.
    """
    room = training_manager.get_room(session_id)
    if not room:
        return

    message = ZoneHistoryMessage(participant_id=str(session_id), history=history)
    await room.broadcast_to_spectators(message.model_dump_json())
