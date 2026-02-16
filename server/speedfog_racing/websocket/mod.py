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

from speedfog_racing.models import Caster, Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.layer_service import (
    compute_zone_update,
    get_layer_for_node,
    get_start_node,
)
from speedfog_racing.websocket.manager import (
    SEND_TIMEOUT,
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    AuthOkMessage,
    ErrorMessage,
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStartMessage,
    SeedInfo,
    SpawnItem,
)
from speedfog_racing.websocket.spectator import broadcast_race_state_update

logger = logging.getLogger(__name__)

MOD_AUTH_TIMEOUT = 5.0  # seconds to wait for auth message
HEARTBEAT_INTERVAL = 30.0  # seconds between pings


def _get_graph_json(participant: Participant) -> dict[str, Any] | None:
    """Get graph_json from participant's race seed."""
    seed = participant.race.seed
    return seed.graph_json if seed else None


async def send_zone_update(
    websocket: WebSocket,
    node_id: str,
    graph_json: dict[str, Any],
    zone_history: list[dict[str, Any]] | None,
) -> None:
    """Send a zone_update unicast to the originating mod."""
    msg = compute_zone_update(node_id, graph_json, zone_history)
    if msg:
        try:
            await asyncio.wait_for(websocket.send_text(json.dumps(msg)), timeout=SEND_TIMEOUT)
        except Exception:
            logger.warning("Failed to send zone_update")


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

    try:
        # Wait for auth message with timeout
        try:
            auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=MOD_AUTH_TIMEOUT)
        except TimeoutError:
            logger.warning(f"Mod auth timeout: race={race_id}")
            await websocket.close(code=4001, reason="Auth timeout")
            return

        auth_msg = json.loads(auth_data)

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

            await send_auth_ok(websocket, participant)

            # Send zone_update on reconnect (race already running)
            seed = participant.race.seed
            if participant.race.status == RaceStatus.RUNNING and seed and seed.graph_json:
                zone = participant.current_zone or get_start_node(seed.graph_json)
                if zone:
                    await send_zone_update(
                        websocket, zone, seed.graph_json, participant.zone_history
                    )
        # Session closed — released back to pool

        # Register connection
        await manager.connect_mod(race_id, participant_id, user_id, websocket)

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
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

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
                    await handle_event_flag(websocket, session_maker, participant_id, msg)
                elif msg_type == "finished":
                    await handle_finished(websocket, session_maker, participant_id, msg)
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
    except Exception as e:
        logger.error(f"Error in mod websocket: {e}")
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


async def _heartbeat_loop(websocket: WebSocket) -> None:
    """Send periodic ping messages to the mod."""
    ping_json = PingMessage().model_dump_json()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await asyncio.wait_for(websocket.send_text(ping_json), timeout=SEND_TIMEOUT)
    except Exception:
        # Connection lost — close so the main loop's receive_text() raises WebSocketDisconnect
        try:
            await websocket.close()
        except Exception:
            pass


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


async def send_auth_error(websocket: WebSocket, message: str) -> None:
    """Send auth error and close connection."""
    error = AuthErrorMessage(message=message)
    await websocket.send_text(error.model_dump_json())
    await websocket.close()


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send a generic error message to the mod."""
    error = ErrorMessage(message=message)
    try:
        await asyncio.wait_for(websocket.send_text(error.model_dump_json()), timeout=SEND_TIMEOUT)
    except Exception:
        pass


async def send_auth_ok(websocket: WebSocket, participant: Participant) -> None:
    """Send successful auth response with race state."""
    race = participant.race
    seed = race.seed

    # Extract event_ids from graph_json (event_map gates + finish_event)
    event_ids: list[int] = []
    if seed and seed.graph_json:
        event_map = seed.graph_json.get("event_map", {})
        if event_map:
            event_ids = sorted(int(k) for k in event_map.keys())
            finish = seed.graph_json.get("finish_event")
            if isinstance(finish, int) and finish not in event_ids:
                event_ids.append(finish)

    # Extract gem items from care_package for runtime spawning by the mod
    spawn_items: list[SpawnItem] = []
    if seed and seed.graph_json:
        care_pkg = seed.graph_json.get("care_package", [])
        spawn_items = [
            SpawnItem(id=item["id"], qty=1)
            for item in care_pkg
            if item.get("type") == 4 and item.get("id", 0) != 0
        ]

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
        ),
        seed=SeedInfo(
            seed_id=str(seed.id) if seed else None,
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,  # Mods don't need the graph
            event_ids=event_ids,
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
            await _send_error(websocket, "Race not running")
            return

        if isinstance(msg.get("igt_ms"), int):
            participant.igt_ms = msg["igt_ms"]
        if isinstance(msg.get("death_count"), int):
            participant.death_count = msg["death_count"]

        race = participant.race
        if race.status == RaceStatus.RUNNING and participant.status == ParticipantStatus.READY:
            participant.status = ParticipantStatus.PLAYING
            graph_json = _get_graph_json(participant)
            if graph_json:
                start_node = get_start_node(graph_json)
                if start_node:
                    participant.current_zone = start_node
                    participant.current_layer = 0
                    history = participant.zone_history or []
                    history.append({"node_id": start_node, "igt_ms": 0})
                    participant.zone_history = history

        await db.commit()

    # Broadcast player update to spectators (detached objects)
    await manager.broadcast_player_update(
        participant.race_id, participant, graph_json=_get_graph_json(participant)
    )


async def handle_event_flag(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Handle event flag trigger from mod."""
    flag_id = msg.get("flag_id")
    if not isinstance(flag_id, int):
        return

    is_finish = False
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
            await _send_error(websocket, "Race not running")
            return

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

            # Check if node already discovered (ignore duplicates)
            old_history = participant.zone_history or []
            if any(entry.get("node_id") == node_id for entry in old_history):
                return  # Already discovered

            # Record the node and update current position
            participant.igt_ms = igt
            participant.current_zone = node_id
            entry = {"node_id": node_id, "igt_ms": igt}
            participant.zone_history = [*old_history, entry]

            # current_layer is a high watermark (used for ranking) — never regress
            if node_layer > participant.current_layer:
                participant.current_layer = node_layer

            await db.commit()

    # Session closed — safe to open new sessions or broadcast

    if is_finish:
        await handle_finished(websocket, session_maker, participant_id, {"igt_ms": igt})
        return

    # Broadcast updated leaderboard (detached objects)
    await manager.broadcast_leaderboard(
        participant.race_id,
        participant.race.participants,
        graph_json=seed_graph,
    )

    # Unicast zone_update to originating mod
    if node_id and seed_graph:
        await send_zone_update(websocket, node_id, seed_graph, participant.zone_history)


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
            await _send_error(websocket, "Race not running")
            return

        participant.status = ParticipantStatus.FINISHED
        if isinstance(msg.get("igt_ms"), int):
            participant.igt_ms = msg["igt_ms"]
        participant.finished_at = datetime.now(UTC)

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
                        conn.websocket, start_node, graph_json, zone_history=None
                    )

        # Also notify spectators of status change
        await manager.broadcast_race_status(race_id, "running", started_at=started_at)
        logger.info(f"Race start broadcast: race={race_id}")
