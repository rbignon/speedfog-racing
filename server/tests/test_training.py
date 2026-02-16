"""Tests for training mode."""

import asyncio
import os
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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
    get_played_seed_counts,
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
        poolclass=NullPool,
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
            "limgrave_start": {"type": "start", "layer": 0, "tier": 1, "name": "Limgrave Start"},
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


@pytest.mark.asyncio
async def test_get_played_seed_counts_empty(async_session, training_user):
    """No sessions → empty counts."""
    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {}


@pytest.mark.asyncio
async def test_get_played_seed_counts_one_pool(async_session, training_user, training_seed):
    """One session → count 1 for that pool."""
    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1}


@pytest.mark.asyncio
async def test_get_played_seed_counts_distinct(async_session, training_user, training_seed):
    """Two sessions on same seed → still count 1."""
    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1}


@pytest.mark.asyncio
async def test_get_played_seed_counts_excludes_discarded(
    async_session, training_user, training_seed
):
    """Discarded seeds are excluded from the played count."""
    # Play the seed
    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    # Verify it's counted
    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1}

    # Discard the seed
    async with async_session() as db:
        from sqlalchemy import update

        await db.execute(
            update(Seed).where(Seed.id == training_seed.id).values(status=SeedStatus.DISCARDED)
        )
        await db.commit()

    # Verify it's no longer counted
    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {}


@pytest.mark.asyncio
async def test_get_played_seed_counts_multiple_pools(
    async_session, training_user, sample_graph_json
):
    """Seeds across multiple pools are counted separately."""
    async with async_session() as db:
        seed_a = Seed(
            seed_number="a_001",
            pool_name="training_standard",
            graph_json=sample_graph_json,
            total_layers=10,
            folder_path="/tmp/a.zip",
            status=SeedStatus.AVAILABLE,
        )
        seed_b = Seed(
            seed_number="b_001",
            pool_name="training_sprint",
            graph_json=sample_graph_json,
            total_layers=5,
            folder_path="/tmp/b.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_a, seed_b])
        await db.flush()
        db.add(TrainingSession(user_id=training_user.id, seed_id=seed_a.id))
        db.add(TrainingSession(user_id=training_user.id, seed_id=seed_b.id))
        await db.commit()

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1, "training_sprint": 1}


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

    from speedfog_racing.rate_limit import limiter

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Monkeypatch get_pool_config so "training_standard" returns a training config
    monkeypatch.setattr(
        "speedfog_racing.api.training.get_pool_config",
        lambda name: TRAINING_POOL_CONFIG if name == "training_standard" else None,
    )

    # Disable rate limiting in tests to avoid 429 across test functions
    limiter.enabled = False

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()
    limiter.enabled = True


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
async def test_create_training_session_api_conflict(test_client, training_user, training_seed):
    """POST /api/training returns 409 if user already has an active session."""
    async with test_client as client:
        headers = {"Authorization": f"Bearer {training_user.api_token}"}
        resp1 = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers=headers,
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers=headers,
        )
        assert resp2.status_code == 409
        assert "active training session" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_training_session_api_after_abandon(test_client, training_user, training_seed):
    """POST /api/training succeeds after abandoning the active session."""
    async with test_client as client:
        headers = {"Authorization": f"Bearer {training_user.api_token}"}
        resp1 = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers=headers,
        )
        assert resp1.status_code == 201
        session_id = resp1.json()["id"]

        # Abandon it
        resp_abandon = await client.post(
            f"/api/training/{session_id}/abandon",
            headers=headers,
        )
        assert resp_abandon.status_code == 200

        # Now creating a new one should work
        resp2 = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers=headers,
        )
        assert resp2.status_code == 201


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


# =============================================================================
# Task 2: Pool stats with played_by_user
# =============================================================================


