"""Tests for dashboard-related API enhancements."""

import os

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
            progress_nodes=[
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
    """GET /training includes current_layer computed from progress_nodes."""
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
