"""Integration tests for the `winners` field on GET /api/daily/week."""

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
async def dw_win_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dw_win_session_maker(dw_win_engine):
    return async_sessionmaker(dw_win_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dw_win_client(dw_win_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with dw_win_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_winners_null_for_current_week(dw_win_client):
    """For a week containing today, `winners` is null (not yet decided)."""
    response = await dw_win_client.get("/api/daily/week")
    assert response.status_code == 200
    body = response.json()
    assert body["winners"] is None


@pytest.mark.asyncio
async def test_winners_empty_for_past_week_no_qualified(dw_win_client):
    """For a past week with no qualified runs, `winners` is []."""
    response = await dw_win_client.get("/api/daily/week?date=2024-01-08")
    assert response.status_code == 200
    body = response.json()
    assert body["winners"] == []


@pytest.mark.asyncio
async def test_winners_list_for_past_week_with_finisher(
    dw_win_client, dw_win_session_maker, monkeypatch
):
    """For a past week with qualified runs, `winners` lists the tied users."""
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))

    async with dw_win_session_maker() as db:
        organizer = User(
            twitch_id="sys-w-org",
            twitch_username="sysw",
            twitch_display_name="Sysw",
        )
        alice = User(
            twitch_id="t-alice-w",
            twitch_username="alice_w",
            twitch_display_name="Alice W",
        )
        db.add_all([organizer, alice])
        await db.flush()

        monday = date(2026, 5, 25)
        started = datetime.combine(monday, datetime.min.time(), tzinfo=UTC).replace(hour=8)
        race = Race(
            name="d-w-test",
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
        db.add(
            Participant(
                race_id=race.id,
                user_id=alice.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=1000,
                zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                death_count=0,
            )
        )
        await db.commit()

    response = await dw_win_client.get("/api/daily/week?date=2026-05-26")
    assert response.status_code == 200
    body = response.json()
    assert body["winners"] is not None
    assert len(body["winners"]) == 1
    assert body["winners"][0]["user"]["twitch_username"] == "alice_w"
    assert body["winners"][0]["total_points"] == 50
