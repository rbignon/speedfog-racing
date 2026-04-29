"""Tests for GET /api/daily/week."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.services.daily_seed_loop import daily_date_for


@pytest.fixture
async def dw_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dw_async_session_maker(dw_async_engine):
    return async_sessionmaker(dw_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dw_test_client(dw_async_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with dw_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


def _user(**overrides) -> User:
    defaults = dict(
        id=uuid4(),
        twitch_id=f"u-{uuid4().hex[:8]}",
        twitch_username=f"user-{uuid4().hex[:6]}",
        twitch_display_name="User",
        twitch_avatar_url=None,
        api_token=f"tok-{uuid4().hex[:8]}",
        role=UserRole.USER,
    )
    defaults.update(overrides)
    return User(**defaults)


def _daily_race(*, organizer: User, the_date, status: RaceStatus = RaceStatus.RUNNING, **overrides):
    started = datetime(the_date.year, the_date.month, the_date.day, 8, 0, tzinfo=UTC)
    defaults = dict(
        id=uuid4(),
        name=f"Daily Seed - {the_date}",
        organizer_id=organizer.id,
        status=status,
        is_public=True,
        open_registration=True,
        private_dag=False,
        daily_date=the_date,
        exclude_from_elo=True,
        started_at=started,
        seeds_released_at=started,
        late_join_window_minutes=1440,
        race_duration_minutes=1440,
        created_at=started - timedelta(minutes=30),
    )
    defaults.update(overrides)
    return Race(**defaults)


@pytest.mark.asyncio
async def test_week_endpoint_returns_seven_days(dw_test_client, dw_async_session_maker) -> None:
    today = daily_date_for(datetime.now(UTC))
    week_start = today - timedelta(days=today.weekday())

    # Pick a past day (Monday of the current week, unless today is Monday).
    past_index = 0 if today.weekday() != 0 else None  # skip if today == Monday

    async with dw_async_session_maker() as db:
        organizer = _user()
        db.add(organizer)
        await db.flush()

        if past_index is not None:
            past_date = week_start + timedelta(days=past_index)
            past_race = _daily_race(
                organizer=organizer, the_date=past_date, status=RaceStatus.FINISHED
            )
            db.add(past_race)
            await db.flush()

            finisher = _user()
            db.add(finisher)
            await db.flush()

            finisher_part = Participant(
                id=uuid4(),
                race_id=past_race.id,
                user_id=finisher.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=2_520_000,
                current_layer=4,
                death_count=1,
                finished_at=past_race.started_at + timedelta(minutes=42),
            )
            db.add(finisher_part)

        today_race = _daily_race(organizer=organizer, the_date=today)
        db.add(today_race)

        await db.commit()

    response = await dw_test_client.get("/api/daily/week")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["today"] == today.isoformat()
    assert data["week_start"] == week_start.isoformat()
    assert len(data["days"]) == 7
    assert [d["weekday"] for d in data["days"]] == [0, 1, 2, 3, 4, 5, 6]

    today_cell = data["days"][today.weekday()]
    assert today_cell["state"] == "today"
    assert today_cell["race_id"] is not None
    assert today_cell["finishers_count"] == 0
    assert today_cell["podium"] == []

    if past_index is not None:
        past_cell = data["days"][past_index]
        assert past_cell["state"] == "past"
        assert past_cell["finishers_count"] == 1
        assert past_cell["podium"][0]["placement"] == 1
        assert past_cell["podium"][0]["igt_ms"] == 2_520_000

    for i in range(today.weekday() + 1, 7):
        assert data["days"][i]["state"] == "future"
        assert data["days"][i]["race_id"] is None

    for i in range(today.weekday()):
        if past_index is not None and i == past_index:
            continue
        assert data["days"][i]["state"] == "missing_past"
        assert data["days"][i]["race_id"] is None
