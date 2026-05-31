"""Integration tests for GET /api/daily/week/leaderboard."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
)


@pytest.fixture
async def wl_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def wl_async_session_maker(wl_async_engine):
    return async_sessionmaker(wl_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def wl_client(wl_async_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with wl_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_returns_empty_for_future_week(wl_client):
    response = await wl_client.get("/api/daily/week/leaderboard?date=2099-01-04")
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["dailies_total"] == 0


@pytest.mark.asyncio
async def test_returns_aggregated_ranking_for_past_week(wl_client, wl_async_session_maker):
    async with wl_async_session_maker() as db:
        organizer = User(
            twitch_id="sys-wl-org",
            twitch_username="syswl",
            twitch_display_name="Syswl",
        )
        alice = User(
            twitch_id="t-alicewl",
            twitch_username="alicewl",
            twitch_display_name="Alicewl",
        )
        bob = User(
            twitch_id="t-bobwl",
            twitch_username="bobwl",
            twitch_display_name="Bobwl",
        )
        db.add_all([organizer, alice, bob])
        await db.flush()

        monday = date(2026, 5, 25)
        started = datetime.combine(monday, datetime.min.time(), tzinfo=UTC).replace(hour=8)
        race = Race(
            name="dwl",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            daily_date=monday,
            exclude_from_elo=True,
            is_public=True,
            open_registration=True,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
            started_at=started,
            seeds_released_at=started,
        )
        db.add(race)
        await db.flush()
        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=alice.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1000,
                    zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                    death_count=2,
                ),
                Participant(
                    race_id=race.id,
                    user_id=bob.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2000,
                    zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                    death_count=5,
                ),
            ]
        )
        await db.commit()

    response = await wl_client.get("/api/daily/week/leaderboard?date=2026-05-26")
    assert response.status_code == 200
    body = response.json()
    assert body["week_starting"] == "2026-05-25"
    assert body["week_ending"] == "2026-05-31"
    assert body["dailies_total"] == 1
    assert [e["user"]["twitch_username"] for e in body["entries"]] == ["alicewl", "bobwl"]
    assert body["entries"][0]["total_points"] == 100
    assert body["entries"][1]["total_points"] == 50
    assert body["entries"][0]["rank"] == 1
    assert body["entries"][1]["rank"] == 2
    assert body["entries"][0]["dailies_played"] == 1
    assert body["entries"][0]["total_deaths"] == 2


@pytest.mark.asyncio
async def test_invalid_date_returns_422(wl_client):
    response = await wl_client.get("/api/daily/week/leaderboard?date=not-a-date")
    assert response.status_code == 422
