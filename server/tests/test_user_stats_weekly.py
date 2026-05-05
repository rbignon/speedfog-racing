"""Tests for compute_weekly_series."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)
from speedfog_racing.services.user_stats_service import compute_weekly_series


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture
async def seed(db):
    # conftest.py auto-seeds the default "standard" Pool row when the schema
    # is created, so the FK on pool_name is already satisfied.
    s = Seed(
        seed_number="weekly_test_seed",
        pool_name="standard",
        graph_json={"nodes": [], "edges": [], "layers": []},
        total_layers=1,
        folder_path="/fake/seed/path",
        status=SeedStatus.CONSUMED,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.fixture
async def player(db):
    user = User(
        twitch_id="42",
        twitch_username="player",
        twitch_display_name="Player",
        api_token="player_token",
        role=UserRole.USER,
    )
    user.created_at = _utc(2026, 1, 5)  # Monday
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_empty_user_returns_one_zero_week(db, player):
    series = await compute_weekly_series(db, player, now=_utc(2026, 1, 5))

    assert series.weeks_count == 1
    assert series.races == [0]
    assert series.daily == [0]
    assert series.solo == [0]
    assert series.organized == [0]
    assert series.capped is False


async def test_caps_at_52_weeks_for_old_account(db):
    user = User(
        twitch_id="43",
        twitch_username="vet",
        twitch_display_name="Vet",
        api_token="vet_token",
        role=UserRole.USER,
    )
    user.created_at = _utc(2024, 1, 1)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    series = await compute_weekly_series(db, user, now=_utc(2026, 5, 4))

    assert series.weeks_count == 52
    assert len(series.races) == 52
    assert series.capped is True


async def test_solo_counts_a_finished_session_in_the_right_week(db, player, seed):
    session = TrainingSession(
        user_id=player.id,
        seed_id=seed.id,
        status=TrainingSessionStatus.FINISHED,
    )
    session.created_at = _utc(2026, 1, 12)  # week 2
    db.add(session)
    await db.commit()

    series = await compute_weekly_series(db, player, now=_utc(2026, 1, 19))

    assert series.weeks_count == 3  # weeks 1, 2, 3
    assert series.solo == [0, 1, 0]
    assert series.races == [0, 0, 0]


async def test_cancelled_solo_excluded(db, player, seed):
    session = TrainingSession(
        user_id=player.id,
        seed_id=seed.id,
        status=TrainingSessionStatus.CANCELLED,
    )
    session.created_at = _utc(2026, 1, 12)
    db.add(session)
    await db.commit()

    series = await compute_weekly_series(db, player, now=_utc(2026, 1, 19))

    assert series.solo == [0, 0, 0]


async def test_race_uses_started_at_then_scheduled_at_then_created_at(db, player):
    """Race date follows api.helpers.race_date(): started_at ?? scheduled_at ?? created_at."""
    race = Race(
        organizer_id=player.id,
        name="r1",
        status=RaceStatus.FINISHED,
        scheduled_at=_utc(2026, 1, 12),
        started_at=_utc(2026, 1, 19),
    )
    race.created_at = _utc(2026, 1, 5)
    db.add(race)
    await db.commit()
    await db.refresh(race)

    participant = Participant(
        race_id=race.id,
        user_id=player.id,
        status=ParticipantStatus.FINISHED,
        igt_ms=1234,
    )
    db.add(participant)
    await db.commit()

    series = await compute_weekly_series(db, player, now=_utc(2026, 1, 19))

    # Three weeks: [Jan 5, Jan 12, Jan 19]. started_at is Jan 19 -> last bucket.
    assert series.weeks_count == 3
    assert series.races == [0, 0, 1]


async def test_organized_count_uses_race_date(db, player):
    race = Race(
        organizer_id=player.id,
        name="org",
        status=RaceStatus.SETUP,
        scheduled_at=_utc(2026, 1, 12),
    )
    race.created_at = _utc(2026, 1, 5)
    db.add(race)
    await db.commit()

    series = await compute_weekly_series(db, player, now=_utc(2026, 1, 19))

    # No started_at -> fall back to scheduled_at (Jan 12, week 2)
    assert series.organized == [0, 1, 0]
