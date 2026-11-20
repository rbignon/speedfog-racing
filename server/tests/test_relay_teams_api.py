"""Relay team routes, and the rule that nobody is registered on a relay race without a team."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing import api
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Invite,
    Participant,
    Race,
    RaceStatus,
    RelayTeam,
    Seed,
    User,
    UserRole,
)
from tests.relay_fixtures import make_relay_race

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rt_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def rt_session(rt_engine):
    return async_sessionmaker(rt_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def rt_client(rt_session):
    async def override_get_db():
        async with rt_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()


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


@pytest.fixture
async def organizer(rt_session):
    return await _user(rt_session, "orga", UserRole.ORGANIZER)


@pytest.fixture
async def alice(rt_session):
    return await _user(rt_session, "alice")


@pytest.fixture
async def bob(rt_session):
    return await _user(rt_session, "bob")


@pytest.fixture
async def carol(rt_session):
    return await _user(rt_session, "carol")


@pytest.fixture
async def dave(rt_session):
    return await _user(rt_session, "dave")


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


async def _race(session, organizer, teams, *, team_size=3, **fields) -> Race:
    """A relay race in SETUP, open to self-registration, with the given teams."""
    async with session() as db:
        race = await make_relay_race(db, organizer, team_size=team_size, teams=teams)
        race.open_registration = True
        for key, value in fields.items():
            setattr(race, key, value)
        await db.commit()
        return race


async def _teams(session, race: Race) -> list[RelayTeam]:
    async with session() as db:
        result = await db.execute(
            select(RelayTeam).where(RelayTeam.race_id == race.id).order_by(RelayTeam.created_at)
        )
        return list(result.scalars())


async def _participants(session, race: Race) -> list[Participant]:
    async with session() as db:
        result = await db.execute(select(Participant).where(Participant.race_id == race.id))
        return list(result.scalars())


def _team_names(detail: dict) -> list[str]:
    return [t["name"] for t in detail["relay_teams"]]


async def _member_of(session, race: Race, user: User) -> Participant:
    async with session() as db:
        result = await db.execute(
            select(Participant).where(
                Participant.race_id == race.id, Participant.user_id == user.id
            )
        )
        return result.scalar_one()


async def test_join_a_relay_race_needs_a_team(rt_client, rt_session, organizer, alice, bob):
    race = await _race(rt_session, organizer, [[bob]])
    team = (await _teams(rt_session, race))[0]
    async with rt_client as client:
        bare = await client.post(f"/api/races/{race.id}/join", headers=_auth(alice))
        assert bare.status_code == 400
        assert bare.json()["detail"] == "Pick a team to join a relay race"
        assert await _participants(rt_session, race) != []
        assert len(await _participants(rt_session, race)) == 1
        ok = await client.post(
            f"/api/races/{race.id}/join",
            json={"relay_team_id": str(team.id)},
            headers=_auth(alice),
        )
    assert ok.status_code == 200
    assert ok.json()["relay_team_id"] == str(team.id)


async def test_join_route_moves_a_runner_and_deletes_the_team_they_emptied(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob], [alice]])
    team1, team2 = await _teams(rt_session, race)
    async with rt_client as client:
        response = await client.post(
            f"/api/races/{race.id}/relay-teams/{team1.id}/join", headers=_auth(alice)
        )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert _team_names(detail) == ["Team 1"]
    assert len(detail["participants"]) == 2
    assert len(detail["relay_teams"][0]["member_ids"]) == 2


async def test_placeholder_survives_being_emptied_and_only_an_empty_team_is_deleted(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob], [alice], []])
    team1, team2, placeholder = await _teams(rt_session, race)
    async with rt_client as client:
        joined = await client.post(
            f"/api/races/{race.id}/relay-teams/{placeholder.id}/join", headers=_auth(alice)
        )
        assert joined.status_code == 200
        refused = await client.delete(
            f"/api/races/{race.id}/relay-teams/{placeholder.id}", headers=_auth(organizer)
        )
        assert refused.status_code == 409
        moved = await client.post(
            f"/api/races/{race.id}/relay-teams/{team1.id}/join", headers=_auth(alice)
        )
        assert str(placeholder.id) in [t["id"] for t in moved.json()["relay_teams"]]
        stranger = await client.delete(
            f"/api/races/{race.id}/relay-teams/{placeholder.id}", headers=_auth(alice)
        )
        assert stranger.status_code == 403
        deleted = await client.delete(
            f"/api/races/{race.id}/relay-teams/{placeholder.id}", headers=_auth(organizer)
        )
    assert deleted.status_code == 204
    assert len(await _teams(rt_session, race)) == 1


async def test_full_team_refuses_join_move_and_organizer_move(
    rt_client, rt_session, organizer, alice, bob, carol, dave
):
    race = await _race(rt_session, organizer, [[alice, bob], [carol]], team_size=2)
    team1, team2 = await _teams(rt_session, race)
    carol_member = await _member_of(rt_session, race, carol)
    async with rt_client as client:
        join = await client.post(
            f"/api/races/{race.id}/relay-teams/{team1.id}/join", headers=_auth(carol)
        )
        assert join.status_code == 409
        assert join.json()["detail"] == "Team is full"
        fresh = await client.post(
            f"/api/races/{race.id}/join",
            json={"relay_team_id": str(team1.id)},
            headers=_auth(dave),
        )
        assert fresh.status_code == 409
        moved = await client.post(
            f"/api/races/{race.id}/participants/{carol_member.id}/relay-team",
            json={"team_id": str(team1.id)},
            headers=_auth(organizer),
        )
        assert moved.status_code == 409
        same = await client.post(
            f"/api/races/{race.id}/relay-teams/{team2.id}/join", headers=_auth(carol)
        )
        assert same.status_code == 409
        by_stranger = await client.post(
            f"/api/races/{race.id}/participants/{carol_member.id}/relay-team",
            json={"team_id": str(team2.id)},
            headers=_auth(alice),
        )
    assert by_stranger.status_code == 403


async def test_organizer_moves_a_runner(rt_client, rt_session, organizer, alice, bob, carol):
    race = await _race(rt_session, organizer, [[alice], [bob, carol]])
    team1, team2 = await _teams(rt_session, race)
    bob_member = await _member_of(rt_session, race, bob)
    async with rt_client as client:
        moved = await client.post(
            f"/api/races/{race.id}/participants/{bob_member.id}/relay-team",
            json={"team_id": str(team1.id)},
            headers=_auth(organizer),
        )
    assert moved.status_code == 200, moved.text
    by_team = {t["id"]: t["member_ids"] for t in moved.json()["relay_teams"]}
    assert str(bob_member.id) in by_team[str(team1.id)]
    assert str(bob_member.id) not in by_team[str(team2.id)]


async def test_runners_cannot_create_teams_when_turned_off(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob]], relay_runners_create_teams=False)
    async with rt_client as client:
        runner = await client.post(
            f"/api/races/{race.id}/relay-teams", json={}, headers=_auth(alice)
        )
        assert runner.status_code == 403
        join = await client.post(
            f"/api/races/{race.id}/join", json={"create_team": True}, headers=_auth(alice)
        )
        assert join.status_code == 403
        assert len(await _participants(rt_session, race)) == 1
        boss = await client.post(
            f"/api/races/{race.id}/relay-teams", json={}, headers=_auth(organizer)
        )
    assert boss.status_code == 200
    new_team = boss.json()["relay_teams"][-1]
    assert new_team["placeholder"] is True and new_team["member_ids"] == []


async def test_runner_created_team_holds_its_creator_and_joins_them_to_the_race(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob]])
    async with rt_client as client:
        response = await client.post(
            f"/api/races/{race.id}/relay-teams", json={"name": None}, headers=_auth(alice)
        )
    assert response.status_code == 200, response.text
    detail = response.json()
    team = detail["relay_teams"][-1]
    assert team["name"] == "Team 2" and len(team["member_ids"]) == 1
    assert team["placeholder"] is False
    assert team["color_index"] == 1
    assert team["first_runner_id"] == team["member_ids"][0]
    assert len(detail["participants"]) == 2


async def test_open_registration_maximum_counts_runners_not_teams(
    rt_client, rt_session, organizer, alice, bob, carol
):
    race = await _race(rt_session, organizer, [[alice, bob]], max_participants=2)
    async with rt_client as client:
        response = await client.post(
            f"/api/races/{race.id}/relay-teams", json={}, headers=_auth(carol)
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "Race is full"
    assert len(await _teams(rt_session, race)) == 1


async def test_leaving_clears_first_runner_and_deletes_a_runner_made_team(
    rt_client, rt_session, organizer, alice, bob, carol
):
    race = await _race(rt_session, organizer, [[alice, bob], [carol]])
    team1, team2 = await _teams(rt_session, race)
    async with rt_client as client:
        left = await client.post(f"/api/races/{race.id}/leave", headers=_auth(alice))
        assert left.status_code == 204
        detail = (await client.get(f"/api/races/{race.id}", headers=_auth(bob))).json()
        by_id = {t["id"]: t for t in detail["relay_teams"]}
        assert by_id[str(team1.id)]["first_runner_id"] is None
        gone = await client.post(f"/api/races/{race.id}/leave", headers=_auth(carol))
        assert gone.status_code == 204
        detail = (await client.get(f"/api/races/{race.id}", headers=_auth(bob))).json()
    assert str(team2.id) not in [t["id"] for t in detail["relay_teams"]]


async def test_organizer_removing_a_runner_vacates_the_team(
    rt_client, rt_session, organizer, alice
):
    race = await _race(rt_session, organizer, [[alice], []])
    member = await _member_of(rt_session, race, alice)
    async with rt_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/participants/{member.id}", headers=_auth(organizer)
        )
        assert response.status_code == 204
        detail = (await client.get(f"/api/races/{race.id}", headers=_auth(organizer))).json()
    assert [t["placeholder"] for t in detail["relay_teams"]] == [True]


async def test_rename_and_first_runner_rights(rt_client, rt_session, organizer, alice, bob, carol):
    race = await _race(rt_session, organizer, [[alice, bob], [carol]])
    team1, team2 = await _teams(rt_session, race)
    bob_member = await _member_of(rt_session, race, bob)
    carol_member = await _member_of(rt_session, race, carol)
    url = f"/api/races/{race.id}/relay-teams/{team1.id}"
    async with rt_client as client:
        renamed = await client.patch(url, json={"name": " Red Team "}, headers=_auth(alice))
        assert renamed.status_code == 200
        assert renamed.json()["relay_teams"][0]["name"] == "Red Team"
        refused = await client.patch(url, json={"name": "x"}, headers=_auth(carol))
        assert refused.status_code == 403
        outsider = await client.patch(
            url, json={"first_runner_id": str(carol_member.id)}, headers=_auth(organizer)
        )
        assert outsider.status_code == 400
        first = await client.patch(
            url, json={"first_runner_id": str(bob_member.id)}, headers=_auth(organizer)
        )
        assert first.status_code == 200
        assert first.json()["relay_teams"][0]["first_runner_id"] == str(bob_member.id)
        blank = await client.patch(url, json={"name": "   "}, headers=_auth(alice))
        assert blank.status_code == 422
        long = await client.patch(url, json={"name": "x" * 41}, headers=_auth(alice))
    assert long.status_code == 422


async def test_unknown_team_and_team_of_another_race_are_404(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob]])
    other = await _race(rt_session, organizer, [[alice], []], team_size=2)
    foreign = (await _teams(rt_session, other))[1]
    async with rt_client as client:
        response = await client.post(
            f"/api/races/{race.id}/relay-teams/{foreign.id}/join", headers=_auth(alice)
        )
        assert response.status_code == 404
        joined = await client.post(
            f"/api/races/{race.id}/join",
            json={"relay_team_id": str(foreign.id)},
            headers=_auth(alice),
        )
    assert joined.status_code == 404
    assert len(await _participants(rt_session, race)) == 1


async def test_the_other_creation_sites_refuse_a_relay_race_without_a_team(
    rt_client, rt_session, organizer, alice, bob, carol
):
    race = await _race(rt_session, organizer, [[bob]])
    team = (await _teams(rt_session, race))[0]
    async with rt_session() as db:
        db.add(Invite(race_id=race.id, twitch_username="alice", token="tok_alice"))
        db.add(Invite(race_id=race.id, twitch_username="carol", token="tok_carol"))
        await db.commit()
    base = f"/api/races/{race.id}/participants"
    async with rt_client as client:
        info = (await client.get("/api/invite/tok_alice")).json()
        assert info["race_id"] == str(race.id)
        assert info["relay_team_size"] == 3
        assert [t["name"] for t in info["relay_teams"]] == ["Team 1"]

        bare = await client.post("/api/invite/tok_alice/accept", headers=_auth(alice))
        assert bare.status_code == 400
        created = await client.post(
            "/api/invite/tok_alice/accept", json={"create_team": True}, headers=_auth(alice)
        )
        assert created.status_code == 200
        assert created.json()["participant"]["relay_team_id"] is not None
        picked = await client.post(
            "/api/invite/tok_carol/accept",
            json={"relay_team_id": str(team.id)},
            headers=_auth(carol),
        )
        assert picked.status_code == 200
        assert picked.json()["participant"]["relay_team_id"] == str(team.id)

        dave = await _user(rt_session, "dave")
        assert (
            await client.post(base, json={"twitch_username": "dave"}, headers=_auth(organizer))
        ).status_code == 400
        added = await client.post(
            base,
            json={"twitch_username": "dave", "relay_team_id": str(team.id)},
            headers=_auth(organizer),
        )
        assert added.status_code == 200
        assert added.json()["participant"]["relay_team_id"] == str(team.id)
        assert dave.id is not None
        invited = await client.post(
            base, json={"twitch_username": "unknown_twitch_name"}, headers=_auth(organizer)
        )
    assert invited.json()["invite"] is not None


async def test_team_routes_are_refused_outside_setup_and_on_a_solo_race(
    rt_client, rt_session, organizer, alice, bob
):
    race = await _race(rt_session, organizer, [[bob]], status=RaceStatus.RUNNING)
    team = (await _teams(rt_session, race))[0]
    async with rt_session() as db:
        solo_seed = Seed(
            seed_number="solo_rt",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/solo_rt",
        )
        db.add(solo_seed)
        await db.flush()
        solo = Race(name="Solo", organizer_id=organizer.id, seed_id=solo_seed.id)
        db.add(solo)
        await db.commit()
    async with rt_client as client:
        running = await client.post(
            f"/api/races/{race.id}/relay-teams/{team.id}/join", headers=_auth(alice)
        )
        assert running.status_code == 400
        assert running.json()["detail"] == "Teams can only be changed in SETUP status"
        on_solo = await client.post(
            f"/api/races/{solo.id}/relay-teams", json={}, headers=_auth(organizer)
        )
    assert on_solo.status_code == 400
    assert on_solo.json()["detail"] == "Not a relay race"


async def test_team_change_broadcasts_race_state(
    rt_client, rt_session, organizer, alice, bob, monkeypatch
):
    race = await _race(rt_session, organizer, [[bob]])
    team = (await _teams(rt_session, race))[0]
    calls: list[str] = []

    async def leaderboard(*args, **kwargs):
        calls.append("leaderboard")

    async def state(*args, **kwargs):
        calls.append("state")

    from speedfog_racing.websocket.race.manager import manager

    monkeypatch.setattr(manager, "broadcast_leaderboard", leaderboard)
    monkeypatch.setattr(api.relay_teams, "broadcast_race_state_update", state)
    async with rt_client as client:
        response = await client.post(
            f"/api/races/{race.id}/relay-teams/{team.id}/join", headers=_auth(alice)
        )
    assert response.status_code == 200
    assert calls == ["leaderboard", "state"]
