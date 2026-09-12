import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    Participant,
    ParticipantStatus,
    PhantomSkinUnlock,
    Race,
    RaceStatus,
    RewardNotification,
    User,
)
from speedfog_racing.rewards.catalog import PHANTOM_SKINS, PSEUDO_PHANTOM_SKIN_IDS
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
            await svc.grant_permanent_badge(user.id, "weekly_daily_champion")


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
        await svc.grant_name_template(user.id, "daily_crown", reason="weekly daily champion")
        await db.commit()

    async with async_session() as db:
        rows = (await db.execute(select(NameTemplateUnlock))).scalars().all()
        assert len(rows) == 1
        assert rows[0].template_id == "daily_crown"

        notifs = (await db.execute(select(RewardNotification))).scalars().all()
        assert any(n.kind == "name_template_unlocked" for n in notifs)


async def test_grant_name_template_is_idempotent(async_session):
    user = await _make_user(async_session)
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "daily_crown")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_name_template(user.id, "daily_crown")
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
        await svc.sync_transient_holders("weekly_daily_champion", {a.id, b.id}, reason="initial")
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
        await svc.sync_transient_holders("weekly_daily_champion", {a.id, b.id})
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("weekly_daily_champion", {b.id, c.id})
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
        await svc.sync_transient_holders("weekly_daily_champion", {a.id})
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        user.equipped_badge_id = "weekly_daily_champion"
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("weekly_daily_champion", set())
        await db.commit()

    async with async_session() as db:
        user = await db.get(User, a.id)
        assert user.equipped_badge_id is None


async def test_sync_transient_no_op_for_unchanged_set(async_session):
    a = await _make_user(async_session, "a")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("weekly_daily_champion", {a.id})
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("weekly_daily_champion", {a.id})
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
            await svc.set_equipped_name_template(a.id, "daily_crown")


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
        await svc.grant_name_template(a.id, "daily_crown")
        await db.commit()

    async with async_session() as db:
        svc = RewardsService(db)
        inv = await svc.get_user_inventory(a.id)
        assert "early_adopter" in {b.id for b in inv.held_badges}
        assert "daily_crown" in {t.id for t in inv.unlocked_templates}


async def _seed_finished_participations(db, user_id, count, *, status=None):
    """Create `count` Race + Participant rows for the user. Defaults to FINISHED."""
    if status is None:
        status = ParticipantStatus.FINISHED
    for i in range(count):
        race = Race(name=f"r-{i}", status=RaceStatus.FINISHED, organizer_id=user_id)
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=user_id, status=status))
    await db.commit()


