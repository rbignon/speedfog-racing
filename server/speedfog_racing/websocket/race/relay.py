"""Relay races on the mod socket: what a mod is told about its team and its
role, and the baton operations.

The operations (``request_handoff``, ``store_state``, ``request_take``,
``confirm_taken``, ``set_ready``, ``holder_connection_changed``, and the take
timer) each take ``RaceRoom.relay_lock``, so they run one at a time per race.
All but ``set_ready`` read the team through ``team_for_update``, whose row lock
orders a flip and a progress write of the same team; ``set_ready`` reads only
the member's team id, without a lock. See ``docs/RELAY.md`` ("Baton").
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.discord import fire_race_finished_notifications
from speedfog_racing.models import (
    TERMINAL_PARTICIPANT_STATUSES,
    Caster,
    ChatChannel,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
)
from speedfog_racing.services.layer_service import get_start_node
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.services.relay import (
    RELAY_REFUSAL_MESSAGES,
    RELAY_RELEASE_TIMEOUT_S,
    RELAY_TAKE_TIMEOUT_S,
    RelayRefusal,
    baton_free_in_s,
    baton_is_free,
    copy_team_result,
    holds_baton,
    leaderboard_entries,
    load_relay_row,
    receive_refusal,
    relay_flags,
    relay_warp_flag,
    team_cap,
    team_defeat_flags,
)
from speedfog_racing.websocket.handler import is_igt_plausible
from speedfog_racing.websocket.schemas import (
    CharacterState,
    RelayFlags,
    RelayInfo,
    RelayMember,
    RelayRefusedMessage,
    RelayReleaseMessage,
    RelayTakeMessage,
    RelayUpdateMessage,
    persist_system_chat,
)

if TYPE_CHECKING:
    from speedfog_racing.websocket.race.manager import RaceRoom

logger = logging.getLogger(__name__)


@dataclass
class PendingHandoff:
    """A handoff in flight, kept per team on ``RaceRoom.relay_pending``.

    Phase ``release``: the holder was asked for its state (``relay_release``),
    which must come back before ``expires_at``. Phase ``take``: the baton went
    to ``target_id`` (``relay_take``), whose ``relay_taken`` is awaited; its
    ``timer`` frees the baton at ``expires_at``. A take whose timer fired stays
    here, so its late ``relay_taken`` is still recognised. ``expires_at`` is
    on ``time.monotonic()``; an expired handoff blocks no request.
    """

    handoff_id: str
    team_id: uuid.UUID
    giver_id: uuid.UUID | None
    target_id: uuid.UUID
    phase: Literal["release", "take"]
    expires_at: float
    timer: asyncio.Task[None] | None = None

    def expired(self, now: float) -> bool:
        return now >= self.expires_at


def relay_member_wire(
    member: Participant, *, connected: Collection[uuid.UUID], ready: Collection[uuid.UUID]
) -> RelayMember:
    """One member as the team row and ``RelayInfo`` list them. ``ready`` is the
    member's last ``relay_ready``, false while the mod is not connected."""
    return RelayMember(
        participant_id=str(member.id),
        name=member.user.twitch_display_name or member.user.twitch_username,
        zones=member.relay_zones,
        status=member.status.value,
        online=member.id in connected,
        ready=member.id in connected and member.id in ready,
        validated=member.relay_validated,
    )


def relay_zone_name(team: RelayTeam, graph_json: Mapping[str, Any] | None) -> str | None:
    """Display name of the zone a taker would restart: the node of the team's
    ``entry_flag_id`` in ``event_map``, or the start node before any gate.
    None when the graph does not know it."""
    if not graph_json:
        return None
    nodes = graph_json.get("nodes")
    if not isinstance(nodes, dict):
        return None
    if team.entry_flag_id is None:
        node_id = get_start_node(dict(graph_json))
    else:
        node_id = (graph_json.get("event_map") or {}).get(str(team.entry_flag_id))
    node = nodes.get(node_id) if isinstance(node_id, str) else None
    if not isinstance(node, dict):
        return None
    name = node.get("display_name")
    return name if isinstance(name, str) and name else node_id


