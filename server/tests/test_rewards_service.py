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


async def test_refresh_top1_elo_holders_grants_runebearer_to_top5(async_session):
    from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD

    async with async_session() as db:
        # Top 5 settled players (descending ELO) and one provisional player
        # whose high ELO should be ignored.
        ranked = [
            User(
                twitch_id=f"tid-r{i}",
                twitch_username=f"r{i}",
                elo_rating=2000 - i * 50,
                elo_races=PROVISIONAL_THRESHOLD,
            )
            for i in range(5)
        ]
        sixth = User(
            twitch_id="tid-r5",
            twitch_username="r5",
            elo_rating=1700,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        provisional = User(
            twitch_id="tid-p",
            twitch_username="p",
            elo_rating=2500,
            elo_races=1,
        )
        db.add_all([*ranked, sixth, provisional])
        await db.commit()
        for u in [*ranked, sixth, provisional]:
            await db.refresh(u)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
        unlocked = {
            row[0]
            for row in (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "runebearer",
                    )
                )
            ).all()
        }
        assert unlocked == {u.id for u in ranked}
        assert sixth.id not in unlocked
        assert provisional.id not in unlocked


async def test_refresh_top1_elo_holders_runebearer_includes_rank5_ties(async_session):
    from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD

    async with async_session() as db:
        # Four players strictly above, three tied at the rank-5 ELO.
        above = [
            User(
                twitch_id=f"tid-a{i}",
                twitch_username=f"a{i}",
                elo_rating=2000 - i * 50,
                elo_races=PROVISIONAL_THRESHOLD,
            )
            for i in range(4)
        ]
        tied = [
            User(
                twitch_id=f"tid-t{i}",
                twitch_username=f"t{i}",
                elo_rating=1700,
                elo_races=PROVISIONAL_THRESHOLD,
            )
            for i in range(3)
        ]
        db.add_all([*above, *tied])
        await db.commit()
        for u in [*above, *tied]:
            await db.refresh(u)

    async with async_session() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
        unlocked = {
            row[0]
            for row in (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "runebearer",
                    )
                )
            ).all()
        }
        assert unlocked == {u.id for u in (*above, *tied)}


async def test_refresh_top1_elo_holders_runebearer_idempotent(async_session):
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
        await svc.refresh_top1_elo_holders()
        await db.commit()

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == a.id,
                        NameTemplateUnlock.template_id == "runebearer",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


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
        await RewardsService(db).check_veteran_eligibility(u.id)
        await db.commit()

    async with async_session() as db:
        grants = (
            (await db.execute(select(BadgeGrant).where(BadgeGrant.user_id == u.id))).scalars().all()
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
        await RewardsService(db).check_veteran_eligibility(u.id)
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
        await RewardsService(db).check_veteran_eligibility(u.id)
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
        await RewardsService(db).check_veteran_eligibility(u.id)
        await db.commit()

    async with async_session() as db:
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == u.id,
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
        await svc.check_veteran_eligibility(u.id)
        await svc.check_veteran_eligibility(u.id)
        await svc.check_veteran_eligibility(u.id)
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
        await RewardsService(db).check_veteran_eligibility(u.id)
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
