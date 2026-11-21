"""Relay races on the mod socket: what a mod is told about its team and its role."""

import logging
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
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
    baton_free_in_s,
    copy_team_result,
    holds_baton,
    leaderboard_entries,
    load_relay_row,
    relay_flags,
    team_cap,
)
from speedfog_racing.websocket.schemas import (
    RelayFlags,
    RelayInfo,
    RelayMember,
    RelayUpdateMessage,
    persist_system_chat,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingHandoff:
    """A handoff awaiting its answer or its acknowledgement, kept per team on
    ``RaceRoom.relay_pending``. The handlers of the baton operations give it
    its fields."""


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
) -> None:
    """Send each connected mod of the team a ``relay_update`` with its own role.

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
        if member.id not in connected:
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