def build_relay_info(
    team: RelayTeam,
    members: Sequence[Participant],
    me: Participant,
    *,
    total_layers: int,
    flags: dict[str, int],
    connected: Collection[uuid.UUID],
    ready: Collection[uuid.UUID],
    now: datetime,
    graph_json: Mapping[str, Any] | None = None,
) -> RelayInfo:
    """``me``'s view of ``team``. A holder is a holder only while the baton is
    not free: after a take nobody acknowledged, the nominal holder waits like
    the others and may take the baton back."""
    cap = team_cap(total_layers, members)
    holder_online = team.holder_id is not None and team.holder_id in connected
    is_holder = holds_baton(team, me.id)
    return RelayInfo(
        team_id=str(team.id),
        team_name=team.name,
        team_status=team.status.value,
        cap=cap,
        holder_id=str(team.holder_id) if team.holder_id else None,
        holder_online=holder_online,
        zone_name=relay_zone_name(team, graph_json),
        baton_free_in_s=baton_free_in_s(team, holder_connected=holder_online, now=now),
        role="holder" if is_holder else "waiting",
        gates_locked=is_holder and me.relay_zones >= cap,
        members=[relay_member_wire(m, connected=connected, ready=ready) for m in members],
        flags=RelayFlags(**flags),
    )


async def send_relay_updates(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    team_id: uuid.UUID,
    *,
    graph_json: Mapping[str, Any] | None = None,
    to: Collection[uuid.UUID] | None = None,
) -> None:
    """Send each connected mod of the team a ``relay_update`` with its own role
    (only the members in ``to`` when given).

    ``graph_json`` is the race's seed graph when the caller holds it (a mod
    handler caches it): the seed is then not loaded again.
    """
    from speedfog_racing.websocket.race.manager import manager

    room = manager.get_room(race_id)
    if room is None:
        return
    async with session_maker() as db:
        graph = graph_json if graph_json is not None else await _race_graph(db, race_id)
        row = await load_relay_row(db, team_id, graph)
    if row is None or graph is None:
        return
    flags = relay_flags(graph)
    if flags is None:
        return
    connected = set(room.mods.keys())
    now = datetime.now(UTC)
    for member in row.members:
        if member.id not in connected or (to is not None and member.id not in to):
            continue
        info = build_relay_info(
            row.team,
            row.members,
            member,
            total_layers=int(graph.get("total_layers") or 0),
            flags=flags,
            connected=connected,
            ready=room.relay_ready,
            now=now,
            graph_json=graph,
        )
        await room.send_to_mod(member.id, RelayUpdateMessage(relay=info).model_dump_json())


async def finish_team(
    session_maker: async_sessionmaker[AsyncSession],
    team_id: uuid.UUID,
    holder_id: uuid.UUID,
    igt_ms: int,
) -> None:
    """A relay team's finish: its holder killed the final boss at ``igt_ms``.

    ``handle_finished`` on the team: FINISHED, ``finished_at``, the layer set to
    the seed's total, the result copied onto the members still in
    (``copy_team_result``), the final boss counted for the holder (the cap
    never refuses it), the public chat line, auto-finish, then the same
    broadcasts, plus a ``relay_update`` that tells the team's mods their race
    is over. A relay race has no deathless rule, IGT cutoff or projection.
    """
    # Local imports: these modules import this one.
    from speedfog_racing.websocket.race.manager import manager
    from speedfog_racing.websocket.race.mod import _set_layer
    from speedfog_racing.websocket.race.spectator import broadcast_race_state_update

    race_transitioned = False
    async with session_maker() as db:
        team = await _load_finishing_team(db, team_id)
        if team is None:
            return
        race = team.race
        if race.status != RaceStatus.RUNNING or team.status in TERMINAL_PARTICIPANT_STATUSES:
            return

        team.status = ParticipantStatus.FINISHED
        # Never below the recorded IGT: replays after a restore report stale values.
        team.igt_ms = max(team.igt_ms, igt_ms)
        team.finished_at = datetime.now(UTC)
        if race.seed:
            _set_layer(team, race.seed.total_layers, team.igt_ms)
        holder = next((m for m in team.members if m.id == holder_id), None)
        if holder is not None:
            holder.relay_zones += 1
        copy_team_result(team, team.members)
        await db.commit()
        logger.info("Relay team finished: %s, igt=%dms", team.id, team.igt_ms)

        # Fresh rows of the whole field: another team may have finished
        # meanwhile, and auto-finish reads every participant.
        db.expire_all()
        team = await _load_finishing_team(db, team_id)
        if team is None:
            return
        race, members = team.race, list(team.members)
        team_finished_json = await persist_system_chat(
            db, race.id, ChatChannel.PUBLIC, f"{team.name} has finished the race!"
        )
        race_transitioned = await check_race_auto_finish(db, race)
        race_finished_json: str | None = None
        if race_transitioned:
            logger.info("Race finished: %s", race.id)
            race_finished_json = await persist_system_chat(
                db, race.id, ChatChannel.PUBLIC, "The race has finished."
            )
        await db.commit()

    # Session closed. All broadcasts use detached objects.
    graph = race.seed.graph_json if race.seed else None
    if race_transitioned:
        # race_state first, so spectators get status=finished and the history together.
        await broadcast_race_state_update(race.id, race)
        await manager.broadcast_race_status(race.id, "finished")
        fire_race_finished_notifications(race)

    await manager.broadcast_leaderboard(race.id, leaderboard_entries(race, graph), graph_json=graph)
    await send_relay_updates(session_maker, race.id, team.id, graph_json=graph)

    # Unlock the PUBLIC channel for the finished members before the notice.
    room = manager.get_room(race.id)
    if room:
        for member in members:
            if member.status == ParticipantStatus.FINISHED:
                room.set_participant_status(member.user_id, ParticipantStatus.FINISHED)
        await room.broadcast_chat_public(team_finished_json, race)
        if race_finished_json is not None:
            await room.broadcast_chat_public(race_finished_json, race)


