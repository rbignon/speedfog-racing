"""Smoke tests for the daily streak schema additions."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import DailyStreakFreeze, User


@pytest.fixture
async def streak_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def streak_async_session(streak_async_engine):
    return async_sessionmaker(streak_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_user_has_daily_streak_columns_with_defaults(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t1", twitch_username="t1")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        assert user.daily_current_streak == 0
        assert user.daily_best_streak == 0
        assert user.daily_freeze_count == 0
        assert user.daily_last_qualifying_date is None


@pytest.mark.asyncio
async def test_daily_streak_freeze_round_trip(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t2", twitch_username="t2")
        db.add(user)
        await db.flush()
        freeze = DailyStreakFreeze(
            user_id=user.id,
            daily_date=date(2026, 5, 9),
            consumed_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        )
        db.add(freeze)
        await db.commit()

        row = (
            await db.execute(select(DailyStreakFreeze).where(DailyStreakFreeze.user_id == user.id))
        ).scalar_one()
        assert row.daily_date == date(2026, 5, 9)
        assert row.consumed_at.replace(tzinfo=UTC) == datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
