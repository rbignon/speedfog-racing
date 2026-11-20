"""Relay rules: the cap, the team rows and the team model."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RelayTeam,
    User,
    UserRole,
)
from speedfog_racing.services.relay import (
    default_team_name,
    is_active_member,
    leaderboard_entries,
    relay_cap,
    relay_rows,
    reset_relay_team,
    team_cap,
)

from .relay_fixtures import make_relay_race

PLAYING = ParticipantStatus.PLAYING
ABANDONED = ParticipantStatus.ABANDONED


def member(status: ParticipantStatus) -> Participant:
    return Participant(id=uuid.uuid4(), status=status)


@pytest.fixture
async def rr_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _users(db: AsyncSession, count: int) -> list[User]:
    users = [
        User(
            twitch_id=f"rr_{i}",
            twitch_username=f"rr_user_{i}",
            twitch_display_name=f"RR User {i}",
            api_token=f"rr_token_{i}",
            role=UserRole.ORGANIZER,
        )
        for i in range(count)
    ]
    db.add_all(users)
    await db.flush()
    return users


@pytest.mark.parametrize(
    "layers,members,cap", [(30, 3, 11), (12, 3, 5), (12, 2, 7), (13, 3, 6), (12, 1, 13)]
)
def test_relay_cap(layers, members, cap):
    assert relay_cap(layers, members) == cap


def test_team_cap_is_recomputed_on_the_members_still_in():
    members = [member(PLAYING), member(PLAYING), member(ABANDONED)]
    assert team_cap(12, members) == 7  # 2 active, not 3
    assert team_cap(12, [member(ABANDONED)]) == 13  # never divides by zero


def test_a_disqualified_member_is_not_active():
    assert not is_active_member(member(ParticipantStatus.DISQUALIFIED))
    assert is_active_member(member(ParticipantStatus.FINISHED))


def test_default_team_name_skips_taken_names():
    assert default_team_name([]) == "Team 1"
    assert default_team_name(["Team 2"]) == "Team 3"  # count + 1 = 2 is taken
    assert default_team_name(["Team 1", "Team 3"]) == "Team 4"


async def test_rows_group_members_and_hide_empty_teams_once_started(rr_session):
    async with rr_session() as db:
        org, a, b, c, d = await _users(db, 5)
        race = await make_relay_race(db, org, teams=[[a, b], [c, d], []])
        teams, parts = race.relay_teams, race.participants
        setup_rows = relay_rows(teams, parts, total_layers=12, setup=True)
        assert [len(r.members) for r in setup_rows] == [2, 2, 0]
        assert len(relay_rows(teams, parts, total_layers=12, setup=False)) == 2
        assert [r.cap for r in setup_rows][:2] == [7, 7]


async def test_a_team_row_reads_the_team_and_names_the_holder(rr_session):
    async with rr_session() as db:
        org, a, b = await _users(db, 3)
        race = await make_relay_race(db, org, teams=[[a, b]])
        team = race.relay_teams[0]
        team.holder_id = race.participants[1].id
        team.current_layer = 4
        team.igt_ms = 90_000
        [row] = relay_rows(race.relay_teams, race.participants, total_layers=12, setup=True)
        assert row.id == team.id
        assert (row.current_layer, row.igt_ms) == (4, 90_000)
        assert row.holder is race.participants[1]


async def test_solo_race_entries_are_its_participants(rr_session):
    async with rr_session() as db:
        org, a = await _users(db, 2)
        race = Race(name="Solo", organizer_id=org.id)
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=a.id))
        await db.commit()
        loaded = (
            await db.execute(select(Race).options(selectinload(Race.participants)))
        ).scalar_one()
        assert leaderboard_entries(loaded, {"total_layers": 12}) is loaded.participants


async def test_relay_race_entries_are_team_rows(rr_session):
    async with rr_session() as db:
        org, a, b = await _users(db, 3)
        race = await make_relay_race(db, org, teams=[[a, b]])
        rows = leaderboard_entries(race, {"total_layers": 12})
        assert [r.id for r in rows] == [race.relay_teams[0].id]


async def test_reset_returns_a_team_to_a_fresh_one_keeping_its_identity(rr_session):
    async with rr_session() as db:
        org, a, b = await _users(db, 3)
        race = await make_relay_race(db, org, teams=[[a, b]])
        team = race.relay_teams[0]
        first = team.first_runner_id
        team.holder_id = race.participants[1].id
        team.status = PLAYING
        team.current_layer = 5
        team.igt_ms = 1000
        team.entry_flag_id = 1050294007
        team.zone_history = [{"node_id": "x"}]
        team.layer_entry_igts = {"1": 10}
        team.baton_free = True
        reset_relay_team(team)
        assert (team.status, team.current_layer, team.igt_ms) == (
            ParticipantStatus.REGISTERED,
            0,
            0,
        )
        assert team.entry_flag_id is None and team.holder_id is None and not team.baton_free
        assert team.zone_history is None and team.layer_entry_igts == {}
        assert team.first_runner_id == first and team.name == "Team 1"


async def test_deleting_a_relay_race_removes_its_teams(rr_session):
    async with rr_session() as db:
        org, a, b = await _users(db, 3)
        race = await make_relay_race(db, org, teams=[[a, b], []])
        race.relay_teams[0].holder_id = race.participants[0].id
        await db.commit()
        await db.delete(race)
        await db.commit()
        assert (await db.scalar(select(func.count(RelayTeam.id)))) == 0
