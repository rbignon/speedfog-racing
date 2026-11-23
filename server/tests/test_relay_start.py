"""Relay start rules and what a reset does to the teams."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RelayTeam,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import RaceRoom, SpectatorConnection, manager
from tests.relay_fixtures import make_relay_race, progress_graph

pytestmark = pytest.mark.asyncio

READY = ParticipantStatus.READY
REGISTERED = ParticipantStatus.REGISTERED


@pytest.fixture
async def rs_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def rs_client(rs_session):
    async def override_get_db():
        async with rs_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def organizer(rs_session):
    return await _user(rs_session, "orga", UserRole.ORGANIZER)


@pytest.fixture
async def players(rs_session):
    return [await _user(rs_session, f"p{i}") for i in range(8)]


async def _user(session, name: str, role: UserRole = UserRole.USER) -> User:
    async with session() as db:
        user = User(
            twitch_id=f"id_{name}",
            twitch_username=name,
            twitch_display_name=name,
            api_token=f"token_{name}",
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


async def _race(session, organizer, teams, statuses, graph=None) -> Race:
    """A relay race in SETUP with seeds released; ``statuses`` gives each member's
    status, in the order of the members of ``teams``. ``graph`` replaces the
    seed's default graph (a start broadcast to a room needs real nodes)."""
    async with session() as db:
        race = await make_relay_race(db, organizer, team_size=3, teams=teams, graph=graph)
        race.seeds_released_at = datetime.now(UTC)
        members = await db.execute(
            select(Participant)
            .where(Participant.race_id == race.id)
            .order_by(Participant.created_at, Participant.id)
        )
        ordered = {m.user_id: m for m in members.scalars()}
        flat = [u for users in teams for u in users]
        for i, (user, status) in enumerate(zip(flat, statuses, strict=True)):
            ordered[user.id].status = status
            # Distinct join times: members are listed by created_at.
            ordered[user.id].created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i)
        await db.commit()
        return race


async def _load(session, race: Race):
    async with session() as db:
        teams = list(
            (
                await db.execute(
                    select(RelayTeam)
                    .where(RelayTeam.race_id == race.id)
                    .order_by(RelayTeam.created_at, RelayTeam.name)
                )
            ).scalars()
        )
        members = list(
            (await db.execute(select(Participant).where(Participant.race_id == race.id))).scalars()
        )
        return teams, members


def _member(members, user: User) -> Participant:
    return next(m for m in members if m.user_id == user.id)


async def test_start_needs_two_teams_whose_first_runner_is_ready(
    rs_client, rs_session, organizer, players
):
    a, b, c, d = players[:4]
    # c, Team 2's first runner, is not ready; d is.
    waiting = await _race(
        rs_session, organizer, [[a, b], [c, d]], [READY, READY, REGISTERED, READY]
    )
    alone = await _race(rs_session, organizer, [[a, b]], [READY, READY])
    async with rs_client as client:
        short = await client.post(f"/api/races/{waiting.id}/start", headers=_auth(organizer))
        single = await client.post(f"/api/races/{alone.id}/start", headers=_auth(organizer))
    assert short.status_code == 400
    assert short.json()["detail"] == "Team 2's first runner is not ready"
    assert single.status_code == 400
    assert single.json()["detail"] == "At least 2 teams are required to start a relay race"


async def test_a_first_runner_alone_is_enough_to_start(rs_client, rs_session, organizer, players):
    a, b, c, d = players[:4]
    race = await _race(
        rs_session, organizer, [[a, b], [c, d]], [READY, REGISTERED, READY, REGISTERED]
    )
    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))
    assert resp.status_code == 200, resp.text


async def test_a_team_without_a_first_runner_cannot_start(
    rs_client, rs_session, organizer, players
):
    a, b, c, d = players[:4]
    race = await _race(rs_session, organizer, [[a, b], [c, d]], [READY] * 4)
    async with rs_session() as db:
        team = (await db.execute(select(RelayTeam).where(RelayTeam.name == "Team 2"))).scalar_one()
        team.first_runner_id = None
        await db.commit()
    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Team 2 has no first runner"


async def test_admin_does_not_start_a_relay_race_short(rs_client, rs_session, players):
    admin = await _user(rs_session, "boss", UserRole.ADMIN)
    a, b = players[:2]
    race = await _race(rs_session, admin, [[a, b]], [READY, READY])
    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(admin))
    assert resp.status_code == 400


