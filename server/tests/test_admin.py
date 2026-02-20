"""Test admin API endpoints."""

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
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
    """Create a temporary seed pool directory with zip files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()

        zip_path = pool_dir / "seed_abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "speedfog_abc123/graph.json",
                json.dumps({"total_layers": 10, "nodes": []}),
            )

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
async def test_discard_pool_endpoint(test_client, admin_user, async_session):
    """Discard endpoint marks available seeds as discarded."""
    # Add seeds directly to database
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="d001",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d001.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        db.add(
            Seed(
                seed_number="d002",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d002.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        db.add(
            Seed(
                seed_number="d003",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d003.zip",
                status=SeedStatus.CONSUMED,
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/discard",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # discard_pool marks both AVAILABLE and CONSUMED seeds as DISCARDED
        assert data["discarded"] == 3
        assert data["pool_name"] == "training_standard"

        # Verify stats show updated counts
        stats_response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert stats_response.status_code == 200
        pools = stats_response.json()["pools"]
        assert pools["training_standard"]["available"] == 0
        assert pools["training_standard"]["discarded"] == 3
        assert pools["training_standard"]["consumed"] == 0


@pytest.mark.asyncio
async def test_discard_pool_requires_admin(test_client, regular_user):
    """Discard endpoint requires admin role."""
    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/discard",
            json={"pool_name": "standard"},
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


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


# =============================================================================
# User Management Tests
# =============================================================================


@pytest.fixture
async def organizer_user(async_session):
    """Create an organizer user."""
    async with async_session() as db:
        user = User(
            twitch_id="org456",
            twitch_username="organizer_user",
            api_token="organizer_test_token",
            role=UserRole.ORGANIZER,
            last_seen=datetime(2026, 1, 15, tzinfo=UTC),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_list_users_requires_admin(test_client, regular_user):
    """List users requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_forbidden_for_organizer(test_client, organizer_user):
    """Organizer role cannot access admin endpoints."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {organizer_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_works_for_admin(test_client, admin_user, regular_user, organizer_user):
    """Admin can list all users."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3
        usernames = {u["twitch_username"] for u in data}
        assert "admin_user" in usernames
        assert "regular_user" in usernames
        assert "organizer_user" in usernames


@pytest.mark.asyncio
async def test_update_user_role_to_organizer(test_client, admin_user, regular_user):
    """Admin can promote user to organizer."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{regular_user.id}",
            json={"role": "organizer"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "organizer"


@pytest.mark.asyncio
async def test_update_user_role_to_user(test_client, admin_user, organizer_user):
    """Admin can demote organizer to user."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{organizer_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "user"


@pytest.mark.asyncio
async def test_update_user_role_to_admin_rejected(test_client, admin_user, regular_user):
    """Cannot set admin role via API."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{regular_user.id}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_user_requires_admin(test_client, regular_user, organizer_user):
    """Regular users cannot update roles."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{organizer_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_admin_role_rejected(test_client, admin_user):
    """Cannot change an admin's role."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{admin_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 400
        assert "admin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_nonexistent_user(test_client, admin_user):
    """Updating a nonexistent user returns 404."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/users/00000000-0000-0000-0000-000000000000",
            json={"role": "organizer"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 404


# =============================================================================
# Global Activity Feed Tests
# =============================================================================


@pytest.fixture
async def activity_data(async_session, admin_user, regular_user):
    """Create activity data: a race with participant, organizer, caster, and a training session."""
    async with async_session() as db:
        seed = Seed(
            seed_number="activity_seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Activity Race",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=regular_user.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=120000,
            death_count=5,
        )
        db.add(participant)

        caster = Caster(
            race_id=race.id,
            user_id=regular_user.id,
        )
        db.add(caster)

        training = TrainingSession(
            user_id=regular_user.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=90000,
            death_count=3,
        )
        db.add(training)

        await db.commit()
        return {"race": race, "participant": participant, "caster": caster, "training": training}


@pytest.mark.asyncio
async def test_activity_requires_admin(test_client, regular_user):
    """Activity endpoint requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_activity_requires_auth(test_client):
    """Activity endpoint requires authentication."""
    async with test_client as client:
        response = await client.get("/api/admin/activity")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_activity_works_for_admin(test_client, admin_user, activity_data):
    """Admin can access the global activity feed."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "has_more" in data
        # 1 race_participant + 1 race_organizer + 1 race_caster + 1 training = 4
        assert data["total"] == 4
        types = {i["type"] for i in data["items"]}
        assert "race_participant" in types
        assert "race_organizer" in types
        assert "race_caster" in types
        assert "training" in types


@pytest.mark.asyncio
async def test_activity_items_include_user(test_client, admin_user, activity_data):
    """Activity items include user info."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert "user" in item
            user = item["user"]
            assert "id" in user
            assert "twitch_username" in user


@pytest.mark.asyncio
async def test_activity_pagination(test_client, admin_user, activity_data):
    """Activity endpoint supports offset and limit."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity?limit=2&offset=0",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 4
        assert data["has_more"] is True

        response2 = await client.get(
            "/api/admin/activity?limit=2&offset=2",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        data2 = response2.json()
        assert len(data2["items"]) == 2
        assert data2["has_more"] is False
