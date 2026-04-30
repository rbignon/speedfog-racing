"""Tests for ORM models introduced by the rewards system."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    RewardNotification,
    User,
)


@pytest.fixture
async def async_engine():
    """Create async in-memory SQLite engine with schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def _make_user(async_session) -> User:
    async with async_session() as db:
        u = User(
            twitch_id="tid-1",
            twitch_username="alice",
            twitch_display_name="Alice",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def test_user_has_equip_columns(async_session):
    user = await _make_user(async_session)
    assert user.equipped_badge_id is None
    assert user.equipped_name_template_id is None


async def test_badge_grant_round_trip(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        grant = BadgeGrant(
            user_id=user.id,
            badge_id="early_adopter",
            reason="test",
        )
        db.add(grant)
        await db.commit()
        await db.refresh(grant)
        assert grant.id is not None
        assert grant.granted_at is not None
        assert grant.revoked_at is None


async def test_name_template_unlock_unique(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        a = NameTemplateUnlock(user_id=user.id, template_id="elo_crown")
        db.add(a)
        await db.commit()

    async with async_session() as db:
        b = NameTemplateUnlock(user_id=user.id, template_id="elo_crown")
        db.add(b)
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_reward_notification_round_trip(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        n = RewardNotification(
            user_id=user.id,
            kind="badge_granted",
            reward_id="early_adopter",
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)
        assert n.created_at is not None
        assert n.dismissed_at is None
