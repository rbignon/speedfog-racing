"""Relay races: the seed capability and the block a relay seed carries.

A relay seed is a seed whose ``graph.json`` has a top-level ``relay`` object
(the generator writes it when its relay plugin is enabled).
"""

import math
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus, RelayTeam, Seed

RELAY_PLUGIN = "relay"

RELAY_TEAM_SIZE_MIN = 2
RELAY_TEAM_SIZE_MAX = 6
RELAY_TEAM_NAME_MAX = 40


def seed_has_relay(graph_json: Mapping[str, Any]) -> bool:
    """Whether a seed supports relay races: ``relay`` is a non-empty object."""
    block = graph_json.get(RELAY_PLUGIN)
    return isinstance(block, dict) and bool(block)


def relay_seed_clause() -> ColumnElement[bool]:
    """SQL twin of ``seed_has_relay``: reads ``Seed.relay``, which the pool scan
    sets when it adds the seed, so no query parses a graph."""
    clause: ColumnElement[bool] = Seed.relay.is_(True)
    return clause


def relay_flags(graph_json: Mapping[str, Any]) -> dict[str, int] | None:
    """The seed's relay block minus ``warp_flag_count``, or None for a plain seed."""
    if not seed_has_relay(graph_json):
        return None
    block: Mapping[str, Any] = graph_json[RELAY_PLUGIN]
    return {k: v for k, v in block.items() if k != "warp_flag_count"}


def relay_cap(total_layers: int, active_members: int) -> int:
    """Zones one runner may play: ``ceil(total_layers / active_members) + 1``."""
    return math.ceil(total_layers / active_members) + 1


def is_active_member(p: Participant) -> bool:
    """Whether a member still shares the team's run (not abandoned, not disqualified)."""
    return p.status not in (ParticipantStatus.ABANDONED, ParticipantStatus.DISQUALIFIED)


def team_cap(total_layers: int, members: Sequence[Participant]) -> int:
    """The team's cap on the members still in; never divides by zero."""
    return relay_cap(total_layers, max(1, sum(1 for m in members if is_active_member(m))))


def default_team_name(existing: Collection[str]) -> str:
    """``Team {n}``, the lowest n at or above the team count plus one that is not taken."""
    n = len(existing) + 1
    while f"Team {n}" in existing:
        n += 1
    return f"Team {n}"


def reset_relay_team(team: RelayTeam) -> None:
    """Back to a fresh team: progress, baton and state cleared, status REGISTERED.

    Identity (name, color, placeholder) and ``first_runner_id`` are kept.
    """
    team.status = ParticipantStatus.REGISTERED
    team.current_zone = None
    team.current_layer = 0
    team.igt_ms = 0
    team.death_count = 0
    team.finished_at = None
    team.last_igt_change_at = None
    team.zone_history = None
    team.layer_entry_igts = {}
    team.entry_flag_id = None
    team.character_state = None
    team.character_state_igt_ms = None
    team.holder_id = None
    team.holder_offline_since = None
    team.baton_free = False


def _members_by_team(race: Race) -> list[tuple[RelayTeam, list[Participant]]]:
    """The teams in ``created_at`` order, each with its members (a team can be empty)."""
    by_team: dict[UUID, list[Participant]] = defaultdict(list)
    for p in sorted(race.participants, key=lambda p: p.created_at):
        if p.relay_team_id is not None:
            by_team[p.relay_team_id].append(p)
    return [
        (t, by_team.get(t.id, [])) for t in sorted(race.relay_teams, key=lambda t: t.created_at)
    ]


def relay_start_error(race: Race) -> str | None:
    """Why a relay race cannot start yet, or None.

    A team with no member is ignored. At least two other teams are needed, each
    with at least two ready members; a member who is not ready is left out at
    the start (``prepare_relay_start``) and does not count here.
    """
    teams = [(t, members) for t, members in _members_by_team(race) if members]
    if len(teams) < 2:
        return "At least 2 teams are required to start a relay race"
    for team, members in teams:
        if sum(1 for m in members if m.status == ParticipantStatus.READY) < RELAY_TEAM_SIZE_MIN:
            return f"{team.name} needs at least {RELAY_TEAM_SIZE_MIN} ready runners"
    return None


