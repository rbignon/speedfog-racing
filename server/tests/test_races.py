"""Test race API endpoints."""

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
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)


@pytest.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Create async session factory."""
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def organizer(async_session):
    """Create an organizer user."""
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
    """Create a player user."""
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
    """Create a temporary seed zip with mock content."""
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
    """Create an available seed."""
    async with async_session() as db:
        seed = Seed(
            seed_number="abc123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/seed_123456.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return seed


@pytest.fixture
async def seed_with_zip(async_session, seed_zip_context):
    """Create an available seed with a real zip file."""
    async with async_session() as db:
        seed = Seed(
            seed_number="abc123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path=str(seed_zip_context),
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return seed


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
# Race Creation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_race_requires_auth(test_client):
    """Creating a race requires authentication."""
    async with test_client as client:
        response = await client.post("/api/races", json={"name": "Test Race"})
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_race_success(test_client, organizer, seed):
    """Creating a race succeeds with valid data."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Test Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Race"
        assert data["status"] == "draft"
        assert data["organizer"]["twitch_username"] == "organizer"
        assert data["pool_name"] == "standard"


@pytest.mark.asyncio
async def test_create_race_forbidden_for_user_role(test_client, player, seed):
    """Users with USER role cannot create races."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Test Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_race_allowed_for_organizer(test_client, organizer, seed):
    """Users with ORGANIZER role can create races."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Organizer Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Organizer Race"


