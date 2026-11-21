"""Relay progress: only the baton holder is listened to, and what it does goes to its team."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from speedfog_racing.models import Participant, ParticipantStatus, RaceStatus, RelayTeam
from speedfog_racing.services.relay import copy_team_result, counts_zone_on_exit, relay_cap
from speedfog_racing.websocket.handler import extract_boss_flags
from speedfog_racing.websocket.race.relay_mod import RelayModHandler

from . import test_integration as _integration
from .relay_fixtures import (
    BOSS_FLAG,
    BOSS_NODE,
    FINAL_NODE,
    FINISH_FLAG,
    FOG_FLAG,
    PLAIN_NODE,
    PROGRESS_TOTAL_LAYERS,
    SECOND_FOG_FLAG,
    START_GRACE,
    START_NODE,
    THIRD_FOG_FLAG,
    RelayModClient,
    barrier,
    load_member,
    load_members,
    load_race,
    load_team,
    patch_member,
    patch_team,
    progress_graph,
    setup_relay_race,
    start_relay,
)

integration_db = _integration.integration_db
integration_client = _integration.integration_client

PLAYING = ParticipantStatus.PLAYING
FINISHED = ParticipantStatus.FINISHED
CAP = relay_cap(PROGRESS_TOTAL_LAYERS, 2)
EVENT_MAP = progress_graph()["event_map"]


@pytest.fixture
def relay_race(integration_db, integration_client):
    return setup_relay_race(integration_db)


@pytest.fixture
def mods(integration_client, relay_race):
    started = start_relay(integration_client, relay_race)
    yield started
    for mod in started.values():
        mod.close()


def _pid(relay_race, team: int, member: int) -> str:
    return relay_race["teams"][team]["members"][member]["participant_id"]


def _zones(update: dict[str, Any], participant_id: str) -> int:
    return next(
        m["zones"] for m in update["relay"]["members"] if m["participant_id"] == participant_id
    )


def _gate(mod: RelayModClient, flag: int, igt_ms: int, message_id: int) -> None:
    """Take a fog gate; the zone_update is the handler's last word on it."""
    mod.send_event_flag(flag, igt_ms=igt_ms, message_id=message_id)
    mod.receive_until("zone_update", lambda m: m["node_id"] == EVENT_MAP[str(flag)])


