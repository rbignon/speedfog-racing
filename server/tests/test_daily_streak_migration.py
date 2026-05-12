"""Behavioral tests for the daily streak schema additions."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import DailyStreakFreeze, User


@pytest.fixture
async def streak_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # SQLite does not enforce FOREIGN KEY constraints unless told to;
        # cascade-on-delete behavior depends on it.
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def streak_async_session(streak_async_engine):
    return async_sessionmaker(streak_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_user_freeze_count_check_constraint_rejects_three(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t1", twitch_username="t1", daily_freeze_count=3)
        db.add(user)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_user_best_streak_below_current_rejected(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(
            twitch_id="t2",
            twitch_username="t2",
            daily_current_streak=5,
            daily_best_streak=2,
        )
        db.add(user)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_daily_streak_freeze_cascade_on_user_delete(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t3", twitch_username="t3")
        db.add(user)
        await db.flush()
        user_id = user.id
        db.add(DailyStreakFreeze(user_id=user_id, daily_date=date(2026, 5, 9)))
        await db.commit()

        await db.delete(user)
        await db.commit()

        remaining = (
            await db.execute(select(DailyStreakFreeze).where(DailyStreakFreeze.user_id == user_id))
        ).all()
        assert remaining == []


@pytest.mark.asyncio
async def test_daily_streak_freeze_consumed_at_server_default(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t4", twitch_username="t4")
        db.add(user)
        await db.flush()
        freeze = DailyStreakFreeze(user_id=user.id, daily_date=date(2026, 5, 9))
        db.add(freeze)
        await db.commit()
        await db.refresh(freeze)

        # SQLite's CURRENT_TIMESTAMP server default populates the column on
        # INSERT; we only verify a datetime landed, not the exact value.
        from datetime import datetime

        assert freeze.consumed_at is not None
        assert isinstance(freeze.consumed_at, datetime)


@pytest.mark.asyncio
async def test_daily_streak_freeze_duplicate_pk_rejected(streak_async_session) -> None:
    async with streak_async_session() as db:
        user = User(twitch_id="t5", twitch_username="t5")
        db.add(user)
        await db.flush()
        db.add(DailyStreakFreeze(user_id=user.id, daily_date=date(2026, 5, 9)))
        await db.commit()

    async with streak_async_session() as db:
        db.add(DailyStreakFreeze(user_id=user.id, daily_date=date(2026, 5, 9)))
        with pytest.raises(IntegrityError):
            await db.commit()
