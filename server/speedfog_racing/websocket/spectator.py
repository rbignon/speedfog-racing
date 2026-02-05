"""WebSocket handler for spectator connections."""

import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, Race
from speedfog_racing.websocket.manager import manager, participant_to_info, sort_leaderboard
from speedfog_racing.websocket.schemas import (
    ParticipantInfo,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)

logger = logging.getLogger(__name__)


async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, db: AsyncSession
) -> None:
    """Handle a spectator WebSocket connection."""
    await websocket.accept()

    try:
        # Get race with all data
        race = await get_race_with_details(db, race_id)
        if not race:
            await websocket.close(code=4004, reason="Race not found")
            return

        # Send initial race state
        await send_race_state(websocket, race)

        # Register connection
        await manager.connect_spectator(race_id, websocket)

        # Keep connection alive - spectators only receive broadcasts
        # They don't send messages, just wait for server pushes
        while True:
            # Wait for client messages (ping/pong handled by FastAPI)
            # Spectators don't send meaningful messages, but we need to keep the connection
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        logger.info(f"Spectator disconnected: race={race_id}")
    except Exception as e:
        logger.error(f"Error in spectator websocket: {e}")
    finally:
        await manager.disconnect_spectator(race_id, websocket)


async def get_race_with_details(db: AsyncSession, race_id: uuid.UUID) -> Race | None:
    """Get race with seed and participants loaded."""
    result = await db.execute(
        select(Race)
        .options(
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
        .where(Race.id == race_id)
    )
    return result.scalar_one_or_none()


async def send_race_state(websocket: WebSocket, race: Race) -> None:
    """Send initial race state to spectator."""
    seed = race.seed

    # Build participant list
    sorted_participants = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [participant_to_info(p) for p in sorted_participants]

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
            scheduled_start=race.scheduled_start,
        ),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=seed.graph_json if seed else None,  # Spectators get the graph
        ),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())
