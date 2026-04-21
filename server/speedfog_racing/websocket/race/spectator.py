"""WebSocket handler for spectator connections."""

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

from speedfog_racing.auth import get_user_by_token
from speedfog_racing.config import settings
from speedfog_racing.models import (
    Caster,
    ChatChannel,
    Invite,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.models import (
    ChatMessage as ChatMessageModel,
)
from speedfog_racing.services.i18n import translate_graph_json
from speedfog_racing.websocket.handler import BaseSpectatorHandler
from speedfog_racing.websocket.race.manager import (
    SEND_TIMEOUT,
    SpectatorConnection,
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    ChatBroadcastMessage,
    ChatHistoryMessage,
    ParticipantInfo,
    PendingInviteInfo,
    RaceInfoUpdateMessage,
    RaceStateMessage,
    SeedInfo,
    SendChatMessage,
    build_race_info,
)

logger = logging.getLogger(__name__)

MAX_CHAT_HISTORY_MESSAGES = 50  # recent messages sent to each new spectator


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


async def load_chat_history(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    race: Race,
    channel: ChatChannel,
) -> ChatHistoryMessage:
    """Load the most recent chat messages from DB and return the message.

    Capped at MAX_CHAT_HISTORY_MESSAGES (most recent). This keeps the
    payload and DB load bounded when a long-running race accumulates
    hundreds of messages and many spectators connect in rapid succession.
    The chat is ephemeral; older messages are not exposed to new viewers.
    """
    async with session_maker() as db:
        # Fetch the most recent N messages via created_at DESC + LIMIT, then
        # reverse in-memory so the client still receives them chronologically.
        # Outer-join PlayerTraitScores so users without scored races still
        # appear (trait = None).
        result = await db.execute(
            select(ChatMessageModel, User, PlayerTraitScores)
            .outerjoin(User, ChatMessageModel.user_id == User.id)
            .outerjoin(PlayerTraitScores, PlayerTraitScores.user_id == User.id)
            .where(
                ChatMessageModel.race_id == race_id,
                ChatMessageModel.channel == channel,
            )
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
            .limit(MAX_CHAT_HISTORY_MESSAGES)
        )
        rows = list(reversed(result.all()))

        if not rows:
            return ChatHistoryMessage(channel=channel.value, messages=[])

        traits_by_user = {
            user.id: traits.dominant_trait
            for _, user, traits in rows
            if user is not None and traits is not None
        }

    # Build role lookup from race relationships
    # (already loaded, detached with expire_on_commit=False)
    participant_user_ids = {p.user_id for p in race.participants}
    caster_user_ids = {c.user_id for c in race.casters}

    def _resolve_role(user: User) -> str:
        if race.organizer_id == user.id:
            return "organizer"
        if user.role == UserRole.ADMIN:
            return "admin"
        if user.id in caster_user_ids:
            return "caster"
        if user.id in participant_user_ids:
            return "participant"
        return "spectator"

    messages = []
    for chat_msg, user, _traits in rows:
        if user is None:
            # System message (no user)
            messages.append(
                ChatBroadcastMessage(
                    channel=channel.value,
                    username="",
                    display_name=None,
                    avatar_url=None,
                    role="system",
                    dominant_trait=None,
                    message=chat_msg.message,
                    timestamp=chat_msg.created_at.isoformat(),
                )
            )
        else:
            messages.append(
                ChatBroadcastMessage(
                    channel=channel.value,
                    username=user.twitch_username,
                    display_name=user.twitch_display_name,
                    avatar_url=user.twitch_avatar_url,
                    role=_resolve_role(user),
                    dominant_trait=traits_by_user.get(chat_msg.user_id),
                    message=chat_msg.message,
                    timestamp=chat_msg.created_at.isoformat(),
                )
            )

    return ChatHistoryMessage(channel=channel.value, messages=messages)


class RaceSpectatorHandler(BaseSpectatorHandler):
    """Spectator WebSocket handler for race connections."""

    AUTH_GRACE_PERIOD = 2.0

    def __init__(
        self,
        websocket: WebSocket,
        race_id: uuid.UUID,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, race_id, session_maker)
        self._conn = SpectatorConnection(websocket=websocket, locale=self.locale)
        self._chat_info: dict[str, str | None] | None = None
        self._message_handlers["chat"] = self._handle_chat

    async def _auth_and_setup(self) -> bool:
        async with self.session_maker() as db:
            race = await get_race_with_details(db, self.entity_id)  # type: ignore[arg-type]
            if not race:
                await self.websocket.close(code=4004, reason="Race not found")
                return False

            user_obj = await self._try_auth(db)
            user_id = user_obj.id if user_obj else None
            self._conn.user_id = user_id
            self._conn.locale = self.locale

            if user_obj:
                # Prefer user's DB locale over query param
                if user_obj.locale:
                    self._conn.locale = user_obj.locale
                    self.locale = user_obj.locale

                # Determine role in this race
                role: str | None = None
                if race.organizer_id == user_id:
                    role = "organizer"
                elif user_obj.role == UserRole.ADMIN:
                    role = "admin"
                elif any(c.user_id == user_id for c in race.casters):
                    role = "caster"
                elif any(p.user_id == user_id for p in race.participants):
                    role = "participant"

                if role is not None:
                    self._conn.role = role

                    if role == "participant":
                        participant = next(
                            (p for p in race.participants if p.user_id == user_id), None
                        )
                        if participant:
                            self._conn.participant_id = participant.id
                            self._conn.is_playing = (
                                race.status == RaceStatus.RUNNING
                                and participant.status == ParticipantStatus.PLAYING
                            )

                # Load dominant_trait from PlayerTraitScores
                trait_scores = await db.get(PlayerTraitScores, user_id)
                dominant_trait = trait_scores.dominant_trait if trait_scores else None

                self._chat_info = {
                    "username": user_obj.twitch_username,
                    "display_name": user_obj.twitch_display_name,
                    "avatar_url": user_obj.twitch_avatar_url,
                    "role": role or "spectator",
                    "dominant_trait": dominant_trait,
                }

            # Send initial race state (session still open for lazy access)
            await send_race_state(self.websocket, race, locale=self._conn.locale)
        # Session closed, released back to pool within ~2s of connect

        # Load chat history in parallel, send sequentially (safe for single WS)
        chat_loads: list[Any] = []
        if self._conn.role is not None:
            chat_loads.append(
                load_chat_history(
                    self.session_maker,
                    self.entity_id,  # type: ignore[arg-type]
                    race,
                    ChatChannel.PARTICIPANTS,
                )
            )
        if self._conn.user_id is not None and not self._conn.is_playing:
            chat_loads.append(
                load_chat_history(
                    self.session_maker,
                    self.entity_id,  # type: ignore[arg-type]
                    race,
                    ChatChannel.PUBLIC,
                )
            )
        if chat_loads:
            histories = await asyncio.gather(*chat_loads)
            for hist in histories:
                await self.websocket.send_text(hist.model_dump_json())

        return True

    async def _register(self) -> None:
        await manager.connect_spectator(self.entity_id, self._conn)  # type: ignore[arg-type]

    async def _unregister(self) -> None:
        await manager.disconnect_spectator(self.entity_id, self._conn)  # type: ignore[arg-type]

    async def _handle_chat(self, msg: dict[str, Any]) -> None:
        if self._chat_info is None:
            return  # Not authenticated

        try:
            chat_msg = SendChatMessage.model_validate(msg)
        except Exception:
            return

        # Validate channel access
        channel = chat_msg.channel
        if channel == "participants" and self._conn.role is None:
            return  # Spectators cannot write to participants channel
        if channel == "public" and self._conn.is_playing:
            return  # Playing participants cannot write to public

        room = manager.get_room(self.entity_id)  # type: ignore[arg-type]
        if room is None:
            return

        broadcast = ChatBroadcastMessage(
            channel=channel,
            username=self._chat_info["username"],  # type: ignore[arg-type]
            display_name=self._chat_info["display_name"],
            avatar_url=self._chat_info["avatar_url"],
            role=self._chat_info["role"],  # type: ignore[arg-type]
            dominant_trait=self._chat_info["dominant_trait"],
            message=chat_msg.message,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Persist to DB
        async with self.session_maker() as db:
            db_msg = ChatMessageModel(
                race_id=self.entity_id,
                channel=ChatChannel(channel),
                user_id=self._conn.user_id,
                message=chat_msg.message,
            )
            db.add(db_msg)
            await db.commit()

        # Broadcast to appropriate connections
        msg_json = broadcast.model_dump_json()
        if channel == "participants":
            await room.broadcast_chat_participants(msg_json)
        else:
            await room.broadcast_chat_public(msg_json)

    async def _try_auth(self, db: AsyncSession) -> User | None:
        """Wait briefly for an auth message. Returns User or None.

        Clients should send either ``{"type": "auth", "token": "..."}`` or
        ``{"type": "no_auth"}`` immediately after connect so the server does
        not have to wait for the full grace period before sending race_state.
        """
        try:
            data = await asyncio.wait_for(
                self.websocket.receive_text(), timeout=self.AUTH_GRACE_PERIOD
            )
            msg = json.loads(data)
            if msg.get("type") == "auth" and isinstance(msg.get("token"), str):
                user = await get_user_by_token(db, msg["token"])
                if user:
                    user.last_seen = datetime.now(UTC)
                    await db.commit()
                    return user
        except TimeoutError:
            pass
        except (json.JSONDecodeError, WebSocketDisconnect):
            pass
        return None


async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Handle a spectator WebSocket connection with optional auth."""
    handler = RaceSpectatorHandler(websocket, race_id, session_maker)
    await handler.run()


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
    sorted_participants, _ = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(
            p, connected_ids=connected_ids, graph_json=graph, include_zone_history=True
        )
        for p in sorted_participants
    ]

    # Always re-query pending invites here rather than relying on the caller
    # to eager-load Race.invites: every existing call site to
    # broadcast_race_state_update would otherwise need an extra option, and
    # the tiny dedicated query is cheaper than auditing every path.
    from speedfog_racing.database import async_session_maker

    async with async_session_maker() as inv_db:
        pending_rows = (
            (
                await inv_db.execute(
                    select(Invite)
                    .where(Invite.race_id == race.id, Invite.accepted.is_(False))
                    .order_by(Invite.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
    pending_invites = [
        PendingInviteInfo(
            id=str(inv.id),
            twitch_username=inv.twitch_username,
            created_at=inv.created_at.isoformat(),
        )
        for inv in pending_rows
    ]

    message = RaceStateMessage(
        race=build_race_info(race, countdown_seconds=settings.countdown_seconds),
        seed=build_seed_info(race, locale=locale),
        participants=participant_infos,
        pending_invites=pending_invites,
    )
    await websocket.send_text(message.model_dump_json())


async def broadcast_race_state_update(race_id: uuid.UUID, race: Race) -> None:
    """Send race_state to each spectator with per-connection locale."""
    room = manager.get_room(race_id)
    if not room:
        return

    # Snapshot to avoid issues with concurrent dict modification
    snapshot = list(room.spectators.values())

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
            room.spectators.pop(conn.connection_id, None)


async def broadcast_race_info_update(race: Race) -> None:
    """Push a RaceInfo snapshot to every connected mod and spectator.

    Called from PATCH /races whenever a race-level field changes so clients
    can refresh their cached state (race_duration_minutes extension,
    max_participants bump, etc.) without reconnecting.
    """
    room = manager.get_room(race.id)
    if not room:
        return
    message = RaceInfoUpdateMessage(
        race=build_race_info(race, countdown_seconds=settings.countdown_seconds),
    )
    await room.broadcast_to_all(message.model_dump_json())
