"""Tests for scheduled_at feature on races."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Seed,
    SeedStatus,
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


@pytest.fixture
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="sched_org",
            twitch_username="sched_organizer",
            twitch_display_name="Schedule Organizer",
            api_token="sched_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="sched_player",
            twitch_username="sched_player",
            twitch_display_name="Schedule Player",
            api_token="sched_player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="sched_seed_1",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/sched_seed.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
async def seed2(async_session):
    """Second available seed for multi-race tests."""
    async with async_session() as db:
        s = Seed(
            seed_number="sched_seed_2",
            pool_name="standard",
            graph_json={"total_layers": 8, "nodes": []},
            total_layers=8,
            folder_path="/test/sched_seed2.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


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


def _future(hours: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _past(hours: int = 2) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


# =============================================================================
# Create with scheduled_at
# =============================================================================


@pytest.mark.asyncio
async def test_create_race_with_scheduled_at(test_client, organizer, seed):
    """Creating a race with a future scheduled_at succeeds."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={
                "name": "Scheduled Race",
                "pool_name": "standard",
                "scheduled_at": _future(24),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Scheduled Race"
        assert data["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_create_race_without_scheduled_at(test_client, organizer, seed):
    """Creating a race without scheduled_at defaults to null."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Unscheduled Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        assert response.json()["scheduled_at"] is None


@pytest.mark.asyncio
async def test_create_race_past_scheduled_at_rejected(test_client, organizer, seed):
    """Creating a race with a past scheduled_at returns 400."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={
                "name": "Past Race",
                "pool_name": "standard",
                "scheduled_at": _past(2),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "past" in response.json()["detail"].lower()


# =============================================================================
# PATCH endpoint
# =============================================================================


@pytest.mark.asyncio
async def test_patch_scheduled_at(test_client, organizer, seed):
    """Organizer can update scheduled_at on a setup race."""
    async with test_client as client:
        # Create race
        create_resp = await client.post(
            "/api/races",
            json={"name": "Patch Test", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        # Patch
        future = _future(48)
        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": future},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_patch_clear_scheduled_at(test_client, organizer, seed):
    """Organizer can clear scheduled_at by setting it to null."""
    async with test_client as client:
        # Create with scheduled_at
        create_resp = await client.post(
            "/api/races",
            json={
                "name": "Clear Test",
                "pool_name": "standard",
                "scheduled_at": _future(24),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]
        assert create_resp.json()["scheduled_at"] is not None

        # Clear
        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": None},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["scheduled_at"] is None


@pytest.mark.asyncio
async def test_patch_past_scheduled_at_rejected(test_client, organizer, seed):
    """Patching with a past scheduled_at returns 400."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Past Patch", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": _past(2)},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 400
        assert "past" in patch_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_non_organizer_rejected(test_client, organizer, player, seed):
    """Non-organizer cannot PATCH a race."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Auth Test", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": _future(24)},
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert patch_resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_running_race_rejected(test_client, organizer, seed):
    """Cannot PATCH a running race."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Running Patch", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        # Release seeds and start the race
        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": _future(24)},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 400
        assert "setup" in patch_resp.json()["detail"].lower()


# =============================================================================
# List sort order
# =============================================================================


@pytest.mark.asyncio
async def test_list_scheduled_races_sorted(test_client, organizer, seed, seed2):
    """Open races with scheduled_at come sorted by scheduled_at ASC."""
    async with test_client as client:
        # Create race with later schedule
        resp1 = await client.post(
            "/api/races",
            json={
                "name": "Later Race",
                "pool_name": "standard",
                "scheduled_at": _future(48),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        resp1.json()["id"]

        # Create race with earlier schedule
        resp2 = await client.post(
            "/api/races",
            json={
                "name": "Sooner Race",
                "pool_name": "standard",
                "scheduled_at": _future(2),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        resp2.json()["id"]

        # List all races
        list_resp = await client.get("/api/races")
        assert list_resp.status_code == 200
        races = list_resp.json()["races"]
        names = [r["name"] for r in races]

        # "Sooner Race" should come before "Later Race"
        sooner_idx = names.index("Sooner Race")
        later_idx = names.index("Later Race")
        assert sooner_idx < later_idx


# =============================================================================
# Race detail includes scheduled_at
# =============================================================================


@pytest.mark.asyncio
async def test_race_detail_includes_scheduled_at(test_client, organizer, seed):
    """Race detail response includes scheduled_at field."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={
                "name": "Detail Test",
                "pool_name": "standard",
                "scheduled_at": _future(24),
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        detail_resp = await client.get(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert detail_resp.status_code == 200
        assert detail_resp.json()["scheduled_at"] is not None
