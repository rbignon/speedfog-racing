"""Relay races: the seed capability and the block a relay seed carries.

A relay seed is a seed whose ``graph.json`` has a top-level ``relay`` object
(the generator writes it when its relay plugin is enabled).
"""

import logging
import math
import secrets
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    TERMINAL_PARTICIPANT_STATUSES,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    Seed,
)

if TYPE_CHECKING:
    from speedfog_racing.websocket.schemas import RelayLootEntry

logger = logging.getLogger(__name__)

RELAY_PLUGIN = "relay"

RELAY_TEAM_SIZE_MIN = 2
RELAY_TEAM_SIZE_MAX = 6
RELAY_TEAM_NAME_MAX = 40

# Seconds an offline holder keeps the baton before a teammate may take it.
RELAY_OFFLINE_WAIT_S = 60
# Seconds a holder has to answer a relay_release with its state.
RELAY_RELEASE_TIMEOUT_S = 15.0
# Seconds a new holder has to acknowledge a relay_take; then the baton is free.
RELAY_TAKE_TIMEOUT_S = 30.0

# The largest save token: the mod writes it as the seed's 24 token flags
# (``token_bits``), and 0, a save with none of them raised, is never drawn.
RELAY_TOKEN_MAX = 2**24 - 1


class RelayRefusal(StrEnum):
    """Why a relay request was refused: the ``code`` of ``relay_refused``."""

    NOT_HOLDER = "not_holder"
    TARGET_UNAVAILABLE = "target_unavailable"
    TARGET_AT_CAP = "target_at_cap"
    AT_CAP = "at_cap"
    HOLDER_ONLINE = "holder_online"
    NOT_READY = "not_ready"
    NOT_VALIDATED = "not_validated"
    BUSY = "busy"


# The message carried with each code (wire text, see docs/PROTOCOL.md).
RELAY_REFUSAL_MESSAGES: dict[RelayRefusal, str] = {
    RelayRefusal.NOT_HOLDER: "You do not hold the baton",
    RelayRefusal.TARGET_UNAVAILABLE: "This runner cannot take the baton now",
    RelayRefusal.TARGET_AT_CAP: "This teammate has reached their zone quota",
    RelayRefusal.AT_CAP: "You have reached your zone quota",
    RelayRefusal.HOLDER_ONLINE: "The baton cannot be taken yet",
    RelayRefusal.NOT_READY: "Wait at the Roundtable Hold first",
    RelayRefusal.NOT_VALIDATED: "No fresh save was validated for this runner",
    RelayRefusal.BUSY: "The baton cannot move right now",
}


def seed_has_relay(graph_json: Mapping[str, Any]) -> bool:
    """Whether a seed supports relay races: it carries the graph.json 4.16
    block, a ``relay`` object holding a ``loot`` object (possibly empty) and an
    integer ``roundtable_warp_flag``. An earlier block, or a seed exported
    without a build, is not a relay seed."""
    block = graph_json.get(RELAY_PLUGIN)
    if not isinstance(block, dict) or not isinstance(block.get("loot"), dict):
        return False
    warp = block.get("roundtable_warp_flag")
    return isinstance(warp, int) and not isinstance(warp, bool)


def relay_seed_clause() -> ColumnElement[bool]:
    """SQL twin of ``seed_has_relay``: reads ``Seed.relay``, which the pool scan
    sets when it adds the seed, so no query parses a graph."""
    clause: ColumnElement[bool] = Seed.relay.is_(True)
    return clause


def relay_flags(graph_json: Mapping[str, Any]) -> dict[str, int] | None:
    """The integer keys of the seed's relay block but ``warp_flag_count``, or
    None for a plain seed."""
    if not seed_has_relay(graph_json):
        return None
    block: Mapping[str, Any] = graph_json[RELAY_PLUGIN]
    return {
        k: v
        for k, v in block.items()
        if k != "warp_flag_count" and isinstance(v, int) and not isinstance(v, bool)
    }


