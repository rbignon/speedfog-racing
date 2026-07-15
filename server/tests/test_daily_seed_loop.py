"""Tests for the Daily Seed background creation loop."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    DailySeedSchedule,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
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


async def _seed_pool_and_system_user(session_maker, *, seeds: int = 3) -> None:
    """Mirror the production-side bootstrapping: schedule rows, system user,
    and a few AVAILABLE seeds in the standard pool so the loop has something
    to assign."""
    async with session_maker() as db:
        for weekday in range(7):
            db.add(DailySeedSchedule(weekday=weekday, pool_name="standard"))
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
    assert created.exclude_from_elo is True
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
                exclude_from_elo=True,
                started_at=datetime(2026, 4, 26, 8, 0, tzinfo=UTC),
                seeds_released_at=datetime(2026, 4, 26, 8, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is None
