"""Tests for ORM models introduced by the rewards system."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    PhantomSkinUnlock,
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


async def test_user_has_equipped_phantom_skin_id_column(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="phantom_eq",
            twitch_username="alice_phantom",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        assert user.equipped_phantom_skin_id is None
        user.equipped_phantom_skin_id = "gold-aura"
        await db.commit()
        await db.refresh(user)
        assert user.equipped_phantom_skin_id == "gold-aura"


async def test_phantom_skin_unlock_unique_per_user_and_skin(async_session):
    async with async_session() as db:
        user = User(twitch_id="phantom_uniq", twitch_username="bob_phantom")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(PhantomSkinUnlock(user_id=user.id, skin_id="gold-aura"))
        await db.commit()
    async with async_session() as db:
        db.add(PhantomSkinUnlock(user_id=user.id, skin_id="gold-aura"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_phantom_skin_unlock_two_skins_same_user(async_session):
    async with async_session() as db:
        user = User(twitch_id="phantom_two", twitch_username="carol_phantom")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(PhantomSkinUnlock(user_id=user.id, skin_id="gold-aura"))
        db.add(PhantomSkinUnlock(user_id=user.id, skin_id="silver-aura"))
        await db.commit()
    async with async_session() as db:
        from sqlalchemy import select

        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(PhantomSkinUnlock.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert {r.skin_id for r in rows} == {"gold-aura", "silver-aura"}