async def _load_finishing_team(db: AsyncSession, team_id: uuid.UUID) -> RelayTeam | None:
    """A team with its members and its race as ``handle_finished`` loads a
    runner's: seed, field with users and teams, casters (the race's teams are
    named: reached through ``RelayTeam.race``, their default selectin is not
    followed)."""
    race = selectinload(RelayTeam.race)
    result = await db.execute(
        select(RelayTeam)
        .where(RelayTeam.id == team_id)
        .options(
            selectinload(RelayTeam.members).selectinload(Participant.user),
            race.selectinload(Race.seed),
            race.selectinload(Race.relay_teams),
            race.selectinload(Race.participants).selectinload(Participant.user),
            race.selectinload(Race.casters).selectinload(Caster.user),
        )
    )
    return result.scalar_one_or_none()


async def _race_graph(db: AsyncSession, race_id: uuid.UUID) -> dict[str, Any] | None:
    result = await db.execute(
        select(Race).where(Race.id == race_id).options(selectinload(Race.seed))
    )
    race = result.scalar_one_or_none()
    return race.seed.graph_json if race and race.seed else None


# ---------------------------------------------------------------------------
# Baton operations
# ---------------------------------------------------------------------------
def team_for_update(
    *, participant_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None
) -> Select[tuple[RelayTeam]]:
    """A team row-locked (``FOR UPDATE``, a no-op on SQLite), found through one
    of its members or by id, with its members and their users, and its race
    (without the race's teams). The progress handlers' committing loads take
    the same lock (``RelayModHandler._team_select``): a flip and a progress
    write of one team are ordered by the database."""
    statement = select(RelayTeam)
    if participant_id is not None:
        statement = statement.join(Participant, Participant.relay_team_id == RelayTeam.id).where(
            Participant.id == participant_id
        )
    else:
        statement = statement.where(RelayTeam.id == team_id)
    return statement.options(
        selectinload(RelayTeam.members).selectinload(Participant.user),
        selectinload(RelayTeam.race).raiseload(Race.relay_teams),
    ).with_for_update(of=RelayTeam)


