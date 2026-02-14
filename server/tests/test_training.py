"""Tests for training mode."""

import asyncio
import os
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import speedfog_racing.database as db_module
import speedfog_racing.main as main_module
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
    generate_token,
)
from speedfog_racing.services.seed_service import get_pool_config
from speedfog_racing.services.training_service import (
    create_training_session,
    get_training_seed,
)

# Use a unique test database file for training tests
TRAINING_TEST_DB = os.path.join(tempfile.gettempdir(), "speedfog_training_test.db")


@pytest.fixture(scope="function")
def async_session():
    """Set up a fresh async database for training tests.

    Patches the database module so API routes and WS handlers use the same DB.
    Yields an async_sessionmaker.
    """
    if os.path.exists(TRAINING_TEST_DB):
        os.remove(TRAINING_TEST_DB)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{TRAINING_TEST_DB}",
        echo=False,
    )
    test_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    asyncio.run(_create_tables(test_engine))

    # Patch modules
    original_engine = db_module.engine
    original_session_maker = db_module.async_session_maker

    db_module.engine = test_engine
    db_module.async_session_maker = test_session_maker
    main_module.async_session_maker = test_session_maker

    try:
        yield test_session_maker
    finally:
        db_module.engine = original_engine
        db_module.async_session_maker = original_session_maker
        main_module.async_session_maker = original_session_maker

        asyncio.run(test_engine.dispose())
        if os.path.exists(TRAINING_TEST_DB):
            os.remove(TRAINING_TEST_DB)


async def _create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def sample_graph_json():
    """Minimal graph_json for training tests."""
    return {
        "version": "4.0",
        "total_layers": 10,
        "total_nodes": 20,
        "total_paths": 3,
        "start_node": "limgrave_start",
        "final_boss": "erdtree_boss",
        "event_map": {"1040292800": "limgrave_start", "1040292801": "stormveil_01"},
        "finish_event": 1040292899,
        "nodes": {
            "limgrave_start": {"layer": 0, "tier": 1, "name": "Limgrave Start"},
            "stormveil_01": {"layer": 1, "tier": 2, "name": "Stormveil"},
        },
        "edges": [{"from": "limgrave_start", "to": "stormveil_01"}],
    }


@pytest.fixture
async def training_user(async_session):
    """A regular user for training."""
    async with async_session() as db:
        user = User(
            twitch_id="train_user_1",
            twitch_username="trainer",
            api_token=generate_token(),
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def training_seed(async_session, sample_graph_json):
    """A seed in a training pool."""
    async with async_session() as db:
        seed = Seed(
            seed_number="train_001",
            pool_name="training_standard",
            graph_json=sample_graph_json,
            total_layers=10,
            folder_path="/tmp/seed_train_001.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return seed


# =============================================================================
# Task 1: Model tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_training_session(async_session, training_user, training_seed):
    """TrainingSession can be created and persisted."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        assert session.id is not None
        assert session.status == TrainingSessionStatus.ACTIVE
        assert session.mod_token is not None
        assert len(session.mod_token) > 20
        assert session.igt_ms == 0
        assert session.death_count == 0
        assert session.progress_nodes is None
        assert session.finished_at is None


@pytest.mark.asyncio
async def test_training_session_seed_stays_available(async_session, training_user, training_seed):
    """Creating a training session does NOT consume the seed."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

        # Reload seed
        result = await db.execute(select(Seed).where(Seed.id == training_seed.id))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.AVAILABLE


# =============================================================================
# Task 3: Pool type filtering tests
# =============================================================================


def test_pool_config_includes_type(tmp_path, monkeypatch):
    """get_pool_config reads the type field from config.toml."""
    pool_dir = tmp_path / "training_standard"
    pool_dir.mkdir()
    (pool_dir / "config.toml").write_text(
        '[display]\ntype = "training"\nestimated_duration = "~1h"\n'
    )
    monkeypatch.setattr(
        "speedfog_racing.services.seed_service.settings",
        type("S", (), {"seeds_pool_dir": str(tmp_path)})(),
    )
    config = get_pool_config("training_standard")
    assert config is not None
    assert config["type"] == "training"


def test_pool_config_defaults_to_race(tmp_path, monkeypatch):
    """Pools without type field default to 'race'."""
    pool_dir = tmp_path / "standard"
    pool_dir.mkdir()
    (pool_dir / "config.toml").write_text('[display]\nestimated_duration = "~1h"\n')
    monkeypatch.setattr(
        "speedfog_racing.services.seed_service.settings",
        type("S", (), {"seeds_pool_dir": str(tmp_path)})(),
    )
    config = get_pool_config("standard")
    assert config is not None
    assert config["type"] == "race"


# =============================================================================
# Task 4: Training service tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_training_seed_excludes_played(async_session, training_user, training_seed):
    """get_training_seed skips seeds already played by the user."""
    async with async_session() as db:
        # First pick should work
        seed = await get_training_seed(db, "training_standard", training_user.id)
        assert seed is not None
        assert seed.id == training_seed.id

        # Create a session for this seed
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

    async with async_session() as db:
        # Second pick should return None (only seed is already played)
        seed = await get_training_seed(db, "training_standard", training_user.id, allow_reset=False)
        assert seed is None


@pytest.mark.asyncio
async def test_get_training_seed_resets_when_exhausted(async_session, training_user, training_seed):
    """When all seeds are played, reset and pick from all."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

    async with async_session() as db:
        seed = await get_training_seed(db, "training_standard", training_user.id, allow_reset=True)
        assert seed is not None
        assert seed.id == training_seed.id


@pytest.mark.asyncio
async def test_create_training_session_service(async_session, training_user, training_seed):
    """create_training_session creates a session and returns it with seed loaded."""
    async with async_session() as db:
        session = await create_training_session(db, training_user.id, "training_standard")
        assert session.status == TrainingSessionStatus.ACTIVE
        assert session.seed_id == training_seed.id
        assert session.user_id == training_user.id


# =============================================================================
# Task 6: API endpoint tests
# =============================================================================

TRAINING_POOL_CONFIG = {
    "type": "training",
    "estimated_duration": "~1h",
    "description": "Training pool",
}


@pytest.fixture
def test_client(async_session, monkeypatch):
    """Create test client with async database override and training pool config."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Monkeypatch get_pool_config so "training_standard" returns a training config
    monkeypatch.setattr(
        "speedfog_racing.api.training.get_pool_config",
        lambda name: TRAINING_POOL_CONFIG if name == "training_standard" else None,
    )

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_training_session_api(test_client, training_user, training_seed):
    """POST /api/training creates a session."""
    async with test_client as client:
        resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "active"
        assert data["pool_name"] == "training_standard"
        assert data["seed_total_layers"] == 10


@pytest.mark.asyncio
async def test_list_training_sessions_api(test_client, training_user, training_seed):
    """GET /api/training lists user's sessions."""
    async with test_client as client:
        # Create a session first
        await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )

        resp = await client.get(
            "/api/training",
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "active"


@pytest.mark.asyncio
async def test_get_training_session_detail_api(test_client, training_user, training_seed):
    """GET /api/training/{id} returns detail with graph_json."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        session_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/training/{session_id}",
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph_json"] is not None
        assert data["seed_total_layers"] == 10


@pytest.mark.asyncio
async def test_abandon_training_session_api(test_client, training_user, training_seed):
    """POST /api/training/{id}/abandon transitions to ABANDONED."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        session_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/training/{session_id}/abandon",
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "abandoned"
        assert resp.json()["finished_at"] is not None