def relay_cap(total_layers: int, active_members: int) -> int:
    """Zones one runner may play: ``ceil(total_layers / active_members) + 1``."""
    return math.ceil(total_layers / active_members) + 1


def is_active_member(p: Participant) -> bool:
    """Whether a member still shares the team's run (not abandoned, not disqualified)."""
    return p.status not in (ParticipantStatus.ABANDONED, ParticipantStatus.DISQUALIFIED)


def shares_cap(p: Participant) -> bool:
    """Whether a member counts in the team's cap: one who plays, PLAYING (their
    save passed the fresh-save gate, at their first report) or FINISHED. A
    member never connected (REGISTERED), or connected without a validated save
    yet (READY), cannot take the baton: a teammate playing alone is not held to
    a cap made for them, and the cap drops once they are validated."""
    return p.status in (ParticipantStatus.PLAYING, ParticipantStatus.FINISHED)


def team_cap(total_layers: int, members: Sequence[Participant]) -> int:
    """The team's cap on the members who share it (``shares_cap``); never
    divides by zero."""
    return relay_cap(total_layers, max(1, sum(1 for m in members if shares_cap(m))))


def draw_relay_token() -> int:
    """A member's save token, drawn when their save passes the fresh-save gate:
    1 to ``RELAY_TOKEN_MAX``, unpredictable (``secrets``), so a runner cannot
    write it into another save before their mod is told it."""
    return secrets.randbelow(RELAY_TOKEN_MAX) + 1


def holds_baton(team: RelayTeam, participant_id: UUID | None) -> bool:
    """Whether ``participant_id`` plays the team's run now: its holder while the
    baton is not free (exactly when ``RelayInfo.role`` reads ``holder``). Only
    this runner's progress messages are applied to the team."""
    return participant_id is not None and team.holder_id == participant_id and not team.baton_free


def counts_zone_on_exit(
    boss_flags: Mapping[int, str], graph_json: Mapping[str, Any], node_id: str
) -> bool:
    """Whether leaving ``node_id`` for a new layer counts a zone for the runner.

    A zone whose boss the server tracks (``boss_flags``, from
    ``extract_boss_flags``) counts for the runner who kills that boss, so
    leaving it counts nothing; the final boss's zone is never left. Any other
    zone counts for the runner who exits it.
    """
    if node_id in boss_flags.values():
        return False
    nodes = graph_json.get("nodes")
    node = nodes.get(node_id) if isinstance(nodes, dict) else None
    return not (isinstance(node, dict) and node.get("type") == "final_boss")


def copy_team_result(team: RelayTeam, members: Sequence[Participant]) -> None:
    """Copy a team's result (finished or out) onto its members still in.

    Status, IGT, finish time, deaths and layer, so the pages that read
    participants show the run; a disqualified team leaves its other members
    abandoned. A member who never played (no fresh save validated: never
    connected, or no report since the start) goes out with the team instead,
    as a member going out then: abandoned, the progress snapshot, no finish
    time. A member already out keeps their own row, and nobody's
    ``zone_history`` is touched (the run's history stays on the team).
    """
    status = (
        ParticipantStatus.ABANDONED
        if team.status == ParticipantStatus.DISQUALIFIED
        else team.status
    )
    for member in members:
        if not is_active_member(member):
            continue
        played = bool(member.relay_validated)
        member.status = status if played else ParticipantStatus.ABANDONED
        member.igt_ms = team.igt_ms
        member.finished_at = team.finished_at if played else None
        member.death_count = team.death_count
        member.current_layer = team.current_layer


def abandon_team(team: RelayTeam, members: Sequence[Participant]) -> None:
    """Put a team out (ABANDONED) and copy that result onto its members still in."""
    team.status = ParticipantStatus.ABANDONED
    copy_team_result(team, members)


