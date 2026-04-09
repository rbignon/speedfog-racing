"""WebSocket handler for mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.discord import fire_race_finished_notifications
from speedfog_racing.models import (
    Caster,
    ChatChannel,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
)
from speedfog_racing.services.grace_service import resolve_zone_query
from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_start_node,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
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
from speedfog_racing.websocket.manager import (
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    AuthOkMessage,
    DeathCountsMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    SeedInfo,
    extract_spawn_items,
    persist_system_chat,
)
from speedfog_racing.websocket.spectator import broadcast_race_state_update, load_chat_history

logger = logging.getLogger(__name__)

# Shared entrances (DuplicateEntrance in FogMod) inject multiple SetEventFlag
# instructions for the same warp, all resolving to the same node_id via event_map.
# The mod sends each flag as a separate WebSocket message within a single frame,
# so they arrive with near-identical IGT. This tolerance window deduplicates them.
SHARED_ENTRANCE_DEDUP_MS = 1000


def is_shared_entrance_duplicate(history: list[dict[str, Any]], node_id: str, igt: int) -> bool:
    """Check if this event flag is a duplicate from shared entrance multi-flag injection."""
    return bool(
        history
        and history[-1].get("node_id") == node_id
        and abs(history[-1].get("igt_ms", 0) - igt) <= SHARED_ENTRANCE_DEDUP_MS
    )


def _is_countdown_active(race: Race) -> bool:
    """Check if the race is still in the countdown period after starting."""
    if not race.started_at or settings.countdown_seconds <= 0:
        return False
    started = race.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    effective_start = started + timedelta(seconds=settings.countdown_seconds)
    return datetime.now(UTC) < effective_start


def _get_graph_json(participant: Participant) -> dict[str, Any] | None:
    """Get graph_json from participant's race seed."""
    seed = participant.race.seed
    return seed.graph_json if seed else None


def _set_layer(participant: Participant, new_layer: int, entry_igt: int) -> None:
    """Set current_layer and record its entry IGT (first-write-wins).

    A fresh dict is assigned so SQLAlchemy picks up the change on JSON
    columns (in-place mutation is not auto-tracked).
    """
    participant.current_layer = new_layer
    entries = dict(participant.layer_entry_igts or {})
    key = str(new_layer)
    if key not in entries:
        entries[key] = entry_igt
        participant.layer_entry_igts = entries


def _participant_load_options() -> list[Any]:
    """Eager-load options for loading a participant with all broadcast data."""
    return [
        selectinload(Participant.user),
        selectinload(Participant.race).selectinload(Race.seed),
        selectinload(Participant.race)
        .selectinload(Race.participants)
        .selectinload(Participant.user),
        selectinload(Participant.race).selectinload(Race.casters).selectinload(Caster.user),
    ]


def _participant_light_load_options() -> list[Any]:
    """Eager-load options for participant without other participants/casters.

    Sufficient for processing a single message and broadcasting a
    player_update. Handlers that need the full participant list (for
    leaderboard broadcasts or death aggregation) should call
    _load_participant instead.
    """
    return [
        selectinload(Participant.user),
        selectinload(Participant.race).selectinload(Race.seed),
    ]


async def _load_participant(db: AsyncSession, participant_id: uuid.UUID) -> Participant | None:
    """Load participant with all relationships needed for broadcast."""
    result = await db.execute(
        select(Participant)
        .options(*_participant_load_options())
        .where(Participant.id == participant_id)
    )
    return result.scalar_one_or_none()


async def _load_race_participants(db: AsyncSession, race_id: uuid.UUID) -> list[Participant]:
    """Load a race's participants (with users) for leaderboard broadcast.

    Cheaper than _load_participant: skips the disconnecting participant's
    own eager tree, the seed, and the casters. The caller must supply
    graph_json from an earlier load (it does not change during a race).
    """
    result = await db.execute(
        select(Race)
        .where(Race.id == race_id)
        .options(selectinload(Race.participants).selectinload(Participant.user))
    )
    race = result.scalar_one_or_none()
    return list(race.participants) if race else []


async def _load_participant_light(
    db: AsyncSession, participant_id: uuid.UUID
) -> Participant | None:
    """Load participant with minimal relationships (no other participants/casters)."""
    result = await db.execute(
        select(Participant)
        .options(*_participant_light_load_options())
        .where(Participant.id == participant_id)
    )
    return result.scalar_one_or_none()


