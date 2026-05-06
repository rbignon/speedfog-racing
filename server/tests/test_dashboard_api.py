"""Tests for dashboard-related API enhancements."""

import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
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


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


SAMPLE_GRAPH = {
    "nodes": {
        "start": {"tier": 0, "display_name": "Start"},
        "limgrave_a": {"tier": 1, "display_name": "Limgrave A"},
        "liurnia_b": {"tier": 2, "display_name": "Liurnia B"},
        "boss": {"tier": 3, "display_name": "Final Boss"},
    },
    "edges": [],
    "total_nodes": 4,
}


@pytest.fixture
async def dashboard_user(async_session):
    """Create a user with active training and active race for dashboard tests."""
    async with async_session() as db:
        user = User(
            twitch_id="dash_user_1",
            twitch_username="dash_player",
            twitch_display_name="DashPlayer",
            api_token="dash_test_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.flush()

        seed = Seed(
            seed_number="dash_seed_001",
            pool_name="standard",
            graph_json=SAMPLE_GRAPH,
            total_layers=3,
            folder_path="/fake/seed/dash",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Active training with progress at tier 2
        training = TrainingSession(
            user_id=user.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.ACTIVE,
            zone_history=[
                {"node_id": "start", "igt_ms": 0},
                {"node_id": "limgrave_a", "igt_ms": 60000},
                {"node_id": "liurnia_b", "igt_ms": 120000},
            ],
        )
        db.add(training)

        # Running race with participant
        race = Race(
            name="Dash Race",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            current_layer=2,
            igt_ms=90000,
            death_count=3,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_training_list_includes_current_layer(test_client, dashboard_user):
    """GET /training includes current_layer computed from zone_history."""
    async with test_client as client:
        response = await client.get(
            "/api/training",
            headers={"Authorization": f"Bearer {dashboard_user.api_token}"},
        )
        assert response.status_code == 200
        sessions = response.json()
        active = [s for s in sessions if s["status"] == "active"]
        assert len(active) == 1
        assert active[0]["current_layer"] == 2  # tier 2 = liurnia_b
        assert active[0]["seed_total_layers"] == 3


@pytest.mark.asyncio
async def test_my_races_includes_progress(test_client, dashboard_user):
    """GET /users/me/races includes my_current_layer, my_igt_ms, my_death_count."""
    async with test_client as client:
        response = await client.get(
            "/api/users/me/races",
            headers={"Authorization": f"Bearer {dashboard_user.api_token}"},
        )
        assert response.status_code == 200
        races = response.json()["races"]
        running = [r for r in races if r["status"] == "running"]
        assert len(running) == 1
        assert running[0]["my_current_layer"] == 2
        assert running[0]["my_igt_ms"] == 90000
        assert running[0]["my_death_count"] == 3
        assert running[0]["seed_total_layers"] == 3


@pytest.mark.asyncio
async def test_my_races_excludes_daily_seeds(test_client, async_session):
    """Daily Seed participations are filtered out of /me/races to avoid
    duplicating the today cell of the dashboard's weekly grid."""
    async with async_session() as db:
        user = User(
            twitch_id="daily_user_1",
            twitch_username="daily_player",
            api_token="daily_test_token",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="daily_org_1",
            twitch_username="system:daily",
            api_token="daily_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="daily_seed_001",
            pool_name="standard",
            graph_json=SAMPLE_GRAPH,
            total_layers=3,
            folder_path="/fake/seed/daily",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Daily Seed race in which the user participated.
        daily_race = Race(
            name="Daily 2026-04-29",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            daily_date=date(2026, 4, 29),
        )
        db.add(daily_race)
        await db.flush()

        db.add(
            Participant(
                race_id=daily_race.id,
                user_id=user.id,
                status=ParticipantStatus.PLAYING,
                igt_ms=42000,
                death_count=1,
            )
        )

        # Regular race in which the user also participated, to confirm we
        # only filter out daily ones.
        regular_race = Race(
            name="Regular Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
        )
        db.add(regular_race)
        await db.flush()

        db.add(
            Participant(
                race_id=regular_race.id,
                user_id=user.id,
                status=ParticipantStatus.PLAYING,
                igt_ms=10000,
                death_count=0,
            )
        )

        await db.commit()
        await db.refresh(user)

    async with test_client as client:
        response = await client.get(
            "/api/users/me/races",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 200
        races = response.json()["races"]
        names = [r["name"] for r in races]
        assert "Regular Race" in names
        assert "Daily 2026-04-29" not in names
        assert all(r.get("daily_date") is None for r in races)


@pytest.mark.asyncio
async def test_my_races_filter_by_status(test_client, async_session):
    """``status=setup,running`` keeps only matching races and drops finished ones."""
    async with async_session() as db:
        user = User(
            twitch_id="my_filter_u",
            twitch_username="my_filter",
            twitch_display_name="MyFilter",
            api_token="my_filter_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.flush()

        seed = Seed(
            seed_number="my_filter_seed",
            pool_name="standard",
            graph_json=SAMPLE_GRAPH,
            total_layers=3,
            folder_path="/fake/seed/my_filter",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        db.add_all(
            [
                Race(
                    name="Setup R",
                    organizer_id=user.id,
                    seed_id=seed.id,
                    status=RaceStatus.SETUP,
                ),
                Race(
                    name="Running R",
                    organizer_id=user.id,
                    seed_id=seed.id,
                    status=RaceStatus.RUNNING,
                ),
                Race(
                    name="Finished R",
                    organizer_id=user.id,
                    seed_id=seed.id,
                    status=RaceStatus.FINISHED,
                ),
            ]
        )
        await db.commit()

    async with test_client as client:
        # Multi-value filter: keep setup + running, drop finished.
        response = await client.get(
            "/api/users/me/races?status=setup,running",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 200
        names = {r["name"] for r in response.json()["races"]}
        assert names == {"Setup R", "Running R"}

        # Single-value filter: only running.
        response = await client.get(
            "/api/users/me/races?status=running",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 200
        names = {r["name"] for r in response.json()["races"]}
        assert names == {"Running R"}

        # Invalid value: 400 with a helpful message.
        response = await client.get(
            "/api/users/me/races?status=bogus",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 400
        assert "status" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_training_filter_by_status(test_client, async_session):
    """``status=active`` drops finished/cancelled training sessions."""
    async with async_session() as db:
        user = User(
            twitch_id="train_filter_u",
            twitch_username="train_filter",
            twitch_display_name="TrainFilter",
            api_token="train_filter_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.flush()

        seed = Seed(
            seed_number="train_filter_seed",
            pool_name="standard",
            graph_json=SAMPLE_GRAPH,
            total_layers=3,
            folder_path="/fake/seed/train_filter",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        db.add_all(
            [
                TrainingSession(
                    user_id=user.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.ACTIVE,
                ),
                TrainingSession(
                    user_id=user.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.FINISHED,
                    igt_ms=120000,
                ),
                TrainingSession(
                    user_id=user.id,
                    seed_id=seed.id,
                    status=TrainingSessionStatus.CANCELLED,
                ),
            ]
        )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/training?status=active",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) == 1
        assert sessions[0]["status"] == "active"

        # Invalid value: 400.
        response = await client.get(
            "/api/training?status=bogus",
            headers={"Authorization": f"Bearer {user.api_token}"},
        )
        assert response.status_code == 400
