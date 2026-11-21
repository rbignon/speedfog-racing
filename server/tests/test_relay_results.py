"""A relay team's result outside the live page: one entry per team, ranked by the team."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import compute_race_stats, race_response
from speedfog_racing.database import Base, get_db
from speedfog_racing.discord import build_podium
from speedfog_racing.main import app
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus, User
from tests.relay_fixtures import make_relay_race

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(maker):
    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _users(db, n: int) -> list[User]:
    users = [
        User(
            twitch_id=f"res{i}",
            twitch_username=f"res{i}",
            twitch_display_name=f"Res {i}",
            api_token=f"rest{i}",
        )
        for i in range(n)
    ]
    db.add_all(users)
    await db.flush()
    return users


@pytest.fixture
async def finished(maker):
    """Team 1 (3 members, one left early) finishes second at 700 s, Team 2 (2 members)
    first at 600 s, Team 3 out after 90 s, Team 4 out without ever starting. Team 1 is
    created first with the worse result, so creation order cannot pass for ranking;
    its leaver's own row (200 s) differs from the team's."""
    async with maker() as db:
        users = await _users(db, 10)
        race = await make_relay_race(
            db,
            users[0],
            teams=[users[0:3], users[3:5], users[5:8], users[8:10]],
        )
        finish = datetime.now(UTC)
        teams = {t.name: t for t in race.relay_teams}
        spec = {"Team 1": (700_000, 1), "Team 2": (600_000, 0)}
        for name, (igt, off) in spec.items():
            team = teams[name]
            team.status = ParticipantStatus.FINISHED
            team.igt_ms = igt
            team.finished_at = finish + timedelta(seconds=off)
        teams["Team 3"].status = ParticipantStatus.ABANDONED
        teams["Team 3"].igt_ms = 90_000
        teams["Team 4"].status = ParticipantStatus.ABANDONED
        for p in race.participants:
            team = next(t for t in race.relay_teams if t.id == p.relay_team_id)
            p.status = team.status
            p.igt_ms = team.igt_ms
            p.finished_at = team.finished_at
        # A member of Team 1 who left early keeps a snapshot, not the result.
        leaver = next(p for p in race.participants if p.user_id == users[2].id)
        leaver.status = ParticipantStatus.ABANDONED
        leaver.igt_ms = 200_000
        leaver.current_layer = 2
        leaver.finished_at = None
        race.status = RaceStatus.FINISHED
        await db.commit()
        by_team = {
            name: [p for p in race.participants if p.relay_team_id == t.id]
            for name, t in teams.items()
        }
        return race.id, users, by_team


async def test_teammates_share_their_team_placement(maker, finished):
    race_id, _, by_team = finished
    async with maker() as db:
        _, starters, placements = await compute_race_stats(db, [race_id])
    assert {placements[(race_id, m.id)] for m in by_team["Team 2"]} == {1}
    team1_finishers = [m for m in by_team["Team 1"] if m.status == ParticipantStatus.FINISHED]
    assert len(team1_finishers) == 2
    assert {placements[(race_id, m.id)] for m in team1_finishers} == {2}
    assert not any((race_id, m.id) in placements for m in by_team["Team 3"])
    # Teams that played: Team 4 never started (every row at 0) and counts for nothing.
    assert starters[race_id] == 3


async def test_podium_names_teams_once(maker, finished):
    race_id, _, _ = finished
    async with maker() as db:
        race = (
            await db.execute(
                select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
            )
        ).scalar_one()
        # Participants are read for their user only on solo races.
        assert build_podium(race.participants, race.relay_teams) == [
            {"name": "Team 2", "igt": "10:00"},
            {"name": "Team 1", "igt": "11:40"},
        ]


async def test_race_card_previews_rank_by_team(maker, finished):
    race_id, _, _ = finished
    async with maker() as db:
        race = (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.seed),
                )
            )
        ).scalar_one()
        previews = race_response(race).participant_previews
    assert [p.placement for p in previews] == [1, 1, 2, 2, None]


async def _activity_item(client, user, race_id) -> dict:
    resp = await client.get(f"/api/users/{user.twitch_username}/activity")
    return next(i for i in resp.json()["items"] if i.get("race_id") == str(race_id))


async def test_profile_activity_names_the_team(client, finished):
    race_id, users, _ = finished
    item = await _activity_item(client, users[0], race_id)
    assert (item["relay_team_name"], item["placement"]) == ("Team 1", 2)
    assert item["total_starters"] == 3


async def test_early_leaver_keeps_their_own_row_in_a_finished_team(client, finished):
    race_id, users, _ = finished
    item = await _activity_item(client, users[2], race_id)
    assert item["relay_team_name"] == "Team 1"
    assert "placement" not in item
    assert (item["status"], item["igt_ms"]) == ("finished", 200_000)
