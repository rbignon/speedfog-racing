"""The relay race option: creation, edits, and what a relay race stays out of."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    User,
    UserRole,
    counts_for_community_stats,
)
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.services.speedrun_service import (
    counts_on_boards_clause,
    race_unranked_code,
    race_unranked_reason,
)
from speedfog_racing.websocket.schemas import build_race_info
from tests.relay_fixtures import make_relay_race, make_relay_seed

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ro_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def ro_session(ro_async_engine):
    return async_sessionmaker(ro_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def ro_client(ro_session):
    async def override_get_db():
        async with ro_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _user(session, name: str, role: UserRole = UserRole.ORGANIZER) -> User:
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


@pytest.fixture
async def organizer(ro_session):
    return await _user(ro_session, "orga")


@pytest.fixture
async def admin(ro_session):
    return await _user(ro_session, "boss", UserRole.ADMIN)


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


def _body(**extra):
    return {"name": "R", "pool_name": "standard", "relay_team_size": 3, **extra}


async def _count_races(session) -> int:
    async with session() as db:
        return (await db.execute(select(func.count(Race.id)))).scalar_one()


@pytest.mark.parametrize(
    "extra",
    [
        {"race_items": True},
        {"deathless": True},
        {"late_join_window_minutes": 30, "race_duration_minutes": 120},
        {"mode": "speedrun"},
        {"mode": "set_seed", "seed": "abc"},
        {"relay_team_size": 1},
        {"relay_team_size": 7},
    ],
)
async def test_create_relay_refuses(ro_client, ro_session, organizer, extra):
    async with ro_session() as db:
        await make_relay_seed(db, suffix="refuse")
        await db.commit()
    async with ro_client as client:
        response = await client.post("/api/races", json=_body(**extra), headers=_auth(organizer))
    assert response.status_code == 422, response.text
    assert await _count_races(ro_session) == 0


async def test_create_relay_puts_a_racing_organizer_in_team_1(ro_client, ro_session, organizer):
    async with ro_session() as db:
        await make_relay_seed(db, suffix="create", total_layers=12)
        await db.commit()
    async with ro_client as client:
        created = await client.post(
            "/api/races", json=_body(organizer_participates=True), headers=_auth(organizer)
        )
        assert created.status_code == 201, created.text
        detail = (await client.get(f"/api/races/{created.json()['id']}")).json()
    team = detail["relay_teams"][0]
    assert [t["name"] for t in detail["relay_teams"]] == ["Team 1"]
    assert team["member_ids"] == [detail["participants"][0]["id"]]
    assert team["first_runner_id"] == detail["participants"][0]["id"]
    assert detail["participants"][0]["relay_team_id"] == team["id"]
    assert (detail["relay_team_size"], detail["relay_cap"]) == (3, 5)
    assert detail["unranked_code"] == "relay"


async def test_create_relay_without_an_organizer_makes_no_team(ro_client, ro_session, organizer):
    async with ro_session() as db:
        await make_relay_seed(db, suffix="noteam")
        await db.commit()
    async with ro_client as client:
        created = await client.post("/api/races", json=_body(), headers=_auth(organizer))
        detail = (await client.get(f"/api/races/{created.json()['id']}")).json()
    assert detail["relay_teams"] == []


async def test_create_relay_without_a_relay_seed_leaves_no_race(ro_client, ro_session, organizer):
    async with ro_client as client:
        response = await client.post("/api/races", json=_body(), headers=_auth(organizer))
    assert response.status_code == 400
    assert "No relay seed available" in response.json()["detail"]
    assert await _count_races(ro_session) == 0


async def test_solo_race_has_no_relay_fields(ro_client, ro_session, organizer):
    async with ro_session() as db:
        # a plain seed, no relay block
        from speedfog_racing.models import Seed

        db.add(
            Seed(
                seed_number="plain",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": []},
                total_layers=5,
                folder_path="/test/plain",
            )
        )
        await db.commit()
    async with ro_client as client:
        created = await client.post(
            "/api/races", json={"name": "Solo", "pool_name": "standard"}, headers=_auth(organizer)
        )
        detail = (await client.get(f"/api/races/{created.json()['id']}")).json()
    assert (detail["relay_team_size"], detail["relay_cap"], detail["relay_teams"]) == (
        None,
        None,
        [],
    )


async def _relay_race(session, organizer, **kw) -> uuid.UUID:
    async with session() as db:
        race = await make_relay_race(db, organizer, teams=[[]])
        for key, value in kw.items():
            setattr(race, key, value)
        await db.commit()
        return race.id


@pytest.mark.parametrize(
    "patch", [{"race_items": True}, {"deathless": True}, {"late_join_window_minutes": 30}]
)
async def test_patch_cannot_turn_on_what_relay_excludes(ro_client, ro_session, organizer, patch):
    race_id = await _relay_race(ro_session, organizer)
    async with ro_client as client:
        response = await client.patch(f"/api/races/{race_id}", json=patch, headers=_auth(organizer))
    assert response.status_code == 400, response.text
    assert "not available on a relay race" in response.json()["detail"]


async def test_patch_can_still_turn_the_excluded_options_off(ro_client, ro_session, organizer):
    race_id = await _relay_race(ro_session, organizer)
    async with ro_client as client:
        response = await client.patch(
            f"/api/races/{race_id}", json={"deathless": False}, headers=_auth(organizer)
        )
    assert response.status_code == 200, response.text


async def test_runners_create_teams_is_a_setup_only_relay_only_toggle(
    ro_client, ro_session, organizer, monkeypatch
):
    from unittest.mock import AsyncMock

    from speedfog_racing.api import races as races_api

    broadcast = AsyncMock()
    monkeypatch.setattr(races_api, "broadcast_race_info_update", broadcast)
    setup = await _relay_race(ro_session, organizer)
    running = await _relay_race(ro_session, organizer, status=RaceStatus.RUNNING)
    async with ro_session() as db:
        from speedfog_racing.models import Seed

        db.add(
            Seed(
                seed_number="plain",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": []},
                total_layers=5,
                folder_path="/test/plain",
            )
        )
        await db.flush()
        seed_id = (
            await db.execute(select(Seed.id).where(Seed.seed_number == "plain"))
        ).scalar_one()
        solo = Race(name="solo", organizer_id=organizer.id, seed_id=seed_id)
        db.add(solo)
        await db.commit()
        solo_id = solo.id

    async with ro_client as client:
        ok = await client.patch(
            f"/api/races/{setup}",
            json={"relay_runners_create_teams": False},
            headers=_auth(organizer),
        )
        assert ok.status_code == 200, ok.text
        assert broadcast.await_count == 1
        late = await client.patch(
            f"/api/races/{running}",
            json={"relay_runners_create_teams": True},
            headers=_auth(organizer),
        )
        assert late.status_code == 400
        not_relay = await client.patch(
            f"/api/races/{solo_id}",
            json={"relay_runners_create_teams": False},
            headers=_auth(organizer),
        )
        assert not_relay.status_code == 400
        assert not_relay.json()["detail"] == "Not a relay race"
    async with ro_session() as db:
        assert (await db.get(Race, setup)).relay_runners_create_teams is False


async def test_build_race_info_carries_the_relay_toggles(ro_session, organizer):
    async with ro_session() as db:
        race = await make_relay_race(db, organizer, team_size=4, teams=[[]])
        race.relay_runners_create_teams = False
        info = build_race_info(race)
    assert (info.relay_team_size, info.relay_runners_create_teams) == (4, False)


async def test_can_join_needs_a_free_slot_when_runners_cannot_create_teams(ro_session, organizer):
    from speedfog_racing.api.helpers import race_response

    async with ro_session() as db:
        full = await _user_db(db, "full")
        race = await make_relay_race(db, organizer, team_size=2, teams=[[full, organizer]])
        race.open_registration = True
        race.max_participants = 10
        race.relay_runners_create_teams = False
        await db.commit()
        race = await _reload(db, race.id)
        assert race_response(race).can_join is False
        race.relay_runners_create_teams = True
        assert race_response(race).can_join is True
        race.relay_runners_create_teams = False
        db.add(RelayTeam(race_id=race.id, name="Team 2", color_index=1, placeholder=True))
        await db.commit()
        race = await _reload(db, race.id)
        assert race_response(race).can_join is True


async def _user_db(db, name: str) -> User:
    user = User(twitch_id=f"id_{name}", twitch_username=name, api_token=f"t_{name}")
    db.add(user)
    await db.flush()
    return user


async def _reload(db, race_id):
    from sqlalchemy.orm import selectinload

    from speedfog_racing.models import Seed

    result = await db.execute(
        select(Race)
        .where(Race.id == race_id)
        .options(
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.seed).selectinload(Seed.pool),
            selectinload(Race.organizer),
            selectinload(Race.casters),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def test_relay_race_cannot_join_an_event(ro_client, ro_session, organizer, admin):
    race_id = await _relay_race(ro_session, organizer)
    async with ro_client as client:
        response = await client.post(
            f"/api/admin/races/{race_id}/event",
            json={"event_id": str(uuid.uuid4()), "slot": "semi_a:1"},
            headers=_auth(admin),
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "A relay race cannot join an event"


async def _finished_relay_race(db, organizer, member) -> Race:
    race = await make_relay_race(db, organizer, teams=[[member]])
    race.is_public = True
    race.status = RaceStatus.FINISHED
    for p in race.participants:
        p.status = ParticipantStatus.FINISHED
        p.igt_ms = 60_000
    await db.commit()
    return race


async def test_relay_race_counts_on_no_board_and_in_no_community_stat(ro_session, organizer):
    async with ro_session() as db:
        member = await _user_db(db, "m1")
        race = await _finished_relay_race(db, organizer, member)
        assert race_unranked_code(race) == "relay"
        assert race_unranked_reason(race)
        for clause in (counts_on_boards_clause(), counts_for_community_stats()):
            found = await db.execute(select(Race.id).where(Race.id == race.id, clause))
            assert found.first() is None


async def test_relay_finish_grants_no_reward(ro_session, organizer):
    async with ro_session() as db:
        member, other = await _user_db(db, "m1"), await _user_db(db, "m2")
        race = await _finished_relay_race(db, organizer, member)
        # a second runner on another team, so the race would otherwise be a duel
        team = RelayTeam(race_id=race.id, name="Team 2", color_index=1)
        db.add(team)
        await db.flush()
        db.add(
            Participant(
                race_id=race.id,
                user_id=other.id,
                relay_team_id=team.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=90_000,
            )
        )
        await db.commit()
        race = await _reload(db, race.id)
        svc = RewardsService(db)
        await svc.grant_race_win_rewards(race)
        await svc.check_finish_reward_milestones(member.id)
        await db.commit()
        from speedfog_racing.models import BadgeGrant, PhantomSkinUnlock

        assert (await db.execute(select(PhantomSkinUnlock))).first() is None
        assert (await db.execute(select(BadgeGrant))).first() is None
