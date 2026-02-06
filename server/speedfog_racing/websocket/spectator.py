"""WebSocket handler for spectator connections."""

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_user_by_token
from speedfog_racing.models import Caster, Participant, Race, RaceStatus
from speedfog_racing.websocket.manager import (
    SpectatorConnection,
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    ParticipantInfo,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)

logger = logging.getLogger(__name__)

# Grace period for auth message (seconds)
AUTH_GRACE_PERIOD = 2.0


def compute_dag_access(user_id: uuid.UUID | None, race: Race) -> bool:
    """Determine if a user should see the full DAG.

    Rules:
    - FINISHED: always True (race is over, nothing to hide)
    - RUNNING: True UNLESS user is a participant
    - DRAFT/OPEN: True only for non-participating organizer or caster
    """
    if race.status == RaceStatus.FINISHED:
        return True

    if race.status == RaceStatus.RUNNING:
        if user_id is None:
            return True
        # Participants can't see the DAG while running
        for p in race.participants:
            if p.user_id == user_id:
                return False
        return True

    # DRAFT or OPEN
    if user_id is None:
        return False

    # Non-participating organizer gets access
    if race.organizer_id == user_id:
        is_participant = any(p.user_id == user_id for p in race.participants)
        if not is_participant:
            return True

    # Casters get access
    for c in race.casters:
        if c.user_id == user_id:
            return True

    return False


def build_seed_info(race: Race, dag_access: bool) -> SeedInfo:
    """Build SeedInfo with or without graph data based on DAG access."""
    seed = race.seed
    if not seed:
        return SeedInfo(total_layers=0)

    graph_json = seed.graph_json or {}
    nodes = graph_json.get("nodes", {})
    total_nodes = len(nodes) if isinstance(nodes, dict) else 0

    # Count paths/edges
    total_paths = 0
    if isinstance(nodes, dict):
        for node_data in nodes.values():
            if isinstance(node_data, dict):
                total_paths += len(node_data.get("connections", []))

    if dag_access:
        return SeedInfo(
            total_layers=seed.total_layers,
            graph_json=seed.graph_json,
            total_nodes=total_nodes,
            total_paths=total_paths,
        )
    else:
        return SeedInfo(
            total_layers=seed.total_layers,
            graph_json=None,
            total_nodes=total_nodes,
            total_paths=total_paths,
        )


async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, db: AsyncSession
) -> None:
    """Handle a spectator WebSocket connection with optional auth."""
    await websocket.accept()

    conn = SpectatorConnection(websocket=websocket)

    try:
        # Get race with all data
        race = await get_race_with_details(db, race_id)
        if not race:
            await websocket.close(code=4004, reason="Race not found")
            return

        # Wait for optional auth message
        user_id = await _try_auth(websocket, db)
        conn.user_id = user_id

        # Compute DAG access based on role
        conn.dag_access = compute_dag_access(user_id, race)

        # Send initial race state with appropriate visibility
        await send_race_state(
            websocket,
            race,
            dag_access=conn.dag_access,
            include_history=(race.status == RaceStatus.FINISHED),
        )

        # Register connection
        await manager.connect_spectator(race_id, conn)

        # Keep connection alive - spectators only receive broadcasts
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        logger.info(f"Spectator disconnected: race={race_id}")
    except Exception as e:
        logger.error(f"Error in spectator websocket: {e}")
    finally:
        await manager.disconnect_spectator(race_id, conn)


async def _try_auth(websocket: WebSocket, db: AsyncSession) -> uuid.UUID | None:
    """Wait briefly for an auth message. Returns user_id or None."""
    try:
        data = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_GRACE_PERIOD)
        msg = json.loads(data)
        if msg.get("type") == "auth" and isinstance(msg.get("token"), str):
            user = await get_user_by_token(db, msg["token"])
            if user:
                return user.id
    except TimeoutError:
        pass
    except (json.JSONDecodeError, WebSocketDisconnect):
        pass
    return None


async def get_race_with_details(db: AsyncSession, race_id: uuid.UUID) -> Race | None:
    """Get race with seed, participants, and casters loaded."""
    result = await db.execute(
        select(Race)
        .options(
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.casters).selectinload(Caster.user),
        )
        .where(Race.id == race_id)
    )
    return result.scalar_one_or_none()


async def send_race_state(
    websocket: WebSocket,
    race: Race,
    *,
    dag_access: bool = False,
    include_history: bool = False,
) -> None:
    """Send race state to spectator with appropriate DAG visibility."""
    sorted_participants = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(p, include_history=include_history) for p in sorted_participants
    ]

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
        ),
        seed=build_seed_info(race, dag_access),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())


async def broadcast_race_state_update(race_id: uuid.UUID, race: Race) -> None:
    """Recompute and send race_state to each spectator based on their access."""
    room = manager.get_room(race_id)
    if not room:
        return

    include_history = race.status == RaceStatus.FINISHED

    disconnected: list[int] = []
    for i, conn in enumerate(room.spectators):
        dag_access = compute_dag_access(conn.user_id, race)
        conn.dag_access = dag_access
        try:
            await send_race_state(
                conn.websocket,
                race,
                dag_access=dag_access,
                include_history=include_history,
            )
        except Exception:
            disconnected.append(i)

    for i in reversed(disconnected):
        room.spectators.pop(i)
