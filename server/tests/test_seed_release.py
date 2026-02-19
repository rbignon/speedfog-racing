"""Tests for seed release workflow."""

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Race,
    RaceStatus,
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
            twitch_id="org123",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="organizer_token",
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
            twitch_id="player123",
            twitch_username="player1",
            twitch_display_name="Player One",
            api_token="player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
def seed_zip_context():
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "seed_abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("speedfog_abc123/lib/speedfog_race_mod.dll", "mock dll")
            zf.writestr("speedfog_abc123/ModEngine/config.toml", "[config]")
            zf.writestr(
                "speedfog_abc123/graph.json",
                json.dumps({"total_layers": 10, "nodes": []}),
            )
            zf.writestr("speedfog_abc123/launch_speedfog.bat", "@echo off\necho Launch")
        yield zip_path


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="abc123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/seed_123456.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
async def seed_with_zip(async_session, seed_zip_context):
    async with async_session() as db:
        s = Seed(
            seed_number="abc123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path=str(seed_zip_context),
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


# =============================================================================
# Release Seeds Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_release_seeds_organizer(test_client, organizer, seed):
    """Organizer can release seeds for a SETUP race."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Release Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["seeds_released_at"] is not None


@pytest.mark.asyncio
async def test_release_seeds_non_organizer_forbidden(test_client, organizer, player, seed):
    """Non-organizer cannot release seeds."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Release Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_release_seeds_already_released(test_client, organizer, seed):
    """Cannot release seeds twice."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Release Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        resp = await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_release_seeds_not_setup(test_client, organizer, async_session):
    """Cannot release seeds for non-SETUP race."""
    async with async_session() as db:
        s = Seed(
            seed_number="sr_run",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/sr_run",
            status=SeedStatus.CONSUMED,
        )
        db.add(s)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=s.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        resp = await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400


# =============================================================================
# Download Gating Tests
# =============================================================================


@pytest.mark.asyncio
async def test_download_blocked_before_release(test_client, organizer, player, seed):
    """Participant cannot download before seeds are released."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Gate Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        resp = await client.get(
            f"/api/races/{race_id}/my-seed-pack",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 403
        assert "released" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_download_allowed_after_release(
    test_client, organizer, player, seed_with_zip, seed_zip_context
):
    """Participant can download after seeds are released."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Gate Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Release seeds
        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Download after release
        resp = await client.get(
            f"/api/races/{race_id}/my-seed-pack",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"


# =============================================================================
# Reroll Resets Release Tests
# =============================================================================


@pytest.mark.asyncio
async def test_reroll_clears_seeds_released(test_client, organizer, async_session):
    """Rerolling after release resets seeds_released_at to NULL."""
    async with async_session() as db:
        seed_a = Seed(
            seed_number="sr_a",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/sr_a",
            status=SeedStatus.CONSUMED,
        )
        seed_b = Seed(
            seed_number="sr_b",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/sr_b",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_a, seed_b])
        await db.flush()

        race = Race(
            name="Reroll Release Test",
            organizer_id=organizer.id,
            seed_id=seed_a.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        resp = await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.json()["seeds_released_at"] is not None

        resp = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["seeds_released_at"] is None


# =============================================================================
# Start Race Requires Release Tests
# =============================================================================


@pytest.mark.asyncio
async def test_start_blocked_before_release(test_client, organizer, seed):
    """Cannot start race before seeds are released."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Start Gate Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400
        assert "release" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_allowed_after_release(test_client, organizer, seed):
    """Can start race after seeds are released."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Start Gate Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        resp = await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
