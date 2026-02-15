"""WebSocket handler for spectator connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_user_by_token
from speedfog_racing.models import Caster, Participant, Race
from speedfog_racing.websocket.manager import (
    SEND_TIMEOUT,
    SpectatorConnection,
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)

logger = logging.getLogger(__name__)

# Grace period for auth message (seconds).
# Spectator connections are intentionally unauthenticated by default (public races).
# Optional auth within this window identifies the user for future role-based features.
# Accepted risk: unauthenticated connections can observe public race state. This is
# by design — race data (leaderboard, zone progress) is intended to be public.
AUTH_GRACE_PERIOD = 2.0
HEARTBEAT_INTERVAL = 30.0  # seconds between pings


def build_seed_info(race: Race) -> SeedInfo:
    """Build SeedInfo — always includes graph_json for client-side filtering."""
    seed = race.seed
    if not seed:
        return SeedInfo(total_layers=0)

    graph_json = seed.graph_json or {}

    total_nodes = graph_json.get("total_nodes")
    if total_nodes is None:
        nodes = graph_json.get("nodes", {})
        total_nodes = len(nodes) if isinstance(nodes, dict) else 0

    total_paths = graph_json.get("total_paths", 0)

    return SeedInfo(
        total_layers=seed.total_layers,
        graph_json=seed.graph_json,
        total_nodes=total_nodes,
        total_paths=total_paths,
    )


async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Handle a spectator WebSocket connection with optional auth."""
    await websocket.accept()

    conn = SpectatorConnection(websocket=websocket)

    try:
        # Open a short-lived session for init only
        async with session_maker() as db:
            race = await get_race_with_details(db, race_id)
            if not race:
                await websocket.close(code=4004, reason="Race not found")
                return

            user_id = await _try_auth(websocket, db)
            conn.user_id = user_id

            # Send initial race state (session still open for lazy access)
            await send_race_state(websocket, race)
        # Session closed — released back to pool within ~2s of connect

        # Register connection
        await manager.connect_spectator(race_id, conn)

        # Start heartbeat in background
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        try:
            # Keep connection alive — spectators only receive broadcasts
            while True:
                try:
                    await websocket.receive_text()
                except WebSocketDisconnect:
                    break
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Spectator disconnected: race={race_id}")
    except Exception as e:
        logger.error(f"Error in spectator websocket: {e}")
    finally:
        await manager.disconnect_spectator(race_id, conn)


async def _heartbeat_loop(websocket: WebSocket) -> None:
    """Send periodic ping messages to the spectator."""
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


async def _try_auth(websocket: WebSocket, db: AsyncSession) -> uuid.UUID | None:
    """Wait briefly for an auth message. Returns user_id or None."""
    try:
        data = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_GRACE_PERIOD)
        msg = json.loads(data)
        if msg.get("type") == "auth" and isinstance(msg.get("token"), str):
            user = await get_user_by_token(db, msg["token"])
            if user:
                user.last_seen = datetime.now(UTC)
                await db.commit()
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
) -> None:
    """Send race state to spectator."""
    room = manager.get_room(race.id)
    connected_ids = set(room.mods.keys()) if room else set()
    graph = race.seed.graph_json if race.seed else None
    sorted_participants = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(p, connected_ids=connected_ids, graph_json=graph)
        for p in sorted_participants
    ]

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
            started_at=race.started_at.isoformat() if race.started_at else None,
        ),
        seed=build_seed_info(race),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())


async def broadcast_race_state_update(race_id: uuid.UUID, race: Race) -> None:
    """Recompute and send race_state to each spectator based on their access."""
    room = manager.get_room(race_id)
    if not room:
        return

    # Send race_state to each spectator concurrently
    async def _send_to(i: int, conn: SpectatorConnection) -> int | None:
        try:
            await asyncio.wait_for(
                send_race_state(conn.websocket, race),
                timeout=SEND_TIMEOUT,
            )
        except Exception:
            logger.warning("Error sending race state to spectator %d in race %s", i, race_id)
            return i
        return None

    results = await asyncio.gather(*(_send_to(i, conn) for i, conn in enumerate(room.spectators)))
    # Remove failed connections in reverse order
    for idx in sorted((r for r in results if r is not None), reverse=True):
        room.spectators.pop(idx)
