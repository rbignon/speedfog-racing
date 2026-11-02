"""Tests for the Daily Seed background creation loop."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base
from speedfog_racing.models import (
    DailySeedSchedule,
    Pool,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services import daily_seed_loop
from speedfog_racing.services.daily_seed_loop import (
    create_daily_seed_if_needed,
    daily_date_for,
    daily_start_at,
)

# Tick time after the canonical 08:00 UTC rotation: the loop should pick the
# 27th regardless of how late in the day it actually fires.
TICK_TIME = datetime(2026, 4, 27, 8, 3, tzinfo=UTC)


@pytest.fixture
async def ds_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def ds_async_session_maker(ds_async_engine):
    return async_sessionmaker(ds_async_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_pool_and_system_user(
    session_maker, *, seeds: int = 3, deathless: bool = False
) -> None:
    """Mirror the production-side bootstrapping: schedule rows, system user,
    and a few AVAILABLE seeds in the standard pool so the loop has something
    to assign."""
    async with session_maker() as db:
        for weekday in range(7):
            db.add(DailySeedSchedule(weekday=weekday, pool_name="standard", deathless=deathless))
        db.add(
            User(
                twitch_id="system:daily",
                twitch_username="speedfog_daily",
                twitch_display_name="Daily Seed",
                api_token=None,
                role=UserRole.SYSTEM,
            )
        )
        for i in range(seeds):
            db.add(
                Seed(
                    seed_number=f"daily-{i}",
                    pool_name="standard",
                    graph_json={"total_layers": 5, "nodes": []},
                    total_layers=5,
                    folder_path=f"/test/daily-{i}",
                    status=SeedStatus.AVAILABLE,
                )
            )
        await db.commit()


def test_daily_date_for_rotates_at_0800_utc() -> None:
    # Strictly before 08:00 UTC -> previous date.
    assert daily_date_for(datetime(2026, 4, 27, 7, 59, tzinfo=UTC)) == date(2026, 4, 26)
    # On or after 08:00 UTC -> current date.
    assert daily_date_for(datetime(2026, 4, 27, 8, 0, tzinfo=UTC)) == date(2026, 4, 27)
    assert daily_date_for(datetime(2026, 4, 27, 23, 59, tzinfo=UTC)) == date(2026, 4, 27)


def test_daily_start_at_anchors_to_0800_utc() -> None:
    assert daily_start_at(date(2026, 4, 27)) == datetime(2026, 4, 27, 8, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_daily_tick_creates_running_daily_at_strict_0800(ds_async_session_maker) -> None:
    await _seed_pool_and_system_user(ds_async_session_maker)
    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None
    assert created.name == "Daily - 2026-04-27 - Standard"
    assert created.daily_date == date(2026, 4, 27)
    assert created.started_at == datetime(2026, 4, 27, 8, 0, tzinfo=UTC)
    assert created.seeds_released_at == created.started_at
    assert created.status == RaceStatus.RUNNING
    assert created.late_join_window_minutes == 1440
    assert created.race_duration_minutes == 1440
    assert created.deathless is False
    assert created.is_public is True
    assert created.open_registration is True
    assert created.seed_id is not None  # a seed was assigned
    assert created.organizer.role == UserRole.SYSTEM


@pytest.mark.asyncio
async def test_daily_tick_is_idempotent(ds_async_session_maker) -> None:
    await _seed_pool_and_system_user(ds_async_session_maker)
    first = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    second = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_daily_tick_applies_schedule_deathless(ds_async_session_maker) -> None:
    await _seed_pool_and_system_user(ds_async_session_maker, deathless=True)
    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None
    assert created.deathless is True


@pytest.mark.asyncio
async def test_daily_tick_skips_when_previous_daily_still_running(ds_async_session_maker) -> None:
    """A previous-day daily that is still RUNNING blocks creation of today's
    daily, since hard-close should have transitioned it first."""
    await _seed_pool_and_system_user(ds_async_session_maker)
    # Insert yesterday's daily without a duration so close_expired_races
    # cannot finalize it on its own.
    async with ds_async_session_maker() as db:
        organizer = (
            await db.execute(select(User).where(User.twitch_id == "system:daily"))
        ).scalar_one()
        db.add(
            Race(
                id=uuid4(),
                name="Daily Seed - 2026-04-26 - Standard",
                organizer_id=organizer.id,
                status=RaceStatus.RUNNING,
                is_public=True,
                open_registration=True,
                daily_date=date(2026, 4, 26),
                started_at=datetime(2026, 4, 26, 8, 0, tzinfo=UTC),
                seeds_released_at=datetime(2026, 4, 26, 8, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is None


@pytest.mark.asyncio
async def test_daily_tick_never_draws_seen_seeds(ds_async_session_maker) -> None:
    """A Daily Seed counts on the boards: it takes an AVAILABLE seed, even
    below the floor where a normal race would take a SEEN one, and no daily is
    created from SEEN seeds alone."""
    await _seed_pool_and_system_user(ds_async_session_maker, seeds=0)
    async with ds_async_session_maker() as db:
        for i in range(5):
            db.add(
                Seed(
                    seed_number=f"seen-{i}",
                    pool_name="standard",
                    graph_json={"total_layers": 5, "nodes": []},
                    total_layers=5,
                    folder_path=f"/test/seen-{i}",
                    status=SeedStatus.SEEN,
                )
            )
        await db.commit()

    assert await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME) is None

    async with ds_async_session_maker() as db:
        db.add(
            Seed(
                seed_number="fresh-0",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": []},
                total_layers=5,
                folder_path="/test/fresh-0",
                status=SeedStatus.AVAILABLE,
            )
        )
        await db.commit()

    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None
    async with ds_async_session_maker() as db:
        seed = await db.get(Seed, created.seed_id)
        assert seed is not None and seed.seed_number == "fresh-0"


@pytest.fixture(autouse=True)
def _forget_seed_shortage_alert(monkeypatch) -> None:
    """Every test starts with no seed shortage alert sent yet, whatever ran before."""
    monkeypatch.setattr(daily_seed_loop, "_shortage_alerted_on", None)


@pytest.fixture
def admin_alerts(monkeypatch) -> dict[str, AsyncMock]:
    """The loop's admin alerts, mocked."""
    alerts = {"unavailable": AsyncMock(), "low": AsyncMock()}
    monkeypatch.setattr(daily_seed_loop, "notify_daily_seed_unavailable", alerts["unavailable"])
    monkeypatch.setattr(daily_seed_loop, "notify_daily_pools_low", alerts["low"])
    return alerts


