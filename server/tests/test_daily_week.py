"""Tests for GET /api/daily/week."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    DailySeedSchedule,
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
    assert today_cell["starters_count"] == 0
    assert today_cell["podium"] == []

    if past_index is not None:
        past_cell = data["days"][past_index]
        assert past_cell["state"] == "past"
        assert past_cell["starters_count"] == 1
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


@pytest.mark.asyncio
async def test_week_endpoint_populates_my_result_for_authenticated_user(
    dw_test_client, dw_async_session_maker
) -> None:
    today = daily_date_for(datetime.now(UTC))
    week_start = today - timedelta(days=today.weekday())
    if today.weekday() == 0:
        pytest.skip("Need at least one past weekday in the current week")
    past_date = week_start  # Monday of the current week

    async with dw_async_session_maker() as db:
        organizer = _user()
        db.add(organizer)
        await db.flush()

        me = _user(api_token="my-token")
        db.add(me)
        await db.flush()

        other = _user()
        db.add(other)
        await db.flush()

        past_race = _daily_race(organizer=organizer, the_date=past_date, status=RaceStatus.FINISHED)
        db.add(past_race)
        await db.flush()

        started = past_race.started_at
        other_part = Participant(
            id=uuid4(),
            race_id=past_race.id,
            user_id=other.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=2_520_000,
            current_layer=4,
            death_count=1,
            finished_at=started + timedelta(minutes=42),
        )
        me_part = Participant(
            id=uuid4(),
            race_id=past_race.id,
            user_id=me.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=2_700_000,
            current_layer=4,
            death_count=2,
            finished_at=started + timedelta(minutes=45),
        )
        db.add(other_part)
        db.add(me_part)

        await db.commit()

    response = await dw_test_client.get(
        "/api/daily/week", headers={"Authorization": "Bearer my-token"}
    )
    assert response.status_code == 200, response.text
    data = response.json()

    past_cell = data["days"][past_date.weekday()]
    my = past_cell["my_result"]
    assert my is not None
    assert my["status"] == "finished"
    assert my["placement"] == 2
    assert my["total_starters"] == 2
    assert my["igt_ms"] == 2_700_000
    assert my["death_count"] == 2

    # Cells with no participation must not carry my_result.
    other_index = (past_date.weekday() + 1) % 7
    assert data["days"][other_index]["my_result"] is None


@pytest.mark.asyncio
async def test_week_endpoint_starters_count_excludes_no_shows(
    dw_test_client, dw_async_session_maker
) -> None:
    """starters_count counts participants with igt_ms > 0, excluding no-shows.

    A user who registered but never launched the game has igt_ms == 0 and
    must not bloat the denominator next to a placement.
    """
    today = daily_date_for(datetime.now(UTC))
    week_start = today - timedelta(days=today.weekday())
    if today.weekday() == 0:
        pytest.skip("Need at least one past weekday in the current week")
    past_date = week_start

    async with dw_async_session_maker() as db:
        organizer = _user()
        db.add(organizer)
        await db.flush()

        me = _user(api_token="my-token")
        starter = _user()
        no_show = _user()
        for u in (me, starter, no_show):
            db.add(u)
        await db.flush()

        race = _daily_race(organizer=organizer, the_date=past_date, status=RaceStatus.FINISHED)
        db.add(race)
        await db.flush()

        # Me: finished.
        db.add(
            Participant(
                id=uuid4(),
                race_id=race.id,
                user_id=me.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=2_700_000,
                current_layer=4,
                death_count=0,
                finished_at=race.started_at + timedelta(minutes=45),
            )
        )
        # Real abandon: started running, quit mid-race.
        db.add(
            Participant(
                id=uuid4(),
                race_id=race.id,
                user_id=starter.id,
                status=ParticipantStatus.ABANDONED,
                igt_ms=900_000,
                current_layer=2,
                death_count=3,
            )
        )
        # No-show: registered but never launched.
        db.add(
            Participant(
                id=uuid4(),
                race_id=race.id,
                user_id=no_show.id,
                status=ParticipantStatus.ABANDONED,
                igt_ms=0,
                current_layer=0,
                death_count=0,
            )
        )

        await db.commit()

    response = await dw_test_client.get(
        "/api/daily/week", headers={"Authorization": "Bearer my-token"}
    )
    assert response.status_code == 200, response.text
    data = response.json()

    past_cell = data["days"][past_date.weekday()]
    assert past_cell["starters_count"] == 2
    assert past_cell["participants_count"] == 3
    assert past_cell["my_result"]["total_starters"] == 2


@pytest.mark.asyncio
async def test_week_endpoint_today_pending_when_loop_has_not_run(
    dw_test_client, dw_async_session_maker
) -> None:
    """When no Race row exists for today (loop has not fired yet).

    The cell must still render with state='today', race_id=None, empty podium,
    and starters_count=0. Pool information comes from the schedule row.
    """
    today = daily_date_for(datetime.now(UTC))

    async with dw_async_session_maker() as db:
        # No races, no setup needed. Just commit an empty session.
        await db.commit()

    response = await dw_test_client.get("/api/daily/week")
    assert response.status_code == 200, response.text
    data = response.json()

    today_cell = data["days"][today.weekday()]
    assert today_cell["state"] == "today"
    assert today_cell["race_id"] is None
    assert today_cell["podium"] == []
    assert today_cell["starters_count"] == 0


@pytest.mark.asyncio
async def test_week_endpoint_handles_missing_schedule_row(
    dw_test_client, dw_async_session_maker
) -> None:
    """Schedule rows that exist are reflected; missing rows return null pool.

    When a schedule row exists for a weekday, pool_name and pool_display_name
    must reflect that row's pool. When missing, both must be None (not crash).
    """
    today = daily_date_for(datetime.now(UTC))

    # Find two distinct future weekdays in the current week.
    if today.weekday() >= 5:
        pytest.skip("Need at least two future weekdays in the current week")

    seeded_weekday = today.weekday() + 1
    missing_weekday = today.weekday() + 2

    async with dw_async_session_maker() as db:
        # The "standard" Pool is auto-seeded by conftest's after_create listener.
        # Just add a schedule row pointing at it for seeded_weekday.
        schedule = DailySeedSchedule(weekday=seeded_weekday, pool_name="standard")
        db.add(schedule)
        # missing_weekday: do NOT add a row.

        await db.commit()

    response = await dw_test_client.get("/api/daily/week")
    assert response.status_code == 200, response.text
    data = response.json()

    # Seeded weekday should have pool information.
    seeded_cell = data["days"][seeded_weekday]
    assert seeded_cell["state"] == "future"
    assert seeded_cell["pool_name"] == "standard"
    assert seeded_cell["pool_display_name"] == "Standard"

    # Missing weekday should have null pool fields.
    missing_cell = data["days"][missing_weekday]
    assert missing_cell["state"] == "future"
    assert missing_cell["pool_name"] is None
    assert missing_cell["pool_display_name"] is None


@pytest.mark.asyncio
async def test_week_endpoint_accepts_date_param_anchors_on_past_week(
    dw_test_client, dw_async_session_maker
) -> None:
    today = daily_date_for(datetime.now(UTC))
    # Anchor 10 days in the past so the resulting week_start is strictly
    # before this week's Monday (the today cell stays the real current day).
    anchor = today - timedelta(days=10)
    expected_week_start = anchor - timedelta(days=anchor.weekday())

    async with dw_async_session_maker() as db:
        organizer = _user()
        db.add(organizer)
        await db.flush()

        anchor_race = _daily_race(organizer=organizer, the_date=anchor, status=RaceStatus.FINISHED)
        db.add(anchor_race)
        await db.commit()

    response = await dw_test_client.get(f"/api/daily/week?date={anchor.isoformat()}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["week_start"] == expected_week_start.isoformat()
    # `today` in the response always reflects the real current rotation date.
    assert data["today"] == today.isoformat()
    assert len(data["days"]) == 7
    assert [d["weekday"] for d in data["days"]] == [0, 1, 2, 3, 4, 5, 6]

    anchor_cell = data["days"][anchor.weekday()]
    assert anchor_cell["date"] == anchor.isoformat()
    assert anchor_cell["state"] == "past"
    assert anchor_cell["race_id"] is not None
    # No cell in this past week is "today" since today is in a later week.
    assert all(d["state"] != "today" for d in data["days"])


@pytest.mark.asyncio
async def test_week_endpoint_date_param_for_current_rotation_returns_current_week(
    dw_test_client, dw_async_session_maker
) -> None:
    today = daily_date_for(datetime.now(UTC))
    week_start = today - timedelta(days=today.weekday())

    async with dw_async_session_maker() as db:
        organizer = _user()
        db.add(organizer)
        await db.flush()
        db.add(_daily_race(organizer=organizer, the_date=today))
        await db.commit()

    response = await dw_test_client.get(f"/api/daily/week?date={today.isoformat()}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["week_start"] == week_start.isoformat()
    assert data["today"] == today.isoformat()
    assert data["days"][today.weekday()]["state"] == "today"


@pytest.mark.asyncio
async def test_week_endpoint_rejects_malformed_date(dw_test_client) -> None:
    response = await dw_test_client.get("/api/daily/week?date=not-a-date")
    assert response.status_code == 422
