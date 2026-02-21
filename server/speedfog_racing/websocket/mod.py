"""WebSocket handler for mod connections."""

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

from speedfog_racing.discord import build_podium, notify_race_finished
from speedfog_racing.models import Caster, Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.grace_service import resolve_zone_query
from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_start_node,
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
from speedfog_racing.websocket.manager import (
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    AuthOkMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    SeedInfo,
    extract_spawn_items,
)
from speedfog_racing.websocket.spectator import broadcast_race_state_update

logger = logging.getLogger(__name__)


def _get_graph_json(participant: Participant) -> dict[str, Any] | None:
    """Get graph_json from participant's race seed."""
    seed = participant.race.seed
    return seed.graph_json if seed else None


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


async def _load_participant(db: AsyncSession, participant_id: uuid.UUID) -> Participant | None:
    """Load participant with all relationships needed for broadcast."""
    result = await db.execute(
        select(Participant)
        .options(*_participant_load_options())
        .where(Participant.id == participant_id)
    )
    return result.scalar_one_or_none()


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

            if manager.is_mod_connected(race_id, participant.id):
                logger.warning(
                    f"Mod duplicate connection: race={race_id}, participant={participant.id}"
                )
                await send_auth_error(websocket, "Already connected from another client")
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
                        websocket, zone, seed.graph_json, participant.zone_history, mod_locale
                    )
        # Session closed — released back to pool

        # Register connection (includes locale)
        await manager.connect_mod(race_id, participant_id, user_id, websocket, mod_locale)

        # Broadcast updated connection status to all clients
        try:
            async with session_maker() as db:
                p = await _load_participant(db, participant_id)
                if p:
                    await manager.broadcast_leaderboard(
                        race_id, p.race.participants, graph_json=_get_graph_json(p)
                    )
        except Exception:
            logger.warning(f"Failed to broadcast connect: race={race_id}")

        # Start heartbeat in background
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            # Main message loop
            while True:
                data = await websocket.receive_text()
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
                    await handle_status_update(websocket, session_maker, participant_id, msg)
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
            await manager.disconnect_mod(race_id, participant_id)
            # Broadcast updated connection status to remaining clients
            try:
                async with session_maker() as db:
                    p = await _load_participant(db, participant_id)
                    if p:
                        await manager.broadcast_leaderboard(
                            race_id, p.race.participants, graph_json=_get_graph_json(p)
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

    # Build participant list
    room = manager.get_room(race.id)
    connected_ids = set(room.mods.keys()) if room else set()
    graph = seed.graph_json if seed else None
    sorted_participants = sort_leaderboard(race.participants)
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
        ),
        seed=SeedInfo(
            seed_id=str(seed.id) if seed else None,
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,  # Mods don't need the graph
            event_ids=event_ids,
            finish_event=finish_event_id,
            spawn_items=spawn_items,
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
) -> None:
    """Handle periodic status update from mod."""
    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
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

        if participant.status == ParticipantStatus.FINISHED:
            return  # Silently drop — IGT is frozen at finish time

        if isinstance(msg.get("igt_ms"), int):
            participant.igt_ms = msg["igt_ms"]

        # Transition READY→PLAYING first so current_zone/zone_history are
        # set before death attribution (handles reconnect with deaths > 0).
        race = participant.race
        became_playing = False
        if race.status == RaceStatus.RUNNING and participant.status == ParticipantStatus.READY:
            participant.status = ParticipantStatus.PLAYING
            became_playing = True
            graph_json = _get_graph_json(participant)
            if graph_json:
                start_node = get_start_node(graph_json)
                if start_node:
                    participant.current_zone = start_node
                    participant.current_layer = 0
                    history = participant.zone_history or []
                    history.append({"node_id": start_node, "igt_ms": 0})
                    participant.zone_history = history

        new_death_count = msg.get("death_count")
        if isinstance(new_death_count, int):
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
                # Deep-copy entries so mutations don't affect the committed
                # state — SQLAlchemy compares new vs committed to detect dirt.
                history = [dict(e) for e in participant.zone_history]
                for entry in history:
                    if entry.get("node_id") == participant.current_zone:
                        entry["deaths"] = entry.get("deaths", 0) + delta
                        break
                participant.zone_history = history
            participant.death_count = new_death_count

        await db.commit()

    if became_playing:
        # READY→PLAYING: broadcast full leaderboard so all clients see the transition
        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=_get_graph_json(participant),
        )
    else:
        # Broadcast player update to spectators (detached objects)
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=_get_graph_json(participant)
        )


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

    is_finish = False
    is_revisit = False
    igt = 0
    node_id: str | None = None
    seed_graph: dict[str, Any] | None = None

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

        if participant.status == ParticipantStatus.FINISHED:
            return  # Silently drop — player already finished

        seed = participant.race.seed
        if not seed or not seed.graph_json:
            return

        seed_graph = seed.graph_json
        event_map = seed_graph.get("event_map", {})
        finish_event = seed_graph.get("finish_event")

        # Update IGT
        igt = msg.get("igt_ms", 0) if isinstance(msg.get("igt_ms"), int) else 0

        # Check finish event first (not in event_map — it's a boss kill, not a fog gate)
        if flag_id == finish_event:
            participant.igt_ms = igt
            participant.current_layer = seed.total_layers
            await db.commit()
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

            # Check if node already discovered
            old_history = participant.zone_history or []
            is_revisit = any(entry.get("node_id") == node_id for entry in old_history)

            if is_revisit:
                # Already discovered — just update position (like zone_query)
                participant.current_zone = node_id
                participant.igt_ms = igt
                await db.commit()
            else:
                # New discovery — record in history and update ranking
                participant.igt_ms = igt
                participant.current_zone = node_id
                new_entry = {"node_id": node_id, "igt_ms": igt}
                participant.zone_history = [*old_history, new_entry]

                # current_layer is a high watermark (used for ranking) — never regress
                if node_layer > participant.current_layer:
                    participant.current_layer = node_layer

                await db.commit()

    # Session closed — safe to open new sessions or broadcast

    if is_finish:
        await handle_finished(websocket, session_maker, participant_id, {"igt_ms": igt})
        return

    if not is_revisit:
        # Broadcast updated leaderboard only for new discoveries
        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=seed_graph,
        )

    # Unicast zone_update to originating mod
    if node_id and seed_graph:
        await send_zone_update(websocket, node_id, seed_graph, participant.zone_history, locale)

    # Broadcast player position to spectators (so DAG view updates)
    if is_revisit:
        await manager.broadcast_player_update(
            participant.race_id, participant, graph_json=seed_graph
        )


