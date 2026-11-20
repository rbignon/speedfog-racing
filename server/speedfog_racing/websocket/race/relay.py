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

from speedfog_racing.models import Participant, Race, RelayTeam
from speedfog_racing.services.layer_service import get_start_node
from speedfog_racing.services.relay import (
    baton_free_in_s,
    load_relay_row,
    relay_flags,
    team_cap,
)
from speedfog_racing.websocket.schemas import (
    RelayFlags,
    RelayInfo,
    RelayMember,
    RelayUpdateMessage,
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
    is_holder = me.id == team.holder_id and not team.baton_free
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
    session_maker: async_sessionmaker[AsyncSession], race_id: uuid.UUID, team_id: uuid.UUID
) -> None:
    """Send each connected mod of the team a ``relay_update`` with its own role."""
    from speedfog_racing.websocket.race.manager import manager

    room = manager.get_room(race_id)
    if room is None:
        return
    async with session_maker() as db:
        graph = await _race_graph(db, race_id)
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


async def _race_graph(db: AsyncSession, race_id: uuid.UUID) -> dict[str, Any] | None:
    result = await db.execute(
        select(Race).where(Race.id == race_id).options(selectinload(Race.seed))
    )
    race = result.scalar_one_or_none()
    return race.seed.graph_json if race and race.seed else None
