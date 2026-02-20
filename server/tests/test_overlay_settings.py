"""Tests for user overlay settings API."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, generate_token


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
async def user_with_token(async_session):
    """Create a user in the DB and return (user, token)."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_settings",
            twitch_username="settingsuser",
            twitch_display_name="Settings User",
            api_token=token,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, token


@pytest.fixture
def test_client(async_session):
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_overlay_settings(test_client, user_with_token):
    """PATCH /users/me/settings updates overlay_settings."""
    _, token = user_with_token
    async with test_client as client:
        response = await client.patch(
            "/api/users/me/settings",
            json={"font_size": 24.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overlay_settings"]["font_size"] == 24.0


@pytest.mark.asyncio
async def test_update_overlay_settings_validates_range(test_client, user_with_token):
    """PATCH /users/me/settings rejects out-of-range font_size."""
    _, token = user_with_token
    async with test_client as client:
        response = await client.patch(
            "/api/users/me/settings",
            json={"font_size": 200.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_overlay_settings_merges(test_client, user_with_token):
    """PATCH /users/me/settings merges with existing settings."""
    _, token = user_with_token
    async with test_client as client:
        # First set font_size
        await client.patch(
            "/api/users/me/settings",
            json={"font_size": 20.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Then update again — should still have font_size
        response = await client.patch(
            "/api/users/me/settings",
            json={"font_size": 22.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["overlay_settings"]["font_size"] == 22.0


@pytest.mark.asyncio
async def test_get_me_includes_overlay_settings(test_client, user_with_token):
    """/auth/me includes overlay_settings."""
    _, token = user_with_token
    async with test_client as client:
        await client.patch(
            "/api/users/me/settings",
            json={"font_size": 24.0},
            headers={"Authorization": f"Bearer {token}"},
        )
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["overlay_settings"] == {"font_size": 24.0}


@pytest.mark.asyncio
async def test_get_me_overlay_settings_null_by_default(test_client, async_session):
    """/auth/me returns null overlay_settings for new users."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_fresh",
            twitch_username="freshuser",
            twitch_display_name="Fresh User",
            api_token=token,
        )
        db.add(user)
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["overlay_settings"] is None
