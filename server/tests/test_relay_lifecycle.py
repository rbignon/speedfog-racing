"""Relay lifecycle: a member going out (abandon, removal, disqualification,
inactivity), a team going out, the forced end and a server restart."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import speedfog_racing.api.races as races_api
import speedfog_racing.services.inactivity_monitor as monitor
import speedfog_racing.websocket.race.relay as relay_ws
from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    User,
    UserRole,
)
from speedfog_racing.services.relay import baton_free_in_s, race_teams_for_update
from speedfog_racing.services.sanctions_service import disqualify
from speedfog_racing.websocket.race.manager import manager
from speedfog_racing.websocket.race.relay_mod import RelayModHandler

from . import test_integration as _integration
from .relay_fixtures import (
    FOG_FLAG,
    SECOND_FOG_FLAG,
    THIRD_FOG_FLAG,
    RelayModClient,
    barrier,
    connect_spectator,
    load_member,
    load_members,
    load_race,
    load_team,
    make_receiver,
    make_relay_race,
    member_view,
    pass_gate,
    patch_member,
    patch_team,
    progress_graph,
    run_relay_race,
    setup_relay_race,
    started_mods,
)

integration_db = _integration.integration_db
integration_client = _integration.integration_client

STATE = {
    "attributes": [10, 10, 10, 10, 10, 10, 10, 10],
    "level": 9,
    "runes": 0,
    "items": [],
    "grace_flags": [],
}


def _twelve_layers() -> dict[str, Any]:
    graph = progress_graph()
    graph["total_layers"] = 12
    return graph


@pytest.fixture
def relay_race(integration_db, integration_client):
    return setup_relay_race(integration_db)


@pytest.fixture
def mods(integration_client, relay_race):
    yield from started_mods(integration_client, relay_race)


@pytest.fixture
def trio(integration_db, integration_client):
    """Two teams of three on a 12-layer seed: cap 5, and 7 once a member is out."""
    return setup_relay_race(integration_db, team_size=3, graph=_twelve_layers())


@pytest.fixture
def trio_mods(integration_client, trio):
    yield from started_mods(integration_client, trio)


def _member(relay_race: dict[str, Any], team: int, index: int) -> dict[str, Any]:
    member: dict[str, Any] = relay_race["teams"][team]["members"][index]
    return member


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


def _abandon(client, relay_race: dict[str, Any], team: int, index: int) -> None:
    user = _member(relay_race, team, index)["user"]
    response = client.post(f"/api/races/{relay_race['race_id']}/abandon", headers=_auth(user))
    assert response.status_code == 200, response.json()


def _take(mod: RelayModClient) -> None:
    """Take the free baton and acknowledge it (no take timer left behind)."""
    mod.send({"type": "relay_take_request"})
    take = mod.receive_until("relay_take")
    mod.send({"type": "relay_taken", "handoff_id": take["handoff_id"]})
    barrier(mod)


def _chat(relay_race: dict[str, Any]) -> list[tuple[ChatChannel, str]]:
    async def read() -> list[tuple[ChatChannel, str]]:
        async with relay_race["db"]() as db:
            result = await db.execute(
                select(ChatMessage)
                .where(ChatMessage.race_id == UUID(relay_race["race_id"]))
                .order_by(ChatMessage.created_at)
            )
            return [(m.channel, m.message) for m in result.scalars()]

    return asyncio.run(read())


def _statuses(members: list[Participant]) -> dict[str, ParticipantStatus]:
    return {str(m.id): m.status for m in members}


# --- A member out ---


def test_holder_abandon_frees_the_baton_at_once(integration_client, trio, trio_mods):
    holder = _member(trio, 0, 0)
    waiting = trio_mods[_member(trio, 0, 1)["participant_id"]]
    make_receiver(waiting)

    _abandon(integration_client, trio, 0, 0)

    upd = waiting.receive_until("relay_update", lambda m: m["relay"]["holder_id"] is None)
    # 12 layers, 2 members left: no 60 s wait, the cap recomputed.
    assert (upd["relay"]["baton_free_in_s"], upd["relay"]["cap"]) == (0, 7)
    assert member_view(upd, holder["participant_id"])["status"] == "abandoned"
    assert (ChatChannel.PUBLIC, "Relay Runner 0 has abandoned the race.") in _chat(trio)
    _take(waiting)
    assert load_team(trio).holder_id == UUID(waiting.participant_id)


def test_abandon_lifts_the_cap_lock_of_a_remaining_holder(integration_client, trio, trio_mods):
    holder_id = _member(trio, 0, 0)["participant_id"]
    patch_member(trio, holder_id, relay_zones=5)  # at the cap of a team of 3

    _abandon(integration_client, trio, 0, 2)

    upd = trio_mods[holder_id].receive_until("relay_update", lambda m: m["relay"]["cap"] == 7)
    assert (upd["relay"]["role"], upd["relay"]["gates_locked"]) == ("holder", False)
    assert load_team(trio).holder_id == UUID(holder_id)


def test_team_is_out_when_its_last_member_abandons_and_the_race_can_end(
    integration_client, relay_race, mods
):
    patch_team(relay_race, 1, status=ParticipantStatus.FINISHED)
    for member in relay_race["teams"][1]["members"]:
        patch_member(relay_race, member["participant_id"], status=ParticipantStatus.FINISHED)

    _abandon(integration_client, relay_race, 0, 0)
    assert load_team(relay_race).status == ParticipantStatus.PLAYING  # one member left
    _abandon(integration_client, relay_race, 0, 1)

    assert load_team(relay_race).status == ParticipantStatus.ABANDONED
    assert load_race(relay_race).status == RaceStatus.FINISHED  # the other team had finished
    # The team's mods learn their race is over and lower their lock.
    mods[_member(relay_race, 0, 1)["participant_id"]].receive_until(
        "relay_update", lambda m: m["relay"]["team_status"] == "abandoned"
    )
    assert (ChatChannel.PUBLIC, "Team 1 is out.") in _chat(relay_race)


def test_organizer_removes_a_member_during_the_race(integration_client, trio, trio_mods):
    pid = _member(trio, 0, 1)["participant_id"]

    response = integration_client.delete(
        f"/api/races/{trio['race_id']}/participants/{pid}", headers=_auth(trio["organizer"])
    )

    assert response.status_code == 204
    member = load_member(trio, pid)
    assert member.status == ParticipantStatus.ABANDONED
    assert member.relay_team_id == UUID(trio["teams"][0]["id"])  # the row is kept
    holder = trio_mods[_member(trio, 0, 0)["participant_id"]]
    holder.receive_until("relay_update", lambda m: m["relay"]["cap"] == 7)
    assert (ChatChannel.PARTICIPANTS, "Relay Runner 1 has been removed from the race") in _chat(
        trio
    )


def test_removing_a_member_already_out_is_refused(integration_client, trio, trio_mods):
    _abandon(integration_client, trio, 0, 1)

    response = integration_client.delete(
        f"/api/races/{trio['race_id']}/participants/{_member(trio, 0, 1)['participant_id']}",
        headers=_auth(trio["organizer"]),
    )

    assert response.status_code == 400


def test_disqualifying_a_member_puts_the_team_out(integration_client, trio, trio_mods):
    team_id = trio["teams"][0]["id"]
    cheater = _member(trio, 0, 1)["participant_id"]
    spectator = connect_spectator(integration_client, trio["race_id"])
    try:
        spectator.receive_until("leaderboard_update")  # the snapshot sent at connect
        response = integration_client.post(
            f"/api/races/{trio['race_id']}/participants/{cheater}/disqualify",
            json={"reason": "Cheating"},
            headers=_auth(trio["organizer"]),
        )
        assert response.status_code == 200, response.json()

        assert load_team(trio).status == ParticipantStatus.DISQUALIFIED
        statuses = _statuses(load_members(trio))
        assert statuses.pop(cheater) == ParticipantStatus.DISQUALIFIED
        assert set(statuses.values()) == {ParticipantStatus.ABANDONED}
        board = spectator.receive_until("leaderboard_update")
        leaderboard_row = next(p for p in board["participants"] if p["id"] == team_id)
        assert leaderboard_row["status"] == "disqualified"
        trio_mods[_member(trio, 0, 0)["participant_id"]].receive_until(
            "relay_update", lambda m: m["relay"]["team_status"] == "disqualified"
        )
    finally:
        spectator.close()


def test_cancelling_a_disqualification_restores_the_member_never_the_team(
    integration_client, trio, trio_mods
):
    cheater = _member(trio, 0, 1)["participant_id"]
    path = f"/api/races/{trio['race_id']}/participants/{cheater}/disqualify"
    headers = _auth(trio["organizer"])
    assert integration_client.post(path, json={"reason": "x"}, headers=headers).status_code == 200

    assert integration_client.delete(path, headers=headers).status_code == 200

    assert load_team(trio).status == ParticipantStatus.DISQUALIFIED
    # Their run was going on, but their team is out: it ends abandoned.
    assert set(_statuses(load_members(trio)).values()) == {ParticipantStatus.ABANDONED}


def test_a_pending_take_whose_receiver_goes_out_frees_the_baton(
    integration_client, relay_race, mods
):
    giver = mods[_member(relay_race, 0, 0)["participant_id"]]
    target = mods[_member(relay_race, 0, 1)["participant_id"]]
    make_receiver(target)
    giver.send({"type": "relay_handoff_request", "to_participant_id": target.participant_id})
    release = giver.receive_until("relay_release")
    giver.send(
        {
            "type": "relay_state",
            "handoff_id": release["handoff_id"],
            "state": STATE,
            "igt_ms": 3_000,
        }
    )
    target.receive_until("relay_take")

    _abandon(integration_client, relay_race, 0, 1)

    upd = giver.receive_until("relay_update", lambda m: m["relay"]["holder_id"] is None)
    assert upd["relay"]["baton_free_in_s"] == 0
    team = load_team(relay_race)
    assert (team.holder_id, team.baton_free) == (None, True)
    # The take is dropped, its timer cancelled (the fixture checks none outlives the test).
    room = manager.get_room(UUID(relay_race["race_id"]))
    assert not relay_ws.awaiting_take(room, team.id, UUID(target.participant_id))


def test_a_release_whose_target_goes_out_is_dropped(integration_client, trio, trio_mods):
    holder = trio_mods[_member(trio, 0, 0)["participant_id"]]
    target = trio_mods[_member(trio, 0, 1)["participant_id"]]
    make_receiver(target)
    holder.send({"type": "relay_handoff_request", "to_participant_id": target.participant_id})
    release = holder.receive_until("relay_release")

    _abandon(integration_client, trio, 0, 1)
    holder.receive_until("relay_update", lambda m: m["relay"]["cap"] == 7)
    holder.send(
        {
            "type": "relay_state",
            "handoff_id": release["handoff_id"],
            "state": STATE,
            "igt_ms": 3_000,
        }
    )

    # An unknown handoff now: answered with the holder's own role.
    assert holder.receive_until("relay_update")["relay"]["role"] == "holder"
    assert load_team(trio).holder_id == UUID(holder.participant_id)


def test_a_member_offline_stamp_follows_their_mod(integration_client, relay_race, mods):
    member = _member(relay_race, 0, 1)
    holder = mods[_member(relay_race, 0, 0)["participant_id"]]

    mods[member["participant_id"]].disconnect()
    holder.receive_until(
        "relay_update", lambda m: not member_view(m, member["participant_id"])["online"]
    )
    assert load_member(relay_race, member["participant_id"]).last_igt_change_at is not None

    mods[member["participant_id"]].close()
    back = mods[member["participant_id"]] = RelayModClient.connect(
        integration_client, relay_race["race_id"], member["mod_token"], member["participant_id"]
    )
    assert back.auth(protocol_version="1.19")["type"] == "auth_ok"
    holder.receive_until(
        "relay_update", lambda m: member_view(m, member["participant_id"])["online"]
    )
    assert load_member(relay_race, member["participant_id"]).last_igt_change_at is None


def test_banning_a_member_puts_their_team_out(integration_client, trio, trio_mods):
    admin = trio["organizer"]

    async def promote() -> None:
        async with trio["db"]() as db:
            user = await db.get(User, admin.id)
            assert user is not None
            user.role = UserRole.ADMIN
            await db.commit()

    asyncio.run(promote())
    holder = _member(trio, 0, 0)

    response = integration_client.post(
        f"/api/admin/users/{holder['user'].id}/ban",
        json={"reason": "Cheating"},
        headers=_auth(admin),
    )

    assert response.status_code == 200, response.json()
    team = load_team(trio)
    # The banned holder's baton does not wait for their mod's 60 s: the team is out.
    assert (team.status, team.holder_id) == (ParticipantStatus.DISQUALIFIED, None)
    statuses = _statuses(load_members(trio))
    assert statuses.pop(holder["participant_id"]) == ParticipantStatus.DISQUALIFIED
    assert set(statuses.values()) == {ParticipantStatus.ABANDONED}
    trio_mods[_member(trio, 0, 1)["participant_id"]].receive_until(
        "relay_update", lambda m: m["relay"]["team_status"] == "disqualified"
    )
    assert (ChatChannel.PUBLIC, "Team 1 is out.") in _chat(trio)


def test_a_member_going_out_keeps_how_far_the_team_was(integration_client, trio, trio_mods):
    holder = trio_mods[_member(trio, 0, 0)["participant_id"]]

    pass_gate(holder, FOG_FLAG, 20_000, 1)  # layer 1
    _abandon(integration_client, trio, 0, 2)
    pass_gate(holder, SECOND_FOG_FLAG, 40_000, 2)  # layer 2
    _abandon(integration_client, trio, 0, 1)
    pass_gate(holder, THIRD_FOG_FLAG, 60_000, 3)  # layer 3
    _abandon(integration_client, trio, 0, 0)  # the last one: the team is out

    assert load_team(trio).status == ParticipantStatus.ABANDONED
    rows = {
        str(m.id): (m.status, m.current_layer, m.igt_ms, m.finished_at) for m in load_members(trio)
    }
    assert rows == {
        _member(trio, 0, 2)["participant_id"]: (ParticipantStatus.ABANDONED, 1, 20_000, None),
        _member(trio, 0, 1)["participant_id"]: (ParticipantStatus.ABANDONED, 2, 40_000, None),
        _member(trio, 0, 0)["participant_id"]: (ParticipantStatus.ABANDONED, 3, 60_000, None),
    }


def test_a_take_restarts_the_team_inactivity_clock(relay_race, mods):
    waiting = mods[_member(relay_race, 0, 1)["participant_id"]]
    make_receiver(waiting)
    patch_team(relay_race, baton_free=True, last_igt_change_at=_ago(29))

    _take(waiting)

    # The new holder gets the whole 30 minutes for their first report.
    assert _aware(load_team(relay_race).last_igt_change_at) > _ago(1)


def test_start_and_reset_lock_the_teams_before_any_member_changes(
    monkeypatch, integration_client, relay_race
):
    seen: list[bool] = []
    real = races_api.lock_race_teams

    async def spy(db: AsyncSession, race_id: UUID) -> Any:
        seen.append(any(isinstance(row, Participant) for row in (*db.dirty, *db.new)))
        return await real(db, race_id)

    monkeypatch.setattr(races_api, "lock_race_teams", spy)
    headers = _auth(relay_race["organizer"])
    rid = relay_race["race_id"]

    assert integration_client.post(f"/api/races/{rid}/start", headers=headers).status_code == 200
    assert integration_client.post(f"/api/races/{rid}/reset", headers=headers).status_code == 200

    assert seen == [False, False]  # called by both, no member changed yet
    statement = race_teams_for_update(uuid4()).compile(dialect=postgresql.dialect())
    assert str(statement).endswith("FOR UPDATE OF relay_teams")


# --- Forced end ---


def test_force_finish_puts_unfinished_teams_out(integration_client, relay_race, mods):
    patch_team(relay_race, 1, status=ParticipantStatus.FINISHED)
    for member in relay_race["teams"][1]["members"]:
        patch_member(relay_race, member["participant_id"], status=ParticipantStatus.FINISHED)

    response = integration_client.post(
        f"/api/races/{relay_race['race_id']}/finish", headers=_auth(relay_race["organizer"])
    )

    assert response.status_code == 200, response.json()
    assert load_team(relay_race).status == ParticipantStatus.ABANDONED
    assert all(m.status == ParticipantStatus.ABANDONED for m in load_members(relay_race))
    assert load_team(relay_race, 1).status == ParticipantStatus.FINISHED  # kept
    mods[_member(relay_race, 0, 1)["participant_id"]].receive_until(
        "relay_update", lambda m: m["relay"]["team_status"] == "abandoned"
    )


# --- Inactivity and restart (rows only, no mod) ---


@pytest.fixture
async def session_maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _relay(
    session_maker: async_sessionmaker[AsyncSession], *, minutes: int = 120
) -> dict[str, Any]:
    """Two teams (3 and 2 members) playing for ``minutes``, each held by its
    first member. Returns the race id, the team ids and the member ids."""
    async with session_maker() as db:
        organizer = User(
            twitch_id="org", twitch_username="org", api_token="org", role=UserRole.ORGANIZER
        )
        users = [
            User(
                twitch_id=f"runner_{i}",
                twitch_username=f"runner_{i}",
                twitch_display_name=f"Runner {i}",
                api_token=f"runner_{i}",
            )
            for i in range(5)
        ]
        db.add_all([organizer, *users])
        await db.flush()
        race = await make_relay_race(db, organizer, team_size=3, teams=[users[:3], users[3:]])
        await run_relay_race(db, race, started_at=datetime.now(UTC) - timedelta(minutes=minutes))
        by_user = {p.user_id: p.id for p in race.participants}
        teams = sorted(race.relay_teams, key=lambda t: t.name)
        return {
            "race_id": race.id,
            "organizer": organizer.id,
            "teams": [t.id for t in teams],
            "members": [[by_user[u.id] for u in users[:3]], [by_user[u.id] for u in users[3:]]],
        }


async def _patch(session_maker, model: type, row_id: UUID, **fields: Any) -> None:
    async with session_maker() as db:
        row = await db.get(model, row_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await db.commit()


async def _get(session_maker, model: type, row_id: UUID) -> Any:
    async with session_maker() as db:
        return await db.get(model, row_id)


async def _public_lines(session_maker, race_id: UUID) -> list[str]:
    async with session_maker() as db:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.race_id == race_id, ChatMessage.channel == ChatChannel.PUBLIC)
            .order_by(ChatMessage.created_at)
        )
        return [m.message for m in result.scalars()]


def _ago(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def test_stale_team_igt_abandons_the_holder_not_the_waiting_runners(session_maker):
    relay = await _relay(session_maker)
    team_id, (holder, *waiting) = relay["teams"][0], relay["members"][0]
    await _patch(session_maker, RelayTeam, team_id, last_igt_change_at=_ago(31))

    races, abandoned = await monitor.abandon_stale_relay_teams(session_maker)

    assert (races, abandoned) == ([relay["race_id"]], {holder})
    team = await _get(session_maker, RelayTeam, team_id)
    assert (team.status, team.holder_id, team.baton_free) == (
        ParticipantStatus.PLAYING,
        None,
        True,
    )
    # The free baton's own 30 minutes start now.
    assert _aware(team.last_igt_change_at) > _ago(1)
    for pid in waiting:
        assert (await _get(session_maker, Participant, pid)).status == ParticipantStatus.PLAYING
    other = await _get(session_maker, RelayTeam, relay["teams"][1])
    assert other.holder_id == relay["members"][1][0]
    assert await _public_lines(session_maker, relay["race_id"]) == [
        "Runner 0 has abandoned the race due to inactivity."
    ]


async def test_stale_team_without_holder_is_out(session_maker):
    relay = await _relay(session_maker)
    team_id = relay["teams"][0]
    await _patch(
        session_maker,
        RelayTeam,
        team_id,
        holder_id=None,
        baton_free=True,
        last_igt_change_at=_ago(31),
    )

    races, abandoned = await monitor.abandon_stale_relay_teams(session_maker)

    assert (races, abandoned) == ([relay["race_id"]], set())
    team = await _get(session_maker, RelayTeam, team_id)
    assert team.status == ParticipantStatus.ABANDONED
    for pid in relay["members"][0]:
        assert (await _get(session_maker, Participant, pid)).status == ParticipantStatus.ABANDONED
    assert await _public_lines(session_maker, relay["race_id"]) == ["Team 1 is out."]


@pytest.mark.parametrize("index", [0, 1], ids=["holder", "waiting"])
async def test_member_offline_for_30_minutes_is_abandoned(session_maker, index):
    relay = await _relay(session_maker)
    holder, offline_member = relay["members"][0][0], relay["members"][0][index]
    await _patch(session_maker, Participant, offline_member, last_igt_change_at=_ago(31))

    _, abandoned = await monitor.abandon_inactive_participants(session_maker)

    assert abandoned == {offline_member}
    team = await _get(session_maker, RelayTeam, relay["teams"][0])
    assert team.status == ParticipantStatus.PLAYING
    if offline_member == holder:
        assert (team.holder_id, team.baton_free) == (None, True)
    else:
        assert (team.holder_id, team.baton_free) == (holder, False)
    assert await _public_lines(session_maker, relay["race_id"]) == [
        f"Runner {index} has abandoned the race due to inactivity."
    ]


async def test_a_baton_freed_for_inactivity_gets_30_minutes_before_the_team_is_out(
    session_maker,
):
    # The holder's mod left 31 minutes ago: the team's IGT stopped then too.
    relay = await _relay(session_maker)
    team_id, holder = relay["teams"][0], relay["members"][0][0]
    await _patch(session_maker, Participant, holder, last_igt_change_at=_ago(31))
    await _patch(session_maker, RelayTeam, team_id, last_igt_change_at=_ago(31))

    # One pass of the monitor, in the loop's order.
    _, abandoned = await monitor.abandon_inactive_participants(session_maker)
    _, stale = await monitor.abandon_stale_relay_teams(session_maker)

    assert (abandoned, stale) == ({holder}, set())
    team = await _get(session_maker, RelayTeam, team_id)
    assert (team.status, team.holder_id, team.baton_free) == (
        ParticipantStatus.PLAYING,
        None,
        True,
    )


async def test_connected_waiting_runner_is_never_inactive(session_maker):
    relay = await _relay(session_maker, minutes=120)  # stamps null: every mod connected

    assert (await monitor.abandon_inactive_participants(session_maker))[1] == set()
    assert (await monitor.abandon_stale_relay_teams(session_maker))[1] == set()
    assert (await _get(session_maker, RelayTeam, relay["teams"][0])).holder_id is not None


async def test_restart_makes_an_absent_holder_takeable(session_maker):
    relay = await _relay(session_maker)  # RUNNING, holders set, no stamp anywhere

    await relay_ws.stamp_offline_runners(session_maker)

    team = await _get(session_maker, RelayTeam, relay["teams"][0])
    assert team.holder_offline_since is not None
    since = _aware(team.holder_offline_since)
    assert baton_free_in_s(team, holder_connected=False, now=since) == 60
    assert baton_free_in_s(team, holder_connected=False, now=since + timedelta(seconds=60)) == 0
    # Every member's 30 minutes offline start at the restart too.
    for pid in relay["members"][1]:
        assert (await _get(session_maker, Participant, pid)).last_igt_change_at is not None


async def test_restart_keeps_the_stamps_already_there(session_maker):
    relay = await _relay(session_maker)
    since = _ago(5)
    await _patch(session_maker, RelayTeam, relay["teams"][0], holder_offline_since=since)
    await _patch(session_maker, Participant, relay["members"][1][1], last_igt_change_at=since)

    await relay_ws.stamp_offline_runners(session_maker)

    team = await _get(session_maker, RelayTeam, relay["teams"][0])
    assert _aware(team.holder_offline_since) == since
    member = await _get(session_maker, Participant, relay["members"][1][1])
    assert _aware(member.last_igt_change_at) == since
    other = await _get(session_maker, RelayTeam, relay["teams"][1])
    assert _aware(other.holder_offline_since) > since  # stamped at the restart


@pytest.mark.parametrize(
    "status,offline_min,race_status,expected",
    [
        (ParticipantStatus.PLAYING, 31, RaceStatus.RUNNING, True),
        (ParticipantStatus.PLAYING, 29, RaceStatus.RUNNING, False),
        # Their mod came back since the query: no stamp any more.
        (ParticipantStatus.PLAYING, None, RaceStatus.RUNNING, False),
        # A no-show: never validated.
        (ParticipantStatus.READY, None, RaceStatus.RUNNING, True),
        (ParticipantStatus.REGISTERED, None, RaceStatus.RUNNING, True),
        (ParticipantStatus.READY, None, RaceStatus.FINISHED, False),
        (ParticipantStatus.ABANDONED, 31, RaceStatus.RUNNING, False),
    ],
)
def test_a_relay_member_is_judged_inactive_again_under_the_locks(
    status, offline_min, race_status, expected
):
    team = RelayTeam(race=Race(status=race_status))
    member = Participant(
        status=status,
        last_igt_change_at=_ago(offline_min) if offline_min is not None else None,
    )

    assert monitor._still_inactive(_ago(30))(team, member) is expected
    if expected:
        assert member.status == ParticipantStatus.ABANDONED


async def test_a_team_whose_first_holder_never_reported_is_out_in_the_end(session_maker):
    relay = await _relay(session_maker)
    team_id, (holder, *waiting) = relay["teams"][0], relay["members"][0]
    await _patch(
        session_maker, RelayTeam, team_id, status=ParticipantStatus.READY, last_igt_change_at=None
    )
    await _patch(
        session_maker,
        Participant,
        holder,
        status=ParticipantStatus.READY,
        relay_validated=False,
        created_at=_ago(120),
    )

    # The holder is a no-show: the baton is free, and its 30 minutes start.
    _, abandoned = await monitor.abandon_inactive_participants(session_maker)
    assert abandoned == {holder}
    team = await _get(session_maker, RelayTeam, team_id)
    assert (team.status, team.holder_id, team.baton_free) == (ParticipantStatus.READY, None, True)
    assert _aware(team.last_igt_change_at) > _ago(1)

    # Nobody took it in 30 minutes.
    await _patch(session_maker, RelayTeam, team_id, last_igt_change_at=_ago(31))
    races, _ = await monitor.abandon_stale_relay_teams(session_maker)

    assert races == [relay["race_id"]]
    assert (await _get(session_maker, RelayTeam, team_id)).status == ParticipantStatus.ABANDONED
    for pid in waiting:
        assert (await _get(session_maker, Participant, pid)).status == ParticipantStatus.ABANDONED


async def test_one_failing_relay_member_does_not_stop_the_pass(session_maker, monkeypatch):
    relay = await _relay(session_maker)
    for pid in (relay["members"][0][1], relay["members"][1][1]):
        await _patch(session_maker, Participant, pid, last_igt_change_at=_ago(31))
    real = relay_ws.take_member_out
    calls: list[UUID] = []

    async def flaky(session_maker: Any, race_id: UUID, pid: UUID, *args: Any, **kw: Any) -> Any:
        calls.append(pid)
        if len(calls) == 1:
            raise RuntimeError("deadlock detected")
        return await real(session_maker, race_id, pid, *args, **kw)

    monkeypatch.setattr(relay_ws, "take_member_out", flaky)

    _, abandoned = await monitor.abandon_inactive_participants(session_maker)

    assert len(calls) == 2
    assert abandoned == {calls[1]}


async def test_one_failing_stale_team_does_not_stop_the_others(session_maker, monkeypatch):
    relay = await _relay(session_maker)
    for team_id in relay["teams"]:
        await _patch(session_maker, RelayTeam, team_id, last_igt_change_at=_ago(31))
    real = relay_ws.member_out
    calls: list[UUID] = []

    async def flaky(session_maker: Any, race_id: UUID, change: Any, **kw: Any) -> Any:
        calls.append(kw["team_id"])
        if len(calls) == 1:
            raise RuntimeError("deadlock detected")
        return await real(session_maker, race_id, change, **kw)

    monkeypatch.setattr(relay_ws, "member_out", flaky)

    races, abandoned = await monitor.abandon_stale_relay_teams(session_maker)

    holders = {relay["teams"][i]: relay["members"][i][0] for i in (0, 1)}
    assert (races, abandoned) == ([relay["race_id"]], {holders[calls[1]]})


async def test_the_monitor_pass_goes_on_when_the_stale_team_check_fails(session_maker, monkeypatch):
    relay = await _relay(session_maker)
    # The other team finished; this one's last member still in, its holder, went
    # offline 31 minutes ago.
    await _patch(session_maker, RelayTeam, relay["teams"][1], status=ParticipantStatus.FINISHED)
    for pid in relay["members"][1]:
        await _patch(session_maker, Participant, pid, status=ParticipantStatus.FINISHED)
    for pid in relay["members"][0][1:]:
        await _patch(session_maker, Participant, pid, status=ParticipantStatus.ABANDONED)
    await _patch(session_maker, Participant, relay["members"][0][0], last_igt_change_at=_ago(31))

    async def broken(session_maker: Any) -> Any:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(monitor, "abandon_stale_relay_teams", broken)
    task = asyncio.create_task(monitor.inactivity_monitor_loop(session_maker))
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if "The race has finished." in await _public_lines(session_maker, relay["race_id"]):
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    race = await _get(session_maker, Race, relay["race_id"])
    assert race.status == RaceStatus.FINISHED
    assert await _public_lines(session_maker, relay["race_id"]) == [
        "Runner 0 has abandoned the race due to inactivity.",
        "Team 1 is out.",
        "The race has finished.",
    ]


async def test_a_validation_never_brings_back_a_member_who_went_out(session_maker, monkeypatch):
    relay = await _relay(session_maker)
    pid = relay["members"][0][1]
    await _patch(
        session_maker, Participant, pid, status=ParticipantStatus.READY, relay_validated=False
    )
    handler = RelayModHandler(AsyncMock(), relay["race_id"], session_maker)
    handler._participant_id = pid
    real = RelayModHandler._read_gate

    async def gate_then_removed(self: RelayModHandler, db: AsyncSession) -> Any:
        gate = await real(self, db)
        # Between the lock-free read and the write, the member is removed.
        await _patch(session_maker, Participant, pid, status=ParticipantStatus.ABANDONED)
        return gate

    monkeypatch.setattr(RelayModHandler, "_read_gate", gate_then_removed)

    await handler._handle_status_update({"type": "status_update", "igt_ms": 2_000})

    member = await _get(session_maker, Participant, pid)
    assert (member.status, member.relay_validated) == (ParticipantStatus.ABANDONED, False)


async def test_a_team_is_announced_out_once_and_only_while_the_race_runs(session_maker):
    relay = await _relay(session_maker)

    def abandon(team: RelayTeam, member: Participant) -> bool:
        member.status = ParticipantStatus.ABANDONED
        return True

    def cheat(team: RelayTeam, member: Participant) -> bool:
        disqualify(member, by_id=relay["organizer"], reason="Cheating", now=datetime.now(UTC))
        return True

    race_id = relay["race_id"]
    for pid in relay["members"][1]:
        await relay_ws.take_member_out(session_maker, race_id, pid, abandon)
    # A member of a team already out is disqualified: the team was out already.
    await relay_ws.take_member_out(session_maker, race_id, relay["members"][1][0], cheat)
    assert (await _get(session_maker, RelayTeam, relay["teams"][1])).status == (
        ParticipantStatus.DISQUALIFIED
    )
    # A disqualification once the race finished puts its team out, without a line.
    await _patch(session_maker, Race, race_id, status=RaceStatus.FINISHED)
    await relay_ws.take_member_out(session_maker, race_id, relay["members"][0][0], cheat)
    assert (await _get(session_maker, RelayTeam, relay["teams"][0])).status == (
        ParticipantStatus.DISQUALIFIED
    )

    assert await _public_lines(session_maker, race_id) == ["Team 2 is out."]