def apply_member_out(
    team: RelayTeam,
    members: Sequence[Participant],
    participant: Participant,
    *,
    disqualified: bool = False,
    snapshot: bool = True,
) -> bool:
    """What a member going out does to their team; True when the team, still
    in the race until then, went out.

    ``participant`` (one of ``members``) is already ABANDONED or DISQUALIFIED.
    Their row takes a snapshot of the team's progress (IGT, deaths, layer;
    their own status kept, never a finish time or ``zone_history``), so it
    tells how far the team was when their race ended; ``snapshot`` False for
    a member who was out already before this change (disqualified after
    abandoning), whose row keeps the snapshot of then. While the team is in
    the race, a baton they held is free at once (no holder, ``baton_free``):
    no 60 s wait, and nobody gets it automatically. The team's IGT stamp
    restarts then, so the free baton gets the whole inactivity timeout before
    the team is out for it. The cap follows on its own (``team_cap`` counts
    the members who share it). ``disqualified`` puts the team out as DISQUALIFIED,
    finished or not (what a cheater obtained reached the team); otherwise the
    team is out (ABANDONED) once no member is left in. A team put out gets its
    result copied onto its members still in (``copy_team_result``: a
    disqualified team leaves them abandoned).
    """
    if snapshot:
        participant.igt_ms = team.igt_ms
        participant.death_count = team.death_count
        participant.current_layer = team.current_layer
    in_race = team.status not in TERMINAL_PARTICIPANT_STATUSES
    if in_race and team.holder_id == participant.id:
        team.holder_id = None
        team.holder_offline_since = None
        team.baton_free = True
        team.last_igt_change_at = datetime.now(UTC)
    if disqualified:
        if team.status != ParticipantStatus.DISQUALIFIED:
            team.status = ParticipantStatus.DISQUALIFIED
            copy_team_result(team, members)
        return in_race
    if not in_race or any(is_active_member(m) for m in members):
        return False
    abandon_team(team, members)
    return True


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


def relay_warp_flag(flags: Mapping[str, int], entry_flag_id: int | None) -> int:
    """The flag that warps a receiver to the entrance of the connection whose
    zone-tracking flag is ``entry_flag_id`` (``relay_flags``' bases); the Chapel
    warp flag before the team's first gate."""
    if entry_flag_id is None:
        return flags["chapel_warp_flag"]
    return flags["warp_flag_base"] + (entry_flag_id - flags["zone_flag_base"])


def team_defeat_flags(
    graph_json: Mapping[str, Any], zone_history: Sequence[Mapping[str, Any]] | None
) -> list[int]:
    """The defeat flag of every node the team's history marks killed
    (``boss_kill_igt_ms``), sorted, each once: what a receiver's game must
    hold dead, the current zone's boss included."""
    nodes = graph_json.get("nodes")
    if not isinstance(nodes, dict):
        return []
    flags: set[int] = set()
    for entry in zone_history or []:
        if "boss_kill_igt_ms" not in entry:
            continue
        node = nodes.get(entry.get("node_id"))
        flag = node.get("defeat_flag") if isinstance(node, dict) else None
        if isinstance(flag, int) and not isinstance(flag, bool) and flag > 0:
            flags.add(flag)
    return sorted(flags)


def loot_entry(graph_json: Mapping[str, Any], flag: int) -> "RelayLootEntry | None":
    """What the boss whose defeat flag is ``flag`` gives: the seed's relay
    ``loot`` entry for it (keyed by the flag as a decimal string), or None.
    It is only asked for a boss the team killed, so an entry missing, or one
    out of the wire bounds (a mod could not read it), is logged."""
    # Local import: websocket.schemas pulls in the services package, which
    # imports this module.
    from speedfog_racing.websocket.schemas import RelayLootEntry

    block = graph_json.get(RELAY_PLUGIN)
    loot = block.get("loot") if isinstance(block, Mapping) else None
    raw = loot.get(str(flag)) if isinstance(loot, Mapping) else None
    if raw is None:
        logger.warning("Relay loot entry missing: flag=%s", flag)
        return None
    try:
        return RelayLootEntry.model_validate(
            {**raw, "flag": flag} if isinstance(raw, Mapping) else raw
        )
    except ValidationError:
        logger.warning("Relay loot entry unusable: flag=%s", flag)
        return None


