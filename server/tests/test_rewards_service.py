import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import BadgeGrant, NameTemplateUnlock, RewardNotification, User
from speedfog_racing.rewards.service import (
    LifecycleMismatchError,
    NotOwnedError,
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


async def test_grant_name_template_creates_unlock_and_notification(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "elo_crown", reason="reached top 1")
        await db.commit()

    async with async_session() as db:
        rows = (await db.execute(select(NameTemplateUnlock))).scalars().all()
        assert len(rows) == 1
        assert rows[0].template_id == "elo_crown"

        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert any(n.kind == "name_template_unlocked" for n in notifs)


async def test_grant_name_template_is_idempotent(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "elo_crown")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "elo_crown")
        await db.commit()

    async with async_session() as db:
        rows = (await db.execute(select(NameTemplateUnlock))).scalars().all()
        assert len(rows) == 1


async def test_grant_name_template_rejects_unknown(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(UnknownRewardError):
            await svc.grant_name_template(user.id, "nope")


async def test_grant_default_name_template_is_noop(async_session):
    """The 'default' template is implicit; no row is created."""
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "default")
        await db.commit()

    async with async_session() as db:
        rows = (await db.execute(select(NameTemplateUnlock))).scalars().all()
        assert len(rows) == 0


async def test_sync_transient_grants_to_new_holders(async_session):
    a = await _make_user(async_session, "a")
    b = await _make_user(async_session, "b")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {a.id, b.id}, reason="initial")
        await db.commit()

    async with async_session() as db:
        grants = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.revoked_at.is_(None))))
            .scalars()
            .all()
        )
        assert {g.user_id for g in grants} == {a.id, b.id}

        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert sum(1 for n in notifs if n.kind == "badge_granted") == 2
        assert sum(1 for n in notifs if n.kind == "badge_revoked") == 0


async def test_sync_transient_diffs_holder_set(async_session):
    a = await _make_user(async_session, "a")
    b = await _make_user(async_session, "b")
    c = await _make_user(async_session, "c")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {a.id, b.id})
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {b.id, c.id})
        await db.commit()

    async with async_session() as db:
        active = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.revoked_at.is_(None))))
            .scalars()
            .all()
        )
        assert {g.user_id for g in active} == {b.id, c.id}

        revoked = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.revoked_at.is_not(None))))
            .scalars()
            .all()
        )
        assert {g.user_id for g in revoked} == {a.id}

        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        granted = [n for n in notifs if n.kind == "badge_granted"]
        revoked_n = [n for n in notifs if n.kind == "badge_revoked"]
        assert {n.user_id for n in granted} == {a.id, b.id, c.id}
        assert {n.user_id for n in revoked_n} == {a.id}


async def test_sync_transient_clears_equipped_badge_on_revoke(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {a.id})
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        user.equipped_badge_id = "top1_elo"
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", set())
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_badge_id is None


async def test_sync_transient_no_op_for_unchanged_set(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {a.id})
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("top1_elo", {a.id})
        await db.commit()

    async with async_session() as db:
        grants = (await db.execute(select(BadgeGrant))).scalars().all()
        assert len(grants) == 1
        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert len(notifs) == 1


async def test_sync_transient_rejects_permanent_badge(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(LifecycleMismatchError):
            await svc.sync_transient_holders("early_adopter", {a.id})


async def test_set_equipped_badge_validates_ownership(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(NotOwnedError):
            await svc.set_equipped_badge(a.id, "early_adopter")


async def test_set_equipped_badge_accepts_owned(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(a.id, "early_adopter")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_badge(a.id, "early_adopter")
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_badge_id == "early_adopter"


async def test_set_equipped_badge_accepts_none(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        user = await db.get(User, a.id)
        user.equipped_badge_id = "early_adopter"
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_badge(a.id, None)
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_badge_id is None


async def test_set_equipped_template_default_always_allowed(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_name_template(a.id, "default")
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_name_template_id == "default"


async def test_set_equipped_template_validates_ownership(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(NotOwnedError):
            await svc.set_equipped_name_template(a.id, "elo_crown")


async def test_set_equipped_template_none_falls_back_to_default(async_session):
    """Passing None falls back to DEFAULT_TEMPLATE_ID, not NULL."""
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_name_template(a.id, None)
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_name_template_id == "default"


async def test_dismiss_notifications_sets_dismissed_at(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(a.id, "early_adopter")
        await svc.grant_permanent_badge(a.id, "contributor")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        count = await svc.dismiss_notifications(a.id)
        await db.commit()
        assert count == 2

    async with async_session() as db:
        svc = RewardsService(db)
        pending = await svc.get_pending_notifications(a.id)
        assert pending == []


async def test_get_user_inventory_returns_held_badges_and_unlocks(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_permanent_badge(a.id, "early_adopter")
        await svc.grant_name_template(a.id, "elo_crown")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        inv = await svc.get_user_inventory(a.id)
        assert "early_adopter" in {b.id for b in inv.held_badges}
        assert "elo_crown" in {t.id for t in inv.unlocked_templates}


async def test_refresh_top1_elo_holders_picks_highest_above_threshold(async_session):
    from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD

    async with async_session() as db:
        veteran_high = User(
            twitch_id="tid-vh",
            twitch_username="vh",
            elo_rating=1800,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        veteran_low = User(
            twitch_id="tid-vl",
            twitch_username="vl",
            elo_rating=1700,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        rookie = User(
            twitch_id="tid-r",
            twitch_username="r",
            elo_rating=1900,
            elo_races=1,
        )
        db.add_all([veteran_high, veteran_low, rookie])
        await db.commit()
        await db.refresh(veteran_high)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
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
        assert holders == [veteran_high.id]


async def test_refresh_top1_elo_holders_handles_ties(async_session):
    from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD

    async with async_session() as db:
        a = User(
            twitch_id="tid-a", twitch_username="a", elo_rating=1800, elo_races=PROVISIONAL_THRESHOLD
        )
        b = User(
            twitch_id="tid-b", twitch_username="b", elo_rating=1800, elo_races=PROVISIONAL_THRESHOLD
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a)
        await db.refresh(b)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
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
        assert set(holders) == {a.id, b.id}


async def test_refresh_top1_elo_holders_grants_elo_crown_template(async_session):
    from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD

    async with async_session() as db:
        a = User(
            twitch_id="tid-a", twitch_username="a", elo_rating=1800, elo_races=PROVISIONAL_THRESHOLD
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
        from speedfog_racing.models import NameTemplateUnlock

        rows = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == a.id,
                        NameTemplateUnlock.template_id == "elo_crown",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
