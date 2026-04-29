"""Tests covering ELO/stats exclusion for races flagged ``exclude_from_elo``."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import (
    recalculate_all_stats,
    update_elo_ratings,
)


@pytest.fixture
async def elo_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def elo_async_session(elo_async_engine):
    return async_sessionmaker(elo_async_engine, class_=AsyncSession, expire_on_commit=False)


async def _make_finished_race(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    exclude_from_elo: bool,
    suffix: str,
) -> UUID:
    """Insert a finished 2-player race and return its id."""
    async with session_maker() as db:
        users = [
            User(
                twitch_id=f"u-{suffix}-{i}",
                twitch_username=f"player_{suffix}_{i}",
                api_token=f"tok-{suffix}-{i}",
                role=UserRole.USER,
            )
            for i in range(2)
        ]
        organizer = User(
            twitch_id=f"org-{suffix}",
            twitch_username=f"org_{suffix}",
            api_token=f"tok-org-{suffix}",
            role=UserRole.ORGANIZER,
        )
        db.add_all([*users, organizer])
        await db.flush()

        seed = Seed(
            seed_number=f"seed-{suffix}",
            pool_name="standard",
            graph_json={"nodes": {}, "total_layers": 5},
            total_layers=5,
            folder_path=f"/test/seed-{suffix}",
            status=SeedStatus.CONSUMED,
            difficulty_score=1.0,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name=f"Race {suffix}",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            exclude_from_elo=exclude_from_elo,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=users[0].id,
                    mod_token=f"mt-{suffix}-0",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_000_000,
                    death_count=2,
                ),
                Participant(
                    race_id=race.id,
                    user_id=users[1].id,
                    mod_token=f"mt-{suffix}-1",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_500_000,
                    death_count=4,
                ),
            ]
        )
        await db.commit()
        return race.id


@pytest.mark.asyncio
async def test_excluded_race_writes_no_elo_history(elo_async_session) -> None:
    race_id = await _make_finished_race(elo_async_session, exclude_from_elo=True, suffix="excl")
    async with elo_async_session() as db:
        await update_elo_ratings(race_id, db)
    async with elo_async_session() as db:
        rows = (await db.execute(select(EloHistory))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_included_race_writes_elo_history(elo_async_session) -> None:
    """Sanity check: the same setup with exclude_from_elo=False does write history."""
    race_id = await _make_finished_race(elo_async_session, exclude_from_elo=False, suffix="incl")
    async with elo_async_session() as db:
        await update_elo_ratings(race_id, db)
    async with elo_async_session() as db:
        rows = (await db.execute(select(EloHistory))).scalars().all()
        assert {row.race_id for row in rows} == {race_id}


@pytest.mark.asyncio
async def test_recalculate_all_stats_skips_excluded_races(elo_async_session) -> None:
    excluded_id = await _make_finished_race(elo_async_session, exclude_from_elo=True, suffix="r1")
    included_id = await _make_finished_race(elo_async_session, exclude_from_elo=False, suffix="r2")
    async with elo_async_session() as db:
        await recalculate_all_stats(db)
    async with elo_async_session() as db:
        rows = (await db.execute(select(EloHistory))).scalars().all()
        race_ids = {row.race_id for row in rows}
        assert included_id in race_ids
        assert excluded_id not in race_ids
