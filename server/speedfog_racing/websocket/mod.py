"""WebSocket handler for mod connections."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.layer_service import get_layer_for_node
from speedfog_racing.websocket.manager import manager, participant_to_info, sort_leaderboard
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    AuthOkMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    SeedInfo,
)
from speedfog_racing.websocket.spectator import broadcast_race_state_update

logger = logging.getLogger(__name__)


async def handle_mod_websocket(websocket: WebSocket, race_id: uuid.UUID, db: AsyncSession) -> None:
    """Handle a mod WebSocket connection."""
    await websocket.accept()

    participant: Participant | None = None

    try:
        # Wait for auth message
        auth_data = await websocket.receive_text()
        auth_msg = json.loads(auth_data)

        if auth_msg.get("type") != "auth" or "mod_token" not in auth_msg:
            await send_auth_error(websocket, "Invalid auth message")
            return

        mod_token = auth_msg["mod_token"]

        # Validate mod token and get participant
        participant = await authenticate_mod(db, race_id, mod_token)
        if not participant:
            await send_auth_error(websocket, "Invalid mod token or race")
            return

        # Check race status
        race = participant.race
        if race.status == RaceStatus.FINISHED:
            await send_auth_error(websocket, "Race has already finished")
            return

        # Check for duplicate connections
        if manager.is_mod_connected(race_id, participant.id):
            await send_auth_error(websocket, "Already connected from another client")
            return

        # Send auth_ok with race state
        await send_auth_ok(websocket, participant)

        # Register connection
        await manager.connect_mod(race_id, participant.id, participant.user_id, websocket)

        # Main message loop
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from mod (ignored): {e}")
                continue

            msg_type = msg.get("type")

            if msg_type == "ready":
                await handle_ready(db, participant)
            elif msg_type == "status_update":
                await handle_status_update(db, participant, msg)
            elif msg_type == "event_flag":
                await handle_event_flag(db, participant, msg)
            elif msg_type == "finished":
                await handle_finished(db, participant, msg)
            else:
                logger.warning(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"Mod disconnected: race={race_id}")
    except Exception as e:
        logger.error(f"Error in mod websocket: {e}")
    finally:
        if participant:
            await manager.disconnect_mod(race_id, participant.id)


async def authenticate_mod(
    db: AsyncSession, race_id: uuid.UUID, mod_token: str
) -> Participant | None:
    """Authenticate a mod connection by token."""
    result = await db.execute(
        select(Participant)
        .options(
            selectinload(Participant.user),
            selectinload(Participant.race).selectinload(Race.seed),
            selectinload(Participant.race)
            .selectinload(Race.participants)
            .selectinload(Participant.user),
        )
        .where(Participant.race_id == race_id, Participant.mod_token == mod_token)
    )
    return result.scalar_one_or_none()


async def send_auth_error(websocket: WebSocket, message: str) -> None:
    """Send auth error and close connection."""
    error = AuthErrorMessage(message=message)
    await websocket.send_text(error.model_dump_json())
    await websocket.close()


async def send_auth_ok(websocket: WebSocket, participant: Participant) -> None:
    """Send successful auth response with race state."""
    race = participant.race
    seed = race.seed

    # Extract event_ids from graph_json
    event_ids = None
    if seed and seed.graph_json:
        event_map = seed.graph_json.get("event_map", {})
        if event_map:
            event_ids = sorted(int(k) for k in event_map.keys())

    # Build participant list
    room = manager.get_room(race.id)
    connected_ids = set(room.mods.keys()) if room else set()
    sorted_participants = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(p, connected_ids=connected_ids) for p in sorted_participants
    ]

    message = AuthOkMessage(
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
        ),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,  # Mods don't need the graph
            event_ids=event_ids,
        ),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())


async def handle_ready(db: AsyncSession, participant: Participant) -> None:
    """Handle player ready signal."""
    if participant.status == ParticipantStatus.REGISTERED:
        participant.status = ParticipantStatus.READY
        await db.commit()
        logger.info(f"Participant ready: {participant.id}")

        # Broadcast leaderboard update
        await db.refresh(participant.race, ["participants"])
        for p in participant.race.participants:
            await db.refresh(p, ["user"])
        await manager.broadcast_leaderboard(participant.race_id, participant.race.participants)


async def handle_status_update(
    db: AsyncSession, participant: Participant, msg: dict[str, Any]
) -> None:
    """Handle periodic status update from mod."""
    if isinstance(msg.get("igt_ms"), int):
        participant.igt_ms = msg["igt_ms"]
    if isinstance(msg.get("death_count"), int):
        participant.death_count = msg["death_count"]

    # Set to playing if race is running
    race = participant.race
    if race.status == RaceStatus.RUNNING and participant.status == ParticipantStatus.READY:
        participant.status = ParticipantStatus.PLAYING

    await db.commit()

    # Broadcast player update to spectators
    await db.refresh(participant, ["user"])
    await manager.broadcast_player_update(participant.race_id, participant)


async def handle_event_flag(
    db: AsyncSession, participant: Participant, msg: dict[str, Any]
) -> None:
    """Handle event flag trigger from mod."""
    flag_id = msg.get("flag_id")
    if not isinstance(flag_id, int):
        return

    seed = participant.race.seed
    if not seed or not seed.graph_json:
        return

    event_map = seed.graph_json.get("event_map", {})
    finish_event = seed.graph_json.get("finish_event")

    # Resolve flag_id to node_id
    node_id = event_map.get(str(flag_id))
    if node_id is None:
        logger.warning(f"Unknown event flag {flag_id} from participant {participant.id}")
        return

    # Update IGT
    igt = msg.get("igt_ms", 0) if isinstance(msg.get("igt_ms"), int) else 0
    participant.igt_ms = igt

    # Check if node already discovered (ignore duplicates)
    old_history = participant.zone_history or []
    if any(entry.get("node_id") == node_id for entry in old_history):
        return  # Already discovered

    # Update zone history and layer
    participant.current_layer = get_layer_for_node(node_id, seed.graph_json)
    participant.current_zone = node_id
    entry = {"node_id": node_id, "igt_ms": igt}
    participant.zone_history = [*old_history, entry]

    # Check if this is the finish event
    if flag_id == finish_event:
        await handle_finished(db, participant, {"igt_ms": igt})
        return

    await db.commit()

    # Broadcast updated leaderboard
    await db.refresh(participant.race, ["participants"])
    for p in participant.race.participants:
        await db.refresh(p, ["user"])
    await manager.broadcast_leaderboard(participant.race_id, participant.race.participants)


async def handle_finished(db: AsyncSession, participant: Participant, msg: dict[str, Any]) -> None:
    """Handle player finish event."""
    participant.status = ParticipantStatus.FINISHED
    if isinstance(msg.get("igt_ms"), int):
        participant.igt_ms = msg["igt_ms"]
    participant.finished_at = datetime.now(UTC).replace(tzinfo=None)

    await db.commit()
    logger.info(f"Participant finished: {participant.id}, igt={participant.igt_ms}ms")

    # Check if all players finished
    await db.refresh(participant.race, ["participants"])
    all_finished = all(
        p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
        for p in participant.race.participants
    )

    if all_finished:
        participant.race.status = RaceStatus.FINISHED
        await db.commit()
        logger.info(f"Race finished: {participant.race_id}")
        await manager.broadcast_race_status(participant.race_id, "finished")

        # Reload race with casters for DAG access computation
        race = participant.race
        await db.refresh(race, ["casters"])
        for c in race.casters:
            await db.refresh(c, ["user"])

        # Push full graph + zone_history to all spectators
        await broadcast_race_state_update(participant.race_id, race)

    # Broadcast leaderboard (with zone_history when race is finished)
    for p in participant.race.participants:
        await db.refresh(p, ["user"])
    await manager.broadcast_leaderboard(
        participant.race_id,
        participant.race.participants,
        include_history=all_finished,
    )


async def broadcast_race_start(race_id: uuid.UUID) -> None:
    """Broadcast race start to all connections (mods + spectators)."""
    room = manager.get_room(race_id)
    if room:
        # Send race_start to mods
        message = RaceStartMessage()
        await room.broadcast_to_mods(message.model_dump_json())
        # Also notify spectators of status change
        await manager.broadcast_race_status(race_id, "running")
        logger.info(f"Race start broadcast: race={race_id}")
