"""Mod connections of a relay race: the team runs one run, its baton holder plays it.

``RelayModHandler`` is the race handler whose entity, for the three progress
messages (``status_update``, ``event_flag``, ``zone_query``), is the runner's
``RelayTeam``: the shared handlers of ``BaseModHandler`` move the team's zone,
layer, IGT, history and deaths, and their guards (fresh save, wrong save) judge
the team's IGT. Only the baton holder is listened to (``holds_baton``), and not
before acknowledging a baton just given to them (``_listened``). Every other
member sends the same messages, since a mod does not know it waits: its
``event_flag`` and ``zone_query`` are acknowledged (the mod replays them until
then) and recorded nowhere, and its ``status_update`` only runs its own
fresh-save gate. The five baton messages (``relay_*``) go to the operations of
``websocket/race/relay.py``. See ``docs/RELAY.md`` ("Baton", "Cap", "Progress
and guards").
"""

import logging
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import WebSocket
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer, load_only, raiseload, selectinload

from speedfog_racing.models import (
    TERMINAL_PARTICIPANT_STATUSES,
    Caster,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
)
from speedfog_racing.services.debug_flags import merge_debug_flags
from speedfog_racing.services.layer_service import get_layer_for_node
from speedfog_racing.services.relay import (
    RelayTeamRow,
    counts_zone_on_exit,
    holds_baton,
    leaderboard_entries,
    relay_team_row,
)
from speedfog_racing.websocket.handler import MAX_FRESH_IGT_MS, clamp_death_count, clamp_igt
from speedfog_racing.websocket.race.manager import manager
from speedfog_racing.websocket.race.mod import (
    RaceModHandler,
    _is_countdown_active,
    _load_race_with_participants,
    aggregate_death_counts,
)
from speedfog_racing.websocket.race.relay import (
    awaiting_take,
    confirm_taken,
    finish_team,
    holder_connection_changed,
    request_handoff,
    request_take,
    send_relay_updates,
    set_ready,
    store_state,
)
from speedfog_racing.websocket.schemas import (
    DeathCountsMessage,
    ErrorCode,
    RelayHandoffRequestMessage,
    RelayReadyMessage,
    RelayStateMessage,
    RelayTakenMessage,
    RelayTakeRequestMessage,
)

logger = logging.getLogger(__name__)

_Message = TypeVar("_Message", bound=BaseModel)