def team_loot(
    graph_json: Mapping[str, Any], zone_history: Sequence[Mapping[str, Any]] | None
) -> "list[RelayLootEntry]":
    """The loot entry of every boss the team's history marks killed, in the
    order of ``team_defeat_flags``; a boss without a usable entry gives none."""
    entries = (loot_entry(graph_json, flag) for flag in team_defeat_flags(graph_json, zone_history))
    return [entry for entry in entries if entry is not None]


def receive_refusal(
    member: Participant, *, cap: int, connected: bool, ready: bool, asking: bool
) -> str | None:
    """Why ``member`` cannot receive the team's baton now, as a ``relay_refused``
    code, or None. ``asking``: they ask for it (a take) rather than being named
    by the holder (a handoff), which changes the codes and their order.

    A member who is out is never available. A handoff target must be connected
    and ready at the Roundtable Hold, then validated; an asker must be validated, then
    ready. Nobody at or over the cap receives the baton, final zone included.
    """
    if member.status in TERMINAL_PARTICIPANT_STATUSES:
        return RelayRefusal.TARGET_UNAVAILABLE
    waiting_at_chapel = connected and ready
    if not asking and not waiting_at_chapel:
        return RelayRefusal.TARGET_UNAVAILABLE
    if not member.relay_validated:
        return RelayRefusal.NOT_VALIDATED
    if not waiting_at_chapel:
        return RelayRefusal.NOT_READY
    if member.relay_zones >= cap:
        return RelayRefusal.AT_CAP if asking else RelayRefusal.TARGET_AT_CAP
    return None


def baton_is_free(team: RelayTeam, *, holder_connected: bool, now: datetime) -> bool:
    """Whether a teammate may take the baton now (``baton_free_in_s`` is 0)."""
    return baton_free_in_s(team, holder_connected=holder_connected, now=now) == 0


def baton_free_in_s(team: RelayTeam, *, holder_connected: bool, now: datetime) -> int | None:
    """Seconds before the team's baton can be taken, as ``RelayInfo`` tells it.

    0 once it is free: ``baton_free`` is set, the team has no holder, or the
    holder has been offline for the whole wait. None while the holder is online
    and the baton not free. A holder absent with no offline stamp yet (its
    socket just gone, before its disconnect is recorded) is offline since now:
    the whole wait is still ahead. So is a holder stamped at the race start
    during the countdown (a stamp in the future): never more than the wait.
    """
    if team.baton_free or team.holder_id is None:
        return 0
    if holder_connected:
        return None
    since = team.holder_offline_since
    if since is None:
        return RELAY_OFFLINE_WAIT_S
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    left = RELAY_OFFLINE_WAIT_S - int((now - since).total_seconds())
    return min(RELAY_OFFLINE_WAIT_S, max(0, left))


def _members_by_team(race: Race) -> list[tuple[RelayTeam, list[Participant]]]:
    """The teams in ``created_at`` order, each with its members (a team can be empty)."""
    by_team: dict[UUID, list[Participant]] = defaultdict(list)
    for p in sorted(race.participants, key=lambda p: p.created_at):
        if p.relay_team_id is not None:
            by_team[p.relay_team_id].append(p)
    return [
        (t, by_team.get(t.id, [])) for t in sorted(race.relay_teams, key=lambda t: t.created_at)
    ]


def first_runner(team: RelayTeam, members: Sequence[Participant]) -> Participant | None:
    """The member ``team.first_runner_id`` names, or None (an empty team)."""
    return next((m for m in members if m.id == team.first_runner_id), None)