@pytest.mark.asyncio
async def test_daily_tick_alerts_the_admins_once_a_day_when_no_seed_is_left(
    ds_async_session_maker, admin_alerts
) -> None:
    """No seed to draw: no daily, and one admin alert per rotation day rather
    than one per minute the loop tries again."""
    await _seed_pool_and_system_user(ds_async_session_maker, seeds=0)

    for minute in range(3):
        now = TICK_TIME + timedelta(minutes=minute)
        assert await create_daily_seed_if_needed(ds_async_session_maker, now=now) is None
    next_day = TICK_TIME + timedelta(days=1)
    assert await create_daily_seed_if_needed(ds_async_session_maker, now=next_day) is None

    assert [call.args for call in admin_alerts["unavailable"].await_args_list] == [
        ("Standard", date(2026, 4, 27)),
        ("Standard", date(2026, 4, 28)),
    ]
    admin_alerts["low"].assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_tick_warns_the_admins_about_scheduled_pools_at_their_floor(
    ds_async_session_maker, admin_alerts, monkeypatch
) -> None:
    """Once the day's daily exists, every pool of the weekly schedule with no
    more AVAILABLE seeds than its speedrun floor is reported, the others and
    the pools off the schedule are not."""
    monkeypatch.setattr(settings, "speedrun_default_floor", 3)
    await _seed_pool_and_system_user(ds_async_session_maker, seeds=4)
    async with ds_async_session_maker() as db:
        db.add(Pool(name="sprint", config={"name": "Sprint"}, speedrun_floor=1))
        db.add(Pool(name="boss_rush", config={"name": "Boss Rush"}, speedrun_floor=1))
        db.add(Pool(name="off_schedule", config={"name": "Off Schedule"}))
        for weekday, pool in ((2, "sprint"), (3, "boss_rush")):
            schedule = await db.get(DailySeedSchedule, weekday)
            assert schedule is not None
            schedule.pool_name = pool
        for pool, count in (("sprint", 2), ("boss_rush", 1)):
            for i in range(count):
                db.add(
                    Seed(
                        seed_number=f"{pool}-{i}",
                        pool_name=pool,
                        graph_json={"total_layers": 5, "nodes": []},
                        total_layers=5,
                        folder_path=f"/test/{pool}-{i}",
                        status=SeedStatus.AVAILABLE,
                    )
                )
        await db.commit()

    # 2026-04-27 is a Monday: Standard, whose draw leaves 3 seeds, its floor.
    assert await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME) is not None

    admin_alerts["low"].assert_awaited_once_with([("Boss Rush", 1, 1), ("Standard", 3, 3)])
    admin_alerts["unavailable"].assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failing_pool_check_never_costs_the_daily_announcement(
    ds_async_session_maker, admin_alerts, monkeypatch
) -> None:
    """The daily exists once the pool check runs, so no later tick would
    announce it: a failure there skips the admin alert, not the announcement."""
    await _seed_pool_and_system_user(ds_async_session_maker)
    announce = AsyncMock()
    monkeypatch.setattr(daily_seed_loop, "notify_daily_seed_created", announce)
    monkeypatch.setattr(
        daily_seed_loop, "scheduled_pools_at_floor", AsyncMock(side_effect=RuntimeError("boom"))
    )

    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)

    assert created is not None
    announce.assert_awaited_once()
    admin_alerts["low"].assert_not_awaited()
