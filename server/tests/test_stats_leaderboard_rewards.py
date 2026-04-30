"""Equipped badge and name template ids surface on the /api/stats/leaderboard payload."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole


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
async def test_leaderboard_exposes_equipped_reward_ids(test_client, async_session):
    """Players on the leaderboard carry their equipped_badge_id and template id."""
    async with async_session() as db:
        decorated = User(
            twitch_id="lb_decorated",
            twitch_username="decorated",
            twitch_display_name="Decorated",
            api_token="lb_decorated_token",
            role=UserRole.USER,
            elo_rating=1700,
            elo_races=5,
            equipped_badge_id="early_adopter",
            equipped_name_template_id="elo_crown",
        )
        plain = User(
            twitch_id="lb_plain",
            twitch_username="plain",
            twitch_display_name="Plain",
            api_token="lb_plain_token",
            role=UserRole.USER,
            elo_rating=1500,
            elo_races=4,
        )
        db.add_all([decorated, plain])
        await db.commit()

    async with test_client as client:
        resp = await client.get("/api/stats/leaderboard")

    assert resp.status_code == 200
    by_username = {p["twitch_username"]: p for p in resp.json()["players"]}

    assert by_username["decorated"]["equipped_badge_id"] == "early_adopter"
    assert by_username["decorated"]["equipped_name_template_id"] == "elo_crown"
    assert by_username["plain"]["equipped_badge_id"] is None
    assert by_username["plain"]["equipped_name_template_id"] is None
