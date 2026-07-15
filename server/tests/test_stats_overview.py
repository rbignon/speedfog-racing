"""GET /stats/overview: community KPIs + 12-week trend series."""

from datetime import UTC, datetime, timedelta

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
from speedfog_racing.services.analytics_service import compute_public_overview


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


def _user(i: int) -> User:
    return User(
        twitch_id=f"u{i}", twitch_username=f"user{i}", api_token=f"t{i}", role=UserRole.USER
    )


async def test_overview_empty_db(async_session):
    async with async_session() as db:
        data = await compute_public_overview(db)
    assert data["kpis"] == {
        "total_races": 0,
        "active_players": 0,
        "total_deaths": 0,
        "hours_raced": 0.0,
    }
    assert len(data["weekly"]["weeks"]) == 12
    assert data["weekly"]["races"] == [0] * 12
    assert data["weekly"]["active_users"] == [0] * 12
    assert data["weekly"]["deaths"] == [0] * 12
    assert data["weekly"]["hours"] == [0.0] * 12


async def test_overview_counts_public_finished_races_only(async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        a, b, org = _user(1), _user(2), _user(99)
        db.add_all([a, b, org])
        await db.flush()

        public = Race(
            name="pub",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=now - timedelta(days=2),
        )
        private = Race(
            name="priv",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=False,
            started_at=now - timedelta(days=2),
        )
        db.add_all([public, private])
        await db.flush()
        db.add_all(
            [
                Participant(
                    race_id=public.id,
                    user_id=a.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=3_600_000,
                    death_count=4,
                    zone_history=[{"z": 1}, {"z": 2}],
                ),
                Participant(
                    race_id=public.id,
                    user_id=b.id,
                    status=ParticipantStatus.ABANDONED,
                    igt_ms=1_800_000,
                    death_count=6,
                    zone_history=[{"z": 1}, {"z": 2}],
                ),
                Participant(
                    race_id=private.id,
                    user_id=a.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1_000_000,
                    death_count=50,
                    zone_history=[{"z": 1}, {"z": 2}],
                ),
            ]
        )
        # Training this week counts toward weekly active_users. TrainingSession
        # requires a seed (NOT NULL FK).
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
        db.add(
            TrainingSession(user_id=b.id, seed_id=seed.id, status=TrainingSessionStatus.FINISHED)
        )
        await db.commit()
        data = await compute_public_overview(db)

    assert data["kpis"]["total_races"] == 1
    assert data["kpis"]["active_players"] == 2
    assert data["kpis"]["total_deaths"] == 10
    assert data["kpis"]["hours_raced"] == 1.5
    # Everything happened within the current ISO week or the one before;
    # the series total must match regardless of the boundary.
    assert sum(data["weekly"]["races"]) == 1
    assert sum(data["weekly"]["deaths"]) == 10
    assert sum(data["weekly"]["hours"]) == 1.5
    # a played a race, b played a race and a training session: 2 distinct.
    assert max(data["weekly"]["active_users"]) == 2
