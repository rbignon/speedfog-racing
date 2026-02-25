"""Tests for race lifecycle helpers."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def race_setup(async_session):
    """Create a running race with 2 participants."""
    async with async_session() as db:
        user1 = User(
            twitch_id="u1",
            twitch_username="player1",
            api_token="tok1",
            role=UserRole.USER,
        )
        user2 = User(
            twitch_id="u2",
            twitch_username="player2",
            api_token="tok2",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org",
            twitch_username="organizer",
            api_token="tok_org",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user1, user2, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p1 = Participant(
            race_id=race.id,
            user_id=user1.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=300000,
            finished_at=datetime.now(UTC),
        )
        p2 = Participant(
            race_id=race.id,
            user_id=user2.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=200000,
        )
        db.add_all([p1, p2])
        await db.commit()

        return race.id, p1.id, p2.id


@pytest.mark.asyncio
async def test_auto_finish_not_triggered_while_playing(async_session, race_setup):
    """Race stays RUNNING if any participant is still PLAYING."""
    race_id, _, _ = race_setup
    async with async_session() as db:
        result = await db.execute(
            select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
        )
        race = result.scalar_one()
        transitioned = await check_race_auto_finish(db, race)
        assert transitioned is False
        await db.refresh(race)
        assert race.status == RaceStatus.RUNNING


@pytest.mark.asyncio
async def test_auto_finish_when_all_done(async_session, race_setup):
    """Race transitions to FINISHED when all participants are FINISHED or ABANDONED."""
    race_id, _, p2_id = race_setup
    async with async_session() as db:
        p2 = await db.get(Participant, p2_id)
        p2.status = ParticipantStatus.ABANDONED
        await db.commit()

    async with async_session() as db:
        result = await db.execute(
            select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
        )
        race = result.scalar_one()
        transitioned = await check_race_auto_finish(db, race)
        assert transitioned is True
        await db.refresh(race)
        assert race.status == RaceStatus.FINISHED