def test_a_waiting_runner_progress_is_acked_and_recorded_nowhere(relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    waiting = mods[_pid(relay_race, 0, 1)]
    # The holder stands in the boss arena: a kill reported there would count.
    _gate(mods[holder_id], FOG_FLAG, 20_000, 1)

    waiting.send_event_flag(SECOND_FOG_FLAG, igt_ms=30_000, message_id=7)
    assert waiting.receive_until("event_flag_ack")["message_id"] == 7
    waiting.send_event_flag(BOSS_FLAG, igt_ms=31_000, message_id=8)
    assert waiting.receive_until("event_flag_ack")["message_id"] == 8
    waiting.send_zone_query(START_GRACE, igt_ms=32_000, message_id=9)
    assert waiting.receive_until("zone_query_ack")["message_id"] == 9

    team = load_team(relay_race)
    history = team.zone_history or []
    assert [e["node_id"] for e in history] == [START_NODE, BOSS_NODE]
    assert not [e for e in history if "boss_kill_igt_ms" in e]
    assert (team.current_zone, team.current_layer, team.entry_flag_id, team.igt_ms) == (
        BOSS_NODE,
        1,
        FOG_FLAG,
        20_000,
    )
    me = load_member(relay_race, waiting.participant_id)
    assert (me.zone_history, me.relay_zones) == (None, 0)
    assert load_member(relay_race, holder_id).relay_zones == 1  # leaving the start only


def test_a_waiting_runner_report_broadcasts_no_row(relay_race, mods):
    holder = mods[_pid(relay_race, 0, 0)]
    waiting = mods[_pid(relay_race, 0, 1)]
    for igt_ms in (2_000, 3_000):
        waiting.send_status_update(igt_ms=igt_ms, death_count=0, weapons=[33200000, 2000025])
    barrier(waiting)

    holder.send_status_update(igt_ms=2_000, death_count=0)

    # The first row update anyone gets is the holder's own report.
    update = holder.receive_until("player_update")
    assert update["player"]["igt_ms"] == 2_000
    assert update["player"].get("weapons") is None


def test_every_member_passes_the_fresh_save_gate(relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    waiting = mods[_pid(relay_race, 0, 1)]
    # The holder passed the team's own gate with its first report.
    holder = load_member(relay_race, holder_id)
    assert (holder.relay_validated, holder.status) == (True, PLAYING)

    waiting.send_status_update(igt_ms=61_000, death_count=0)
    assert waiting.receive_until("error")["code"] == "fresh_save_required"
    assert load_member(relay_race, waiting.participant_id).relay_validated is False

    waiting.send_status_update(igt_ms=4_000, death_count=0)
    update = waiting.receive_until("relay_update")
    me = next(
        m for m in update["relay"]["members"] if m["participant_id"] == waiting.participant_id
    )
    assert (me["validated"], me["status"]) == (True, "playing")
    row = load_member(relay_race, waiting.participant_id)
    assert (row.relay_validated, row.status) == (True, PLAYING)

    # Validated, a waiting runner's IGT is never judged again.
    waiting.send_status_update(igt_ms=900_000, death_count=0)
    barrier(waiting)
    assert not [m for m in waiting.skipped if m["type"] == "error"]


def test_wrong_save_guard_runs_on_the_team_igt(relay_race, mods):
    holder = mods[_pid(relay_race, 0, 0)]
    patch_team(relay_race, igt_ms=40_000, last_igt_change_at=datetime.now(UTC))

    holder.send_status_update(igt_ms=40_000 + 61_000 + 5_000, death_count=0)
    assert holder.receive_until("error")["code"] == "wrong_save"
    holder.send_event_flag(FOG_FLAG, igt_ms=200_000, message_id=5)
    assert holder.receive_until("event_flag_ack")["message_id"] == 5

    team = load_team(relay_race)
    assert (team.igt_ms, team.current_layer, len(team.zone_history or [])) == (40_000, 0, 1)


def test_team_deaths_continue_across_a_change_of_holder(relay_race, mods):
    first, other = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    # The team has 5 deaths, all on the first holder's save.
    patch_team(relay_race, death_count=5, holder_id=UUID(other))
    patch_member(relay_race, first, death_count=5)

    mods[other].send_status_update(igt_ms=50_000, death_count=0)
    mods[other].receive_until("player_update", lambda m: m["player"]["igt_ms"] == 50_000)
    assert load_team(relay_race).death_count == 5

    mods[other].send_status_update(igt_ms=51_000, death_count=1)
    mods[other].receive_until("player_update", lambda m: m["player"]["death_count"] == 6)
    assert load_team(relay_race).death_count == 6
    # Each member keeps the raw counter of its own save.
    assert load_member(relay_race, other).death_count == 1
    assert load_member(relay_race, first).death_count == 5


def test_deaths_made_while_waiting_never_join_the_team_count(relay_race, mods):
    other = _pid(relay_race, 0, 1)
    waiting = mods[other]
    # Two deaths on the waiting runner's own save (a fall at the Chapel, a
    # giver dying before its return there).
    waiting.send_status_update(igt_ms=2_000, death_count=2)
    barrier(waiting)
    assert load_member(relay_race, other).death_count == 2
    assert load_team(relay_race).death_count == 0

    patch_team(relay_race, holder_id=UUID(other))
    waiting.send_status_update(igt_ms=3_000, death_count=2)
    waiting.receive_until("player_update", lambda m: m["player"]["igt_ms"] == 3_000)
    assert load_team(relay_race).death_count == 0

    waiting.send_status_update(igt_ms=4_000, death_count=3)
    waiting.receive_until("player_update", lambda m: m["player"]["death_count"] == 1)
    assert load_team(relay_race).death_count == 1


def test_a_member_out_keeps_the_team_deaths_on_its_row(relay_race, mods):
    other = _pid(relay_race, 0, 1)
    # Out with the team's count at that moment; its mod keeps reporting.
    patch_member(relay_race, other, status=ParticipantStatus.ABANDONED, death_count=7)

    mods[other].send_status_update(igt_ms=2_000, death_count=1)
    barrier(mods[other])

    assert load_member(relay_race, other).death_count == 7


def test_a_boss_kill_counts_for_the_holder_once(relay_race, mods):
    holder_id, other_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder = mods[holder_id]
    _gate(holder, FOG_FLAG, 20_000, 1)
    assert load_member(relay_race, holder_id).relay_zones == 1  # leaving the start

    holder.send_event_flag(BOSS_FLAG, igt_ms=40_000, message_id=3)
    holder.send_event_flag(BOSS_FLAG, igt_ms=45_000, message_id=4)  # re-report
    holder.receive_until("event_flag_ack", lambda m: m["message_id"] == 4)
    assert load_member(relay_race, holder_id).relay_zones == 2

    # A handoff sets the team's defeat flags on the receiver's game, which
    # re-reports them after a restart: still the same kill.
    patch_team(relay_race, holder_id=UUID(other_id))
    mods[other_id].send_event_flag(BOSS_FLAG, igt_ms=50_000, message_id=5)
    mods[other_id].receive_until("event_flag_ack", lambda m: m["message_id"] == 5)
    barrier(mods[other_id])
    assert load_member(relay_race, other_id).relay_zones == 0
    assert load_member(relay_race, holder_id).relay_zones == 2
    history = load_team(relay_race).zone_history or []
    assert [e.get("boss_kill_igt_ms") for e in history] == [None, 40_000]


def test_a_boss_kill_count_commits_with_its_stamp(monkeypatch, relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    holder = mods[holder_id]
    _gate(holder, FOG_FLAG, 20_000, 1)

    async def crash(self, entity, node_id, igt_ms):
        raise RuntimeError("lost after the stamp")

    # Whatever fails after the kill's commit, the count went with it: a
    # replay of the flag is a duplicate and would never count it again.
    monkeypatch.setattr(RelayModHandler, "_on_boss_killed", crash)
    holder.send_event_flag(BOSS_FLAG, igt_ms=40_000, message_id=2)
    holder.receive_until("event_flag_ack", lambda m: m["message_id"] == 2)
    # The crash ends the holder's socket: its teammate hears of it last.
    teammate = mods[_pid(relay_race, 0, 1)]
    teammate.receive_until(
        "relay_update",
        lambda m: m["relay"]["holder_id"] == holder_id and not m["relay"]["holder_online"],
    )

    assert load_member(relay_race, holder_id).relay_zones == 2
    assert (load_team(relay_race).zone_history or [])[-1]["boss_kill_igt_ms"] == 40_000


def test_exit_counts_only_for_a_zone_without_boss(relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    holder = mods[holder_id]

    _gate(holder, FOG_FLAG, 20_000, 1)  # the start has no boss: +1
    holder.send_event_flag(BOSS_FLAG, igt_ms=40_000, message_id=2)  # the kill: +1
    holder.receive_until("relay_update", lambda m: _zones(m, holder_id) == 2)
    _gate(holder, SECOND_FOG_FLAG, 60_000, 3)  # leaving the arena: +0
    assert load_member(relay_race, holder_id).relay_zones == 2
    assert load_team(relay_race).entry_flag_id == SECOND_FOG_FLAG
    _gate(holder, THIRD_FOG_FLAG, 80_000, 4)  # leaving a zone without boss: +1

    assert load_member(relay_race, holder_id).relay_zones == 3
    team = load_team(relay_race)
    assert team.entry_flag_id == THIRD_FOG_FLAG
    assert [e["node_id"] for e in team.zone_history or []] == [
        START_NODE,
        BOSS_NODE,
        PLAIN_NODE,
        FINAL_NODE,
    ]
    assert [e.get("runner_id") for e in team.zone_history or []] == [holder_id] * 4


def test_reaching_the_cap_locks_the_holder_gates(relay_race, mods):
    holder_id, other_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder = mods[holder_id]
    _gate(holder, FOG_FLAG, 20_000, 1)
    patch_member(relay_race, holder_id, relay_zones=CAP - 1)

    holder.send_event_flag(BOSS_FLAG, igt_ms=40_000, message_id=2)

    locked = holder.receive_until("relay_update")
    assert (locked["relay"]["gates_locked"], _zones(locked, holder_id)) == (True, CAP)
    teammate = mods[other_id].receive_until("relay_update", lambda m: _zones(m, holder_id) == CAP)
    assert teammate["relay"]["gates_locked"] is False
    # What a capped holder does is still recorded: the game allowed it.
    _gate(holder, SECOND_FOG_FLAG, 60_000, 3)
    assert load_team(relay_race).current_layer == 2


def test_the_final_boss_is_accepted_at_the_cap_and_finishes_the_team(relay_race, mods):
    holder_id, other_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder = mods[holder_id]
    for message_id, flag in enumerate((FOG_FLAG, SECOND_FOG_FLAG, THIRD_FOG_FLAG), start=1):
        _gate(holder, flag, 20_000 * message_id, message_id)
    patch_member(relay_race, holder_id, relay_zones=CAP)
    patch_team(relay_race, death_count=4, last_igt_change_at=datetime.now(UTC) - timedelta(hours=1))

    holder.send_event_flag(FINISH_FLAG, igt_ms=600_000, message_id=9)
    assert holder.receive_until("event_flag_ack")["message_id"] == 9
    holder.receive_until("relay_update", lambda m: m["relay"]["team_status"] == "finished")
    # The waiting runner learns it too: its race is over, it lowers its lock.
    mods[other_id].receive_until("relay_update", lambda m: m["relay"]["team_status"] == "finished")
    barrier(holder)  # the finish's last steps did not drop the connection

    team = load_team(relay_race)
    assert (team.status, team.igt_ms, team.current_layer) == (
        FINISHED,
        600_000,
        PROGRESS_TOTAL_LAYERS,
    )
    assert (team.zone_history or [])[-1]["boss_kill_igt_ms"] == 600_000
    assert load_member(relay_race, holder_id).relay_zones == CAP + 1
    members = load_members(relay_race)
    assert {m.status for m in members} == {FINISHED}
    assert all(
        (m.igt_ms, m.death_count, m.current_layer, m.finished_at)
        == (600_000, 4, PROGRESS_TOTAL_LAYERS, team.finished_at)
        for m in members
    )
    assert all(m.zone_history is None for m in members)
    assert load_race(relay_race).status == RaceStatus.RUNNING  # the other team still runs


def test_the_race_ends_when_every_team_has_finished(relay_race, mods):
    for index in (0, 1):
        holder = mods[_pid(relay_race, index, 0)]
        holder.send_event_flag(FINISH_FLAG, igt_ms=30_000, message_id=9)
        holder.receive_until("relay_update", lambda m: m["relay"]["team_status"] == "finished")
        barrier(holder)  # the finish's last steps did not drop the connection

    assert load_race(relay_race).status == RaceStatus.FINISHED


def test_backtrack_keeps_the_handoff_zone(relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    holder = mods[holder_id]
    _gate(holder, FOG_FLAG, 20_000, 1)

    holder.send_zone_query(START_GRACE, igt_ms=25_000, message_id=5)
    assert holder.receive_until("zone_update", lambda m: m.get("message_id") == 5)["node_id"] == (
        START_NODE
    )

    team = load_team(relay_race)
    assert (team.current_zone, team.entry_flag_id) == (START_NODE, FOG_FLAG)
    last = (team.zone_history or [])[-1]
    assert (last["type"], last["runner_id"]) == ("backtrack", holder_id)


def test_a_reconnecting_holder_resumes_the_team_zone(integration_client, relay_race, mods):
    race_id = relay_race["race_id"]
    _gate(mods[_pid(relay_race, 0, 0)], FOG_FLAG, 20_000, 1)

    resumed: list[list[str]] = []
    for member in relay_race["teams"][0]["members"]:
        pid = member["participant_id"]
        mods[pid].close()
        mods[pid] = RelayModClient.connect(integration_client, race_id, member["mod_token"], pid)
        assert mods[pid].auth(drain=False, protocol_version="1.19")["type"] == "auth_ok"
        # A zone to resume comes between auth_ok and the connect broadcast.
        mods[pid].receive_until("leaderboard_update")
        resumed.append([m["node_id"] for m in mods[pid].skipped if m["type"] == "zone_update"])
        # The team hears of the arrival last.
        mods[pid].receive_until("relay_update", lambda m: m["relay"]["holder_online"])

    assert resumed == [[BOSS_NODE], []]  # the holder's team zone; nothing for a waiting runner


def test_the_legacy_finished_message_is_ignored(relay_race, mods):
    holder_id = _pid(relay_race, 0, 0)
    holder = mods[holder_id]

    holder.send({"type": "finished", "igt_ms": 30_000})
    barrier(holder)

    assert load_team(relay_race).status == PLAYING
    assert load_member(relay_race, holder_id).status == PLAYING


def test_debug_flags_land_on_the_holder_row(relay_race, mods):
    holder_id, other_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    mods[other_id].send_status_update(igt_ms=2_000, death_count=0, debug_flags=["one_shot"])
    barrier(mods[other_id])

    mods[holder_id].send_status_update(
        igt_ms=2_000, death_count=0, debug_flags=["infinite_stamina"]
    )
    mods[holder_id].receive_until("player_update", lambda m: m["player"]["igt_ms"] == 2_000)

    assert set(load_member(relay_race, holder_id).debug_flags or {}) == {"infinite_stamina"}
    assert load_member(relay_race, other_id).debug_flags is None


# --- Pure rules ---


@pytest.mark.parametrize(
    "node_id,counts",
    [(START_NODE, True), (BOSS_NODE, False), (PLAIN_NODE, True), (FINAL_NODE, False)],
)
def test_a_zone_counts_on_exit_only_without_a_tracked_boss(node_id, counts):
    graph = progress_graph()
    assert counts_zone_on_exit(extract_boss_flags(graph), graph, node_id) is counts


def test_a_boss_the_server_cannot_track_counts_on_exit():
    # Two arenas sharing a defeat flag: no kill can name its zone, so leaving counts.
    graph = progress_graph()
    graph["nodes"][PLAIN_NODE]["defeat_flag"] = BOSS_FLAG
    assert counts_zone_on_exit(extract_boss_flags(graph), graph, BOSS_NODE) is True


def _member(status: ParticipantStatus) -> Participant:
    return Participant(
        id=uuid4(),
        status=status,
        igt_ms=0,
        death_count=1,
        current_layer=0,
        zone_history=[{"node_id": "own"}],
    )


def test_copy_team_result_writes_the_members_still_in():
    finished_at = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    team = RelayTeam(
        status=FINISHED,
        igt_ms=600_000,
        finished_at=finished_at,
        death_count=9,
        current_layer=12,
        zone_history=[{"node_id": "team"}],
    )
    playing, ready, out = (
        _member(PLAYING),
        _member(ParticipantStatus.READY),
        _member(ParticipantStatus.ABANDONED),
    )

    copy_team_result(team, [playing, ready, out])

    for m in (playing, ready):
        assert (m.status, m.igt_ms, m.finished_at, m.death_count, m.current_layer) == (
            FINISHED,
            600_000,
            finished_at,
            9,
            12,
        )
        assert m.zone_history == [{"node_id": "own"}]
    assert (out.status, out.igt_ms, out.death_count) == (ParticipantStatus.ABANDONED, 0, 1)


def test_a_disqualified_team_leaves_its_other_members_abandoned():
    team = RelayTeam(
        status=ParticipantStatus.DISQUALIFIED,
        igt_ms=100_000,
        finished_at=None,
        death_count=2,
        current_layer=5,
    )
    cheater, teammate = _member(ParticipantStatus.DISQUALIFIED), _member(PLAYING)

    copy_team_result(team, [cheater, teammate])

    assert (cheater.status, teammate.status) == (
        ParticipantStatus.DISQUALIFIED,
        ParticipantStatus.ABANDONED,
    )
    assert teammate.igt_ms == 100_000