@pytest.fixture
def pool_test_client(async_session, monkeypatch):
    """Test client with pool config patched for the pools API."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    monkeypatch.setattr(
        "speedfog_racing.api.pools.get_pool_config",
        lambda name: TRAINING_POOL_CONFIG if "training" in name else {"type": "race"},
    )

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pools_played_by_user_authenticated(
    pool_test_client, training_user, training_seed, async_session
):
    """GET /api/pools?type=training returns played_by_user when authenticated."""
    # Create a training session for the user
    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with pool_test_client as client:
        resp = await client.get(
            "/api/pools?type=training",
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "training_standard" in data
        assert data["training_standard"]["played_by_user"] == 1


@pytest.mark.asyncio
async def test_pools_played_by_user_unauthenticated(pool_test_client, training_seed):
    """GET /api/pools?type=training returns played_by_user=null when not authenticated."""
    async with pool_test_client as client:
        resp = await client.get("/api/pools?type=training")
        assert resp.status_code == 200
        data = resp.json()
        assert "training_standard" in data
        assert data["training_standard"]["played_by_user"] is None


# =============================================================================
# Task 14: WebSocket integration tests
# =============================================================================


@pytest.fixture
def training_ws_client(async_session):
    """Sync test client for WebSocket testing."""
    from starlette.testclient import TestClient

    from speedfog_racing.websocket.training_manager import training_manager

    training_manager.rooms.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    training_manager.rooms.clear()


@pytest.fixture
def training_session_data(async_session, training_user, training_seed):
    """Create a training session and return its data (sync-safe)."""

    async def _setup():
        async with async_session() as db:
            session = await create_training_session(db, training_user.id, "training_standard")
            await db.commit()
            await db.refresh(session)
            return {
                "session_id": str(session.id),
                "mod_token": session.mod_token,
                "user_id": str(training_user.id),
                "api_token": training_user.api_token,
            }

    return asyncio.run(_setup())


def test_training_mod_websocket_auth(training_ws_client, training_session_data):
    """Training mod WS: auth → auth_ok with seed info."""
    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        auth_ok = ws.receive_json()
        assert auth_ok["type"] == "auth_ok"
        assert "seed" in auth_ok
        assert auth_ok["seed"]["event_ids"] is not None

        # Should immediately receive race_start
        start = ws.receive_json()
        assert start["type"] == "race_start"


def test_training_mod_websocket_status_update(
    training_ws_client, training_session_data, async_session
):
    """Training mod WS: status_update persists IGT and deaths."""
    import time
    import uuid as _uuid

    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start

        ws.send_json({"type": "status_update", "igt_ms": 5000, "death_count": 2})
        # Give server time to process before closing the WS
        time.sleep(0.3)

    # Verify persisted in DB
    async def _check():
        async with async_session() as db:
            result = await db.execute(
                select(TrainingSession).where(TrainingSession.id == _uuid.UUID(sid))
            )
            s = result.scalar_one()
            assert s.igt_ms == 5000
            assert s.death_count == 2

    asyncio.run(_check())


def test_training_mod_websocket_event_flag(
    training_ws_client, training_session_data, async_session
):
    """Training mod WS: event_flag updates progress and triggers zone_update."""
    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        auth_ok = ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # initial zone_update (start node)

        # Get a valid event flag from the seed's event_map
        event_ids = auth_ok["seed"]["event_ids"]
        assert len(event_ids) > 0

        # Send first event flag (should be a zone transition)
        ws.send_json({"type": "event_flag", "flag_id": event_ids[0], "igt_ms": 3000})

        # Should receive leaderboard_update (broadcast to all including mod)
        msg = ws.receive_json()
        assert msg["type"] == "leaderboard_update"
        assert len(msg["participants"]) == 1
        p = msg["participants"][0]
        assert p["igt_ms"] == 3000
        assert p["current_layer"] >= 0

        # Then zone_update
        msg = ws.receive_json()
        assert msg["type"] == "zone_update"
        assert "node_id" in msg


def test_training_zone_history_includes_start_node(
    training_ws_client, training_session_data, async_session
):
    """Training mod WS: zone_history includes start node after first status_update."""
    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        auth_ok = ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # initial zone_update (start node)

        # First status_update should record start node in progress_nodes
        ws.send_json({"type": "status_update", "igt_ms": 1000, "death_count": 0})
        msg = ws.receive_json()
        assert msg["type"] == "leaderboard_update"
        p = msg["participants"][0]
        assert p["zone_history"] is not None
        assert len(p["zone_history"]) == 1
        assert p["zone_history"][0]["node_id"] == "limgrave_start"
        assert p["zone_history"][0]["igt_ms"] == 0

        # Send event_flag for stormveil_01 (event_ids[0]=limgrave_start,
        # event_ids[1]=stormveil_01, event_ids[-1]=finish_event)
        event_ids = auth_ok["seed"]["event_ids"]
        ws.send_json({"type": "event_flag", "flag_id": event_ids[1], "igt_ms": 5000})
        msg = ws.receive_json()
        assert msg["type"] == "leaderboard_update"
        p = msg["participants"][0]
        assert len(p["zone_history"]) == 2
        assert p["zone_history"][0]["node_id"] == "limgrave_start"
        assert p["zone_history"][1]["node_id"] == "stormveil_01"


def test_training_mod_websocket_invalid_token(training_ws_client, training_session_data):
    """Training mod WS: invalid token returns auth_error."""
    sid = training_session_data["session_id"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": "invalid_token_xyz"})
        response = ws.receive_json()
        assert response["type"] == "auth_error"


# =============================================================================
# Task 2: Anonymous training spectator WebSocket tests
# =============================================================================


def test_training_spectator_anonymous(training_ws_client, training_session_data):
    """Training spectator WS: anonymous connection receives initial state."""
    sid = training_session_data["session_id"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}/spectate") as ws:
        # Send auth without token (anonymous)
        ws.send_json({"type": "auth"})
        msg = ws.receive_json()
        assert msg["type"] == "race_state"
        assert msg["seed"] is not None
        assert len(msg["participants"]) == 1


def test_training_spectator_owner(training_ws_client, training_session_data):
    """Training spectator WS: owner with valid token receives initial state."""
    sid = training_session_data["session_id"]
    token = training_session_data["api_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}/spectate") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg["type"] == "race_state"
        assert msg["seed"] is not None


def test_training_spectator_anonymous_invalid_session(training_ws_client, training_session_data):
    """Training spectator WS: anonymous connection to non-existent session closes."""
    import uuid as _uuid

    fake_sid = str(_uuid.uuid4())

    with training_ws_client.websocket_connect(f"/ws/training/{fake_sid}/spectate") as ws:
        ws.send_json({"type": "auth"})
        # Should close with error code
        try:
            ws.receive_json()
            assert False, "Should have disconnected"
        except Exception:
            pass


# =============================================================================
# Public read access tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_training_session_anonymous(test_client, training_user, training_seed):
    """GET /api/training/{id} works without auth (public read-only)."""
    async with test_client as client:
        # Create session as authenticated user
        create_resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        session_id = create_resp.json()["id"]

        # Fetch without auth — should succeed
        resp = await client.get(f"/api/training/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph_json"] is not None
        assert data["user"]["twitch_username"] == "trainer"


@pytest.mark.asyncio
async def test_get_training_session_anonymous_not_found(test_client, training_user):
    """GET /api/training/{id} returns 404 for non-existent session (even anon)."""
    import uuid

    async with test_client as client:
        resp = await client.get(f"/api/training/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_abandon_training_session_requires_auth(test_client, training_user, training_seed):
    """POST /api/training/{id}/abandon still requires auth."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        session_id = create_resp.json()["id"]

        # Abandon without auth — should fail
        resp = await client.post(f"/api/training/{session_id}/abandon")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_pack_requires_auth(test_client, training_user, training_seed):
    """GET /api/training/{id}/pack still requires auth."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/training",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        session_id = create_resp.json()["id"]

        resp = await client.get(f"/api/training/{session_id}/pack")
        assert resp.status_code == 401