async def handle_zone_query(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
    locale: str = "en",
) -> None:
    """Handle zone_query from mod (loading screen exit overlay update)."""
    zq = parse_zone_query_input(msg)
    if zq is None:
        return

    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        if participant.race.status != RaceStatus.RUNNING:
            return

        if participant.status == ParticipantStatus.FINISHED:
            return  # Silently drop — player already finished

        seed = participant.race.seed
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
            zone_history=participant.zone_history,
        )
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for race %s",
                zq.grace_entity_id,
                zq.map_id,
                participant.race_id,
            )
            return

        participant.current_zone = node_id
        await db.commit()

    # Unicast zone_update to originating mod
    await send_zone_update(websocket, node_id, graph_json, participant.zone_history, locale)

    # Broadcast player update to spectators (so DAG view updates)
    await manager.broadcast_player_update(participant.race_id, participant, graph_json=graph_json)


async def handle_finished(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Handle player finish event."""
    all_finished = False
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
            return  # Already finished — idempotency guard

        participant.status = ParticipantStatus.FINISHED
        if isinstance(msg.get("igt_ms"), int):
            participant.igt_ms = msg["igt_ms"]
        participant.finished_at = datetime.now(UTC)

        # Bump current_layer to total_layers so progress displays N/N
        seed = participant.race.seed
        if seed:
            participant.current_layer = seed.total_layers

        await db.commit()
        logger.info(f"Participant finished: {participant.id}, igt={participant.igt_ms}ms")

        # Re-load to get fresh race status/version + all participants
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        all_finished = all(
            p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
            for p in participant.race.participants
        )

        if all_finished:
            # Optimistic locking: atomically transition RUNNING → FINISHED
            race_obj = participant.race
            result = await db.execute(
                update(Race)
                .where(
                    Race.id == race_obj.id,
                    Race.status == RaceStatus.RUNNING,
                    Race.version == race_obj.version,
                )
                .values(status=RaceStatus.FINISHED, version=race_obj.version + 1)
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                logger.warning(
                    f"Race {participant.race_id} already transitioned (concurrent update)"
                )
                await db.commit()
            else:
                race_obj.status = RaceStatus.FINISHED
                race_obj.version += 1
                await db.commit()
                logger.info(f"Race finished: {participant.race_id}")
                race_transitioned = True

    # Session closed — all broadcasts use detached objects

    if race_transitioned:
        # Push race_state to spectators BEFORE status change so the client
        # receives status=finished + zone_history atomically in one message.
        await broadcast_race_state_update(participant.race_id, participant.race)
        await manager.broadcast_race_status(participant.race_id, "finished")

        # Fire-and-forget Discord notification (public races only)
        race_obj = participant.race
        if race_obj.is_public:
            task = asyncio.create_task(
                notify_race_finished(
                    race_name=race_obj.name,
                    race_id=str(race_obj.id),
                    pool_name=race_obj.seed.pool_name if race_obj.seed else None,
                    participant_count=len(race_obj.participants),
                    podium=build_podium(race_obj.participants),
                )
            )
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    await manager.broadcast_leaderboard(
        participant.race_id,
        participant.race.participants,
        graph_json=_get_graph_json(participant),
    )


async def broadcast_race_start(
    race_id: uuid.UUID,
    started_at: str | None = None,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """Broadcast race start to all connections (mods + spectators)."""
    room = manager.get_room(race_id)
    if room:
        # Send race_start to mods
        message = RaceStartMessage()
        await room.broadcast_to_mods(message.model_dump_json())

        # Send zone_update for start node to each connected mod
        if graph_json:
            start_node = get_start_node(graph_json)
            if start_node:
                for conn in room.mods.values():
                    await send_zone_update(
                        conn.websocket, start_node, graph_json, None, conn.locale
                    )

        # Also notify spectators of status change
        await manager.broadcast_race_status(race_id, "running", started_at=started_at)
        logger.info(f"Race start broadcast: race={race_id}")
