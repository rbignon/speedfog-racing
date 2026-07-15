"""Smoke tests for the data-model parts of the daily seed migration.

Production runs Alembic on Postgres; the test suite uses ``Base.metadata.create_all``
on SQLite. These tests verify the model-level changes that have to keep working
in both worlds: the SYSTEM user role, the nullable ``api_token``, and the
partial unique index that enforces "one daily per UTC day".
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    DailySeedSchedule,
    Race,
    RaceStatus,
    User,
    UserRole,
)


@pytest.fixture
async def mig_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def mig_async_session(mig_async_engine):
    return async_sessionmaker(mig_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_system_user_can_be_inserted_with_null_api_token(mig_async_session) -> None:
    """The SYSTEM user is created by the migration via a raw SQL INSERT that
    sets ``api_token`` to NULL. We mirror that here: passing ``api_token=None``
    through the ORM would still trigger ``default=generate_token``, so the
    test confirms the *schema* accepts NULL rather than the ORM construction
    pattern (which is correct — the ORM is only used by Twitch-authenticated
    users that always have a token)."""
    async with mig_async_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO users
                    (id, twitch_id, twitch_username, twitch_display_name,
                     role, api_token)
                VALUES
                    (:id, 'system:daily', 'speedfog_daily', 'Daily Seed',
                     'SYSTEM', NULL)
                """
            ).bindparams(id=str(uuid4()))
        )
        await db.commit()

        loaded = (
            await db.execute(select(User).where(User.twitch_id == "system:daily"))
        ).scalar_one()
        assert loaded.api_token is None
        assert loaded.role == UserRole.SYSTEM


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_two_dailies_same_day(mig_async_session) -> None:
    today = date(2026, 4, 27)
    started = datetime(2026, 4, 27, 8, 0, tzinfo=UTC)

    async with mig_async_session() as db:
        organizer = User(
            twitch_id=f"sys-{uuid4().hex[:6]}",
            twitch_username="sys_user",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        db.add(organizer)
        await db.flush()

        db.add(
            Race(
                name="Daily 1",
                organizer_id=organizer.id,
                status=RaceStatus.RUNNING,
                is_public=True,
                daily_date=today,
                exclude_from_stats=True,
                started_at=started,
            )
        )
        await db.commit()

        db.add(
            Race(
                name="Daily 2",
                organizer_id=organizer.id,
                status=RaceStatus.RUNNING,
                is_public=True,
                daily_date=today,
                exclude_from_stats=True,
                started_at=started,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_partial_unique_index_allows_many_non_daily_races(mig_async_session) -> None:
    """daily_date IS NULL rows are excluded from the unique constraint."""
    async with mig_async_session() as db:
        organizer = User(
            twitch_id=f"org-{uuid4().hex[:6]}",
            twitch_username="org_user",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.ORGANIZER,
        )
        db.add(organizer)
        await db.flush()

        for i in range(3):
            db.add(
                Race(
                    name=f"Regular {i}",
                    organizer_id=organizer.id,
                    status=RaceStatus.SETUP,
                    is_public=True,
                )
            )
        await db.commit()

        rows = (await db.execute(select(Race))).scalars().all()
        assert len(rows) == 3
        assert all(r.daily_date is None for r in rows)


@pytest.mark.asyncio
async def test_daily_seed_schedule_round_trip(mig_async_session) -> None:
    async with mig_async_session() as db:
        for weekday in range(7):
            db.add(DailySeedSchedule(weekday=weekday, pool_name="standard"))
        await db.commit()

        rows = (
            (await db.execute(select(DailySeedSchedule).order_by(DailySeedSchedule.weekday)))
            .scalars()
            .all()
        )
        assert [r.weekday for r in rows] == list(range(7))
        assert all(r.pool_name == "standard" for r in rows)