@pytest.mark.asyncio
async def test_create_race_no_seeds_available(test_client, organizer):
    """Creating a race fails if no seeds are available."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Test Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "No available seeds" in response.json()["detail"]


# =============================================================================
# Race Listing Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_races_empty(test_client):
    """Listing races returns empty list when none exist."""
    async with test_client as client:
        response = await client.get("/api/races")
        assert response.status_code == 200
        assert response.json()["races"] == []


@pytest.mark.asyncio
async def test_list_races_with_races(test_client, organizer, seed):
    """Listing races returns created races."""
    async with test_client as client:
        # Create a race first
        await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        response = await client.get("/api/races")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1
        assert races[0]["name"] == "Test Race"


@pytest.mark.asyncio
async def test_list_races_filter_by_status(test_client, organizer, async_session):
    """Listing races can filter by status."""
    # Create seeds and races with different statuses
    async with async_session() as db:
        seed1 = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/1",
            status=SeedStatus.CONSUMED,
        )
        seed2 = Seed(
            seed_number="s2",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/2",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([seed1, seed2])
        await db.flush()

        race1 = Race(
            name="Draft Race",
            organizer_id=organizer.id,
            seed_id=seed1.id,
            status=RaceStatus.DRAFT,
        )
        race2 = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed2.id,
            status=RaceStatus.RUNNING,
        )
        db.add_all([race1, race2])
        await db.commit()

    async with test_client as client:
        # Filter by draft
        response = await client.get("/api/races?status=draft")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1
        assert races[0]["name"] == "Draft Race"

        # Filter by running
        response = await client.get("/api/races?status=running")
        races = response.json()["races"]
        assert len(races) == 1
        assert races[0]["name"] == "Running Race"


# =============================================================================
# Race Details Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_race_not_found(test_client):
    """Getting a nonexistent race returns 404."""
    async with test_client as client:
        response = await client.get("/api/races/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_race_success(test_client, organizer, seed):
    """Getting a race returns its details."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Get race
        response = await client.get(f"/api/races/{race_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Race"
        assert data["participants"] == []
        assert data["seed_total_layers"] == 10


# =============================================================================
# Participant Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_add_participant_requires_auth(test_client, organizer, seed):
    """Adding a participant requires authentication."""
    async with test_client as client:
        # Create race first
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Try to add participant without auth
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_add_participant_requires_organizer(test_client, organizer, player, seed):
    """Adding a participant requires being the organizer."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Try to add participant as non-organizer
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "someone"},
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_add_existing_user_as_participant(test_client, organizer, player, seed):
    """Adding an existing user creates a participant."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Add participant
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["participant"] is not None
        assert data["participant"]["user"]["twitch_username"] == "player1"
        assert data["invite"] is None


@pytest.mark.asyncio
async def test_add_nonexistent_user_creates_invite(test_client, organizer, seed):
    """Adding a nonexistent user creates an invite."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Add nonexistent user
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "unknown_player"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["participant"] is None
        assert data["invite"] is not None
        assert data["invite"]["twitch_username"] == "unknown_player"


@pytest.mark.asyncio
async def test_cannot_add_duplicate_participant(test_client, organizer, player, seed):
    """Cannot add the same user twice."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Add participant
        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Try to add again
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "already a participant" in response.json()["detail"]


@pytest.mark.asyncio
async def test_remove_participant(test_client, organizer, player, seed):
    """Organizer can remove a participant."""
    async with test_client as client:
        # Create race and add participant
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        add_response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        participant_id = add_response.json()["participant"]["id"]

        # Remove participant
        response = await client.delete(
            f"/api/races/{race_id}/participants/{participant_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

        # Verify removed
        race_response = await client.get(f"/api/races/{race_id}")
        assert len(race_response.json()["participants"]) == 0


# =============================================================================
# Race Start Tests
# =============================================================================


@pytest.mark.asyncio
async def test_start_race(test_client, organizer, seed):
    """Organizer can start a race."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Verify started_at is null before start
        get_response = await client.get(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert get_response.json()["started_at"] is None

        # Start race
        response = await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["started_at"] is not None


@pytest.mark.asyncio
async def test_cannot_start_already_started_race(test_client, organizer, seed):
    """Cannot start a race that's already started."""
    async with test_client as client:
        # Create and start race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Try to start again
        response = await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "already started" in response.json()["detail"]


# =============================================================================
# Seed Pack Download Tests
# =============================================================================


@pytest.mark.asyncio
async def test_download_seed_pack_invalid_token(test_client, organizer, seed):
    """Download seed pack returns 404 for invalid token."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Try to download with invalid token (as organizer)
        response = await client.get(
            f"/api/races/{race_id}/download/invalid_token",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_my_seed_pack_success(
    test_client, organizer, player, seed_with_zip, seed_zip_context
):
    """Download my seed pack generates on-demand and returns zip."""
    async with test_client as client:
        # Create race
        create_response = await client.post(
            "/api/races",
            json={"name": "Test Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        # Add participant
        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Download as participant (no need to generate first)
        response = await client.get(
            f"/api/races/{race_id}/my-seed-pack",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "speedfog_player1.zip" in response.headers["content-disposition"]


# =============================================================================
# Race Reset Tests
# =============================================================================


@pytest.mark.asyncio
async def test_reset_race_from_running(test_client, organizer, player, async_session):
    """Resetting a RUNNING race sets status to open and clears participant progress."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s900",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/900",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.PLAYING,
            current_zone="limgrave_start",
            current_layer=3,
            igt_ms=120000,
            death_count=5,
            zone_history=[{"zone": "limgrave_start", "igt_ms": 0}],
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reset",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "open"
        assert data["started_at"] is None

        # Verify participant was reset by fetching race detail
        detail_response = await client.get(f"/api/races/{race_id}")
        detail = detail_response.json()
        p = detail["participants"][0]
        assert p["status"] == "registered"
        assert p["current_layer"] == 0
        assert p["igt_ms"] == 0
        assert p["death_count"] == 0


@pytest.mark.asyncio
async def test_reset_race_from_finished(test_client, organizer, player, async_session):
    """Resetting a FINISHED race sets status to open and clears participant progress."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s901",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/901",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Finished Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.FINISHED,
            current_zone="erdtree",
            current_layer=10,
            igt_ms=600000,
            death_count=20,
            finished_at=datetime.now(UTC),
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reset",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "open"
        assert data["started_at"] is None


@pytest.mark.asyncio
async def test_reset_race_from_draft_fails(test_client, organizer, seed):
    """Resetting a DRAFT race returns 400."""
    async with test_client as client:
        create_response = await client.post(
            "/api/races",
            json={"name": "Draft Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        response = await client.post(
            f"/api/races/{race_id}/reset",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "running or finished" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reset_race_from_open_fails(test_client, organizer, async_session):
    """Resetting an OPEN race returns 400."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s902",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/902",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Open Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.OPEN,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reset",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "running or finished" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reset_race_non_organizer(test_client, organizer, player, async_session):
    """Non-organizer cannot reset a race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s903",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/903",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reset",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


# =============================================================================
# Race Force Finish Tests
# =============================================================================


@pytest.mark.asyncio
async def test_finish_running_race(test_client, organizer, player, async_session):
    """Force-finishing a RUNNING race sets status to finished and preserves progress."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s910",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/910",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.PLAYING,
            current_zone="liurnia_lake",
            current_layer=5,
            igt_ms=300000,
            death_count=10,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/finish",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "finished"

        # Verify participants keep their progress
        detail_response = await client.get(f"/api/races/{race_id}")
        detail = detail_response.json()
        p = detail["participants"][0]
        assert p["current_layer"] == 5
        assert p["igt_ms"] == 300000
        assert p["death_count"] == 10


@pytest.mark.asyncio
async def test_finish_open_race_fails(test_client, organizer, async_session):
    """Force-finishing an OPEN race returns 400."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s911",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/911",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Open Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.OPEN,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/finish",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "running" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_finish_race_non_organizer(test_client, organizer, player, async_session):
    """Non-organizer cannot force-finish a race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s912",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/912",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/finish",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


# =============================================================================
# Race Delete Tests
# =============================================================================


@pytest.mark.asyncio
async def test_delete_race(test_client, organizer, seed):
    """Deleting a race returns 204, and subsequent GET returns 404."""
    async with test_client as client:
        create_response = await client.post(
            "/api/races",
            json={"name": "Doomed Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        response = await client.delete(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

        # Verify the race is gone
        get_response = await client.get(f"/api/races/{race_id}")
        assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_race_non_organizer(test_client, organizer, player, seed):
    """Non-organizer cannot delete a race."""
    async with test_client as client:
        create_response = await client.post(
            "/api/races",
            json={"name": "Protected Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_response.json()["id"]

        response = await client.delete(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_race_releases_seed(test_client, organizer, async_session):
    """Deleting a race releases the seed back to available status."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s920",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/920",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Race With Seed",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.DRAFT,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)
        seed_id = seed.id

    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

    # Verify seed is released
    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(Seed).where(Seed.id == seed_id))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_delete_started_race_keeps_seed_consumed(test_client, organizer, async_session):
    """Deleting a race that was started keeps the seed consumed."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s921",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/921",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Started Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)
        seed_id = seed.id

    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

    # Seed should stay consumed — players already saw it
    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(Seed).where(Seed.id == seed_id))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.CONSUMED
