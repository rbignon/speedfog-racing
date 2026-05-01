"""Tests for the player-facing rewards endpoints."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole, generate_token
from speedfog_racing.rewards.catalog import BADGES, NAME_TEMPLATES


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
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_rewards",
            twitch_username="rewardsuser",
            twitch_display_name="Rewards User",
            api_token=token,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, token


@pytest.fixture
async def admin_with_token(async_session):
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_rewards_admin",
            twitch_username="rewardsadmin",
            twitch_display_name="Rewards Admin",
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


async def test_get_me_returns_inventory(test_client, user_with_token):
    user, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.get("/api/rewards/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["held_badges"] == []
        assert any(t["id"] == "default" for t in data["unlocked_templates"])
        assert data["equipped_badge_id"] is None
        assert data["equipped_name_template_id"] is None


async def test_patch_equipped_rejects_unowned_badge(test_client, user_with_token):
    _, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.patch(
            "/api/rewards/me/equipped",
            json={"equipped_badge_id": "early_adopter"},
            headers=headers,
        )
        assert resp.status_code == 400


async def test_patch_equipped_accepts_default_template(test_client, user_with_token):
    _, token = user_with_token
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.patch(
            "/api/rewards/me/equipped",
            json={"equipped_name_template_id": "default"},
            headers=headers,
        )
        assert resp.status_code == 200


async def test_patch_equipped_clears_badge_with_null(test_client, user_with_token, async_session):
    user, token = user_with_token
    from speedfog_racing.rewards.service import RewardsService

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter")
        await svc.set_equipped_badge(user.id, "early_adopter")
        await db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.patch(
            "/api/rewards/me/equipped",
            json={"equipped_badge_id": None},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["equipped_badge_id"] is None


async def test_get_notifications_lists_pending(test_client, user_with_token, async_session):
    user, token = user_with_token
    from speedfog_racing.rewards.service import RewardsService

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter")
        await db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.get("/api/rewards/notifications", headers=headers)
        assert resp.status_code == 200
        notifs = resp.json()
        assert len(notifs) == 1
        assert notifs[0]["kind"] == "badge_granted"
        assert notifs[0]["reward_id"] == "early_adopter"


async def test_post_dismiss_clears_pending(test_client, user_with_token, async_session):
    user, token = user_with_token
    from speedfog_racing.rewards.service import RewardsService

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter")
        await db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.post("/api/rewards/notifications/dismiss", headers=headers)
        assert resp.status_code == 204

        resp2 = await client.get("/api/rewards/notifications", headers=headers)
        assert resp2.json() == []


async def test_get_me_returns_full_catalog_for_admins(test_client, admin_with_token):
    """Admins see the entire catalog under held_badges/unlocked_templates so they
    can preview any badge/template via the existing settings picker. The
    equipped_* fields stay truthful and reflect the real DB row, not the
    inflated catalog."""
    _, token = admin_with_token
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.get("/api/rewards/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        held_ids = {b["id"] for b in data["held_badges"]}
        template_ids = {t["id"] for t in data["unlocked_templates"]}
        assert held_ids == set(BADGES.keys())
        assert template_ids == set(NAME_TEMPLATES.keys())
        assert data["equipped_badge_id"] is None
        assert data["equipped_name_template_id"] is None


async def test_patch_equipped_allows_admin_without_grant(test_client, admin_with_token):
    """Admins can equip any badge or template without holding it (debug override).
    Non-admins still get the existing 400 NotOwnedError path."""
    _, token = admin_with_token
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.patch(
            "/api/rewards/me/equipped",
            json={
                "equipped_badge_id": "early_adopter",
                "equipped_name_template_id": "elo_crown",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "equipped_badge_id": "early_adopter",
            "equipped_name_template_id": "elo_crown",
        }


async def test_patch_equipped_admin_can_force_transient_badge(test_client, admin_with_token):
    """The ownership bypass also covers transient badges (the original motivation:
    debug what a transient badge looks like without joining the auto-grant set)."""
    _, token = admin_with_token
    transient_id = next(
        (bid for bid, b in BADGES.items() if b.lifecycle == "transient"),
        None,
    )
    assert transient_id is not None, "expected at least one transient badge in the catalog"
    headers = {"Authorization": f"Bearer {token}"}
    async with test_client as client:
        resp = await client.patch(
            "/api/rewards/me/equipped",
            json={"equipped_badge_id": transient_id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["equipped_badge_id"] == transient_id
