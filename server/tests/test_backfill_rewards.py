"""Tests for the rewards backfill script."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import BadgeGrant, NameTemplateUnlock, User, UserRole
from speedfog_racing.scripts.backfill_rewards import backfill_rewards
from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session_maker(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def test_backfill_grants_early_adopter_to_old_accounts(async_session_maker):
    """Users created before the cutoff get early_adopter; newer ones don't."""
    async with async_session_maker() as db:
        old = User(twitch_id="t-old", twitch_username="old")
        new = User(twitch_id="t-new", twitch_username="new")
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old_id = old.id
        new_id = new.id

        # Force created_at via UPDATE since the column has server_default=now().
        await db.execute(
            update(User)
            .where(User.id == old_id)
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.execute(
            update(User)
            .where(User.id == new_id)
            .values(created_at=datetime(2026, 4, 15, tzinfo=UTC))
        )
        await db.commit()

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        grants = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.badge_id == "early_adopter")))
            .scalars()
            .all()
        )
        assert {g.user_id for g in grants} == {old_id}


async def test_backfill_is_idempotent(async_session_maker):
    """Running the script twice produces no duplicate badge grants."""
    async with async_session_maker() as db:
        u = User(twitch_id="t1", twitch_username="alice")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(
            update(User).where(User.id == u.id).values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.commit()

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        grants = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.badge_id == "early_adopter")))
            .scalars()
            .all()
        )
        assert len(grants) == 1


async def test_backfill_grants_top1_elo_to_current_holder(async_session_maker):
    """The top ELO holder gets the transient top1_elo badge and the elo_crown template."""
    async with async_session_maker() as db:
        a = User(
            twitch_id="ta",
            twitch_username="a",
            elo_rating=1900.0,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        b = User(
            twitch_id="tb",
            twitch_username="b",
            elo_rating=1700.0,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a)
        a_id = a.id

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        holders = (
            (
                await db.execute(
                    select(BadgeGrant.user_id).where(
                        BadgeGrant.badge_id == "top1_elo",
                        BadgeGrant.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert holders == [a_id]

        crown_unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "elo_crown"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert crown_unlocks == [a_id]


async def test_backfill_grants_pioneer_alongside_early_adopter(async_session_maker):
    """Old accounts receive the pioneer name template alongside the early_adopter badge."""
    async with async_session_maker() as db:
        old = User(twitch_id="t-old", twitch_username="old")
        new = User(twitch_id="t-new", twitch_username="new")
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        old_id = old.id
        new_id = new.id

        await db.execute(
            update(User)
            .where(User.id == old_id)
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.execute(
            update(User)
            .where(User.id == new_id)
            .values(created_at=datetime(2026, 4, 15, tzinfo=UTC))
        )
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "pioneer"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(unlocks) == {old_id}


async def test_backfill_grants_archon_to_admins(async_session_maker):
    """Users with role=admin get the archon template; non-admins do not."""
    async with async_session_maker() as db:
        admin = User(twitch_id="t-admin", twitch_username="boss", role=UserRole.ADMIN)
        regular = User(twitch_id="t-reg", twitch_username="reg", role=UserRole.ORGANIZER)
        db.add_all([admin, regular])
        await db.commit()
        await db.refresh(admin)
        await db.refresh(regular)
        admin_id = admin.id
        regular_id = regular.id

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "archon"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(unlocks) == {admin_id}
        assert regular_id not in set(unlocks)


async def test_backfill_pioneer_and_archon_idempotent(async_session_maker):
    """Re-running the backfill does not duplicate pioneer or archon unlocks."""
    async with async_session_maker() as db:
        old_admin = User(twitch_id="t-oa", twitch_username="oa", role=UserRole.ADMIN)
        db.add(old_admin)
        await db.commit()
        await db.refresh(old_admin)
        await db.execute(
            update(User)
            .where(User.id == old_admin.id)
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.commit()

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        for template_id in ("pioneer", "archon"):
            rows = (
                (
                    await db.execute(
                        select(NameTemplateUnlock).where(
                            NameTemplateUnlock.template_id == template_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1, f"{template_id} should be granted exactly once"
