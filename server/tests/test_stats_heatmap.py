"""GET /stats/heatmap: public activity grid, bucketed in the requested timezone."""

from datetime import UTC, datetime

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
from speedfog_racing.services.analytics_service import compute_public_heatmap

# Injected "now" so windows and DST fixtures are deterministic.
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


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


async def _race_with_participants(
    db, organizer, users, *, started_at, is_public=True, daily_date=None
) -> Race:
    race = Race(
        name="R",
        organizer_id=organizer.id,
        status=RaceStatus.FINISHED,
        is_public=is_public,
        daily_date=daily_date,
        exclude_from_stats=daily_date is not None,
        started_at=started_at,
    )
    db.add(race)
    await db.flush()
    for u in users:
        db.add(
            Participant(
                race_id=race.id,
                user_id=u.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=1000,
            )
        )
    return race


async def test_timezone_conversion_shifts_day_column(async_session):
    # Saturday 2026-07-11 23:30 UTC is Sunday 01:30 in Europe/Paris (CEST).
    async with async_session() as db:
        a, org = _user(1), _user(99)
        db.add_all([a, org])
        await db.flush()
        await _race_with_participants(
            db, org, [a], started_at=datetime(2026, 7, 11, 23, 30, tzinfo=UTC)
        )
        await db.commit()

        paris = await compute_public_heatmap(db, "Europe/Paris", now=NOW)
        utc = await compute_public_heatmap(db, None, now=NOW)

    assert paris["timezone"] == "Europe/Paris"
    assert paris["grid"][0][6] == 1  # 00-02 bucket, Sunday
    assert sum(v for row in paris["grid"] for v in row) == 1
    assert utc["timezone"] == "UTC"
    assert utc["grid"][11][5] == 1  # 22-24 bucket, Saturday


async def test_dst_boundary_buckets_at_true_local_hour(async_session):
    # Europe/Paris switched to CEST on 2026-03-29. Same UTC hour, different
    # local buckets on either side of the change. Both dates are Wednesdays.
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    async with async_session() as db:
        a, b, org = _user(1), _user(2), _user(99)
        db.add_all([a, b, org])
        await db.flush()
        await _race_with_participants(
            db, org, [a], started_at=datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        )
        await _race_with_participants(
            db, org, [b], started_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        )
        await db.commit()
        data = await compute_public_heatmap(db, "Europe/Paris", now=now)

    assert data["grid"][6][2] == 1  # 13:00 CET -> 12-14 bucket, Wednesday
    assert data["grid"][7][2] == 1  # 14:00 CEST -> 14-16 bucket, Wednesday


async def test_scope_weighting_and_exclusions(async_session):
    started = datetime(2026, 7, 13, 10, 0, tzinfo=UTC)  # Monday 10:00 UTC
    async with async_session() as db:
        a, b, c, org = _user(1), _user(2), _user(3), _user(99)
        db.add_all([a, b, c, org])
        await db.flush()
        # Public non-daily race with 3 participants: +3.
        await _race_with_participants(db, org, [a, b, c], started_at=started)
        # Daily race: excluded entirely.
        await _race_with_participants(
            db, org, [a, b], started_at=started, daily_date=started.date()
        )
        # Private race: excluded entirely.
        await _race_with_participants(db, org, [a], started_at=started, is_public=False)
        # Training session: +1. Explicit created_at (server_default would use
        # the real clock, outside the injected window in future runs).
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
            TrainingSession(
                user_id=a.id,
                seed_id=seed.id,
                status=TrainingSessionStatus.FINISHED,
                created_at=started,
            )
        )
        await db.commit()
        data = await compute_public_heatmap(db, None, now=NOW)

    assert data["grid"][5][0] == 4  # 10-12 bucket, Monday: 3 racers + 1 solo
    assert sum(v for row in data["grid"] for v in row) == 4


async def test_invalid_timezone_falls_back_to_utc(async_session):
    async with async_session() as db:
        data = await compute_public_heatmap(db, "Not/AZone", now=NOW)
    assert data["timezone"] == "UTC"
    assert len(data["grid"]) == 12
    assert all(len(row) == 7 for row in data["grid"])
