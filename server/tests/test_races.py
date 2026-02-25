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
        assert data["status"] == "setup"
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
            name="Setup Race",
            organizer_id=organizer.id,
            seed_id=seed1.id,
            status=RaceStatus.SETUP,
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
        # Filter by setup
        response = await client.get("/api/races?status=setup")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1
        assert races[0]["name"] == "Setup Race"

        # Filter by running
        response = await client.get("/api/races?status=running")
        races = response.json()["races"]
        assert len(races) == 1
        assert races[0]["name"] == "Running Race"


@pytest.mark.asyncio
async def test_list_finished_races_includes_placement(test_client, organizer, async_session):
    """Finished races include participant placement sorted by igt_ms."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_place",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/place",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Finished Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        # Player who finished second (slower)
        player2 = User(
            twitch_id="p2",
            twitch_username="player2",
            twitch_display_name="Player Two",
            api_token="token_p2",
        )
        # Player who finished first (faster)
        player1 = User(
            twitch_id="p1",
            twitch_username="player1_fast",
            twitch_display_name="Player One",
            api_token="token_p1",
        )
        # Player who abandoned (no placement)
        player3 = User(
            twitch_id="p3",
            twitch_username="player3",
            twitch_display_name="Player Three",
            api_token="token_p3",
        )
        db.add_all([player1, player2, player3])
        await db.flush()

        p1 = Participant(
            race_id=race.id,
            user_id=player1.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=100000,
            death_count=2,
        )
        p2 = Participant(
            race_id=race.id,
            user_id=player2.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=200000,
            death_count=5,
        )
        p3 = Participant(
            race_id=race.id,
            user_id=player3.id,
            status=ParticipantStatus.ABANDONED,
            igt_ms=50000,
            death_count=1,
        )
        db.add_all([p1, p2, p3])
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/races?status=finished")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1

        previews = races[0]["participant_previews"]
        assert len(previews) == 3

        # First: fastest finished player (placement 1)
        assert previews[0]["twitch_username"] == "player1_fast"
        assert previews[0]["placement"] == 1

        # Second: slower finished player (placement 2)
        assert previews[1]["twitch_username"] == "player2"
        assert previews[1]["placement"] == 2

        # Third: abandoned player (no placement)
        assert previews[2]["twitch_username"] == "player3"
        assert previews[2]["placement"] is None


@pytest.mark.asyncio
async def test_list_setup_races_no_placement(test_client, organizer, async_session):
    """Setup races have participant previews without placement (capped at 5)."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_setup",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/setup",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Setup Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
        )
        db.add(race)
        await db.flush()

        for i in range(7):
            user = User(
                twitch_id=f"setup_p{i}",
                twitch_username=f"setup_player{i}",
                api_token=f"token_setup_{i}",
            )
            db.add(user)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    status=ParticipantStatus.REGISTERED,
                    igt_ms=0,
                    death_count=0,
                )
            )
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/races?status=setup")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1

        previews = races[0]["participant_previews"]
        # Capped at 5 for non-finished races
        assert len(previews) == 5
        # No placement on setup races
        for p in previews:
            assert p["placement"] is None


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

        # Release seeds first
        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

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
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
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

        # Release seeds first
        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

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

        # Release seeds
        await client.post(
            f"/api/races/{race_id}/release-seeds",
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
    """Resetting a RUNNING race sets status to setup and clears participant progress."""
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
        assert data["status"] == "setup"
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
    """Resetting a FINISHED race sets status to setup and clears participant progress."""
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
        assert data["status"] == "setup"
        assert data["started_at"] is None


@pytest.mark.asyncio
async def test_reset_race_from_setup_fails(test_client, organizer, seed):
    """Resetting a SETUP race returns 400."""
    async with test_client as client:
        create_response = await client.post(
            "/api/races",
            json={"name": "Setup Race"},
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
async def test_finish_setup_race_fails(test_client, organizer, async_session):
    """Force-finishing a SETUP race returns 400."""
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
            name="Setup Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
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
            status=RaceStatus.SETUP,
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


# =============================================================================
# Seed Re-roll Tests
# =============================================================================


@pytest.mark.asyncio
async def test_reroll_seed_setup(test_client, organizer, async_session):
    """Re-rolling seed on a SETUP race assigns a new seed and releases the old one."""
    async with async_session() as db:
        seed_a = Seed(
            seed_number="reroll_a",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/reroll_a",
            status=SeedStatus.CONSUMED,
        )
        seed_b = Seed(
            seed_number="reroll_b",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/reroll_b",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_a, seed_b])
        await db.flush()

        race = Race(
            name="Reroll Test Race",
            organizer_id=organizer.id,
            seed_id=seed_a.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)
        seed_a_id = seed_a.id
        seed_b_id = seed_b.id

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["seed_total_layers"] == 7

    # Verify old seed released, new seed consumed
    async with async_session() as db:
        from sqlalchemy import select

        result_a = await db.execute(select(Seed).where(Seed.id == seed_a_id))
        assert result_a.scalar_one().status == SeedStatus.AVAILABLE

        result_b = await db.execute(select(Seed).where(Seed.id == seed_b_id))
        assert result_b.scalar_one().status == SeedStatus.CONSUMED


@pytest.mark.asyncio
async def test_reroll_seed_running_fails(test_client, organizer, async_session):
    """Cannot re-roll seed on a RUNNING race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="reroll_run",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/reroll_run",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Running Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_reroll_seed_non_organizer_fails(test_client, organizer, player, async_session):
    """Non-organizer cannot re-roll seed."""
    async with async_session() as db:
        seed = Seed(
            seed_number="reroll_noauth",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/reroll_noauth",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Auth Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_reroll_seed_no_available_seeds(test_client, organizer, async_session):
    """Re-roll fails gracefully when pool is exhausted."""
    async with async_session() as db:
        seed = Seed(
            seed_number="reroll_only",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/reroll_only",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="No Seeds Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "No available seeds" in response.json()["detail"]


# =============================================================================
# Private races
# =============================================================================


@pytest.mark.asyncio
async def test_create_private_race(test_client, organizer, seed):
    """Creating a race with is_public=false succeeds."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Secret Race", "is_public": False},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Secret Race"
        assert data["is_public"] is False


@pytest.mark.asyncio
async def test_create_race_default_public(test_client, organizer, seed):
    """Races are public by default."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Public Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        assert response.json()["is_public"] is True


@pytest.mark.asyncio
async def test_private_race_hidden_from_listing(test_client, organizer, async_session):
    """Private races do not appear in the public listing."""
    async with async_session() as db:
        public_seed = Seed(
            seed_number="pub1",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/pub",
            status=SeedStatus.CONSUMED,
        )
        private_seed = Seed(
            seed_number="priv1",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/priv",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([public_seed, private_seed])
        await db.flush()

        public_race = Race(
            name="Public Race",
            organizer_id=organizer.id,
            seed_id=public_seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
        )
        private_race = Race(
            name="Private Race",
            organizer_id=organizer.id,
            seed_id=private_seed.id,
            status=RaceStatus.SETUP,
            is_public=False,
        )
        db.add_all([public_race, private_race])
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/races")
        assert response.status_code == 200
        races = response.json()["races"]
        names = [r["name"] for r in races]
        assert "Public Race" in names
        assert "Private Race" not in names


@pytest.mark.asyncio
async def test_private_race_accessible_by_direct_link(test_client, organizer, async_session):
    """Private races are still accessible via their direct URL."""
    async with async_session() as db:
        seed = Seed(
            seed_number="direct1",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/direct",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Hidden Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=False,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.get(f"/api/races/{race_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Hidden Race"
        assert response.json()["is_public"] is False


@pytest.mark.asyncio
async def test_update_race_toggle_visibility(test_client, organizer, seed):
    """Organizer can toggle is_public via PATCH."""
    async with test_client as client:
        # Create a public race
        create_resp = await client.post(
            "/api/races",
            json={"name": "Toggle Race"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert create_resp.status_code == 201
        race_id = create_resp.json()["id"]
        assert create_resp.json()["is_public"] is True

        # Make it private
        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"is_public": False},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_public"] is False

        # Make it public again
        patch_resp = await client.patch(
            f"/api/races/{race_id}",
            json={"is_public": True},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_public"] is True


@pytest.mark.asyncio
async def test_abandoned_participant_status_update_ignored(
    async_session,
    organizer,
    player,
):
    """status_update from an ABANDONED participant is silently dropped."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abandon_1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": [], "event_map": {}},
            total_layers=5,
            folder_path="/test/abandon1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Abandon Test",
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
            status=ParticipantStatus.ABANDONED,
            igt_ms=100000,
            death_count=5,
        )
        db.add(participant)
        await db.commit()
        p_id = participant.id

    # Verify the participant is still ABANDONED and IGT unchanged
    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.ABANDONED
        assert p.igt_ms == 100000


