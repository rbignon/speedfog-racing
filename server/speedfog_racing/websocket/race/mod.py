"""WebSocket handler for mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from fastapi import WebSocket
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
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.services.daily_streak_service import (
    apply_close_day_to_user,
    apply_qualification_to_user,
    qualifies_for_streak,
)
from speedfog_racing.services.i18n import translate_zone_update
from speedfog_racing.services.layer_service import (
    compute_zone_update,
    get_layer_for_node,
    get_start_node,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.websocket.handler import (
    SEND_TIMEOUT,
    BaseModHandler,
    clamp_igt,
    extract_event_ids,
)
from speedfog_racing.websocket.race.manager import (
    manager,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.race.spectator import broadcast_race_state_update
from speedfog_racing.websocket.schemas import (
    CONDITION_MESSAGES,
    AuthOkMessage,
    DeathCountsMessage,
    ErrorCode,
    ErrorMessage,
    ParticipantInfo,
    RaceStartMessage,
    SeedInfo,
    build_race_info,
    extract_phantom_skins,
    extract_spawn_items,
    persist_system_chat,
    resolve_phantom_skin_for_auth_ok,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Race-specific utilities (kept module-level, used externally or by handler)
# ---------------------------------------------------------------------------
def _is_countdown_active(race: Race) -> bool:
    """Check if the race is still in the countdown period before effective start."""
    if not race.started_at:
        return False
    started = race.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) < started


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


# ---------------------------------------------------------------------------
# DB loaders (kept module-level, used by handler and external callers)
# ---------------------------------------------------------------------------
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


async def _load_race_with_participants(db: AsyncSession, race_id: uuid.UUID) -> Race | None:
    """Load a race + its participants (with users) for leaderboard broadcast.

    Cheaper than _load_participant: skips the disconnecting participant's
    own eager tree, the seed, and the casters. The caller must supply
    graph_json from an earlier load (it does not change during a race).
    The race row is returned so callers can read ``daily_date`` to drive
    per-mod projected payloads.
    """
    result = await db.execute(
        select(Race)
        .where(Race.id == race_id)
        .options(selectinload(Race.participants).selectinload(Participant.user))
    )
    return result.scalar_one_or_none()


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


# ---------------------------------------------------------------------------
# RaceModHandler
# ---------------------------------------------------------------------------
class RaceModHandler(BaseModHandler["Participant"]):  # type: ignore[type-var]
    """Mod WebSocket handler for race connections."""

    def __init__(
        self,
        websocket: WebSocket,
        race_id: uuid.UUID,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, race_id, session_maker)
        self._race_id = race_id  # Typed alias for self.entity_id
        self._message_handlers["ready"] = self._handle_ready
        self._message_handlers["finished"] = self._handle_finished_message
        self._participant_id: uuid.UUID | None = None
        self._user_id: uuid.UUID | None = None
        self._cached_graph_json: dict[str, Any] | None = None
        # Detached participant from auth phase, used by _on_authenticated
        self._auth_participant: Participant | None = None

    def _configure_sentry_scope(self) -> None:
        super()._configure_sentry_scope()
        if self._participant_id:
            sentry_sdk.set_tag("participant_id", str(self._participant_id))
        if self._user_id:
            sentry_sdk.set_user({"id": str(self._user_id)})

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    async def _authenticate(self, mod_token: str) -> bool:
        async with self.session_maker() as db:
            result = await db.execute(
                select(Participant)
                .options(*_participant_load_options())
                .where(
                    Participant.race_id == self._race_id,
                    Participant.mod_token == mod_token,
                )
            )
            participant = result.scalar_one_or_none()

            if not participant:
                logger.warning("Mod auth failed: race=%s, invalid token", self.entity_id)
                await self._send_auth_error("Invalid mod token or race")
                return False

            race = participant.race
            if race.status == RaceStatus.FINISHED:
                logger.info(
                    "Mod rejected (race finished): race=%s, user=%s",
                    self.entity_id,
                    participant.user_id,
                )
                await self._send_auth_error("Race has already finished")
                return False

            self._participant_id = participant.id
            self._user_id = participant.user_id

            if participant.user.locale:
                self.locale = participant.user.locale

            self._cached_graph_json = _get_graph_json(participant)

            # Send auth_ok
            await self._send_auth_ok(participant)

            # Send zone_update on reconnect (race already running)
            seed = participant.race.seed
            if participant.race.status == RaceStatus.RUNNING and seed and seed.graph_json:
                zone = participant.current_zone
                if zone:
                    await self._send_zone_update(
                        zone,
                        seed.graph_json,
                        participant.zone_history,
                    )

                # Send current death counts on reconnect
                counts = aggregate_death_counts(race.participants)
                if counts:
                    await self.websocket.send_text(
                        DeathCountsMessage(counts=counts).model_dump_json()
                    )

        # Store detached participant for use by _on_authenticated
        self._auth_participant = participant
        return True

    async def _send_auth_ok(self, participant: Participant) -> None:
        """Send successful auth response with race state."""
        race = participant.race
        seed = race.seed

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

        room = manager.get_room(race.id)
        connected_ids = set(room.mods.keys()) if room else set()
        graph = seed.graph_json if seed else None
        sorted_participants, _ = sort_leaderboard(race.participants)
        participant_infos: list[ParticipantInfo] = [
            participant_to_info(p, connected_ids=connected_ids, graph_json=graph)
            for p in sorted_participants
        ]

        phantom_skin = resolve_phantom_skin_for_auth_ok(
            participant.user.equipped_phantom_skin_id if participant.user else None
        )
        message = AuthOkMessage(
            participant_id=str(participant.id),
            race=build_race_info(race, countdown_seconds=settings.countdown_seconds),
            seed=SeedInfo(
                seed_id=str(seed.id) if seed else None,
                total_layers=seed.total_layers if seed else 0,
                graph_json=None,  # Mods don't need the graph
                event_ids=event_ids,
                finish_event=finish_event_id,
                spawn_items=spawn_items,
                death_flags=death_flags,
                items_spawned_flag=items_spawned_flag,
                phantom_skins=phantom_skins,
            ),
            participants=participant_infos,
            phantom_skin=phantom_skin,
        )
        await self.websocket.send_text(message.model_dump_json())

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    async def _on_authenticated(self) -> None:
        assert self._participant_id is not None
        assert self._user_id is not None
        await manager.connect_mod(
            self._race_id,
            self._participant_id,
            self._user_id,
            self.websocket,
            self.locale,
            mod_version=self.mod_version,
        )
        # Broadcast updated connection status using detached objects from auth session
        participant = self._auth_participant
        self._auth_participant = None  # Release reference
        try:
            if participant:
                await manager.broadcast_leaderboard(
                    self._race_id,
                    participant.race.participants,
                    graph_json=self._cached_graph_json,
                    daily_date=participant.race.daily_date,
                )
        except Exception:
            logger.warning("Failed to broadcast connect: race=%s", self._race_id)

    async def _on_disconnect(self) -> None:
        assert self._participant_id is not None
        await manager.disconnect_mod(self._race_id, self._participant_id, self.websocket)
        try:
            async with self.session_maker() as db:
                race = await _load_race_with_participants(db, self._race_id)
                if race and race.participants:
                    await manager.broadcast_leaderboard(
                        self._race_id,
                        list(race.participants),
                        graph_json=self._cached_graph_json,
                        daily_date=race.daily_date,
                    )
        except Exception:
            logger.warning("Failed to broadcast disconnect: race=%s", self._race_id)

    # ------------------------------------------------------------------
    # Entity loading
    # ------------------------------------------------------------------
    async def _load_entity(self, db: AsyncSession) -> Participant | None:
        return await _load_participant(db, self._participant_id)  # type: ignore[arg-type]

    async def _load_entity_for_status_update(self, db: AsyncSession) -> Participant | None:
        assert self._participant_id is not None
        if self._cached_graph_json is not None:
            return await _load_participant_no_seed(db, self._participant_id)
        return await _load_participant_light(db, self._participant_id)

    def _get_graph_json(self, entity: Participant) -> dict[str, Any] | None:
        # Prefer cached graph_json (avoids lazy-loading race.seed when
        # the entity was loaded without it, e.g. _load_participant_no_seed).
        if self._cached_graph_json is not None:
            return self._cached_graph_json
        return entity.race.seed.graph_json if entity.race.seed else None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    async def _validate_for_status_update(self, entity: Participant) -> bool:
        if entity.race.status != RaceStatus.RUNNING:
            logger.warning(
                "Rejected status_update: race=%s status=%s",
                entity.race_id,
                entity.race.status.value,
            )
            await self._send_condition(ErrorCode.RACE_NOT_RUNNING)
            return False

        if entity.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
            return False  # Silently drop: IGT is frozen

        if _is_countdown_active(entity.race):
            return False  # Silently drop during countdown

        return True

    async def _validate_for_event_flag(self, entity: Participant, message_id: int | None) -> bool:
        # Ack acknowledges the message at the protocol level (clears the mod's
        # in-flight set, prevents reconnect-replay from injecting stale entries).
        # Error is a user-visible banner explaining the rejection. They are
        # complementary: send the ack whenever message_id is present, and the
        # error for user feedback.
        if entity.race.status != RaceStatus.RUNNING:
            logger.warning(
                "Rejected event_flag: race=%s status=%s",
                entity.race_id,
                entity.race.status.value,
            )
            if message_id is not None:
                await self._send_event_flag_ack(message_id)
            await self._send_condition(ErrorCode.RACE_NOT_RUNNING)
            return False

        if _is_countdown_active(entity.race):
            logger.warning(
                "Rejected event_flag during countdown: race=%s",
                entity.race_id,
            )
            if message_id is not None:
                await self._send_event_flag_ack(message_id)
            await self._send_condition(ErrorCode.COUNTDOWN)
            return False

        if entity.status != ParticipantStatus.PLAYING:
            if message_id is not None:
                await self._send_event_flag_ack(message_id)
            return False

        return True

    async def _validate_for_zone_query(self, entity: Participant, message_id: int | None) -> bool:
        if entity.race.status != RaceStatus.RUNNING:
            if message_id is not None:
                await self._send_zone_query_ack(message_id)
            return False

        if _is_countdown_active(entity.race):
            if message_id is not None:
                await self._send_zone_query_ack(message_id)
            return False

        if entity.status != ParticipantStatus.PLAYING:
            if message_id is not None:
                await self._send_zone_query_ack(message_id)
            return False

        return True

    # ------------------------------------------------------------------
    # Virtual overrides
    # ------------------------------------------------------------------
    def _on_igt_change(self, entity: Participant, igt_ms: int) -> None:
        # Bump on any CHANGED report, including clamped ones: a
        # post-restore replay is activity the inactivity monitor must see.
        # The bump must be evaluated before the base clamp mutates igt_ms.
        if igt_ms != entity.igt_ms:
            entity.last_igt_change_at = datetime.now(UTC)
        super()._on_igt_change(entity, igt_ms)

    def _on_zone_entered(
        self, entity: Participant, node_id: str, graph_json: dict[str, Any], igt: int
    ) -> None:
        node_layer = get_layer_for_node(node_id, graph_json)
        if node_layer > entity.current_layer:
            _set_layer(entity, node_layer, igt)

    def _on_first_init(self, entity: Participant, start_node: str) -> None:
        entity.status = ParticipantStatus.PLAYING
        _set_layer(entity, 0, 0)

    def _wall_reference(self, entity: Participant) -> datetime | None:
        return entity.last_igt_change_at

    # ------------------------------------------------------------------
    # Finish event (called AFTER DB session closed by base class)
    # ------------------------------------------------------------------
    async def _handle_finish_event(
        self,
        entity: Participant,
        igt: int,
        message_id: int | None,
    ) -> None:
        assert self._participant_id is not None
        # handle_finished owns the non-decreasing finish clamp (it also
        # covers the legacy finished-message caller), so the raw value is
        # passed through.
        await handle_finished(
            self.websocket,
            self.session_maker,
            self._participant_id,
            {"igt_ms": igt},
        )

    # ------------------------------------------------------------------
    # Broadcast hooks
    # ------------------------------------------------------------------
    async def _broadcast_after_status_update(
        self,
        entity: Participant,
        *,
        became_active: bool,
        death_delta: int,
        history_changed: bool,
    ) -> None:
        assert self._participant_id is not None

        if death_delta > 0 and entity.race.deathless and entity.status == ParticipantStatus.PLAYING:
            # Eliminate BEFORE the uncommon-path reload below so the
            # subsequent broadcasts already carry the ABANDONED status.
            await handle_deathless_death(self.session_maker, self._participant_id)

        if not became_active and death_delta <= 0:
            await asyncio.gather(
                manager.broadcast_player_update(
                    entity.race_id,
                    entity,
                    graph_json=self._cached_graph_json,
                    daily_date=entity.race.daily_date,
                ),
                self._maybe_unicast_daily_projection(entity),
            )
            return
        else:
            # Uncommon path: reload with full relationships for leaderboard/death broadcasts
            async with self.session_maker() as db:
                reloaded = await _load_participant(db, self._participant_id)
                if not reloaded:
                    return
                entity = reloaded

            if became_active:
                await manager.broadcast_leaderboard(
                    entity.race_id,
                    entity.race.participants,
                    graph_json=_get_graph_json(entity),
                    daily_date=entity.race.daily_date,
                )
            else:
                await manager.broadcast_player_update(
                    entity.race_id,
                    entity,
                    graph_json=_get_graph_json(entity),
                    daily_date=entity.race.daily_date,
                )

        if history_changed:
            await manager.broadcast_zone_history(
                entity.race_id, entity.id, entity.zone_history or []
            )

        if death_delta > 0:
            counts = aggregate_death_counts(entity.race.participants)
            logger.info(
                "Broadcasting death_counts: race=%s, counts=%s",
                entity.race_id,
                counts,
            )
            room = manager.get_room(entity.race_id)
            if room:
                await room.broadcast_to_mods(DeathCountsMessage(counts=counts).model_dump_json())

    async def _maybe_unicast_daily_projection(self, entity: Participant) -> None:
        """For daily races, unicast a fresh projected leaderboard to this mod.

        Only runs on the non-active status_update path: the viewer's IGT
        advanced but no other state changed, so we recompute their
        personal projection without disturbing the rest of the room.
        """
        assert self._participant_id is not None
        if entity.status != ParticipantStatus.PLAYING:
            return
        if entity.race.daily_date is None:
            return

        async with self.session_maker() as db:
            race = await _load_race_with_participants(db, entity.race_id)
            if race is None:
                return
            participants = list(race.participants)

        await manager.send_projected_to_mod(
            race_id=entity.race_id,
            participant_id=self._participant_id,
            participants=participants,
            graph_json=self._cached_graph_json,
        )

    async def _broadcast_after_event_flag(
        self,
        entity: Participant,
        node_id: str | None,
        seed_graph: dict[str, Any] | None,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        if is_first_visit:
            await manager.broadcast_leaderboard(
                entity.race_id,
                entity.race.participants,
                graph_json=seed_graph,
                daily_date=entity.race.daily_date,
            )
        else:
            await manager.broadcast_player_update(
                entity.race_id,
                entity,
                graph_json=seed_graph,
                daily_date=entity.race.daily_date,
            )

        await manager.broadcast_zone_history(entity.race_id, entity.id, entity.zone_history or [])

        if prev_zone_history_len == 1:
            await self._apply_daily_streak(entity)

    async def _apply_daily_streak(self, entity: Participant) -> None:
        """Evaluate Update A for this participant on the qualification crossing.

        Caller fires this only when ``len(zone_history)`` just crossed two on
        an event_flag append (i.e. ``prev_zone_history_len == 1``). Returns
        early on non-daily races; the service-side
        ``last_qualifying_date < race.daily_date`` guard still defends
        against stale replays on the same daily.
        """
        if entity.race.daily_date is None:
            return

        async with self.session_maker() as db:
            new_state = await apply_qualification_to_user(
                db, user_id=entity.user_id, daily_date=entity.race.daily_date
            )
            if new_state is None:
                return
            await RewardsService(db).check_daily_streak_eligibility(entity.user_id)
            await db.commit()

        await manager.send_daily_streak_update_to_user(
            entity.race_id,
            entity.user_id,
            current=new_state.current_streak,
            best=new_state.best_streak,
            freeze_count=new_state.freeze_count,
        )

    async def _broadcast_after_zone_query(
        self,
        entity: Participant,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        if is_first_visit:
            await manager.broadcast_leaderboard(
                entity.race_id,
                entity.race.participants,
                graph_json=_get_graph_json(entity),
                daily_date=entity.race.daily_date,
            )
        else:
            await manager.broadcast_player_update(
                entity.race_id,
                entity,
                graph_json=_get_graph_json(entity),
                daily_date=entity.race.daily_date,
            )

        if prev_zone_history_len is not None:
            await manager.broadcast_zone_history(
                entity.race_id, entity.id, entity.zone_history or []
            )

        if prev_zone_history_len == 1:
            await self._apply_daily_streak(entity)

    # ------------------------------------------------------------------
    # Race-specific message handlers
    # ------------------------------------------------------------------
    async def _handle_ready(self, msg: dict[str, Any]) -> None:
        """Handle player ready signal."""
        assert self._participant_id is not None
        async with self.session_maker() as db:
            participant = await _load_participant(db, self._participant_id)
            if not participant:
                return

            if participant.status != ParticipantStatus.REGISTERED:
                return

            participant.status = ParticipantStatus.READY
            await db.commit()
            logger.info("Participant ready: %s", participant.id)

        await manager.broadcast_leaderboard(
            participant.race_id,
            participant.race.participants,
            graph_json=_get_graph_json(participant),
            daily_date=participant.race.daily_date,
        )

    async def _handle_finished_message(self, msg: dict[str, Any]) -> None:
        """Handle explicit finished message from mod."""
        assert self._participant_id is not None
        await handle_finished(self.websocket, self.session_maker, self._participant_id, msg)


async def handle_deathless_death(
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
) -> None:
    """Eliminate a participant who died in a deathless race.

    Server-authoritative counterpart of ``POST /races/{id}/abandon``: the
    mod only reports the death count in ``status_update``; the guard here
    re-checks state in-session so concurrent transitions collapse to a
    no-op.
    """
    race_transitioned = False

    async with session_maker() as db:
        participant = await _load_participant(db, participant_id)
        if not participant:
            return
        race = participant.race
        if (
            not race.deathless
            or race.status != RaceStatus.RUNNING
            or participant.status != ParticipantStatus.PLAYING
        ):
            return

        participant.status = ParticipantStatus.ABANDONED
        await db.commit()
        logger.info("Deathless elimination: %s", participant.id)

        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        display = participant.user.twitch_display_name or participant.user.twitch_username
        death_public_json = await persist_system_chat(
            db,
            participant.race_id,
            ChatChannel.PUBLIC,
            f"{display} died.",
        )

        # Parity with POST /races/{id}/abandon on dailies: settle the streak
        # now for a player eliminated before qualifying, instead of leaving a
        # stale streak display until the next 08:00 rotation tick.
        streak_result = None
        if participant.race.daily_date is not None and not qualifies_for_streak(
            participant.zone_history
        ):
            streak_result = await apply_close_day_to_user(
                db, user_id=participant.user_id, daily_date=participant.race.daily_date
            )

        race_transitioned = await check_race_auto_finish(db, participant.race)
        race_finished_public_json: str | None = None
        if race_transitioned:
            logger.info("Race finished: %s", participant.race_id)
            finished_msg = (
                "The daily seed is over."
                if participant.race.daily_date is not None
                else "The race has finished."
            )
            race_finished_public_json = await persist_system_chat(
                db, participant.race_id, ChatChannel.PUBLIC, finished_msg
            )
        await db.commit()

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
        daily_date=participant.race.daily_date,
    )
    if not race_transitioned:
        # Parity with POST /races/{id}/abandon: push race_state so spectators
        # see the elimination even when it doesn't end the race.
        await broadcast_race_state_update(participant.race_id, participant.race)

    # Unlock the PUBLIC channel for the eliminated participant before
    # broadcasting so they receive their own elimination notice.
    room = manager.get_room(participant.race_id)
    if room:
        room.set_participant_status(participant.user_id, ParticipantStatus.ABANDONED)
        await room.broadcast_chat_public(death_public_json, participant.race)
        if race_finished_public_json is not None:
            await room.broadcast_chat_public(race_finished_public_json, participant.race)

    if streak_result is not None:
        streak_state, freeze_used = streak_result
        await manager.send_daily_streak_update_to_user(
            participant.race_id,
            participant.user_id,
            current=streak_state.current_streak,
            best=streak_state.best_streak,
            freeze_count=streak_state.freeze_count,
            freeze_consumed_for=participant.race.daily_date if freeze_used else None,
        )


# ---------------------------------------------------------------------------
# Standalone handle_finished (complex, used from 2 call sites)
# ---------------------------------------------------------------------------
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
            try:
                await asyncio.wait_for(
                    websocket.send_text(
                        ErrorMessage(
                            message=CONDITION_MESSAGES[ErrorCode.RACE_NOT_RUNNING],
                            code=ErrorCode.RACE_NOT_RUNNING,
                        ).model_dump_json()
                    ),
                    timeout=SEND_TIMEOUT,
                )
            except Exception:
                pass
            return

        if participant.status == ParticipantStatus.FINISHED:
            return  # Already finished (idempotency guard)

        participant.status = ParticipantStatus.FINISHED
        finished_igt = clamp_igt(msg.get("igt_ms"))
        if finished_igt is not None:
            # Finish cannot undercut the recorded IGT: post-restore replays
            # and legacy clients report stale values.
            participant.igt_ms = max(participant.igt_ms, finished_igt)
        participant.finished_at = datetime.now(UTC)

        # Bump current_layer to total_layers so progress displays N/N
        seed = participant.race.seed
        if seed:
            _set_layer(participant, seed.total_layers, participant.igt_ms)

        await db.commit()
        logger.info("Participant finished: %s, igt=%dms", participant.id, participant.igt_ms)

        # Re-load to get fresh race status/version + all participants
        participant = await _load_participant(db, participant_id)
        if not participant:
            return

        # Persist per-player finish first so its timestamp precedes the
        # race-finished message when the race auto-finishes on this event.
        display = participant.user.twitch_display_name or participant.user.twitch_username
        is_daily = participant.race.daily_date is not None
        finish_msg = (
            f"{display} finished the daily seed!"
            if is_daily
            else f"{display} has finished the race!"
        )
        participant_finished_public_json = await persist_system_chat(
            db, participant.race_id, ChatChannel.PUBLIC, finish_msg
        )

        race_transitioned = await check_race_auto_finish(db, participant.race)
        race_finished_public_json: str | None = None
        if race_transitioned:
            logger.info("Race finished: %s", participant.race_id)
            race_finished_msg = "The daily seed is over." if is_daily else "The race has finished."
            race_finished_public_json = await persist_system_chat(
                db, participant.race_id, ChatChannel.PUBLIC, race_finished_msg
            )
        await db.commit()

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
        daily_date=participant.race.daily_date,
    )

    # Unlock the PUBLIC channel for the finished participant before
    # broadcasting so they receive their own "X has finished" notice.
    # Past public chat history is pulled by the client via the
    # request_chat_history WS message once it detects the transition.
    room = manager.get_room(participant.race_id)
    if room:
        room.set_participant_status(participant.user_id, ParticipantStatus.FINISHED)
        await room.broadcast_chat_public(participant_finished_public_json, participant.race)
        if race_finished_public_json is not None:
            await room.broadcast_chat_public(race_finished_public_json, participant.race)


# ---------------------------------------------------------------------------
# broadcast_race_start (external API, kept module-level)
# ---------------------------------------------------------------------------
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
                    msg = compute_zone_update(start_node, graph_json, None, is_first_visit=True)
                    if msg:
                        msg = translate_zone_update(msg, conn.locale)
                        try:
                            await asyncio.wait_for(
                                conn.websocket.send_text(json.dumps(msg)),
                                timeout=SEND_TIMEOUT,
                            )
                        except Exception:
                            logger.warning(
                                "Failed to send zone_update: race=%s, participant=%s",
                                race_id,
                                conn.participant_id,
                            )

        # Also notify spectators of status change
        await manager.broadcast_race_status(
            race_id, "running", started_at=started_at, countdown_seconds=countdown_seconds
        )
        logger.info("Race start broadcast: race=%s", race_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def handle_mod_websocket(
    websocket: WebSocket,
    race_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle a mod WebSocket connection."""
    handler = RaceModHandler(websocket, race_id, session_maker)
    await handler.run()
