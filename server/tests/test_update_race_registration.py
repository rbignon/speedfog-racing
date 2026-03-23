"""Tests for updating open_registration and max_participants via PATCH /races/{id}."""

import pytest
from sqlalchemy import update
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
            twitch_id="upd_reg_org",
            twitch_username="upd_reg_organizer",
            twitch_display_name="Organizer",
            api_token="upd_reg_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="upd_reg_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/upd_reg_seed.zip",
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


async def _create_race(client, token, **kwargs):
    """Helper to create a race with default settings."""
    payload = {"name": "Test Race", "pool_name": "standard"}
    payload.update(kwargs)
    response = await client.post(
        "/api/races",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()


# =============================================================================
# Update max_participants in SETUP
# =============================================================================


@pytest.mark.asyncio
async def test_update_max_participants_in_setup(test_client, organizer, seed):
    """Organizer can update max_participants on a SETUP race."""
    async with test_client as client:
        race = await _create_race(client, organizer.api_token)

        response = await client.patch(
            f"/api/races/{race['id']}",
            json={"max_participants": 10},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        assert response.json()["max_participants"] == 10


# =============================================================================
# Update open_registration + max_participants together
# =============================================================================


@pytest.mark.asyncio
async def test_update_open_registration_and_max_participants(test_client, organizer, seed):
    """Organizer can enable open_registration and set max_participants together."""
    async with test_client as client:
        race = await _create_race(client, organizer.api_token)

        response = await client.patch(
            f"/api/races/{race['id']}",
            json={"open_registration": True, "max_participants": 8},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["open_registration"] is True
        assert data["max_participants"] == 8


# =============================================================================
# Update registration in RUNNING status (should fail)
# =============================================================================


@pytest.mark.asyncio
async def test_update_registration_in_running_status(test_client, organizer, seed, async_session):
    """Cannot update open_registration on a RUNNING race."""
    async with test_client as client:
        race = await _create_race(client, organizer.api_token)

        # Force race to RUNNING status
        import uuid as uuid_module

        race_uuid = uuid_module.UUID(race["id"])
        async with async_session() as db:
            await db.execute(
                update(Race).where(Race.id == race_uuid).values(status=RaceStatus.RUNNING)
            )
            await db.commit()

        response = await client.patch(
            f"/api/races/{race['id']}",
            json={"open_registration": True, "max_participants": 5},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400


# =============================================================================
# Enable open_registration without max_participants (should fail)
# =============================================================================


@pytest.mark.asyncio
async def test_enable_open_registration_without_max_participants(test_client, organizer, seed):
    """Cannot enable open_registration without providing max_participants."""
    async with test_client as client:
        race = await _create_race(client, organizer.api_token)

        response = await client.patch(
            f"/api/races/{race['id']}",
            json={"open_registration": True},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
