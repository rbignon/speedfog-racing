"""Test admin API endpoints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Seed, SeedStatus, User, UserRole


@pytest.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Create async session factory."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return async_session_maker


@pytest.fixture
async def admin_user(async_session):
    """Create an admin user."""
    async with async_session() as db:
        user = User(
            twitch_id="admin123",
            twitch_username="admin_user",
            api_token="admin_test_token",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def regular_user(async_session):
    """Create a regular user."""
    async with async_session() as db:
        user = User(
            twitch_id="user123",
            twitch_username="regular_user",
            api_token="user_test_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
def seed_pool_dir():
    """Create a temporary seed pool directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()

        seed_dir = pool_dir / "seed_abc123"
        seed_dir.mkdir()
        (seed_dir / "graph.json").write_text(json.dumps({"total_layers": 10, "nodes": []}))

        yield tmpdir


@pytest.fixture
def test_client(async_session):
    """Create test client with async database override."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()


# =============================================================================
# Admin Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_requires_auth(test_client):
    """Scan endpoint requires authentication."""
    async with test_client as client:
        response = await client.post("/api/admin/seeds/scan")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_scan_requires_admin(test_client, regular_user):
    """Scan endpoint requires admin role."""
    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/scan",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_scan_works_for_admin(test_client, admin_user, seed_pool_dir):
    """Scan endpoint works for admin users."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir

        async with test_client as client:
            response = await client.post(
                "/api/admin/seeds/scan",
                headers={"Authorization": f"Bearer {admin_user.api_token}"},
                json={"pool_name": "standard"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["added"] == 1
            assert data["pool_name"] == "standard"


@pytest.mark.asyncio
async def test_stats_requires_admin(test_client, regular_user):
    """Stats endpoint requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_stats_works_for_admin(test_client, admin_user, async_session):
    """Stats endpoint returns correct data for admin."""
    # Add a seed directly to database
    async with async_session() as db:
        seed = Seed(
            seed_number="s999",
            pool_name="standard",
            graph_json={"total_layers": 5},
            total_layers=5,
            folder_path="/test/seed_999",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "pools" in data
        assert "standard" in data["pools"]
        assert data["pools"]["standard"]["available"] == 1