async def _locked_team(
    db: AsyncSession,
    graph_json: dict[str, Any] | None,
    *,
    participant_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> tuple[RelayTeam, dict[str, Any]] | None:
    """``team_for_update``'s team and the race's seed graph (``graph_json``
    when the caller holds it), or None."""
    statement = team_for_update(participant_id=participant_id, team_id=team_id)
    if graph_json is None:
        statement = statement.options(selectinload(RelayTeam.race).selectinload(Race.seed))
    team = (await db.execute(statement)).scalar_one_or_none()
    if team is None:
        return None
    graph = graph_json
    if graph is None and team.race.seed is not None:
        graph = team.race.seed.graph_json
    if graph is None:
        return None
    return team, graph


def _baton_moves(team: RelayTeam) -> bool:
    """Whether the team's baton may move now: its race runs, past the
    countdown, and the team is still in it."""
    # Local import: mod.py imports this module.
    from speedfog_racing.websocket.race.mod import _is_countdown_active

    return (
        team.race.status == RaceStatus.RUNNING
        and not _is_countdown_active(team.race)
        and team.status in (ParticipantStatus.READY, ParticipantStatus.PLAYING)
    )


def _in_flight(room: "RaceRoom", team_id: uuid.UUID) -> bool:
    pending = room.relay_pending.get(team_id)
    return pending is not None and not pending.expired(time.monotonic())


def _set_pending(room: "RaceRoom", team_id: uuid.UUID, pending: PendingHandoff | None) -> None:
    """Replace (or with None drop) the team's handoff, stopping its timer."""
    old = room.relay_pending.pop(team_id, None)
    if old is not None and old.timer is not None and not old.timer.done():
        old.timer.cancel()
    if pending is not None:
        room.relay_pending[team_id] = pending


def awaiting_take(room: "RaceRoom | None", team_id: uuid.UUID, participant_id: uuid.UUID) -> bool:
    """Whether the team's baton went to ``participant_id`` and their
    ``relay_taken`` is still awaited (a take whose timer fired too, the baton
    being free then). Until it comes, their game still carries their own
    save's IGT and deaths: the progress gate hears them as a waiting runner.
    In memory only, so a server restart forgets it."""
    pending = room.relay_pending.get(team_id) if room is not None else None
    return pending is not None and pending.phase == "take" and pending.target_id == participant_id


def _cap(team: RelayTeam, graph: Mapping[str, Any]) -> int:
    return team_cap(int(graph.get("total_layers") or 0), team.members)


async def _refuse(room: "RaceRoom", participant_id: uuid.UUID, code: str) -> None:
    logger.info("Relay request refused: participant=%s code=%s", participant_id, code)
    message = RelayRefusedMessage(code=code, message=RELAY_REFUSAL_MESSAGES[RelayRefusal(code)])
    await room.send_to_mod(participant_id, message.model_dump_json())


def _store_state(team: RelayTeam, state: CharacterState, igt_ms: int) -> bool:
    """Keep ``state`` as the team's last character state, the team's IGT raised
    first to ``igt_ms``. False, and nothing kept, when the wrong-save guard
    refuses ``igt_ms`` (as it would the holder's ``status_update``): the state
    may come from another save, and the next receiver would get it."""
    now = datetime.now(UTC)
    if not is_igt_plausible(team.igt_ms, team.last_igt_change_at, igt_ms, now):
        logger.warning(
            "Dropped relay_state on implausible IGT (wrong save?): team=%s reported=%d recorded=%d",
            team.id,
            igt_ms,
            team.igt_ms,
        )
        return False
    if igt_ms > team.igt_ms:
        team.igt_ms = igt_ms
        team.last_igt_change_at = now
    team.character_state = state.model_dump()
    team.character_state_igt_ms = team.igt_ms
    return True


@dataclass
class _Flip:
    """A committed flip, for what follows the session."""

    race_id: uuid.UUID
    team_id: uuid.UUID
    target_id: uuid.UUID
    pending: PendingHandoff | None
    take: RelayTakeMessage


async def _flip(
    session_maker: async_sessionmaker[AsyncSession],
    db: AsyncSession,
    room: "RaceRoom",
    team: RelayTeam,
    target: Participant,
    *,
    handoff_id: str,
    graph: dict[str, Any],
) -> _Flip:
    """Give ``target`` the baton and commit. A target whose mod is no longer
    connected gets a free baton at once (``baton_free``), and no take is
    awaited from them.

    The awaited take is in the room, with its timer running, before the
    commit: no progress message of the receiver is heard between the two
    (``awaiting_take``), and whatever fails after the commit, the take still
    expires and frees the baton."""
    connected = target.id in room.mods
    giver_id = team.holder_id
    team.holder_id = target.id
    team.holder_offline_since = None
    team.baton_free = not connected
    pending = None
    if connected:
        pending = PendingHandoff(
            handoff_id=handoff_id,
            team_id=team.id,
            giver_id=giver_id,
            target_id=target.id,
            phase="take",
            expires_at=time.monotonic() + RELAY_TAKE_TIMEOUT_S,
        )
        pending.timer = asyncio.create_task(_take_timeout(session_maker, room, pending, graph))
    _set_pending(room, team.id, pending)
    try:
        await db.commit()
    except BaseException:
        _set_pending(room, team.id, None)
        raise
    flags = relay_flags(graph) or {}
    take = RelayTakeMessage(
        handoff_id=handoff_id,
        state=CharacterState.model_validate(team.character_state)
        if team.character_state is not None
        else None,
        igt_ms=team.igt_ms,
        defeat_flags=team_defeat_flags(graph, team.zone_history),
        warp_flag=relay_warp_flag(flags, team.entry_flag_id) if flags else None,
        zone_name=relay_zone_name(team, graph) if team.entry_flag_id is not None else None,
    )
    logger.info(
        "Relay baton flipped: team=%s from=%s to=%s handoff=%s connected=%s",
        team.id,
        giver_id,
        target.id,
        handoff_id,
        connected,
    )
    return _Flip(team.race_id, team.id, target.id, pending, take)


async def _after_flip(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    flip: _Flip,
    graph: dict[str, Any],
) -> None:
    """Send the take to the receiver (when one is awaited) and tell the team."""
    if flip.pending is not None:
        await room.send_to_mod(flip.target_id, flip.take.model_dump_json())
    # The giver's mod locks and goes to the Chapel on the role this tells it.
    await send_relay_updates(session_maker, flip.race_id, flip.team_id, graph_json=graph)


async def _take_timeout(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    pending: PendingHandoff,
    graph: dict[str, Any],
) -> None:
    """A take nobody acknowledged in time frees the baton: any teammate under
    their cap, the giver and the nominal holder included, may take it. Only
    while it is still this team's awaited take, its receiver still holds the
    baton and the baton can still move (a reset or a finish stops it)."""
    await asyncio.sleep(RELAY_TAKE_TIMEOUT_S)
    try:
        async with room.relay_lock:
            if room.relay_pending.get(pending.team_id) is not pending:
                return
            async with session_maker() as db:
                loaded = await _locked_team(db, graph, team_id=pending.team_id)
                if loaded is None:
                    return
                team, _ = loaded
                if team.holder_id != pending.target_id or team.baton_free or not _baton_moves(team):
                    return
                team.baton_free = True
                race_id = team.race_id
                await db.commit()
            logger.info(
                "Relay take not acknowledged, baton free: team=%s handoff=%s",
                pending.team_id,
                pending.handoff_id,
            )
            await send_relay_updates(session_maker, race_id, pending.team_id, graph_json=graph)
    except Exception:
        logger.exception("Relay take timeout failed: team=%s", pending.team_id)


async def request_handoff(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    to_participant_id: str,
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """The holder asks to hand the baton to a teammate: ``relay_release`` back
    when every check passes (a release awaits its state for 15 s), else
    ``relay_refused``. See ``docs/RELAY.md`` ("Baton") for the checks' order."""
    async with room.relay_lock:
        async with session_maker() as db:
            loaded = await _locked_team(db, graph_json, participant_id=participant_id)
            if loaded is None:
                return
            team, graph = loaded
        try:
            wanted: uuid.UUID | None = uuid.UUID(to_participant_id)
        except ValueError:
            wanted = None
        target = next((m for m in team.members if m.id == wanted and m.id != participant_id), None)
        refusal: str | None
        if not _baton_moves(team) or _in_flight(room, team.id):
            refusal = RelayRefusal.BUSY
        elif not holds_baton(team, participant_id):
            refusal = RelayRefusal.NOT_HOLDER
        elif target is None:
            refusal = RelayRefusal.TARGET_UNAVAILABLE
        else:
            refusal = receive_refusal(
                target,
                cap=_cap(team, graph),
                connected=target.id in room.mods,
                ready=target.id in room.relay_ready,
                asking=False,
            )
        if refusal is not None or target is None:
            await _refuse(room, participant_id, refusal or RelayRefusal.TARGET_UNAVAILABLE)
            return
        pending = PendingHandoff(
            handoff_id=uuid.uuid4().hex,
            team_id=team.id,
            giver_id=participant_id,
            target_id=target.id,
            phase="release",
            expires_at=time.monotonic() + RELAY_RELEASE_TIMEOUT_S,
        )
        _set_pending(room, team.id, pending)
        logger.info(
            "Relay release asked: team=%s from=%s to=%s handoff=%s",
            team.id,
            participant_id,
            target.id,
            pending.handoff_id,
        )
        release = RelayReleaseMessage(
            handoff_id=pending.handoff_id,
            to_name=target.user.twitch_display_name or target.user.twitch_username,
        )
        await room.send_to_mod(participant_id, release.model_dump_json())


async def store_state(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    handoff_id: str | None,
    state: CharacterState,
    igt_ms: int,
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """A ``relay_state``: a checkpoint (``handoff_id`` null) or the answer to a
    ``relay_release``.

    From the holder of a running team the state is kept (``_store_state``,
    which drops a state on an implausible IGT); when it is kept and answers the
    pending release in time, the baton then flips to its target (still a member
    in the race). Anything else flips nothing (the release it answers is
    dropped), and the sender of any ``relay_state`` but a plain checkpoint gets
    a ``relay_update``: a giver who already locked learns it still holds the
    baton.
    """
    async with room.relay_lock:
        flip: _Flip | None = None
        async with session_maker() as db:
            loaded = await _locked_team(db, graph_json, participant_id=participant_id)
            if loaded is None:
                return
            team, graph = loaded
            pending = room.relay_pending.get(team.id)
            answered = (
                pending
                if pending is not None
                and handoff_id is not None
                and pending.phase == "release"
                and pending.handoff_id == handoff_id
                and pending.giver_id == participant_id
                and not pending.expired(time.monotonic())
                else None
            )
            if (
                pending is not None
                and pending.phase == "release"
                and (answered is not None or pending.expired(time.monotonic()))
            ):
                _set_pending(room, team.id, None)
            # Heard like a progress message: not before the holder's
            # relay_taken for a baton just received (``awaiting_take``).
            holder = (
                holds_baton(team, participant_id)
                and not awaiting_take(room, team.id, participant_id)
                and _baton_moves(team)
            )
            if holder and _store_state(team, state, igt_ms):
                target = next(
                    (
                        m
                        for m in team.members
                        if answered is not None
                        and m.id == answered.target_id
                        and m.status not in TERMINAL_PARTICIPANT_STATUSES
                    ),
                    None,
                )
                if target is not None:
                    assert handoff_id is not None
                    flip = await _flip(
                        session_maker, db, room, team, target, handoff_id=handoff_id, graph=graph
                    )
                else:
                    await db.commit()
            race_id, team_id = team.race_id, team.id
        if flip is not None:
            await _after_flip(session_maker, room, flip, graph)
        elif handoff_id is not None or not holder:
            await send_relay_updates(
                session_maker, race_id, team_id, graph_json=graph, to=(participant_id,)
            )


async def request_take(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """A teammate asks to take a free baton: ``relay_take`` with the last
    stored state and the team's IGT when every check passes, else
    ``relay_refused``. The nominal holder of a free baton may ask too."""
    async with room.relay_lock:
        flip: _Flip | None = None
        async with session_maker() as db:
            loaded = await _locked_team(db, graph_json, participant_id=participant_id)
            if loaded is None:
                return
            team, graph = loaded
            me = next(m for m in team.members if m.id == participant_id)
            holder_connected = team.holder_id is not None and team.holder_id in room.mods
            if (
                team.holder_id is not None
                and not holder_connected
                and not team.baton_free
                and team.holder_offline_since is None
                and _baton_moves(team)
            ):
                # Its socket is gone but its disconnect not recorded yet (or it
                # never connected): offline since now, the whole wait ahead.
                team.holder_offline_since = datetime.now(UTC)
                await db.commit()
            refusal: str | None
            if not _baton_moves(team) or _in_flight(room, team.id):
                refusal = RelayRefusal.BUSY
            elif not baton_is_free(team, holder_connected=holder_connected, now=datetime.now(UTC)):
                refusal = RelayRefusal.HOLDER_ONLINE
            else:
                refusal = receive_refusal(
                    me,
                    cap=_cap(team, graph),
                    connected=True,
                    ready=participant_id in room.relay_ready,
                    asking=True,
                )
            if refusal is None:
                flip = await _flip(
                    session_maker, db, room, team, me, handoff_id=uuid.uuid4().hex, graph=graph
                )
        if flip is None:
            await _refuse(room, participant_id, refusal or RelayRefusal.BUSY)
            return
        await _after_flip(session_maker, room, flip, graph)


async def confirm_taken(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    handoff_id: str,
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """The receiver acknowledges the pending take: the handoff is over, the
    team is told and the leaderboard broadcast. Late (the timer had freed the
    baton and nobody took it since), it clears ``baton_free``: the receiver
    plays on."""
    async with room.relay_lock:
        async with session_maker() as db:
            loaded = await _locked_team(db, graph_json, participant_id=participant_id)
            if loaded is None:
                return
            team, graph = loaded
            pending = room.relay_pending.get(team.id)
            if (
                pending is None
                or pending.phase != "take"
                or pending.handoff_id != handoff_id
                or pending.target_id != participant_id
            ):
                logger.info(
                    "Ignored relay_taken: participant=%s handoff=%s", participant_id, handoff_id
                )
                return
            _set_pending(room, team.id, None)
            if team.holder_id == participant_id and team.baton_free:
                team.baton_free = False
                await db.commit()
            race_id, team_id = team.race_id, team.id
        logger.info("Relay take acknowledged: team=%s handoff=%s", team_id, handoff_id)
        await send_relay_updates(session_maker, race_id, team_id, graph_json=graph)
        await _broadcast_leaderboard(session_maker, race_id, graph)


async def set_ready(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    ready: bool,
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """A member's ``relay_ready``: whether its mod waits at the Chapel with its
    lock raised (``RaceRoom.relay_ready``, read by ``members[].ready`` and by
    the handoff and take checks). The team is told when it changes."""
    async with room.relay_lock:
        if ready == (participant_id in room.relay_ready):
            return
        if ready:
            if participant_id not in room.mods:
                return
            room.relay_ready.add(participant_id)
        else:
            room.relay_ready.discard(participant_id)
        async with session_maker() as db:
            row = (
                await db.execute(
                    select(Participant.race_id, Participant.relay_team_id).where(
                        Participant.id == participant_id
                    )
                )
            ).one_or_none()
        if row is None or row.relay_team_id is None:
            return
        await send_relay_updates(
            session_maker, row.race_id, row.relay_team_id, graph_json=graph_json
        )


async def holder_connection_changed(
    session_maker: async_sessionmaker[AsyncSession],
    room: "RaceRoom",
    participant_id: uuid.UUID,
    *,
    connected: bool,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """A member's mod connected or disconnected.

    For the holder of a team still in the race, ``holder_offline_since`` is
    cleared, or set to now (the mods count the 60 s down from
    ``baton_free_in_s``) and their pending release dropped. The team's mods are
    told either way (``online``, ``holder_online``). The disconnect of a socket
    a newer one replaced changes nothing.
    """
    async with room.relay_lock:
        if connected != (participant_id in room.mods):
            return
        async with session_maker() as db:
            loaded = await _locked_team(db, graph_json, participant_id=participant_id)
            if loaded is None:
                return
            team, graph = loaded
            if (
                team.holder_id == participant_id
                and team.status not in TERMINAL_PARTICIPANT_STATUSES
            ):
                team.holder_offline_since = None if connected else datetime.now(UTC)
                await db.commit()
            race_id, team_id = team.race_id, team.id
        pending = room.relay_pending.get(team_id)
        if (
            not connected
            and pending is not None
            and pending.phase == "release"
            and pending.giver_id == participant_id
        ):
            _set_pending(room, team_id, None)
        await send_relay_updates(session_maker, race_id, team_id, graph_json=graph)


async def _broadcast_leaderboard(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    graph: dict[str, Any],
) -> None:
    # Local imports: these modules import this one.
    from speedfog_racing.websocket.race.manager import manager
    from speedfog_racing.websocket.race.mod import _load_race_with_participants

    async with session_maker() as db:
        race = await _load_race_with_participants(db, race_id)
    if race is not None:
        await manager.broadcast_leaderboard(
            race_id, leaderboard_entries(race, graph), graph_json=graph
        )
