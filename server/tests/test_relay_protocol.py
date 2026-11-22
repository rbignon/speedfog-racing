"""Protocol 1.19 on the mod socket: the relay auth gate and what a mod is told about its team."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    User,
)
from speedfog_racing.services.relay import RelayTeamRow, baton_free_in_s
from speedfog_racing.websocket.race.manager import RaceRoom, relay_team_to_info
from speedfog_racing.websocket.race.relay import build_relay_info
from speedfog_racing.websocket.schemas import RELAY_OLD_MOD_MESSAGE

from . import test_integration as _integration
from .relay_fixtures import RELAY_BLOCK, RelayModClient
from .test_integration import ModTestClient

integration_db = _integration.integration_db
integration_client = _integration.integration_client
race_with_participants = _integration.race_with_participants
seed_folder = _integration.seed_folder

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
FLAGS = {k: v for k, v in RELAY_BLOCK.items() if k != "warp_flag_count"}
START_ZONE_NAME = "Chapel of Anticipation"
GRAPH = {
    "total_layers": 12,
    "nodes": {
        "start_node": {"type": "start", "display_name": START_ZONE_NAME, "layer": 0},
        "node_a": {"display_name": "Leyndell, Royal Capital", "layer": 1},
    },
    "event_map": {"9000000": "node_a"},
}


def _relay_race_ws(integration_db, race_with_participants, *, relay: bool = True) -> None:
    """Turn the integration race into a running relay race: players 0 and 1 form
    a team held by player 0, player 2 leaves the team."""
    race_id = uuid.UUID(race_with_participants["race_id"])

    async def patch():
        async with integration_db() as db:
            race = (
                await db.execute(
                    select(Race)
                    .where(Race.id == race_id)
                    .options(selectinload(Race.seed), selectinload(Race.participants))
                )
            ).scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph["total_layers"] = 12
            graph["relay"] = dict(RELAY_BLOCK)
            race.seed.graph_json = graph
            race.seed.total_layers = 12
            race.relay_team_size = 2
            race.status = RaceStatus.RUNNING
            team = RelayTeam(race_id=race_id, name="Red Team", status=ParticipantStatus.PLAYING)
            db.add(team)
            await db.flush()
            members = sorted(race.participants, key=lambda p: p.created_at)
            for p in members[:2]:
                p.relay_team_id = team.id
                p.status = ParticipantStatus.PLAYING
            team.holder_id = members[0].id
            team.first_runner_id = members[0].id
            await db.commit()

    asyncio.run(patch())


def test_an_older_mod_is_refused_on_a_relay_race(
    integration_client, race_with_participants, integration_db
):
    _relay_race_ws(integration_db, race_with_participants)
    token = race_with_participants["players"][0]["mod_token"]
    for version in ("1.17", "1.18"):
        with integration_client.websocket_connect(
            f"/ws/mod/{race_with_participants['race_id']}"
        ) as ws:
            response = ModTestClient(ws, token).auth(protocol_version=version)
        assert response["type"] == "auth_error"
        assert response["message"] == RELAY_OLD_MOD_MESSAGE


def test_a_1_18_mod_still_joins_a_solo_race(integration_client, race_with_participants):
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_with_participants['race_id']}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.18")
    assert response["type"] == "auth_ok"
    assert "relay" in response and response["relay"] is None


def test_auth_ok_tells_each_member_its_role(
    integration_client, race_with_participants, integration_db
):
    _relay_race_ws(integration_db, race_with_participants)
    players = race_with_participants["players"]
    race_id = race_with_participants["race_id"]
    auths = []
    for player in players[:2]:
        mod = RelayModClient.connect(integration_client, race_id, player["mod_token"], "")
        try:
            auths.append(mod.auth(protocol_version="1.19"))
        finally:
            mod.close()
    holder_auth, waiting_auth = auths
    assert holder_auth["relay"]["role"] == "holder"
    assert waiting_auth["relay"]["role"] == "waiting"
    assert holder_auth["relay"]["flags"] == FLAGS
    assert holder_auth["relay"]["cap"] == 7  # 12 layers, 2 members
    assert holder_auth["relay"]["team_name"] == "Red Team"
    assert len(holder_auth["relay"]["members"]) == 2


# --- baton_free_in_s ---


def _team(**kwargs) -> RelayTeam:
    fields = {
        "id": uuid.uuid4(),
        "name": "Red Team",
        "status": ParticipantStatus.PLAYING,
        "holder_id": uuid.uuid4(),
        "baton_free": False,
        "holder_offline_since": None,
        "entry_flag_id": None,
    }
    fields.update(kwargs)
    return RelayTeam(**fields)


@pytest.mark.parametrize(
    "offline_for_s,baton_free,connected,expected",
    [
        (None, False, True, None),
        (10, False, False, 50),
        (60, False, False, 0),
        (300, False, False, 0),
        (5, True, False, 0),
        (None, True, True, 0),
        # Absent with no stamp yet (a socket just gone): the whole wait is ahead.
        (None, False, False, 60),
        # Stamped at the race start, still in the countdown: never above the wait.
        (-30, False, False, 60),
    ],
)
def test_baton_free_in_s(offline_for_s, baton_free, connected, expected):
    since = NOW - timedelta(seconds=offline_for_s) if offline_for_s is not None else None
    team = _team(baton_free=baton_free, holder_offline_since=since)
    assert baton_free_in_s(team, holder_connected=connected, now=NOW) == expected


def test_a_team_without_holder_has_a_free_baton():
    assert baton_free_in_s(_team(holder_id=None), holder_connected=False, now=NOW) == 0


def test_a_naive_offline_stamp_is_read_as_utc():
    team = _team(holder_offline_since=(NOW - timedelta(seconds=20)).replace(tzinfo=None))
    assert baton_free_in_s(team, holder_connected=False, now=NOW) == 40


# --- build_relay_info ---


def _member(name: str, *, zones: int = 0, status=ParticipantStatus.PLAYING) -> Participant:
    return Participant(
        id=uuid.uuid4(),
        user=User(twitch_username=name, twitch_display_name=name),
        relay_zones=zones,
        relay_validated=True,
        status=status,
    )


def _info(team, members, me, *, connected=None, ready=(), total_layers=12):
    return build_relay_info(
        team,
        members,
        me,
        total_layers=total_layers,
        flags=FLAGS,
        connected={m.id for m in members} if connected is None else connected,
        ready=ready,
        now=NOW,
        graph_json=GRAPH,
    )


def test_gates_are_locked_for_a_holder_at_the_cap_only():
    # 12 layers, 2 members: cap 7.
    at_cap, other = _member("a", zones=7), _member("b", zones=7)
    team = _team(holder_id=at_cap.id)
    assert _info(team, [at_cap, other], at_cap).gates_locked is True
    assert _info(team, [at_cap, other], other).gates_locked is False
    under = _member("c", zones=6)
    team = _team(holder_id=under.id)
    assert _info(team, [under, other], under).gates_locked is False


def test_relay_info_names_the_zone_a_taker_restarts():
    a, b = _member("a"), _member("b")
    team = _team(holder_id=a.id, entry_flag_id=9000000)
    assert _info(team, [a, b], b).zone_name == "Leyndell, Royal Capital"
    team.entry_flag_id = None
    assert _info(team, [a, b], b).zone_name == START_ZONE_NAME
    team.entry_flag_id = 1234
    assert _info(team, [a, b], b).zone_name is None


def test_relay_member_ready_follows_relay_ready():
    a, b, c = _member("a"), _member("b"), _member("c")
    team = _team(holder_id=a.id)
    # c is ready in the room but its mod is gone: not ready.
    info = _info(team, [b, c], a, connected={a.id, b.id}, ready={b.id, c.id})
    assert [m.ready for m in info.members] == [True, False]
    assert [m.online for m in info.members] == [True, False]


def test_a_free_baton_makes_its_nominal_holder_wait():
    a, b = _member("a"), _member("b")
    team = _team(holder_id=a.id, baton_free=True)
    info = _info(team, [a, b], a)
    assert (info.role, info.baton_free_in_s) == ("waiting", 0)
    assert info.holder_id == str(a.id)


def test_a_leaderboard_row_reads_readiness_from_the_room(monkeypatch):
    from speedfog_racing.websocket.race import manager as manager_module

    a, b = _member("a"), _member("b")
    team = _team(
        holder_id=a.id,
        race_id=uuid.uuid4(),
        current_layer=0,
        igt_ms=0,
        death_count=0,
        color_index=0,
    )
    room = RaceRoom(race_id=team.race_id)
    room.relay_ready.add(b.id)
    monkeypatch.setitem(manager_module.manager.rooms, team.race_id, room)
    row = RelayTeamRow(team, (a, b), cap=7)
    info = relay_team_to_info(row, connected_ids={a.id, b.id})
    assert [m.ready for m in info.relay_members or []] == [False, True]


def test_a_setup_row_sent_to_the_mods_reads_ready_once_its_first_runner_is():
    # The in-game overlay shows the status of its team's leaderboard row.
    first = _member("a", status=ParticipantStatus.REGISTERED)
    mate = _member("b", status=ParticipantStatus.READY)
    team = _team(
        status=ParticipantStatus.REGISTERED,
        holder_id=None,
        first_runner_id=first.id,
        race_id=uuid.uuid4(),
        current_layer=0,
        igt_ms=0,
        death_count=0,
        color_index=0,
    )

    def wire_status() -> str:
        return relay_team_to_info(RelayTeamRow(team, (first, mate), cap=7)).status

    assert wire_status() == "registered"  # a ready teammate is not enough
    first.status = ParticipantStatus.READY
    assert wire_status() == "ready"