def prepare_relay_start(race: Race) -> None:
    """Fix the teams at the start of a validated relay race.

    A member who is not ready is set ABANDONED (still attached to the team, so
    ``team_cap`` ignores them). Each team with a member becomes READY, its baton
    held by its first runner when ready, else by its first ready member.
    """
    for team, members in _members_by_team(race):
        if not members:
            continue
        ready = [m for m in members if m.status == ParticipantStatus.READY]
        for m in members:
            if m.status not in (
                ParticipantStatus.READY,
                ParticipantStatus.ABANDONED,
                ParticipantStatus.DISQUALIFIED,
            ):
                m.status = ParticipantStatus.ABANDONED
        first = next((m for m in ready if m.id == team.first_runner_id), None)
        team.holder_id = (first or ready[0]).id
        team.status = ParticipantStatus.READY


def reset_relay_race(race: Race) -> None:
    """Back to fresh teams after a reset: every team reset, member counters zeroed."""
    for team in race.relay_teams:
        reset_relay_team(team)
    for p in race.participants:
        p.relay_zones = 0
        p.relay_validated = False


@dataclass(frozen=True)
class RelayTeamRow:
    """A team seen as a leaderboard row: the participant fields the leaderboard
    reads come from the team, so a relay race ranks like a solo one."""

    team: RelayTeam
    members: tuple[Participant, ...]
    cap: int

    @property
    def id(self) -> UUID:
        return self.team.id

    @property
    def status(self) -> ParticipantStatus:
        return self.team.status

    @property
    def current_zone(self) -> str | None:
        return self.team.current_zone

    @property
    def current_layer(self) -> int:
        return self.team.current_layer

    @property
    def igt_ms(self) -> int:
        return self.team.igt_ms

    @property
    def death_count(self) -> int:
        return self.team.death_count

    @property
    def color_index(self) -> int:
        return self.team.color_index

    @property
    def zone_history(self) -> list[dict[str, Any]] | None:
        return self.team.zone_history

    @property
    def layer_entry_igts(self) -> dict[str, int]:
        return self.team.layer_entry_igts

    @property
    def finished_at(self) -> datetime | None:
        return self.team.finished_at

    @property
    def holder(self) -> Participant | None:
        return next((m for m in self.members if m.id == self.team.holder_id), None)


def relay_rows(
    teams: Sequence[RelayTeam],
    participants: Sequence[Participant],
    *,
    total_layers: int,
    setup: bool,
) -> list[RelayTeamRow]:
    """One row per team, in ``created_at`` order. A team without member is kept
    only in setup (a placeholder waiting for runners), hidden once started."""
    by_team: dict[UUID, list[Participant]] = defaultdict(list)
    for p in participants:
        if p.relay_team_id is not None:
            by_team[p.relay_team_id].append(p)
    rows = []
    for team in sorted(teams, key=lambda t: t.created_at):
        members = by_team.get(team.id, [])
        if not members and not setup:
            continue
        rows.append(RelayTeamRow(team, tuple(members), team_cap(total_layers, members)))
    return rows


def leaderboard_entries(
    race: Race, graph_json: Mapping[str, Any] | None
) -> Sequence[Participant] | list[RelayTeamRow]:
    """What the leaderboard ranks: the participants of a solo race, the team rows
    of a relay race."""
    if not race.is_relay:
        return race.participants
    total_layers = int((graph_json or {}).get("total_layers") or 0)
    return relay_rows(
        race.relay_teams,
        race.participants,
        total_layers=total_layers,
        setup=race.status == RaceStatus.SETUP,
    )
