"""Tests for admin grant/revoke rewards endpoints."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    RewardNotification,
    User,
    UserRole,
)


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
async def admin_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="admin_rewards",
            twitch_username="admin_rewards",
            api_token="admin_rewards_token",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def regular_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="regular_rewards",
            twitch_username="regular_rewards",
            api_token="regular_rewards_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def target_user(async_session):
    async with async_session() as db:
        user = User(twitch_id="target_user", twitch_username="target_user")
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


async def test_admin_grant_badge_creates_grant_and_notification(
    test_client, admin_user, target_user, async_session
):
    headers = {"Authorization": f"Bearer {admin_user.api_token}"}
    async with test_client as client:
        resp = await client.post(
            f"/api/admin/users/{target_user.id}/badges",
            json={"badge_id": "contributor", "reason": "fixed bug"},
            headers=headers,
        )
        assert resp.status_code == 201

    async with async_session() as db:
        grants = (await db.execute(select(BadgeGrant))).scalars().all()
        assert len(grants) == 1
        assert grants[0].badge_id == "contributor"
        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert len(notifs) == 1


async def test_admin_grant_badge_requires_admin(test_client, regular_user, target_user):
    headers = {"Authorization": f"Bearer {regular_user.api_token}"}
    async with test_client as client:
        resp = await client.post(
            f"/api/admin/users/{target_user.id}/badges",
            json={"badge_id": "contributor"},
            headers=headers,
        )
        assert resp.status_code in (401, 403)


async def test_admin_grant_template(test_client, admin_user, target_user):
    headers = {"Authorization": f"Bearer {admin_user.api_token}"}
    async with test_client as client:
        resp = await client.post(
            f"/api/admin/users/{target_user.id}/templates",
            json={"template_id": "elo_crown"},
            headers=headers,
        )
        assert resp.status_code == 201


async def test_admin_revoke_badge(test_client, admin_user, target_user, async_session):
    from speedfog_racing.rewards.service import RewardsService

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(target_user.id, "contributor")
        await db.commit()

    headers = {"Authorization": f"Bearer {admin_user.api_token}"}
    async with test_client as client:
        resp = await client.delete(
            f"/api/admin/users/{target_user.id}/badges/contributor",
            headers=headers,
        )
        assert resp.status_code == 204

    async with async_session() as db:
        grants = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.revoked_at.is_(None))))
            .scalars()
            .all()
        )
        assert len(grants) == 0


async def test_admin_revoke_template(test_client, admin_user, target_user, async_session):
    from speedfog_racing.rewards.service import RewardsService

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(target_user.id, "elo_crown")
        await db.commit()

    headers = {"Authorization": f"Bearer {admin_user.api_token}"}
    async with test_client as client:
        resp = await client.delete(
            f"/api/admin/users/{target_user.id}/templates/elo_crown",
            headers=headers,
        )
        assert resp.status_code == 204

    async with async_session() as db:
        rows = (await db.execute(select(NameTemplateUnlock))).scalars().all()
        assert len(rows) == 0


async def test_admin_grant_unknown_badge_returns_400(test_client, admin_user, target_user):
    headers = {"Authorization": f"Bearer {admin_user.api_token}"}
    async with test_client as client:
        resp = await client.post(
            f"/api/admin/users/{target_user.id}/badges",
            json={"badge_id": "nope"},
            headers=headers,
        )
        assert resp.status_code == 400