class RelayModHandler(RaceModHandler):
    """Mod WebSocket handler for a relay race (see the module docstring).

    The overrides take a ``RelayTeam`` where ``RaceModHandler`` takes a
    ``Participant``, hence their targeted ``type: ignore``: the base handler
    only reads the progress fields both carry.
    """

    def __init__(
        self,
        websocket: WebSocket,
        race_id: uuid.UUID,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, race_id, session_maker)
        # The raw death counter of the holder's save, from the status_update
        # in flight: stored on their row by the commit that applies it to the
        # team (``_record_debug_flags``), so a rejected report stores nothing.
        self._holder_deaths: int | None = None
        self._message_handlers["relay_ready"] = self._handle_relay_ready
        self._message_handlers["relay_handoff_request"] = self._handle_relay_handoff_request
        self._message_handlers["relay_take_request"] = self._handle_relay_take_request
        self._message_handlers["relay_state"] = self._handle_relay_state
        self._message_handlers["relay_taken"] = self._handle_relay_taken

    # ------------------------------------------------------------------
    # The baton (operations in websocket/race/relay.py)
    # ------------------------------------------------------------------
    def _parse(self, model: type[_Message], msg: dict[str, Any]) -> _Message | None:
        """``msg`` as ``model``, or None (logged) when it does not parse."""
        try:
            return model.model_validate(msg)
        except ValidationError:
            logger.warning("Dropped malformed %s: %s", msg.get("type"), self.log_ref)
            return None

    async def _baton(self, operation: Awaitable[None]) -> None:
        """Run a baton operation; a failure is logged and keeps the socket."""
        try:
            await operation
        except Exception:
            logger.exception("Relay baton operation failed: %s", self.log_ref)

    async def _handle_relay_ready(self, msg: dict[str, Any]) -> None:
        parsed = self._parse(RelayReadyMessage, msg)
        if parsed is None or self._participant_id is None:
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            set_ready(
                self.session_maker,
                room,
                self._participant_id,
                parsed.ready,
                graph_json=self._cached_graph_json,
            )
        )

    async def _handle_relay_handoff_request(self, msg: dict[str, Any]) -> None:
        parsed = self._parse(RelayHandoffRequestMessage, msg)
        if parsed is None or self._participant_id is None:
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            request_handoff(
                self.session_maker,
                room,
                self._participant_id,
                parsed.to_participant_id,
                graph_json=self._cached_graph_json,
            )
        )

    async def _handle_relay_take_request(self, msg: dict[str, Any]) -> None:
        parsed = self._parse(RelayTakeRequestMessage, msg)
        if parsed is None or self._participant_id is None:
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            request_take(
                self.session_maker, room, self._participant_id, graph_json=self._cached_graph_json
            )
        )

    async def _handle_relay_state(self, msg: dict[str, Any]) -> None:
        parsed = self._parse(RelayStateMessage, msg)
        if parsed is None or self._participant_id is None:
            return
        igt_ms = clamp_igt(parsed.igt_ms)
        if igt_ms is None:
            logger.warning("Dropped relay_state with an invalid IGT: %s", self.log_ref)
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            store_state(
                self.session_maker,
                room,
                self._participant_id,
                parsed.handoff_id,
                parsed.state,
                igt_ms,
                graph_json=self._cached_graph_json,
            )
        )

    async def _handle_relay_taken(self, msg: dict[str, Any]) -> None:
        parsed = self._parse(RelayTakenMessage, msg)
        if parsed is None or self._participant_id is None:
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            confirm_taken(
                self.session_maker,
                room,
                self._participant_id,
                parsed.handoff_id,
                graph_json=self._cached_graph_json,
            )
        )

    # ------------------------------------------------------------------
    # Connection hooks
    # ------------------------------------------------------------------
    async def _on_authenticated(self) -> None:
        """A returning holder ends the offline wait; anyone's arrival is news
        to the team (``members[].online``). A returning ex-holder is simply
        a waiting runner (``auth_ok.relay.role``)."""
        await super()._on_authenticated()
        if self._participant_id is None:
            return
        room = manager.get_or_create_room(self._race_id)
        await self._baton(
            holder_connection_changed(
                self.session_maker,
                room,
                self._participant_id,
                connected=True,
                graph_json=self._cached_graph_json,
            )
        )

    async def _on_disconnect(self) -> None:
        """A leaving holder starts the 60 s wait and drops its pending release."""
        # Read first: the manager drops a room left without connections.
        room = manager.get_room(self._race_id)
        await super()._on_disconnect()
        if room is None or self._participant_id is None:
            return
        await self._baton(
            holder_connection_changed(
                self.session_maker,
                room,
                self._participant_id,
                connected=False,
                graph_json=self._cached_graph_json,
            )
        )

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------
    async def _handle_status_update(self, msg: dict[str, Any]) -> None:
        """The holder's report goes to the team, its death counter turned into
        the team's; anyone else's only runs that member's fresh-save gate."""
        holder = False
        validated = False
        reported: int | None = None
        async with self.session_maker() as db:
            gate = await self._read_gate(db)
            if gate is None:
                return
            member, race, team = gate
            holder = self._listened(team)
            if holder:
                reported = clamp_death_count(msg.get("death_count"))
                if reported is not None:
                    # Each save counts its own deaths: the team's count moves
                    # by what the holder's counter moved since its last report.
                    msg = {
                        **msg,
                        "death_count": max(0, team.death_count + reported - member.death_count),
                    }
            elif await self._validate_member(member, race, msg):
                validated = True
                await db.commit()
            team_id = team.id

        if validated:
            await send_relay_updates(
                self.session_maker, self._race_id, team_id, graph_json=self._cached_graph_json
            )
        if not holder:
            return
        self._holder_deaths = reported
        try:
            await super()._handle_status_update(msg)
        finally:
            self._holder_deaths = None

    def _listened(self, team: RelayTeam) -> bool:
        """Whether this runner's progress goes to ``team``: they hold its
        baton (``holds_baton``), and it is not a baton just given to them whose
        ``relay_taken`` is awaited (``awaiting_take``, in the room's memory: no
        query, no lock). Until that acknowledgement their game still carries
        their own save's IGT and deaths, so they are heard as a waiting runner."""
        return (
            self._participant_id is not None
            and holds_baton(team, self._participant_id)
            and not awaiting_take(manager.get_room(self._race_id), team.id, self._participant_id)
        )

    async def _read_gate(self, db: AsyncSession) -> tuple[Participant, Race, RelayTeam] | None:
        """The runner, its race and the baton of its team, in one light query
        (no team history, no field): every member reports about once a second."""
        row = (
            await db.execute(
                select(Participant, Race, RelayTeam)
                .join(Race, Race.id == Participant.race_id)
                .join(RelayTeam, RelayTeam.id == Participant.relay_team_id)
                .where(Participant.id == self._participant_id)
                .options(
                    raiseload(Race.relay_teams),
                    load_only(RelayTeam.holder_id, RelayTeam.baton_free, RelayTeam.death_count),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        member, race, team = row
        return member, race, team

    async def _validate_member(self, member: Participant, race: Race, msg: dict[str, Any]) -> bool:
        """A waiting runner's own fresh-save gate: its first report once the race
        runs validates its save when the IGT is at most ``MAX_FRESH_IGT_MS``,
        READY becoming PLAYING. Items are a union at a handoff, so a member on
        an old save would bring its inventory into the team. Its IGT is never
        judged afterwards. True when the member just passed."""
        if race.status != RaceStatus.RUNNING:
            await self._send_condition(ErrorCode.RACE_NOT_RUNNING)
            return False
        if (
            member.relay_validated
            or member.status in TERMINAL_PARTICIPANT_STATUSES
            or _is_countdown_active(race)
        ):
            return False
        igt_ms = clamp_igt(msg.get("igt_ms"))
        if igt_ms is None:
            return False
        if igt_ms > MAX_FRESH_IGT_MS:
            logger.warning("Rejected stale save (relay member): %s igt_ms=%d", self.log_ref, igt_ms)
            await self._send_condition(ErrorCode.FRESH_SAVE_REQUIRED)
            return False
        member.relay_validated = True
        if member.status == ParticipantStatus.READY:
            member.status = ParticipantStatus.PLAYING
        logger.info("Relay member validated: %s igt_ms=%d", self.log_ref, igt_ms)
        return True

    async def _validate_for_status_update(self, entity: RelayTeam) -> bool:  # type: ignore[override]
        if not await super()._validate_for_status_update(entity):  # type: ignore[arg-type]
            return False
        # Again in the session that commits, under the team's row lock (see
        # ``_team_select``): the baton may have moved since the pre-read.
        return self._listened(entity)

    async def _validate_for_event_flag(  # type: ignore[override]
        self, entity: RelayTeam, message_id: int | None
    ) -> bool:
        if not await super()._validate_for_event_flag(entity, message_id):  # type: ignore[arg-type]
            return False
        if self._listened(entity):
            return True
        logger.info(
            "Ignored event_flag of a waiting runner: %s message_id=%s", self.log_ref, message_id
        )
        if message_id is not None:
            await self._send_event_flag_ack(message_id)
        return False

    async def _validate_for_zone_query(  # type: ignore[override]
        self, entity: RelayTeam, message_id: int | None
    ) -> bool:
        if not await super()._validate_for_zone_query(entity, message_id):  # type: ignore[arg-type]
            return False
        if self._listened(entity):
            return True
        if message_id is not None:
            await self._send_zone_query_ack(message_id)
        return False

    async def _handle_finished_message(self, msg: dict[str, Any]) -> None:
        """The legacy ``finished`` message: a team finishes only on its holder's
        final boss flag."""
        logger.info("Ignored finished message on a relay race: %s", self.log_ref)

    # ------------------------------------------------------------------
    # Entity loading
    # ------------------------------------------------------------------
    def _team_select(self) -> Select[tuple[RelayTeam]]:
        """The runner's team with its members and their users, found through
        the runner's row at each message (placement may change in setup while
        the mod stays connected).

        Every load of the three progress messages commits what it decides, so
        it row-locks the team (``FOR UPDATE``, a no-op on SQLite), as the baton
        operations do (``relay.team_for_update``): a flip waits for the
        progress write in flight, or the write's gate sees the flip. The
        character state, which no progress handler reads, is left out.
        """
        return (
            select(RelayTeam)
            .join(Participant, Participant.relay_team_id == RelayTeam.id)
            .where(Participant.id == self._participant_id)
            .options(
                selectinload(RelayTeam.members).selectinload(Participant.user),
                defer(RelayTeam.character_state),
            )
            .with_for_update(of=RelayTeam)
        )

    async def _load_entity(self, db: AsyncSession) -> RelayTeam | None:  # type: ignore[override]
        """With the race as ``_load_participant`` loads a runner's: seed, field
        with users and teams (leaderboard broadcasts), casters. The race's
        teams are named: reached through ``RelayTeam.race``, their default
        selectin would lead back to the team and is not followed. Their
        character states are left out (no row reads them)."""
        race = selectinload(RelayTeam.race)
        result = await db.execute(
            self._team_select().options(
                race.selectinload(Race.seed),
                race.selectinload(Race.relay_teams).defer(RelayTeam.character_state),
                race.selectinload(Race.participants).selectinload(Participant.user),
                race.selectinload(Race.casters).selectinload(Caster.user),
            )
        )
        return result.scalar_one_or_none()

    async def _load_entity_for_status_update(  # type: ignore[override]
        self, db: AsyncSession
    ) -> RelayTeam | None:
        """With the race alone (and its seed while no graph is cached). The
        race's teams stay out (``raiseload``: a read would be a bug): the 1 Hz
        report never reads them, and they carry every team's history. Also the
        load of boss kills and item uses."""
        race = selectinload(RelayTeam.race)
        options = [race.raiseload(Race.relay_teams)]
        if self._cached_graph_json is None:
            options.append(race.selectinload(Race.seed))
        result = await db.execute(self._team_select().options(*options))
        return result.scalar_one_or_none()

    def _get_graph_json(self, entity: RelayTeam) -> dict[str, Any] | None:  # type: ignore[override]
        if self._cached_graph_json is not None:
            return self._cached_graph_json
        return entity.race.seed.graph_json if entity.race.seed else None

    def _holder(self, team: RelayTeam) -> Participant | None:
        """This runner's row among the team's members (the holder, past the gate)."""
        return next((m for m in team.members if m.id == self._participant_id), None)

    def _row(self, team: RelayTeam, graph_json: dict[str, Any] | None) -> RelayTeamRow:
        return relay_team_row(team, team.members, graph_json)

    # ------------------------------------------------------------------
    # Progress hooks (inside the shared handlers' session)
    # ------------------------------------------------------------------
    def _stamp_runner(self, team: RelayTeam) -> None:
        """Name the holder on the history's last entry (the map tells who played
        a zone). Entries are copied, never mutated in place."""
        history = team.zone_history
        if history and "runner_id" not in history[-1]:
            team.zone_history = [
                *history[:-1],
                {**history[-1], "runner_id": str(self._participant_id)},
            ]

    def _on_first_init(self, entity: RelayTeam, start_node: str) -> None:  # type: ignore[override]
        # The team's fresh-save gate passed on its first holder's report: the
        # team plays, and that report validates the holder's save too.
        super()._on_first_init(entity, start_node)  # type: ignore[arg-type]
        holder = self._holder(entity)
        if holder is not None:
            holder.relay_validated = True
            if holder.status == ParticipantStatus.READY:
                holder.status = ParticipantStatus.PLAYING
        self._stamp_runner(entity)

    def _on_fog_gate(  # type: ignore[override]
        self, entity: RelayTeam, flag_id: int, node_id: str, graph_json: dict[str, Any]
    ) -> None:
        # The zone a handoff restarts; backtracks never move it.
        entity.entry_flag_id = flag_id
        # A zone without a tracked boss counts for the runner who exits it to
        # a new layer (a boss's zone counted on its kill).
        history = entity.zone_history or []
        left = history[-2].get("node_id") if len(history) >= 2 else None
        if (
            isinstance(left, str)
            and get_layer_for_node(node_id, graph_json) > entity.current_layer
            and counts_zone_on_exit(self._boss_flags(graph_json), graph_json, left)
        ):
            holder = self._holder(entity)
            if holder is not None:
                holder.relay_zones += 1

    def _on_zone_entered(  # type: ignore[override]
        self, entity: RelayTeam, node_id: str, graph_json: dict[str, Any], igt: int
    ) -> None:
        super()._on_zone_entered(entity, node_id, graph_json, igt)  # type: ignore[arg-type]
        self._stamp_runner(entity)

    def _record_debug_flags(  # type: ignore[override]
        self, entity: RelayTeam, reported: Any, igt_ms: int
    ) -> list[str]:
        # What the report says of the holder's own save lands on their row:
        # its raw death counter and its debug flags.
        holder = self._holder(entity)
        if holder is None:
            return []
        if self._holder_deaths is not None:
            holder.death_count = self._holder_deaths
        merged, added = merge_debug_flags(
            holder.debug_flags,
            reported,
            igt_ms=igt_ms,
            node_id=entity.current_zone,
            now=datetime.now(UTC),
        )
        if added:
            holder.debug_flags = merged
        return added

    async def _on_debug_flags_recorded(  # type: ignore[override]
        self, entity: RelayTeam, added: list[str]
    ) -> None:
        holder = self._holder(entity)
        if holder is not None:
            await self._alert_debug_flags(holder, entity.race, added, self._get_graph_json(entity))

    def _on_boss_kill_recorded(  # type: ignore[override]
        self, entity: RelayTeam, node_id: str, igt_ms: int
    ) -> None:
        """A new kill counts its zone for the holder who made it, in the commit
        that stamps it (a replay of the flag is a duplicate, so a count lost
        after that commit would be lost for good); a re-report (a restart, or
        a flag a handoff set) never reaches here. Counted even at the cap: the
        game allowed the kill."""
        holder = self._holder(entity)
        if holder is not None:
            holder.relay_zones += 1

    async def _on_boss_killed(  # type: ignore[override]
        self, entity: RelayTeam, node_id: str, igt_ms: int
    ) -> None:
        """The counted kill moves the team's row and its ``relay_update``
        (``members[].zones``, ``gates_locked``)."""
        graph = self._get_graph_json(entity)
        await manager.broadcast_player_update(
            entity.race_id, self._row(entity, graph), graph_json=graph
        )
        await send_relay_updates(self.session_maker, entity.race_id, entity.id, graph_json=graph)

    async def _handle_finish_event(  # type: ignore[override]
        self, entity: RelayTeam, igt: int, message_id: int | None
    ) -> None:
        assert self._participant_id is not None
        await finish_team(self.session_maker, entity.id, self._participant_id, igt)

    # ------------------------------------------------------------------
    # Broadcast hooks: the team's row, never a runner's
    # ------------------------------------------------------------------
    async def _broadcast_after_status_update(  # type: ignore[override]
        self,
        entity: RelayTeam,
        *,
        became_active: bool,
        death_delta: int,
        history_changed: bool,
        weapons: list[int] | None,
    ) -> None:
        graph = self._get_graph_json(entity)
        entries = None
        if became_active or death_delta > 0:
            # The leaderboard and the death counts read the whole field.
            async with self.session_maker() as db:
                race = await _load_race_with_participants(db, entity.race_id)
            if race is None:
                return
            entries = leaderboard_entries(race, graph)

        if became_active and entries is not None:
            await manager.broadcast_leaderboard(entity.race_id, entries, graph_json=graph)
            # The team plays now, its holder validated.
            await send_relay_updates(
                self.session_maker, entity.race_id, entity.id, graph_json=graph
            )
        else:
            await manager.broadcast_player_update(
                entity.race_id, self._row(entity, graph), graph_json=graph, weapons=weapons
            )

        if history_changed:
            await manager.broadcast_zone_history(
                entity.race_id, entity.id, entity.zone_history or []
            )

        if death_delta > 0 and entries is not None:
            room = manager.get_room(entity.race_id)
            if room:
                counts = aggregate_death_counts(entries)
                await room.broadcast_to_mods(DeathCountsMessage(counts=counts).model_dump_json())

    async def _broadcast_after_event_flag(  # type: ignore[override]
        self,
        entity: RelayTeam,
        node_id: str | None,
        seed_graph: dict[str, Any] | None,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        if is_first_visit:
            await manager.broadcast_leaderboard(
                entity.race_id,
                leaderboard_entries(entity.race, seed_graph),
                graph_json=seed_graph,
            )
        else:
            await manager.broadcast_player_update(
                entity.race_id, self._row(entity, seed_graph), graph_json=seed_graph
            )
        await manager.broadcast_zone_history(entity.race_id, entity.id, entity.zone_history or [])
        # The gate moved the zone a taker restarts, and may have counted one.
        await send_relay_updates(
            self.session_maker, entity.race_id, entity.id, graph_json=seed_graph
        )

    async def _broadcast_after_boss_kill(self, entity: RelayTeam) -> None:  # type: ignore[override]
        await manager.broadcast_zone_history(entity.race_id, entity.id, entity.zone_history or [])

    async def _broadcast_after_zone_query(  # type: ignore[override]
        self,
        entity: RelayTeam,
        *,
        is_first_visit: bool,
        prev_zone_history_len: int | None,
    ) -> None:
        graph = self._get_graph_json(entity)
        if is_first_visit:
            await manager.broadcast_leaderboard(
                entity.race_id, leaderboard_entries(entity.race, graph), graph_json=graph
            )
        else:
            await manager.broadcast_player_update(
                entity.race_id, self._row(entity, graph), graph_json=graph
            )
        if prev_zone_history_len is not None:
            await manager.broadcast_zone_history(
                entity.race_id, entity.id, entity.zone_history or []
            )
