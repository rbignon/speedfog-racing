"""Reverting a finished race's ELO so a reset race can be re-rated.

``reset_race`` allows FINISHED -> SETUP. Without reverting, the voided run's
ELO stays applied to users forever and the idempotency guard in
``update_elo_ratings`` (keyed on an existing EloHistory row) permanently blocks
the re-run from being rated. ``revert_elo_ratings`` deletes the race's history
rows and reverses the applied deltas.
"""

from datetime import UTC, datetime

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
from speedfog_racing.services.stats_service import revert_elo_ratings, update_elo_ratings


@pytest.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _make_finished_race(async_session) -> tuple:
    """Create a public, finished 2-player race. Returns (race_id, u1_id, u2_id)."""
    async with async_session() as db:
        u1 = User(twitch_id="e1", twitch_username="e1", api_token="e1", role=UserRole.USER)
        u2 = User(twitch_id="e2", twitch_username="e2", api_token="e2", role=UserRole.USER)
        org = User(
            twitch_id="eorg", twitch_username="eorg", api_token="eorg", role=UserRole.ORGANIZER
        )
        db.add_all([u1, u2, org])
        await db.flush()

        seed = Seed(
            seed_number="elo-s",
            pool_name="standard",
            graph_json={},
            total_layers=5,
            folder_path="/t/elo",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Elo Race",
            organizer_id=org.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=u1.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=300000,
                ),
                Participant(
                    race_id=race.id,
                    user_id=u2.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=350000,
                ),
            ]
        )
        await db.commit()
        return race.id, u1.id, u2.id


@pytest.mark.asyncio
async def test_revert_restores_ratings_and_deletes_history(async_session):
    race_id, u1_id, u2_id = await _make_finished_race(async_session)

    async with async_session() as db:
        await update_elo_ratings(race_id, db)

    async with async_session() as db:
        # Sanity: the run applied ELO and left history.
        u1r = await db.get(User, u1_id)
        u2r = await db.get(User, u2_id)
        assert (u1r.elo_rating, u2r.elo_rating) != (1500.0, 1500.0)
        assert u1r.elo_races == 1 and u2r.elo_races == 1
        rows = (
            (await db.execute(select(EloHistory).where(EloHistory.race_id == race_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 2

    async with async_session() as db:
        await revert_elo_ratings(race_id, db)
        await db.commit()

    async with async_session() as db:
        u1r = await db.get(User, u1_id)
        u2r = await db.get(User, u2_id)
        assert u1r.elo_rating == pytest.approx(1500.0)
        assert u2r.elo_rating == pytest.approx(1500.0)
        assert u1r.elo_races == 0 and u2r.elo_races == 0
        rows = (
            (await db.execute(select(EloHistory).where(EloHistory.race_id == race_id)))
            .scalars()
            .all()
        )
        assert rows == []


@pytest.mark.asyncio
async def test_revert_reenables_rating_for_rerun(async_session):
    """After reverting, a re-run can be rated again (idempotency guard cleared)."""
    race_id, u1_id, _u2_id = await _make_finished_race(async_session)

    async with async_session() as db:
        await update_elo_ratings(race_id, db)

    async with async_session() as db:
        await revert_elo_ratings(race_id, db)
        await db.commit()

    async with async_session() as db:
        await update_elo_ratings(race_id, db)

    async with async_session() as db:
        rows = (
            (await db.execute(select(EloHistory).where(EloHistory.race_id == race_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        u1r = await db.get(User, u1_id)
        assert u1r.elo_races == 1
