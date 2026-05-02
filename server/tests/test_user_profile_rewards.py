"""Tests for the rewards-related fields on the user profile endpoint."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole
from speedfog_racing.rewards.service import RewardsService


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
async def target_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="rewards_profile_user",
            twitch_username="rewards_profile",
            twitch_display_name="RewardsProfile",
            api_token="rewards_profile_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


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
async def test_profile_returns_empty_rewards_for_user_with_none(test_client, target_user):
    """A fresh user with no grants returns an empty held_badges list."""
    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["held_badges"] == []


@pytest.mark.asyncio
async def test_profile_returns_held_badges(test_client, target_user, async_session):
    """After granting a badge, the profile endpoint reflects it with full shape."""
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(target_user.id, "contributor", reason="test")
        await db.commit()

    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")

    assert resp.status_code == 200
    data = resp.json()

    badge_ids = [b["id"] for b in data["held_badges"]]
    assert "contributor" in badge_ids

    contributor = next(b for b in data["held_badges"] if b["id"] == "contributor")
    assert contributor["name"] == "Contributor"
    assert contributor["icon_filename"] == "contributor.svg"
    assert contributor["description"] is not None


@pytest.mark.asyncio
async def test_profile_held_badges_excludes_revoked(test_client, target_user, async_session):
    """A revoked badge must not appear in held_badges."""
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(target_user.id, "contributor", reason="test")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.revoke_badge(target_user.id, "contributor")
        await db.commit()

    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")

    assert resp.status_code == 200
    data = resp.json()
    badge_ids = [b["id"] for b in data["held_badges"]]
    assert "contributor" not in badge_ids


@pytest.mark.asyncio
async def test_profile_exposes_equipped_name_template_id(test_client, target_user, async_session):
    """The profile endpoint surfaces the user's equipped name template id so the
    page heading can apply the matching style."""
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(target_user.id, "elo_crown", reason="test")
        await svc.set_equipped_name_template(target_user.id, "elo_crown")
        await db.commit()

    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["equipped_name_template_id"] == "elo_crown"


@pytest.mark.asyncio
async def test_profile_equipped_name_template_id_null_by_default(test_client, target_user):
    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["equipped_name_template_id"] is None


@pytest.mark.asyncio
async def test_profile_exposes_equipped_phantom_skin_id(test_client, target_user, async_session):
    """The profile endpoint surfaces the user's equipped phantom skin id so the
    profile page can swap the avatar to the skin portrait."""
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(target_user.id, "gold-aura", reason="test")
        await svc.set_equipped_phantom_skin(target_user.id, "gold-aura")
        await db.commit()

    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["equipped_phantom_skin_id"] == "gold-aura"


@pytest.mark.asyncio
async def test_profile_equipped_phantom_skin_id_null_by_default(test_client, target_user):
    """A fresh user with no phantom skin equipped returns null for the field."""
    async with test_client as client:
        resp = await client.get(f"/api/users/{target_user.twitch_username}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["equipped_phantom_skin_id"] is None
