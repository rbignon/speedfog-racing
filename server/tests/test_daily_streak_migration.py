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


@pytest.mark.asyncio
async def test_backfill_computes_streak_from_participations(
    streak_async_session,
) -> None:
    """One user qualifies on day 1..7 (freeze granted), misses day 8
    (freeze absorbed), qualifies day 9. Expected final state:
    current=8, best=8, freezes=0, last_qualifying=day9, one freeze row
    for day 8.
    """
    from speedfog_racing.models import (
        DailyStreakFreeze,
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )
    from speedfog_racing.services.daily_streak_service import backfill_user

    async with streak_async_session() as db:
        user = User(twitch_id="bf1", twitch_username="bf1")
        db.add(user)
        await db.flush()
        # Construct 9 daily races; user qualifies on 1..7 and 9, misses 8.
        for i in range(1, 10):
            d = date(2026, 1, i)
            race = Race(
                name=f"Daily Seed - 2026-01-{i:02d}",
                organizer_id=user.id,
                daily_date=d,
                exclude_from_elo=True,
                status=RaceStatus.FINISHED,
            )
            db.add(race)
            await db.flush()
            if i != 8:
                participant = Participant(
                    race_id=race.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    zone_history=[
                        {"node_id": "start", "igt_ms": 0, "type": "fog"},
                        {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
                    ],
                )
                db.add(participant)
        await db.commit()

        await backfill_user(db, user.id)
        await db.commit()
        await db.refresh(user)

        assert user.daily_current_streak == 8
        assert user.daily_best_streak == 8
        assert user.daily_freeze_count == 0
        assert user.daily_last_qualifying_date == date(2026, 1, 9)

        rows = (
            (
                await db.execute(
                    select(DailyStreakFreeze).where(DailyStreakFreeze.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.daily_date for r in rows] == [date(2026, 1, 8)]
