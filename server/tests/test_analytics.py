"""Tests for analytics-related endpoints (timezone collection via /auth/me)."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole, generate_token


@pytest.fixture
async def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def regular_user(async_session):
    """Create a regular user with an API token."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_regular",
            twitch_username="regularuser",
            twitch_display_name="Regular User",
            api_token=token,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, token


@pytest.fixture
async def admin_user(async_session):
    """Create an admin user with an API token."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_admin",
            twitch_username="adminuser",
            twitch_display_name="Admin User",
            api_token=token,
            role=UserRole.ADMIN,
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
async def test_auth_me_updates_timezone(test_client, regular_user, async_session):
    """GET /api/auth/me?timezone=Europe/Paris updates the user's timezone."""
    _, token = regular_user
    async with test_client as client:
        response = await client.get(
            "/api/auth/me?timezone=Europe%2FParis",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200

    # Verify the timezone was persisted in the DB
    async with async_session() as db:
        result = await db.execute(select(User).where(User.api_token == token))
        user = result.scalar_one()
        assert user.timezone == "Europe/Paris"


@pytest.mark.asyncio
async def test_auth_me_without_timezone_leaves_null(test_client, regular_user, async_session):
    """GET /api/auth/me without timezone param leaves timezone as None."""
    _, token = regular_user
    async with test_client as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200

    # Verify timezone was NOT set
    async with async_session() as db:
        result = await db.execute(select(User).where(User.api_token == token))
        user = result.scalar_one()
        assert user.timezone is None