async def test_check_veteran_below_threshold_does_not_grant(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv1", twitch_username="v1")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD - 1)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        grants = (
            (
                await db.execute(
                    select(BadgeGrant).where(
                        BadgeGrant.user_id == u.id,
                        BadgeGrant.badge_id == "veteran",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert grants == []


async def test_check_veteran_at_threshold_grants_once(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv2", twitch_username="v2")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        grants = (
            (
                await db.execute(
                    select(BadgeGrant).where(
                        BadgeGrant.user_id == u.id,
                        BadgeGrant.badge_id == "veteran",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 1


async def test_check_veteran_grants_weathered_template_alongside_badge(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv2b", twitch_username="v2b")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == u.id,
                        NameTemplateUnlock.template_id == "weathered",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(unlocks) == 1


async def test_check_veteran_below_threshold_skips_template(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv2c", twitch_username="v2c")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD - 1)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == u.id,
                        NameTemplateUnlock.template_id == "weathered",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert unlocks == []


async def test_check_veteran_idempotent_after_grant(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv3", twitch_username="v3")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD + 5)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.check_finish_reward_milestones(u.id)
        await svc.check_finish_reward_milestones(u.id)
        await svc.check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        grants = (
            (
                await db.execute(
                    select(BadgeGrant).where(
                        BadgeGrant.user_id == u.id,
                        BadgeGrant.badge_id == "veteran",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(grants) == 1


async def test_check_veteran_excludes_abandoned_participations(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv4", twitch_username="v4")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        # All ABANDONED, even past threshold count: should not qualify.
        await _seed_finished_participations(
            db, u.id, VETERAN_RACE_THRESHOLD + 5, status=ParticipantStatus.ABANDONED
        )

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        grants = (
            (
                await db.execute(
                    select(BadgeGrant).where(
                        BadgeGrant.user_id == u.id,
                        BadgeGrant.badge_id == "veteran",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert grants == []


async def _frog_badge_grants(db, user_id):
    return (
        (
            await db.execute(
                select(BadgeGrant).where(
                    BadgeGrant.user_id == user_id, BadgeGrant.badge_id == "frog"
                )
            )
        )
        .scalars()
        .all()
    )


async def _speedfrog_template_unlocks(db, user_id):
    return (
        (
            await db.execute(
                select(NameTemplateUnlock).where(
                    NameTemplateUnlock.user_id == user_id,
                    NameTemplateUnlock.template_id == "speedfrog",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_check_finish_first_race_grants_frog_and_speedfrog(async_session):
    async with async_session() as db:
        u = User(twitch_id="tf1", twitch_username="f1")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, 1)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        assert len(await _frog_badge_grants(db, u.id)) == 1
        assert len(await _speedfrog_template_unlocks(db, u.id)) == 1


async def test_check_finish_first_race_emits_notifications(async_session):
    async with async_session() as db:
        u = User(twitch_id="tf2", twitch_username="f2")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, 1)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        notifs = (
            (await db.execute(select(RewardNotification).where(RewardNotification.user_id == u.id)))
            .scalars()
            .all()
        )
        kinds = {(n.kind, n.reward_id) for n in notifs}
        assert ("badge_granted", "frog") in kinds
        assert ("name_template_unlocked", "speedfrog") in kinds


async def test_check_finish_frog_idempotent(async_session):
    async with async_session() as db:
        u = User(twitch_id="tf3", twitch_username="f3")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, 3)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.check_finish_reward_milestones(u.id)
        await svc.check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        assert len(await _frog_badge_grants(db, u.id)) == 1
        assert len(await _speedfrog_template_unlocks(db, u.id)) == 1


async def test_check_finish_daily_participation_grants_frog(async_session):
    from datetime import date

    async with async_session() as db:
        u = User(twitch_id="tf4", twitch_username="f4")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        race = Race(
            name="daily",
            status=RaceStatus.FINISHED,
            organizer_id=u.id,
            daily_date=date(2026, 6, 17),
        )
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=u.id, status=ParticipantStatus.FINISHED))
        await db.commit()

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        assert len(await _frog_badge_grants(db, u.id)) == 1
        assert len(await _speedfrog_template_unlocks(db, u.id)) == 1


async def test_check_finish_no_finished_races_skips_frog(async_session):
    async with async_session() as db:
        u = User(twitch_id="tf5", twitch_username="f5")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, 3, status=ParticipantStatus.ABANDONED)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        assert await _frog_badge_grants(db, u.id) == []
        assert await _speedfrog_template_unlocks(db, u.id) == []


async def test_grant_phantom_skin_creates_unlock_and_notification(async_session):
    user = await _make_user(async_session, "ps_alice")
    async with async_session() as db:
        svc = RewardsService(db)
        unlock = await svc.grant_phantom_skin(user.id, "gold-aura", reason="test")
        await db.commit()
        assert unlock is not None
        assert unlock.skin_id == "gold-aura"
        assert unlock.reason == "test"

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(PhantomSkinUnlock.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        notifs = (
            (
                await db.execute(
                    select(RewardNotification).where(
                        RewardNotification.user_id == user.id,
                        RewardNotification.kind == "phantom_skin_unlocked",
                        RewardNotification.reward_id == "gold-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1


async def test_grant_phantom_skin_is_idempotent(async_session):
    user = await _make_user(async_session, "ps_bob")
    async with async_session() as db:
        svc = RewardsService(db)
        first = await svc.grant_phantom_skin(user.id, "gold-aura")
        await db.commit()
        assert first is not None
    async with async_session() as db:
        svc = RewardsService(db)
        second = await svc.grant_phantom_skin(user.id, "gold-aura")
        await db.commit()
        assert second is None
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(PhantomSkinUnlock.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_grant_phantom_skin_none_is_skipped(async_session):
    user = await _make_user(async_session, "ps_carol")
    async with async_session() as db:
        svc = RewardsService(db)
        result = await svc.grant_phantom_skin(user.id, "none")
        await db.commit()
        assert result is None
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(PhantomSkinUnlock.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
        notifs = (
            (
                await db.execute(
                    select(RewardNotification).where(
                        RewardNotification.user_id == user.id,
                        RewardNotification.kind == "phantom_skin_unlocked",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert notifs == []


async def test_grant_phantom_skin_rejects_unknown(async_session):
    user = await _make_user(async_session, "ps_dave")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(UnknownRewardError):
            await svc.grant_phantom_skin(user.id, "rainbow-aura")


async def test_set_equipped_phantom_skin_owned(async_session):
    user = await _make_user(async_session, "skineq_alice")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(user.id, "gold-aura")
        await svc.set_equipped_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id == "gold-aura"


async def test_set_equipped_phantom_skin_not_owned_raises(async_session):
    user = await _make_user(async_session, "skineq_bob")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(NotOwnedError):
            await svc.set_equipped_phantom_skin(user.id, "gold-aura")


async def test_set_equipped_phantom_skin_none_clears_to_null(async_session):
    user = await _make_user(async_session, "skineq_carol")
    async with async_session() as db:
        await db.execute(
            update(User).where(User.id == user.id).values(equipped_phantom_skin_id="gold-aura")
        )
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_phantom_skin(user.id, None)
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id is None


async def test_set_equipped_phantom_skin_string_none_clears_to_null(async_session):
    user = await _make_user(async_session, "skineq_dave")
    async with async_session() as db:
        await db.execute(
            update(User).where(User.id == user.id).values(equipped_phantom_skin_id="gold-aura")
        )
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_phantom_skin(user.id, "none")
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id is None


async def test_set_equipped_phantom_skin_random_needs_no_unlock(async_session):
    """ "random" is a pseudo skin: always equippable, stored as-is (not NULL)."""
    user = await _make_user(async_session, "skineq_gwen")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_phantom_skin(user.id, "random")
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id == "random"


async def test_grant_phantom_skin_random_is_a_no_op(async_session):
    """ "random" is never owned: granting it must not create an unlock row."""
    user = await _make_user(async_session, "skingr_hugo")
    async with async_session() as db:
        svc = RewardsService(db)
        assert await svc.grant_phantom_skin(user.id, "random") is None
        await db.commit()
    async with async_session() as db:
        unlocks = (await db.execute(select(PhantomSkinUnlock))).scalars().all()
        assert unlocks == []


async def test_set_equipped_phantom_skin_unknown_raises(async_session):
    user = await _make_user(async_session, "skineq_erin")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(UnknownRewardError):
            await svc.set_equipped_phantom_skin(user.id, "rainbow-aura")


async def test_set_equipped_phantom_skin_admin_bypass(async_session):
    user = await _make_user(async_session, "skineq_frank")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_phantom_skin(user.id, "gold-aura", enforce_ownership=False)
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id == "gold-aura"


async def test_revoke_phantom_skin_random_keeps_the_equip_slot(async_session):
    """There is nothing to revoke on a pseudo skin: don't un-equip the choice."""
    user = await _make_user(async_session, "skinrv_ivan")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.set_equipped_phantom_skin(user.id, "random")
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.revoke_phantom_skin(user.id, "random")
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id == "random"


async def test_revoke_phantom_skin_clears_equip_and_unlock(async_session):
    user = await _make_user(async_session, "skinrv_alice")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(user.id, "gold-aura")
        await svc.set_equipped_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.revoke_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fresh.equipped_phantom_skin_id is None
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(PhantomSkinUnlock.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_revoke_phantom_skin_does_not_emit_notification(async_session):
    user = await _make_user(async_session, "skinrv_bob")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.dismiss_notifications(user.id)
        await svc.revoke_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        notifs = (
            (
                await db.execute(
                    select(RewardNotification).where(
                        RewardNotification.user_id == user.id,
                        RewardNotification.dismissed_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert not any(n.reward_id == "gold-aura" for n in notifs)


async def test_revoke_phantom_skin_unknown_raises(async_session):
    user = await _make_user(async_session, "skinrv_erin")
    async with async_session() as db:
        svc = RewardsService(db)
        with pytest.raises(UnknownRewardError):
            await svc.revoke_phantom_skin(user.id, "rainbow-aura")


async def test_inventory_returns_unlocked_phantom_skins_and_equipped(async_session):
    user = await _make_user(async_session, "inv1_alice")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(user.id, "gold-aura")
        await svc.grant_phantom_skin(user.id, "silver-aura")
        await svc.set_equipped_phantom_skin(user.id, "gold-aura")
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        inv = await svc.get_user_inventory(user.id)
    ids = {s.id for s in inv.unlocked_phantom_skins}
    assert ids == {"gold-aura", "silver-aura"}
    assert inv.equipped_phantom_skin_id == "gold-aura"


async def test_inventory_phantom_skins_sorted_by_sort_order(async_session):
    user = await _make_user(async_session, "inv2_bob")
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_phantom_skin(user.id, "crimson-aura")  # sort_order=50
        await svc.grant_phantom_skin(user.id, "gold-aura")  # sort_order=10
        await svc.grant_phantom_skin(user.id, "silver-aura")  # sort_order=20
        await db.commit()
    async with async_session() as db:
        svc = RewardsService(db)
        inv = await svc.get_user_inventory(user.id)
    order = [s.id for s in inv.unlocked_phantom_skins]
    assert order == ["gold-aura", "silver-aura", "crimson-aura"]


async def test_inventory_no_phantom_skins(async_session):
    user = await _make_user(async_session, "inv3_carol")
    async with async_session() as db:
        svc = RewardsService(db)
        inv = await svc.get_user_inventory(user.id)
    assert inv.unlocked_phantom_skins == []
    assert inv.equipped_phantom_skin_id is None


async def test_check_veteran_grants_crimson_aura_alongside_template(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv_crimson", twitch_username="v_crimson")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == u.id,
                        PhantomSkinUnlock.skin_id == "crimson-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_check_veteran_below_threshold_skips_crimson_aura(async_session):
    from speedfog_racing.rewards.catalog import VETERAN_RACE_THRESHOLD

    async with async_session() as db:
        u = User(twitch_id="tv_crimson_below", twitch_username="v_crimson_below")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await _seed_finished_participations(db, u.id, VETERAN_RACE_THRESHOLD - 1)

    async with async_session() as db:
        await RewardsService(db).check_finish_reward_milestones(u.id)
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == u.id,
                        PhantomSkinUnlock.skin_id == "crimson-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def _make_user_with_best_streak(async_session, name: str, best: int) -> User:
    async with async_session() as db:
        u = User(twitch_id=f"tid-{name}", twitch_username=name, daily_best_streak=best)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def test_check_daily_streak_below_threshold_skips_molten_aura(async_session):
    from speedfog_racing.rewards.catalog import DAILY_STREAK_REWARD_THRESHOLD

    user = await _make_user_with_best_streak(
        async_session, "streak_below", DAILY_STREAK_REWARD_THRESHOLD - 1
    )
    async with async_session() as db:
        await RewardsService(db).check_daily_streak_eligibility(user.id)
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user.id,
                        PhantomSkinUnlock.skin_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_check_daily_streak_at_threshold_grants_molten_aura(async_session):
    from speedfog_racing.rewards.catalog import DAILY_STREAK_REWARD_THRESHOLD

    user = await _make_user_with_best_streak(
        async_session, "streak_at", DAILY_STREAK_REWARD_THRESHOLD
    )
    async with async_session() as db:
        await RewardsService(db).check_daily_streak_eligibility(user.id)
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user.id,
                        PhantomSkinUnlock.skin_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        notifications = (
            (
                await db.execute(
                    select(RewardNotification).where(
                        RewardNotification.user_id == user.id,
                        RewardNotification.reward_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifications) == 1


async def test_check_daily_streak_idempotent(async_session):
    from speedfog_racing.rewards.catalog import DAILY_STREAK_REWARD_THRESHOLD

    user = await _make_user_with_best_streak(
        async_session, "streak_idem", DAILY_STREAK_REWARD_THRESHOLD + 5
    )
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.check_daily_streak_eligibility(user.id)
        await svc.check_daily_streak_eligibility(user.id)
        await svc.check_daily_streak_eligibility(user.id)
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user.id,
                        PhantomSkinUnlock.skin_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        notifications = (
            (
                await db.execute(
                    select(RewardNotification).where(
                        RewardNotification.user_id == user.id,
                        RewardNotification.reward_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifications) == 1


# ---------------------------------------------------------------------------
# Random phantom skin draw
# ---------------------------------------------------------------------------


def _seed_catalog(*names: str) -> dict[str, list[int]]:
    """A seed's phantom_skins map, every named skin resolving to one SpEffect."""
    return {name: [1450700] for name in names}


# A freshly generated seed carries every real skin; an older one carries fewer.
ALL_SEED_SKINS = _seed_catalog(*(PHANTOM_SKINS.keys() - PSEUDO_PHANTOM_SKIN_IDS))


async def _user_with_skins(async_session, seq: int, skin_ids: list[str]) -> User:
    """Create a user with a fixed id, so draws stay reproducible run to run."""
    async with async_session() as db:
        user = User(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"phantom-draw-{seq}"),
            twitch_id=f"tid-draw-{seq}",
            twitch_username=f"draw{seq}",
        )
        db.add(user)
        await db.flush()
        for skin_id in skin_ids:
            db.add(PhantomSkinUnlock(user_id=user.id, skin_id=skin_id))
        await db.commit()
        await db.refresh(user)
        return user


async def test_draw_is_stable_for_the_same_draw_key(async_session):
    """A re-draw on reconnect swaps the aura the player is already wearing."""
    user = await _user_with_skins(async_session, 1, sorted(ALL_SEED_SKINS))
    async with async_session() as db:
        svc = RewardsService(db)
        first = await svc.draw_random_phantom_skin(user.id, ALL_SEED_SKINS, "run-1")
        second = await svc.draw_random_phantom_skin(user.id, ALL_SEED_SKINS, "run-1")
    assert first is not None
    assert first == second


async def test_draw_only_returns_unlocked_skins(async_session):
    user = await _user_with_skins(async_session, 2, ["cyan-aura"])
    async with async_session() as db:
        svc = RewardsService(db)
        assert await svc.draw_random_phantom_skin(user.id, ALL_SEED_SKINS, "run-1") == "cyan-aura"


async def test_draw_ignores_skins_missing_from_the_seed_catalog(async_session):
    """An older seed cannot resolve a name it does not know, so never pick one."""
    user = await _user_with_skins(async_session, 3, ["gold-aura", "cyan-aura"])
    async with async_session() as db:
        svc = RewardsService(db)
        drawn = await svc.draw_random_phantom_skin(user.id, _seed_catalog("cyan-aura"), "run-1")
    assert drawn == "cyan-aura"


async def test_draw_skips_catalog_entries_without_speffects(async_session):
    """A catalog entry with no SpEffect applies nothing, so it is no candidate."""
    user = await _user_with_skins(async_session, 6, ["gold-aura", "cyan-aura"])
    catalog = _seed_catalog("cyan-aura") | {"gold-aura": []}
    async with async_session() as db:
        svc = RewardsService(db)
        assert await svc.draw_random_phantom_skin(user.id, catalog, "run-1") == "cyan-aura"


async def test_draw_returns_none_without_any_candidate(async_session):
    user = await _user_with_skins(async_session, 4, [])
    async with async_session() as db:
        svc = RewardsService(db)
        assert await svc.draw_random_phantom_skin(user.id, ALL_SEED_SKINS, "run-1") is None


async def test_draw_varies_across_draw_keys(async_session):
    """Two runs must not be locked onto the same skin."""
    user = await _user_with_skins(async_session, 5, ["gold-aura", "cyan-aura"])
    async with async_session() as db:
        svc = RewardsService(db)
        drawn = {
            await svc.draw_random_phantom_skin(user.id, ALL_SEED_SKINS, f"run-{run}")
            for run in range(20)
        }
    assert drawn == {"gold-aura", "cyan-aura"}


async def test_draw_varies_between_users_on_the_same_run(async_session):
    """Racers in one race must not all be pushed onto the same aura."""
    skins = ["gold-aura", "cyan-aura", "crimson-aura", "molten-aura"]
    users = [await _user_with_skins(async_session, 10 + i, skins) for i in range(12)]
    async with async_session() as db:
        svc = RewardsService(db)
        drawn = {
            await svc.draw_random_phantom_skin(u.id, ALL_SEED_SKINS, "same-run") for u in users
        }
    assert len(drawn) > 1


async def test_a_mid_run_unlock_never_swaps_the_pick_between_older_skins(async_session):
    """Rewards are granted mid-run, and a reconnect re-draws from scratch.

    A pick that shifted because an unrelated skin joined the pool would swap
    the aura of a player who just earned something.
    """
    users = [
        await _user_with_skins(async_session, 30 + i, ["gold-aura", "cyan-aura"]) for i in range(12)
    ]
    async with async_session() as db:
        svc = RewardsService(db)
        before = {
            u.id: await svc.draw_random_phantom_skin(u.id, ALL_SEED_SKINS, "same-run")
            for u in users
        }
        for u in users:
            db.add(PhantomSkinUnlock(user_id=u.id, skin_id="molten-aura"))
        await db.commit()
        after = {
            u.id: await svc.draw_random_phantom_skin(u.id, ALL_SEED_SKINS, "same-run")
            for u in users
        }
    for user_id, previous in before.items():
        assert after[user_id] in {previous, "molten-aura"}
