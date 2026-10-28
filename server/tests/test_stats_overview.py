"""GET /stats/overview: community KPIs + weekly trend series."""

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
from speedfog_racing.services.analytics_service import (
    compute_analytics,
    compute_public_overview,
)


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
    assert len(data["weekly"]["weeks"]) == 20
    assert data["weekly"]["races"] == [0] * 20
    assert data["weekly"]["active_users"] == [0] * 20
    assert data["weekly"]["deaths"] == [0] * 20
    assert data["weekly"]["hours"] == [0.0] * 20


async def test_overview_counts_public_finished_races_only(async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        a, b, c, d, e, f = _user(1), _user(2), _user(3), _user(4), _user(5), _user(6)
        org = _user(99)
        db.add_all([a, b, c, d, e, f, org])
        await db.flush()

        public = Race(
            name="pub",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=now,
        )
        private = Race(
            name="priv",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=False,
            started_at=now,
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
                # d registered for the public race but never played.
                Participant(
                    race_id=public.id,
                    user_id=d.id,
                    status=ParticipantStatus.REGISTERED,
                ),
                # e played only the private race: counts as active, not as volume.
                Participant(
                    race_id=private.id,
                    user_id=e.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1_000_000,
                    death_count=7,
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
        db.add_all(
            [
                TrainingSession(
                    user_id=b.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.FINISHED,
                ),
                TrainingSession(
                    user_id=c.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.FINISHED,
                ),
                # f played inside the weekly window but before the KPI's 30 days.
                TrainingSession(
                    user_id=f.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.FINISHED,
                    created_at=now - timedelta(days=40),
                ),
            ]
        )
        await db.commit()
        data = await compute_public_overview(db)

    assert data["kpis"]["total_races"] == 1
    # Same rule as the weekly active_users series: a (public + private), b,
    # c (training only) and e (private only); d never played, f is too old.
    assert data["kpis"]["active_players"] == 4
    assert data["kpis"]["total_deaths"] == 10
    assert data["kpis"]["hours_raced"] == 1.5
    # Everything happened within the current ISO week or the one before;
    # the series total must match regardless of the boundary.
    assert sum(data["weekly"]["races"]) == 1
    assert sum(data["weekly"]["deaths"]) == 10
    assert sum(data["weekly"]["hours"]) == 1.5
    # c has no race participation: only the training-session path can count them.
    assert data["weekly"]["active_users"][-1] == 4


async def test_overview_active_players_matches_admin_players_kpi(async_session):
    """The /stats tile and the admin "Players (30d)" KPI are computed in two
    places from the same rule: on the same data they must agree."""
    now = datetime.now(UTC)
    async with async_session() as db:
        users = [_user(i) for i in range(1, 8)]
        org = _user(99)
        db.add_all([*users, org])
        await db.flush()
        seed = Seed(
            seed_number="s2",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/s2",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        def race(name: str, status: RaceStatus, public: bool, days_ago: int) -> Race:
            return Race(
                name=name,
                organizer_id=org.id,
                status=status,
                is_public=public,
                started_at=now - timedelta(days=days_ago),
            )

        public = race("pub", RaceStatus.FINISHED, True, 3)
        private = race("priv", RaceStatus.FINISHED, False, 10)
        running = race("run", RaceStatus.RUNNING, True, 1)
        old = race("old", RaceStatus.FINISHED, True, 40)
        db.add_all([public, private, running, old])
        await db.flush()

        played = [{"z": 1}, {"z": 2}]
        db.add_all(
            [
                Participant(race_id=public.id, user_id=users[0].id, zone_history=played),
                Participant(race_id=private.id, user_id=users[1].id, zone_history=played),
                Participant(race_id=running.id, user_id=users[2].id, zone_history=played),
                Participant(race_id=old.id, user_id=users[3].id, zone_history=played),
                Participant(race_id=public.id, user_id=users[4].id, zone_history=[{"z": 1}]),
                TrainingSession(user_id=users[5].id, seed_id=seed.id, created_at=now),
                TrainingSession(
                    user_id=users[6].id,
                    seed_id=seed.id,
                    created_at=now - timedelta(days=40),
                ),
            ]
        )
        await db.commit()

        overview = await compute_public_overview(db)
        admin = await compute_analytics(db)

    # Users 1-3 raced inside the window (public, private, running), user 6
    # trained; user 4 and 7 are too old, user 5 never got past one zone.
    assert overview["kpis"]["active_players"] == 4
    assert admin["kpis"]["active_players_30d"] == overview["kpis"]["active_players"]