def relay_start_error(race: Race) -> str | None:
    """Why a relay race cannot start yet, or None.

    A team with no member is ignored. At least two other teams are needed, and
    each needs its first runner ready: the runner its run starts with. Its other
    members need not be (they may still join while the race runs).
    """
    teams = [(t, members) for t, members in _members_by_team(race) if members]
    if len(teams) < 2:
        return "At least 2 teams are required to start a relay race"
    for team, members in teams:
        first = first_runner(team, members)
        if first is None:
            return f"{team.name} has no first runner"
        if first.status != ParticipantStatus.READY:
            return f"{team.name}'s first runner is not ready"
    return None


def prepare_relay_start(race: Race, *, connected: Collection[UUID], now: datetime) -> None:
    """Fix the teams at the start of a validated relay race (``relay_start_error``).

    Each team with a member becomes READY, its baton held by its first runner.
    The members who are not ready keep their status: they may still connect
    and join their team's run, and the no-show rule takes them out 30 minutes
    into the race otherwise. A holder whose mod is not among ``connected`` is
    offline from ``now``, the race's ``started_at`` (the countdown's end): the
    offline wait starts with the race.
    """
    for team, members in _members_by_team(race):
        first = first_runner(team, members)
        if first is None:
            continue
        team.holder_id = first.id
        team.holder_offline_since = None if team.holder_id in connected else now
        team.status = ParticipantStatus.READY


def reset_relay_race(race: Race) -> None:
    """Back to fresh teams after a reset: every team reset, member counters
    zeroed, and each member's save validation cleared with its token and
    binding."""
    for team in race.relay_teams:
        reset_relay_team(team)
    for p in race.participants:
        p.relay_zones = 0
        p.relay_validated = False
        p.relay_token = None
        p.relay_bound = False


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
        """The team's, except in setup (REGISTERED), where the row reads READY
        once the first runner is: the team can start. Shown only: the team's
        own status, which ``RelayInfo`` carries, stays REGISTERED until the
        start."""
        if self.team.status == ParticipantStatus.REGISTERED:
            first = first_runner(self.team, self.members)
            if first is not None and first.status == ParticipantStatus.READY:
                return ParticipantStatus.READY
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


def relay_team_row(
    team: RelayTeam, members: Sequence[Participant], graph_json: Mapping[str, Any] | None
) -> RelayTeamRow:
    """``team``'s row, its cap computed on ``members`` and the seed's layers."""
    total_layers = int((graph_json or {}).get("total_layers") or 0)
    return RelayTeamRow(team, tuple(members), team_cap(total_layers, members))


def race_teams_for_update(race_id: UUID) -> Select[tuple[RelayTeam]]:
    """Every team of a race, row-locked (``FOR UPDATE``, a no-op on SQLite) in
    ascending id order and read again (``populate_existing``)."""
    return (
        select(RelayTeam)
        .where(RelayTeam.race_id == race_id)
        .order_by(RelayTeam.id)
        .with_for_update(of=RelayTeam)
        .execution_options(populate_existing=True)
    )


async def lock_race_teams(db: AsyncSession, race_id: UUID) -> Sequence[RelayTeam]:
    """Lock a race's teams before a transaction writes them and their members
    together (the start, a reset, a reroll, the forced end). Every relay write
    to both tables locks its team rows first, so two of them never wait on
    each other in opposite orders. Call it before any member row is changed:
    the query flushes what the session holds."""
    return (await db.execute(race_teams_for_update(race_id))).scalars().all()


async def load_relay_row(
    db: AsyncSession, team_id: UUID, graph_json: Mapping[str, Any] | None
) -> RelayTeamRow | None:
    """One team's row, from queries of its own: the team (``zone_history``
    included) and its members with their users. For callers whose entity was
    loaded without ``race.participants``."""
    team = await db.get(RelayTeam, team_id, populate_existing=True)
    if team is None:
        return None
    result = await db.execute(
        select(Participant)
        .where(Participant.relay_team_id == team_id)
        .options(selectinload(Participant.user))
        .order_by(Participant.created_at)
    )
    return relay_team_row(team, list(result.scalars().all()), graph_json)
