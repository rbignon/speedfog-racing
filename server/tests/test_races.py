"""Test race API endpoints."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Race, RaceStatus, Seed, SeedStatus, User, UserRole


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
            role=UserRole.USER,
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
async def seed(async_session):
    """Create an available seed."""
    async with async_session() as db:
        seed = Seed(
            seed_number=123456,
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/seed_123456",
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
            seed_number=1,
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/1",
            status=SeedStatus.CONSUMED,
        )
        seed2 = Seed(
            seed_number=2,
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

        # Start race
        scheduled = datetime.now(UTC).isoformat()
        response = await client.post(
            f"/api/races/{race_id}/start",
            json={"scheduled_start": scheduled},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "countdown"


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

        scheduled = datetime.now(UTC).isoformat()
        await client.post(
            f"/api/races/{race_id}/start",
            json={"scheduled_start": scheduled},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Try to start again
        response = await client.post(
            f"/api/races/{race_id}/start",
            json={"scheduled_start": scheduled},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "already started" in response.json()["detail"]