async def test_start_keeps_a_member_who_is_not_ready_in_the_race(
    rs_client, rs_session, organizer, players
):
    teams = [players[0:3], players[3:6]]
    race = await _race(rs_session, organizer, teams, [READY] * 5 + [REGISTERED])
    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))
    assert resp.status_code == 200
    db_teams, members = await _load(rs_session, race)
    late = _member(members, players[5])
    # They may still connect and join their team's run (the no-show rule
    # takes them out 30 minutes into the race otherwise).
    assert late.status == REGISTERED
    assert late.relay_team_id == db_teams[1].id


async def test_a_member_not_ready_at_the_start_stays_behind_the_spoiler_wall(
    rs_client, rs_session, organizer, players, monkeypatch
):
    teams = [players[0:3], players[3:6]]
    race = await _race(
        rs_session, organizer, teams, [READY] * 5 + [REGISTERED], graph=progress_graph()
    )
    # The open race pages of a runner who starts and of the one not ready.
    room = RaceRoom(race_id=race.id)
    monkeypatch.setitem(manager.rooms, race.id, room)
    pages = {
        user.id: SpectatorConnection(websocket=AsyncMock(), user_id=user.id, role="participant")
        for user in (players[0], players[5])
    }
    for page in pages.values():
        room.spectators[page.connection_id] = page

    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))

    assert resp.status_code == 200
    # Still in the race, as a solo runner who has not connected yet.
    assert pages[players[5].id].participant_status == ParticipantStatus.PLAYING
    assert pages[players[0].id].participant_status == ParticipantStatus.PLAYING


async def test_start_ignores_empty_teams_and_picks_the_first_runner(
    rs_client, rs_session, organizer, players
):
    teams = [players[0:2], players[2:4], players[4:7], []]
    race = await _race(rs_session, organizer, teams, [READY] * 6 + [REGISTERED])
    async with rs_session() as db:
        db_teams = list(
            (
                await db.execute(
                    select(RelayTeam)
                    .where(RelayTeam.race_id == race.id)
                    .order_by(RelayTeam.created_at, RelayTeam.name)
                )
            ).scalars()
        )
        members = list(
            (await db.execute(select(Participant).where(Participant.race_id == race.id))).scalars()
        )
        # Team 1 and Team 3 chose their second member, Team 2 kept its first.
        db_teams[0].first_runner_id = _member(members, players[1]).id
        db_teams[2].first_runner_id = _member(members, players[5]).id
        await db.commit()
    async with rs_client as client:
        resp = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))
    assert resp.status_code == 200
    db_teams, members = await _load(rs_session, race)
    t1, t2, t3, placeholder = db_teams
    assert t1.holder_id == _member(members, players[1]).id
    assert t2.holder_id == _member(members, players[2]).id
    assert t3.holder_id == _member(members, players[5]).id
    assert t1.status == t2.status == READY
    assert placeholder.status == REGISTERED and placeholder.holder_id is None


async def test_reset_gives_back_fresh_teams_and_members(rs_client, rs_session, organizer, players):
    a, b, c, d = players[:4]
    race = await _race(rs_session, organizer, [[a, b], [c, d]], [READY] * 4)
    async with rs_client as client:
        started = await client.post(f"/api/races/{race.id}/start", headers=_auth(organizer))
        assert started.status_code == 200
        db_teams, members = await _load(rs_session, race)
        chosen = _member(members, b)
        async with rs_session() as db:
            for team in (
                await db.execute(select(RelayTeam).where(RelayTeam.race_id == race.id))
            ).scalars():
                team.igt_ms = 90_000
                team.zone_history = [{"node_id": "x"}]
                team.entry_flag_id = 5
                team.character_state = {"k": 1}
                team.first_runner_id = (
                    chosen.id if team.id == db_teams[0].id else team.first_runner_id
                )
            for m in (
                await db.execute(select(Participant).where(Participant.race_id == race.id))
            ).scalars():
                m.relay_zones = 3
                m.relay_validated = True
                m.relay_token = 4242
                m.relay_bound = True
            await db.commit()
        reset = await client.post(f"/api/races/{race.id}/reset", headers=_auth(organizer))
    assert reset.status_code == 200
    db_teams, members = await _load(rs_session, race)
    for team in db_teams:
        assert (
            team.status,
            team.holder_id,
            team.igt_ms,
            team.zone_history,
            team.entry_flag_id,
            team.character_state,
        ) == (REGISTERED, None, 0, None, None, None)
    for m in members:
        assert (m.status, m.relay_zones, m.relay_validated, m.relay_token, m.relay_bound) == (
            REGISTERED,
            0,
            False,
            None,
            False,
        )
    assert db_teams[0].first_runner_id == chosen.id
