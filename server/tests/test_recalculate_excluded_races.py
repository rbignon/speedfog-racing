"""recalculate_all_stats skips exclude-flagged races in the trait replay."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import recalculate_all_stats


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


async def test_excluded_race_feeds_no_traits(async_session):
    async with async_session() as db:
        player = User(twitch_id="p", twitch_username="p", api_token="tp", role=UserRole.USER)
        org = User(twitch_id="o", twitch_username="o", api_token="to", role=UserRole.USER)
        db.add_all([player, org])
        await db.flush()
        race = Race(
            name="daily",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            exclude_from_stats=True,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        db.add(
            Participant(
                race_id=race.id,
                user_id=player.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=1000,
                zone_history=[{"z": 1}, {"z": 2}],
            )
        )
        await db.commit()

        await recalculate_all_stats(db)

        rows = (await db.execute(select(PlayerTraitScores))).scalars().all()
        assert rows == []
