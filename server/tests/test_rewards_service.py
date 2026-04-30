import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import BadgeGrant, RewardNotification, User
from speedfog_racing.rewards.service import (
    LifecycleMismatchError,
    RewardsService,
    UnknownRewardError,
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


async def _make_user(async_session, name: str = "alice") -> User:
    async with async_session() as db:
        u = User(twitch_id=f"tid-{name}", twitch_username=name)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def test_grant_permanent_badge_creates_grant_and_notification(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter", reason="test")
        await db.commit()

    async with async_session() as db:
        grants = (await db.execute(select(BadgeGrant))).scalars().all()
        assert len(grants) == 1
        assert grants[0].badge_id == "early_adopter"
        assert grants[0].revoked_at is None
        assert grants[0].reason == "test"

        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert len(notifs) == 1
        assert notifs[0].kind == "badge_granted"
        assert notifs[0].reward_id == "early_adopter"


async def test_grant_permanent_badge_is_idempotent(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(user.id, "early_adopter")
        await db.commit()

    async with async_session() as db:
        grants = (await db.execute(select(BadgeGrant))).scalars().all()
        assert len(grants) == 1
        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert len(notifs) == 1


async def test_grant_permanent_badge_rejects_transient(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(LifecycleMismatchError):
            await svc.grant_permanent_badge(user.id, "top1_elo")


async def test_grant_permanent_badge_rejects_unknown(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(UnknownRewardError):
            await svc.grant_permanent_badge(user.id, "nope")