# =============================================================================
# Abandon Race Tests
# =============================================================================


@pytest.mark.asyncio
async def test_abandon_race_success(test_client, organizer, player, async_session):
    """Player can abandon a running race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/abn1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Abandon Race",
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
            igt_ms=150000,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # Single participant abandoned → auto-finish kicks in
        assert data["status"] == "finished"


@pytest.mark.asyncio
async def test_abandon_race_not_participant(test_client, organizer, player, async_session):
    """Non-participant cannot abandon a race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn2",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/abn2",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="No Abandon",
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
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_abandon_race_not_running(test_client, organizer, player, async_session):
    """Cannot abandon a race that is not running."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn3",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/abn3",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Setup Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.REGISTERED,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_abandon_race_already_finished(test_client, organizer, player, async_session):
    """Cannot abandon if already finished."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn4",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/abn4",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Finished Player",
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
            status=ParticipantStatus.FINISHED,
            igt_ms=300000,
            finished_at=datetime.now(UTC),
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_abandon_race_auto_finishes_when_last(test_client, organizer, player, async_session):
    """When last playing participant abandons, race auto-finishes."""
    async with async_session() as db:
        player2 = User(
            twitch_id="p2_abn",
            twitch_username="player2_abn",
            api_token="player2_abn_token",
            role=UserRole.USER,
        )
        db.add(player2)
        await db.flush()
        seed = Seed(
            seed_number="s_abn5",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/abn5",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Auto Finish",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        p1 = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=150000,
        )
        p2 = Participant(
            race_id=race.id,
            user_id=player2.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=200000,
            finished_at=datetime.now(UTC),
        )
        db.add_all([p1, p2])
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "finished"