async def _load_participant_no_seed(
    db: AsyncSession, participant_id: uuid.UUID
) -> Participant | None:
    """Load participant with User + Race (without seed/casters).

    Callers that already hold a cached graph_json do not need race.seed.
    This saves one selectinload chain compared to _load_participant_light.
    """
    result = await db.execute(
        select(Participant)
        .options(
            selectinload(Participant.user),
            selectinload(Participant.race),
        )
        .where(Participant.id == participant_id)
    )
    return result.scalar_one_or_none()


def aggregate_death_counts(participants: list[Participant]) -> dict[str, int]:
    """Aggregate deaths per node_id across all participants' zone_history."""
    counts: dict[str, int] = {}
    for p in participants:
        for entry in p.zone_history or []:
            deaths = entry.get("deaths", 0)
            if deaths > 0:
                node_id = entry.get("node_id")
                if node_id:
                    counts[node_id] = counts.get(node_id, 0) + deaths
    return counts


async def handle_mod_websocket(
    websocket: WebSocket,
    race_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle a mod WebSocket connection."""
    await websocket.accept()

    participant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    mod_locale: str = "en"
    # graph_json is immutable during a race; cache at connect time so the
    # disconnect broadcast does not need to reload the seed.
    connect_graph_json: dict[str, Any] | None = None

    try:
        # Wait for auth message with timeout
        try:
            auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=MOD_AUTH_TIMEOUT)
        except TimeoutError:
            logger.warning(f"Mod auth timeout: race={race_id}")
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

        # Auth phase: open session, authenticate, send auth_ok, close session
        async with session_maker() as db:
            participant = await authenticate_mod(db, race_id, mod_token)
            if not participant:
                logger.warning(f"Mod auth failed: race={race_id}, invalid token")
                await send_auth_error(websocket, "Invalid mod token or race")
                return

            race = participant.race
            if race.status == RaceStatus.FINISHED:
                logger.info(
                    f"Mod rejected (race finished): race={race_id}, user={participant.user_id}"
                )
                await send_auth_error(websocket, "Race has already finished")
                return

            # Keep IDs for use after session closes
            participant_id = participant.id
            user_id = participant.user_id

            # Resolve locale from user preference
            if participant.user.locale:
                mod_locale = participant.user.locale

            await send_auth_ok(websocket, participant)

            # Send zone_update on reconnect (race already running)
            seed = participant.race.seed
            if participant.race.status == RaceStatus.RUNNING and seed and seed.graph_json:
                zone = participant.current_zone or get_start_node(seed.graph_json)
                if zone:
                    await send_zone_update(
                        websocket,
                        zone,
                        seed.graph_json,
                        participant.zone_history,
                        mod_locale,
                        race_id=race_id,
                        participant_id=participant_id,
                    )

                # Send current death counts on reconnect
                counts = aggregate_death_counts(race.participants)
                if counts:
                    await websocket.send_text(DeathCountsMessage(counts=counts).model_dump_json())
        # Session closed, released back to pool

        # Cache graph_json (immutable during a race) for later reuse in
        # the disconnect broadcast, avoiding a seed reload.
        connect_graph_json = _get_graph_json(participant)

        # Register connection (includes locale)
        await manager.connect_mod(race_id, participant_id, user_id, websocket, mod_locale)

        # Broadcast updated connection status (reuse detached objects from auth session)
        try:
            await manager.broadcast_leaderboard(
                race_id, participant.race.participants, graph_json=connect_graph_json
            )
        except Exception:
            logger.warning(f"Failed to broadcast connect: race={race_id}")

        # Start heartbeat in background
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))
        rate_limiter = MessageRateLimiter()

        try:
            # Main message loop
            while True:
                data = await websocket.receive_text()

                if not rate_limiter.check():
                    logger.warning(
                        "Rate limit exceeded: race=%s, participant=%s", race_id, participant_id
                    )
                    await websocket.close(code=4008, reason="Rate limit exceeded")
                    return

                try:
                    msg = json.loads(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from mod (ignored): {e}")
                    continue

                msg_type = msg.get("type")

                if msg_type == "pong":
                    pass  # Heartbeat response, no action needed
                elif msg_type == "ready":
                    await handle_ready(session_maker, participant_id)
                elif msg_type == "status_update":
                    await handle_status_update(
                        websocket,
                        session_maker,
                        participant_id,
                        msg,
                        cached_graph_json=connect_graph_json,
                    )
                elif msg_type == "event_flag":
                    await handle_event_flag(
                        websocket, session_maker, participant_id, msg, mod_locale
                    )
                elif msg_type == "finished":
                    await handle_finished(websocket, session_maker, participant_id, msg)
                elif msg_type == "zone_query":
                    await handle_zone_query(
                        websocket, session_maker, participant_id, msg, mod_locale
                    )
                else:
                    logger.warning(f"Unknown message type: {msg_type}")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Mod disconnected: race={race_id}")
    except Exception:
        logger.exception(f"Error in mod websocket: race={race_id}")
    finally:
        if participant_id:
            await manager.disconnect_mod(race_id, participant_id, websocket)
            # Broadcast updated connection status to remaining clients.
            # Reload only Race.participants (+users), reuse the cached
            # graph_json; skip the seed and casters eager loads.
            try:
                async with session_maker() as db:
                    participants = await _load_race_participants(db, race_id)
                    if participants:
                        await manager.broadcast_leaderboard(
                            race_id, participants, graph_json=connect_graph_json
                        )
            except Exception:
                logger.warning(f"Failed to broadcast disconnect: race={race_id}")


async def authenticate_mod(
    db: AsyncSession, race_id: uuid.UUID, mod_token: str
) -> Participant | None:
    """Authenticate a mod connection by token."""
    result = await db.execute(
        select(Participant)
        .options(*_participant_load_options())
        .where(Participant.race_id == race_id, Participant.mod_token == mod_token)
    )
    return result.scalar_one_or_none()


async def send_auth_ok(websocket: WebSocket, participant: Participant) -> None:
    """Send successful auth response with race state."""
    race = participant.race
    seed = race.seed

    # Extract event_ids and finish_event from graph_json
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

    # Build participant list
    room = manager.get_room(race.id)
    connected_ids = set(room.mods.keys()) if room else set()
    graph = seed.graph_json if seed else None
    sorted_participants, _ = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(p, connected_ids=connected_ids, graph_json=graph)
        for p in sorted_participants
    ]

    message = AuthOkMessage(
        participant_id=str(participant.id),
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
            started_at=race.started_at.isoformat() if race.started_at else None,
            seeds_released_at=(
                race.seeds_released_at.isoformat() if race.seeds_released_at else None
            ),
            countdown_seconds=settings.countdown_seconds,
        ),
        seed=SeedInfo(
            seed_id=str(seed.id) if seed else None,
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,  # Mods don't need the graph
            event_ids=event_ids,
            finish_event=finish_event_id,
            spawn_items=spawn_items,
            death_flags=death_flags,
            items_spawned_flag=items_spawned_flag,
        ),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())


async def handle_ready(
    session_maker: async_sessionmaker[AsyncSession], participant_id: uuid.UUID
) -> None:
    """Handle player ready signal."""
    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        if participant.status != ParticipantStatus.REGISTERED:
            return

        participant.status = ParticipantStatus.READY
        await db.commit()
        logger.info(f"Participant ready: {participant.id}")

    # Broadcast leaderboard update (detached objects, readable thanks to expire_on_commit=False)
    await manager.broadcast_leaderboard(
        participant.race_id,
        participant.race.participants,
        graph_json=_get_graph_json(participant),
    )


async def handle_status_update(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
    *,
    cached_graph_json: dict[str, Any] | None = None,
) -> None:
    """Handle periodic status update from mod.

    Uses a minimal DB load (participant + user only) for the common path
    when ``cached_graph_json`` is supplied (saves the race.seed eager
    load on every tick). Falls back to the light load when no cache.
    Only reloads with full relationships when a leaderboard broadcast or
    death aggregation is needed.
    """
    delta = 0
    became_playing = False
    history_changed = False

    async with session_maker() as db:
        if cached_graph_json is not None:
            participant = await _load_participant_no_seed(db, participant_id)
        else:
            participant = await _load_participant_light(db, participant_id)
        if not participant:
            return

        if participant.race.status != RaceStatus.RUNNING:
            logger.warning(
                "Rejected status_update: race=%s status=%s",
                participant.race_id,
                participant.race.status.value,
            )
            await send_error(websocket, "Race not running")
            return

        if participant.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
            return  # Silently drop: IGT is frozen

        # Silently drop status updates during countdown period
        if _is_countdown_active(participant.race):
            return

        # Gate: reject stale saves (pre-existing save with high IGT)
        igt_ms_val = clamp_igt(msg.get("igt_ms"))
        if (
            igt_ms_val is not None
            and participant.status == ParticipantStatus.READY
            and igt_ms_val > MAX_FRESH_IGT_MS
        ):
            logger.warning(
                "Rejected stale save: participant=%s igt_ms=%d",
                participant_id,
                igt_ms_val,
            )
            await send_error(websocket, "Please start a New Game to race")
            return

        if igt_ms_val is not None:
            if igt_ms_val != participant.igt_ms:
                participant.last_igt_change_at = datetime.now(UTC)
            participant.igt_ms = igt_ms_val

        # Transition READY→PLAYING first so current_zone/zone_history are
        # set before death attribution (handles reconnect with deaths > 0).
        race = participant.race
        if race.status == RaceStatus.RUNNING and participant.status == ParticipantStatus.READY:
            participant.status = ParticipantStatus.PLAYING
            became_playing = True
            graph_json = (
                cached_graph_json if cached_graph_json is not None else _get_graph_json(participant)
            )
            if graph_json:
                start_node = get_start_node(graph_json)
                if start_node:
                    participant.current_zone = start_node
                    _set_layer(participant, 0, 0)
                    history = participant.zone_history or []
                    history.append({"node_id": start_node, "igt_ms": 0, "type": "spawn"})
                    participant.zone_history = history
                    history_changed = True

        new_death_count = clamp_death_count(msg.get("death_count"))
        if new_death_count is not None:
            delta = new_death_count - participant.death_count
            if delta < 0:
                logger.warning(
                    "Negative death delta %d for participant %s (stored=%d, received=%d)",
                    delta,
                    participant.id,
                    participant.death_count,
                    new_death_count,
                )
            if delta > 0 and participant.current_zone and participant.zone_history:
                new_history = attribute_deaths(
                    participant.zone_history, participant.current_zone, delta
                )
                participant.zone_history = new_history
                history_changed = True
            participant.death_count = new_death_count

        await db.commit()

    # Common path: only a player_update (no full participant list needed).
    # Use the cached graph_json so the common path never touches race.seed.
    # cached_graph_json was captured at connect time and is immutable during
    # the session (None when no seed is assigned, stable too).
    if not became_playing and delta <= 0:
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=cached_graph_json
        )
        return

    # Uncommon path: reload with full relationships for leaderboard/death broadcasts
    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

    if became_playing:
        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=_get_graph_json(participant),
        )
    else:
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=_get_graph_json(participant)
        )

    if history_changed:
        await manager.broadcast_zone_history(
            participant.race_id, participant.id, participant.zone_history or []
        )

    if delta > 0:
        counts = aggregate_death_counts(participant.race.participants)
        logger.info(
            "Broadcasting death_counts: race=%s, counts=%s",
            participant.race_id,
            counts,
        )
        room = manager.get_room(participant.race_id)
        if room:
            await room.broadcast_to_mods(DeathCountsMessage(counts=counts).model_dump_json())


async def handle_event_flag(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
    locale: str = "en",
) -> None:
    """Handle event flag trigger from mod."""
    flag_id = msg.get("flag_id")
    if not isinstance(flag_id, int):
        return
    raw_message_id = msg.get("message_id")
    message_id = raw_message_id if isinstance(raw_message_id, int) else None

    is_finish = False
    is_first_visit = False
    igt = 0
    node_id: str | None = None
    seed_graph: dict[str, Any] | None = None
    history_changed = False

    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        if participant.race.status != RaceStatus.RUNNING:
            logger.warning(
                "Rejected event_flag: race=%s status=%s",
                participant.race_id,
                participant.race.status.value,
            )
            await send_error(websocket, "Race not running")
            return

        # Guard: reject event flags received during countdown period
        if _is_countdown_active(participant.race):
            logger.warning(
                "Rejected event_flag during countdown: race=%s",
                participant.race_id,
            )
            await send_error(websocket, "Race countdown in progress")
            return

        if participant.status != ParticipantStatus.PLAYING:
            # ACK replayed event flags so the mod clears its in-flight set
            # (e.g. finish event committed but ACK lost before disconnect).
            if message_id is not None:
                await send_event_flag_ack(websocket, message_id)
            return

        seed = participant.race.seed
        if not seed or not seed.graph_json:
            return

        seed_graph = seed.graph_json
        event_map = seed_graph.get("event_map", {})
        finish_event = seed_graph.get("finish_event")

        # Update IGT
        raw_igt = clamp_igt(msg.get("igt_ms"))
        igt = raw_igt if raw_igt is not None else 0

        # Check finish event first (not in event_map, it's a boss kill, not a fog gate)
        if flag_id == finish_event:
            participant.last_igt_change_at = datetime.now(UTC)
            participant.igt_ms = igt
            _set_layer(participant, seed.total_layers, igt)
            await db.commit()
            if message_id is not None:
                await send_event_flag_ack(websocket, message_id)
            is_finish = True
            # Exit session block before calling handle_finished to avoid
            # nested sessions (deadlocks SQLite in tests)
        else:
            # Resolve flag_id to node_id
            node_id = event_map.get(str(flag_id))
            if node_id is None:
                logger.warning(f"Unknown event flag {flag_id} from participant {participant_id}")
                return

            # Resolve layer for this node
            node_layer = get_layer_for_node(node_id, seed_graph)

            old_history = participant.zone_history or []

            if message_id is not None and any(
                entry.get("type", "fog") == "fog" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                await send_event_flag_ack(websocket, message_id)
                return

            if is_shared_entrance_duplicate(old_history, node_id, igt):
                return

            if len(old_history) >= MAX_ZONE_HISTORY:
                logger.warning("zone_history cap reached for participant %s", participant_id)
                return

            is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)

            # Always append to zone_history (including revisits/backtracks)
            participant.last_igt_change_at = datetime.now(UTC)
            participant.igt_ms = igt
            participant.current_zone = node_id
            new_entry: dict[str, Any] = {"node_id": node_id, "igt_ms": igt, "type": "fog"}
            if message_id is not None:
                new_entry["message_id"] = message_id
            participant.zone_history = [*old_history, new_entry]
            history_changed = True

            # current_layer is a high watermark (used for ranking), never regress
            if node_layer > participant.current_layer:
                _set_layer(participant, node_layer, igt)

            await db.commit()
            if message_id is not None:
                await send_event_flag_ack(websocket, message_id)

    # Session closed. Safe to open new sessions or broadcast.

    if is_finish:
        await handle_finished(websocket, session_maker, participant_id, {"igt_ms": igt})
        return

    if is_first_visit:
        # Broadcast updated leaderboard only for new discoveries
        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=seed_graph,
        )
    else:
        # Revisit: broadcast player position update only
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=seed_graph
        )

    if history_changed:
        await manager.broadcast_zone_history(
            participant.race_id, participant.id, participant.zone_history or []
        )

    # Unicast zone_update to originating mod
    if node_id and seed_graph:
        await send_zone_update(
            websocket,
            node_id,
            seed_graph,
            participant.zone_history,
            locale,
            is_first_visit=is_first_visit,
            race_id=participant.race_id,
            participant_id=participant_id,
        )


async def handle_zone_query(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
    locale: str = "en",
) -> None:
    """Handle zone_query from mod (loading screen exit overlay update).

    When the resolved node differs from current_zone, this records a
    zone_history entry (backtrack via death/teleport/quit-out).
    """
    raw_message_id = msg.get("message_id")
    message_id: int | None = raw_message_id if isinstance(raw_message_id, int) else None

    zq = parse_zone_query_input(msg)
    if zq is None:
        if message_id is not None:
            await send_zone_query_ack(websocket, message_id)
        return

    is_first_visit = False
    history_changed = False

    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        if participant.race.status != RaceStatus.RUNNING:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        if _is_countdown_active(participant.race):
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        if participant.status != ParticipantStatus.PLAYING:
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return  # Only PLAYING participants can trigger zone queries

        seed = participant.race.seed
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
            zone_history=participant.zone_history,
        )
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for race %s",
                zq.grace_entity_id,
                zq.map_id,
                participant.race_id,
            )
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return

        # Record zone_history entry when the player moved to a different node
        # (backtrack via death/teleport/quit-out, no event flag fired)
        if node_id != participant.current_zone:
            logger.info(
                "zone_query backtrack: %s -> %s for participant %s",
                participant.current_zone,
                node_id,
                participant_id,
            )
            igt = zq.igt_ms if zq.igt_ms is not None else participant.igt_ms
            old_history = participant.zone_history or []

            # Dedup: if this message_id was already persisted, skip to zone_update
            if message_id is not None and any(
                entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                pass  # Dedup: already persisted, skip to zone_update
            elif len(old_history) >= MAX_ZONE_HISTORY:
                logger.warning("zone_history cap reached for participant %s", participant_id)
            else:
                is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)

                participant.last_igt_change_at = datetime.now(UTC)
                participant.igt_ms = igt
                new_entry: dict[str, Any] = {
                    "node_id": node_id,
                    "igt_ms": igt,
                    "type": "backtrack",
                }
                if message_id is not None:
                    new_entry["message_id"] = message_id
                participant.zone_history = [*old_history, new_entry]
                history_changed = True

            # current_layer is a high watermark, never regress
            node_layer = get_layer_for_node(node_id, graph_json)
            if node_layer > participant.current_layer:
                _set_layer(participant, node_layer, igt)

        participant.current_zone = node_id
        await db.commit()

    # Unicast zone_update to originating mod
    await send_zone_update(
        websocket,
        node_id,
        graph_json,
        participant.zone_history,
        locale,
        is_first_visit=is_first_visit,
        race_id=participant.race_id,
        participant_id=participant_id,
        message_id=message_id,
    )

    # Broadcast based on whether this was a first visit or revisit
    if is_first_visit:
        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=graph_json,
        )
    else:
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=graph_json
        )

    if history_changed:
        await manager.broadcast_zone_history(
            participant.race_id, participant.id, participant.zone_history or []
        )


async def handle_finished(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Handle player finish event."""
    race_transitioned = False

    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        if participant.race.status != RaceStatus.RUNNING:
            logger.warning(
                "Rejected finished: race=%s status=%s",
                participant.race_id,
                participant.race.status.value,
            )
            await send_error(websocket, "Race not running")
            return

        if participant.status == ParticipantStatus.FINISHED:
            return  # Already finished (idempotency guard)

        participant.status = ParticipantStatus.FINISHED
        finished_igt = clamp_igt(msg.get("igt_ms"))
        if finished_igt is not None:
            participant.igt_ms = finished_igt
        participant.finished_at = datetime.now(UTC)

        # Bump current_layer to total_layers so progress displays N/N
        seed = participant.race.seed
        if seed:
            _set_layer(participant, seed.total_layers, participant.igt_ms)

        await db.commit()
        logger.info(f"Participant finished: {participant.id}, igt={participant.igt_ms}ms")

        # Re-load to get fresh race status/version + all participants
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        race_transitioned = await check_race_auto_finish(db, participant.race)
        if race_transitioned:
            logger.info("Race finished: %s", participant.race_id)

    # Session closed. All broadcasts use detached objects.

    if race_transitioned:
        # Push race_state to spectators BEFORE status change so the client
        # receives status=finished + zone_history atomically in one message.
        await broadcast_race_state_update(participant.race_id, participant.race)
        await manager.broadcast_race_status(participant.race_id, "finished")
        fire_race_finished_notifications(participant.race)

    await manager.broadcast_leaderboard(
        participant.race_id,
        participant.race.participants,
        graph_json=_get_graph_json(participant),
    )

    # Notify public chat (persisted) + unlock PUBLIC channel for finished participant
    display = participant.user.twitch_display_name or participant.user.twitch_username
    async with session_maker() as db:
        sys_json = await persist_system_chat(
            db, participant.race_id, ChatChannel.PUBLIC, f"{display} has finished the race!"
        )
        await db.commit()
    room = manager.get_room(participant.race_id)
    if room:
        await room.broadcast_chat_public(sys_json)
        spec_conn = room.get_spectator_by_user_id(participant.user_id)
        if spec_conn and spec_conn.is_playing:
            spec_conn.is_playing = False
            try:
                hist = await load_chat_history(
                    session_maker,
                    participant.race_id,
                    participant.race,
                    ChatChannel.PUBLIC,
                )
                await spec_conn.websocket.send_text(hist.model_dump_json())
            except Exception:
                logger.warning("Failed to send public chat history to finished participant")


async def broadcast_race_start(
    race_id: uuid.UUID,
    started_at: str | None = None,
    graph_json: dict[str, Any] | None = None,
    countdown_seconds: int = 0,
) -> None:
    """Broadcast race start to all connections (mods + spectators)."""
    room = manager.get_room(race_id)
    if room:
        # Send race_start to mods
        message = RaceStartMessage(countdown_seconds=countdown_seconds)
        await room.broadcast_to_mods(message.model_dump_json())

        # Send zone_update for start node to each connected mod
        if graph_json:
            start_node = get_start_node(graph_json)
            if start_node:
                for conn in room.mods.values():
                    await send_zone_update(
                        conn.websocket,
                        start_node,
                        graph_json,
                        None,
                        conn.locale,
                        is_first_visit=True,
                        race_id=race_id,
                        participant_id=conn.participant_id,
                    )

        # Also notify spectators of status change
        await manager.broadcast_race_status(
            race_id, "running", started_at=started_at, countdown_seconds=countdown_seconds
        )
        logger.info(f"Race start broadcast: race={race_id}")
