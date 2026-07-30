"""WebSocket handler for training mod connections."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from fastapi import WebSocket
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.config import settings
from speedfog_racing.discord import send_training_live_notification
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_tier_for_node,
)
from speedfog_racing.websocket.handler import BaseModHandler, extract_event_ids
from speedfog_racing.websocket.schemas import (
    AuthOkMessage,
    DeathCountsMessage,
    ErrorCode,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    RaceInfo,
    RaceStartMessage,
    RaceStatusChangeMessage,
    SeedInfo,
    ZoneHistoryMessage,
    extract_phantom_skins,
    extract_spawn_items,
    resolve_phantom_skin_for_auth_ok,
)
from speedfog_racing.websocket.training.manager import training_manager

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


class TrainingModHandler(BaseModHandler["TrainingSession"]):  # type: ignore[type-var]
    """Mod WebSocket handler for training sessions."""

    def __init__(
        self,
        websocket: WebSocket,
        session_id: uuid.UUID,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, session_id, session_maker)
        self._session_id = session_id  # Typed alias for self.entity_id
        self._user_id: uuid.UUID | None = None
        self._cached_graph_json: dict[str, Any] | None = None

    def _configure_sentry_scope(self) -> None:
        super()._configure_sentry_scope()
        if self._user_id:
            sentry_sdk.set_user({"id": str(self._user_id)})

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    async def _authenticate(self, mod_token: str) -> bool:
        async with self.session_maker() as db:
            result = await db.execute(
                select(TrainingSession)
                .options(*_load_options())
                .where(
                    TrainingSession.id == self._session_id,
                    TrainingSession.mod_token == mod_token,
                )
            )
            session = result.scalar_one_or_none()

            if not session:
                await self._send_auth_error("Invalid mod token or session")
                return False

            if session.status != TrainingSessionStatus.ACTIVE:
                await self._send_auth_error("Solo session is not active")
                return False

            self._user_id = session.user_id
            self.locale = session.user.locale or "en"

            seed = session.seed
            self._cached_graph_json = seed.graph_json if seed else None

            # Send auth_ok
            await self._send_auth_ok_msg(session)

            # Send race_start immediately (training starts right away)
            await self.websocket.send_text(RaceStartMessage().model_dump_json())

            # Send initial zone_update only on reconnect (zone_history exists).
            # For new sessions, the zone_update arrives after the first valid
            # status_update + event_flag/zone_query cycle, avoiding premature
            # display before fresh-save validation passes.
            if seed and seed.graph_json and session.zone_history:
                last_node = session.zone_history[-1].get("node_id")
                if last_node:
                    await self._send_zone_update(
                        last_node,
                        seed.graph_json,
                        session.zone_history,
                    )

                # Send current death counts on reconnect
                counts = _aggregate_session_deaths(session.zone_history)
                if counts:
                    logger.info(
                        "Sending death_counts on reconnect: training=%s, counts=%s",
                        self._session_id,
                        counts,
                    )
                    await self.websocket.send_text(
                        DeathCountsMessage(counts=counts).model_dump_json()
                    )

        # Store detached session for use by _on_authenticated
        self._auth_session = session
        return True

    async def _send_auth_ok_msg(self, session: TrainingSession) -> None:
        """Send auth_ok with training session info."""
        seed = session.seed

        event_ids: list[int] = []
        finish_event_id: int | None = None
        if seed and seed.graph_json:
            event_ids, finish_event_id = extract_event_ids(seed.graph_json)

        spawn_items = extract_spawn_items(seed.graph_json) if seed and seed.graph_json else []
        death_flags = seed.graph_json.get("death_flags", {}) if seed and seed.graph_json else {}
        items_spawned_flag = (
            seed.graph_json.get("items_spawned_flag") if seed and seed.graph_json else None
        )
        phantom_skins = extract_phantom_skins(seed.graph_json) if seed and seed.graph_json else {}

        phantom_skin = resolve_phantom_skin_for_auth_ok(
            session.user.equipped_phantom_skin_id if session.user else None
        )
        message = AuthOkMessage(
            participant_id=str(session.id),
            race=RaceInfo(
                id=str(session.id),
                name=format_pool_display_name(seed.pool) if seed else "Solo",
                status="running",
                started_at=session.created_at.isoformat() if session.created_at else None,
                quit_out_penalty_ms=settings.quit_out_penalty_ms,
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
                phantom_skins=phantom_skins,
            ),
            participants=[build_training_participant_info(session)],
            phantom_skin=phantom_skin,
        )
        await self.websocket.send_text(message.model_dump_json())

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    async def _on_authenticated(self) -> None:
        assert self._user_id is not None
        session_id = self._session_id
        session = self._auth_session
        del self._auth_session  # Release reference

        await training_manager.connect_mod(
            session_id, self._user_id, self.websocket, mod_version=self.mod_version
        )
        await _broadcast_participant_update(session, spectator_only=True)

        # Fire-and-forget: notify Discord if player is live on Twitch.
        # Atomic DB check prevents duplicate notifications on server restart
        # (in-memory cooldown is lost, but discord_notified_at persists).
        # The timestamp is set optimistically before delivery confirmation;
        # if the notification fails (not live, webhook error), it won't retry.
        should_notify = session.discord_notified_at is None
        if should_notify:
            async with self.session_maker() as db:
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
                    pool=session.seed.pool if session.seed else None,
                )
            )
            notif_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _on_disconnect(self) -> None:
        session_id = self._session_id
        await training_manager.disconnect_mod(session_id, self.websocket)
        try:
            async with self.session_maker() as db:
                disc_session = await _load_session(db, session_id)
                if disc_session:
                    await _broadcast_participant_update(disc_session, spectator_only=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Entity loading
    # ------------------------------------------------------------------
    async def _load_entity(self, db: AsyncSession) -> TrainingSession | None:
        return await _load_session(db, self._session_id)

    async def _load_entity_for_status_update(self, db: AsyncSession) -> TrainingSession | None:
        return await _load_session(db, self._session_id)

    def _get_graph_json(self, entity: TrainingSession) -> dict[str, Any] | None:
        if self._cached_graph_json is not None:
            return self._cached_graph_json
        return entity.seed.graph_json if entity.seed else None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    async def _validate_for_status_update(self, entity: TrainingSession) -> bool:
        if entity.status != TrainingSessionStatus.ACTIVE:
            await self._send_condition(ErrorCode.SESSION_INACTIVE)
            return False
        return True

    async def _validate_for_event_flag(
        self, entity: TrainingSession, message_id: int | None
    ) -> bool:
        if entity.status != TrainingSessionStatus.ACTIVE:
            if message_id is not None:
                # ACK replayed event flags so the mod clears its in-flight set
                await self._send_event_flag_ack(message_id)
            else:
                await self._send_condition(ErrorCode.SESSION_INACTIVE)
            return False
        return True

    async def _validate_for_zone_query(
        self, entity: TrainingSession, message_id: int | None
    ) -> bool:
        if entity.status != TrainingSessionStatus.ACTIVE:
            if message_id is not None:
                await self._send_zone_query_ack(message_id)
            return False
        return True

    # ------------------------------------------------------------------
    # Finish event (called AFTER DB session closed by base class)
    # ------------------------------------------------------------------
    async def _handle_finish_event(
        self,
        entity: TrainingSession,
        igt: int,
        message_id: int | None,
    ) -> None:
        # Called AFTER DB session closed by base class.
        # event_flag_ack already sent by base class for finish events.
        session_id = self._session_id
        async with self.session_maker() as db:
            session = await _load_session(db, session_id)
            if not session:
                return
            session.status = TrainingSessionStatus.FINISHED
            session.finished_at = datetime.now(UTC)
            # session.igt_ms already holds the clamped value: the base
            # _on_igt_change ran on this same report before this hook.
            await db.commit()

        # Broadcast finish to spectators
        await _broadcast_participant_update(session)
        await _broadcast_status_change(session_id, "finished")

    # ------------------------------------------------------------------
    # Broadcast hooks
    # ------------------------------------------------------------------
    async def _broadcast_after_status_update(
        self,
        entity: TrainingSession,
        *,
        became_active: bool,
        death_delta: int,
        history_changed: bool,
    ) -> None:
        await _broadcast_participant_update(entity)

        if history_changed:
            await _broadcast_zone_history(self._session_id, entity.zone_history or [])

        # Send death counts to mod when deaths are attributed
        if death_delta > 0:
            counts = _aggregate_session_deaths(entity.zone_history)
            logger.info(
                "Sending death_counts: training=%s, counts=%s",
                self._session_id,
                counts,
            )
            await self.websocket.send_text(DeathCountsMessage(counts=counts).model_dump_json())

    async def _broadcast_after_event_flag(
        self,
        entity: TrainingSession,
        node_id: str | None,
        seed_graph: dict[str, Any] | None,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        await _broadcast_participant_update(entity)
        await _broadcast_zone_history(self._session_id, entity.zone_history or [])

    async def _broadcast_after_zone_query(
        self,
        entity: TrainingSession,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        await _broadcast_participant_update(entity, spectator_only=True)

        if prev_zone_history_len is not None:
            await _broadcast_zone_history(self._session_id, entity.zone_history or [])


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


async def handle_training_mod_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle mod WebSocket for a training session."""
    handler = TrainingModHandler(websocket, session_id, session_maker)
    await handler.run()


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
