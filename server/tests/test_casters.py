"""Tests for caster CRUD endpoints and mutual exclusion."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Race, RaceStatus, Seed, SeedStatus, User, UserRole


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
            twitch_id="org_caster",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="org_caster_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="player_caster",
            twitch_username="player1",
            twitch_display_name="Player One",
            api_token="player_caster_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def caster_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="caster_user",
            twitch_username="caster1",
            twitch_display_name="Caster One",
            api_token="caster_user_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def race_id(async_session, organizer):
    """Create a race directly in the DB and return its ID."""
    async with async_session() as db:
        seed = Seed(
            seed_number=777777,
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/test/seed_777777",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Caster Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.DRAFT,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return str(race.id)


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
# Add Caster Tests
# =============================================================================


@pytest.mark.asyncio
async def test_add_caster_success(test_client, organizer, caster_user, race_id):
    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["user"]["twitch_username"] == "caster1"
        assert "id" in data


@pytest.mark.asyncio
async def test_add_caster_requires_auth(test_client, race_id):
    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_add_caster_requires_organizer(test_client, player, caster_user, race_id):
    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_add_caster_user_not_found(test_client, organizer, race_id):
    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "nonexistent_user"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_caster_duplicate(test_client, organizer, caster_user, race_id):
    async with test_client as client:
        # Add caster first time
        await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        # Try to add again
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 409
        assert "already a caster" in response.json()["detail"]


# =============================================================================
# Remove Caster Tests
# =============================================================================


@pytest.mark.asyncio
async def test_remove_caster_success(test_client, organizer, caster_user, race_id):
    async with test_client as client:
        # Add caster
        add_response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        caster_id = add_response.json()["id"]

        # Remove caster
        response = await client.delete(
            f"/api/races/{race_id}/casters/{caster_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204


@pytest.mark.asyncio
async def test_remove_caster_not_found(test_client, organizer, race_id):
    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race_id}/casters/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 404


# =============================================================================
# Mutual Exclusion Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cannot_add_caster_who_is_participant(test_client, organizer, player, race_id):
    """A participant cannot be added as a caster."""
    async with test_client as client:
        # Add as participant first
        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Try to add as caster
        response = await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 409
        assert "participant" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cannot_add_participant_who_is_caster(test_client, organizer, caster_user, race_id):
    """A caster cannot be added as a participant."""
    async with test_client as client:
        # Add as caster first
        await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Try to add as participant
        response = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 409
        assert "caster" in response.json()["detail"]


# =============================================================================
# Casters in Race Detail Response
# =============================================================================


@pytest.mark.asyncio
async def test_casters_in_race_detail(test_client, organizer, caster_user, race_id):
    async with test_client as client:
        # Add caster
        await client.post(
            f"/api/races/{race_id}/casters",
            json={"twitch_username": "caster1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Get race detail
        response = await client.get(f"/api/races/{race_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["casters"]) == 1
        assert data["casters"][0]["user"]["twitch_username"] == "caster1"


@pytest.mark.asyncio
async def test_race_detail_empty_casters(test_client, organizer, race_id):
    """Race detail returns empty casters list when none exist."""
    async with test_client as client:
        response = await client.get(f"/api/races/{race_id}")
        assert response.status_code == 200
        assert response.json()["casters"] == []
