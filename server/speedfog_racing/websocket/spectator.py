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
from speedfog_racing.config import settings
from speedfog_racing.models import Caster, Participant, PlayerTraitScores, Race, UserRole
from speedfog_racing.services.i18n import translate_graph_json
from speedfog_racing.websocket.common import heartbeat_loop
from speedfog_racing.websocket.manager import (
    SEND_TIMEOUT,
    SpectatorConnection,
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    ChatBroadcastMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
    SendChatMessage,
)

logger = logging.getLogger(__name__)

# Grace period for auth message (seconds).
# Spectator connections are intentionally unauthenticated by default (public races).
# Optional auth within this window identifies the user for future role-based features.
# Accepted risk: unauthenticated connections can observe public race state. This is
# by design: race data (leaderboard, zone progress) is intended to be public.
AUTH_GRACE_PERIOD = 2.0


def build_seed_info(
    race: Race,
    locale: str = "en",
) -> SeedInfo:
    """Build SeedInfo with graph_json for all spectators.

    Graph structure is always included. Participants already receive it
    in SETUP (for the race detail DAG), so hiding it from anonymous
    spectators provides no real benefit and breaks the OBS overlay.
    """
    seed = race.seed
    if not seed:
        return SeedInfo(total_layers=0)

    graph_json = seed.graph_json or {}

    total_nodes = graph_json.get("total_nodes")
    if total_nodes is None:
        nodes = graph_json.get("nodes", {})
        total_nodes = len(nodes) if isinstance(nodes, dict) else 0

    total_paths = graph_json.get("total_paths", 0)

    graph = seed.graph_json
    if graph is not None and locale != "en":
        graph = translate_graph_json(graph, locale)

    return SeedInfo(
        seed_id=str(seed.id),
        total_layers=seed.total_layers,
        graph_json=graph,
        total_nodes=total_nodes,
        total_paths=total_paths,
    )


async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Handle a spectator WebSocket connection with optional auth."""
    await websocket.accept()

    # Read locale from query param (e.g. ?locale=fr)
    query_locale = websocket.query_params.get("locale", "en")

    conn = SpectatorConnection(websocket=websocket, locale=query_locale)

    # chat_info is set only for users with a role (organizer/caster/participant)
    chat_info: dict[str, str | None] | None = None

    try:
        # Open a short-lived session for init only
        async with session_maker() as db:
            race = await get_race_with_details(db, race_id)
            if not race:
                await websocket.close(code=4004, reason="Race not found")
                return

            user_id = await _try_auth(websocket, db)
            conn.user_id = user_id

            # Prefer user's DB locale over query param if set
            if user_id:
                from speedfog_racing.models import User

                user_result = await db.execute(select(User).where(User.id == user_id))
                user_obj = user_result.scalar_one_or_none()
                if user_obj and user_obj.locale:
                    conn.locale = user_obj.locale

                # Determine role in this race
                role: str | None = None
                if race.organizer_id == user_id:
                    role = "organizer"
                elif user_obj and user_obj.role == UserRole.ADMIN:
                    role = "admin"
                elif any(c.user_id == user_id for c in race.casters):
                    role = "caster"
                elif any(p.user_id == user_id for p in race.participants):
                    role = "participant"

                if role is not None and user_obj is not None:
                    # Load dominant_trait from PlayerTraitScores
                    trait_scores = await db.get(PlayerTraitScores, user_id)
                    dominant_trait = trait_scores.dominant_trait if trait_scores else None

                    chat_info = {
                        "username": user_obj.twitch_username,
                        "display_name": user_obj.twitch_display_name,
                        "avatar_url": user_obj.twitch_avatar_url,
                        "role": role,
                        "dominant_trait": dominant_trait,
                    }

            # Send initial race state (session still open for lazy access)
            await send_race_state(websocket, race, locale=conn.locale)
        # Session closed, released back to pool within ~2s of connect

        # Register connection
        await manager.connect_spectator(race_id, conn)

        # Start heartbeat in background
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            # Message loop: parse incoming messages and handle chat if authorized
            while True:
                try:
                    raw = await websocket.receive_text()
                except WebSocketDisconnect:
                    break

                # Ignore pong and non-JSON gracefully
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue

                msg_type = msg.get("type")
                if msg_type == "pong":
                    continue

                if msg_type == "chat":
                    if chat_info is None:
                        # Silently ignore: spectator-only connections cannot chat
                        continue
                    try:
                        chat_msg = SendChatMessage.model_validate(msg)
                    except Exception:
                        continue

                    room = manager.get_room(race_id)
                    if room is None:
                        continue

                    broadcast = ChatBroadcastMessage(
                        username=chat_info["username"],  # type: ignore[arg-type]
                        display_name=chat_info["display_name"],
                        avatar_url=chat_info["avatar_url"],
                        role=chat_info["role"],  # type: ignore[arg-type]
                        dominant_trait=chat_info["dominant_trait"],
                        message=chat_msg.message,
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                    await room.broadcast_to_all(broadcast.model_dump_json())
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
    *,
    locale: str = "en",
) -> None:
    """Send current race state to a spectator."""
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
            seeds_released_at=(
                race.seeds_released_at.isoformat() if race.seeds_released_at else None
            ),
            countdown_seconds=settings.countdown_seconds,
        ),
        seed=build_seed_info(race, locale=locale),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())


async def broadcast_race_state_update(race_id: uuid.UUID, race: Race) -> None:
    """Send race_state to each spectator with per-connection locale."""
    room = manager.get_room(race_id)
    if not room:
        return

    # Snapshot to avoid issues with concurrent list modification
    snapshot = list(room.spectators)

    async def _send_to(conn: SpectatorConnection) -> SpectatorConnection | None:
        try:
            await asyncio.wait_for(
                send_race_state(conn.websocket, race, locale=conn.locale),
                timeout=SEND_TIMEOUT,
            )
        except Exception:
            logger.warning(
                "Error sending race state to spectator in race %s", race_id, exc_info=True
            )
            return conn
        return None

    results = await asyncio.gather(*(_send_to(conn) for conn in snapshot))
    for conn in results:
        if conn is not None:
            try:
                room.spectators.remove(conn)
            except ValueError:
                pass  # Already removed by disconnect handler
