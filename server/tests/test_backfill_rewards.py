"""Tests for the rewards backfill script."""

from datetime import UTC, date, datetime

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
    UserRole,
)
from speedfog_racing.rewards.catalog import (
    DAILY_STREAK_REWARD_THRESHOLD,
    VETERAN_RACE_THRESHOLD,
)
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


async def test_backfill_grants_veteran_to_users_above_threshold(async_session_maker):
    """Users with at least VETERAN_RACE_THRESHOLD finished races receive veteran."""
    async with async_session_maker() as db:
        veteran = User(twitch_id="t-vet", twitch_username="vet")
        rookie = User(twitch_id="t-rook", twitch_username="rook")
        db.add_all([veteran, rookie])
        await db.commit()
        await db.refresh(veteran)
        await db.refresh(rookie)
        veteran_id = veteran.id
        rookie_id = rookie.id

        for i in range(VETERAN_RACE_THRESHOLD):
            race = Race(name=f"v-{i}", status=RaceStatus.FINISHED, organizer_id=veteran_id)
            db.add(race)
            await db.flush()
            db.add(
                Participant(race_id=race.id, user_id=veteran_id, status=ParticipantStatus.FINISHED)
            )

        for i in range(VETERAN_RACE_THRESHOLD - 1):
            race = Race(name=f"r-{i}", status=RaceStatus.FINISHED, organizer_id=rookie_id)
            db.add(race)
            await db.flush()
            db.add(
                Participant(race_id=race.id, user_id=rookie_id, status=ParticipantStatus.FINISHED)
            )
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        grants = (
            (await db.execute(select(BadgeGrant.user_id).where(BadgeGrant.badge_id == "veteran")))
            .scalars()
            .all()
        )
        assert set(grants) == {veteran_id}
        assert rookie_id not in set(grants)


async def test_backfill_grants_frog_pack_to_finishers(async_session_maker):
    """Users with at least one finished race receive frog + speedfrog and notifications."""
    async with async_session_maker() as db:
        finisher = User(twitch_id="t-frog", twitch_username="frogger")
        idle = User(twitch_id="t-idle", twitch_username="idle")
        db.add_all([finisher, idle])
        await db.commit()
        await db.refresh(finisher)
        await db.refresh(idle)
        finisher_id = finisher.id
        idle_id = idle.id

        race = Race(name="f-0", status=RaceStatus.FINISHED, organizer_id=finisher_id)
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=finisher_id, status=ParticipantStatus.FINISHED))
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        badge_holders = set(
            (await db.execute(select(BadgeGrant.user_id).where(BadgeGrant.badge_id == "frog")))
            .scalars()
            .all()
        )
        template_holders = set(
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "speedfrog"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert badge_holders == {finisher_id}
        assert template_holders == {finisher_id}
        assert idle_id not in badge_holders

        notif_kinds = {
            (k, r)
            for k, r in (
                await db.execute(
                    select(RewardNotification.kind, RewardNotification.reward_id).where(
                        RewardNotification.user_id == finisher_id
                    )
                )
            ).all()
        }
        assert ("badge_granted", "frog") in notif_kinds
        assert ("name_template_unlocked", "speedfrog") in notif_kinds


async def test_backfill_veteran_idempotent(async_session_maker):
    """Re-running the backfill does not duplicate veteran grants."""
    async with async_session_maker() as db:
        u = User(twitch_id="t-vetidem", twitch_username="vetidem")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        for i in range(VETERAN_RACE_THRESHOLD):
            race = Race(name=f"i-{i}", status=RaceStatus.FINISHED, organizer_id=u.id)
            db.add(race)
            await db.flush()
            db.add(Participant(race_id=race.id, user_id=u.id, status=ParticipantStatus.FINISHED))
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))
    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
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


async def test_backfill_grants_weathered_and_crimson_aura_to_veterans(async_session_maker):
    """Veterans receive weathered template and crimson-aura skin alongside the badge."""
    async with async_session_maker() as db:
        veteran = User(twitch_id="t-vet-extra", twitch_username="vetextra")
        rookie = User(twitch_id="t-rook-extra", twitch_username="rookextra")
        db.add_all([veteran, rookie])
        await db.commit()
        await db.refresh(veteran)
        await db.refresh(rookie)
        veteran_id = veteran.id
        rookie_id = rookie.id

        for i in range(VETERAN_RACE_THRESHOLD):
            race = Race(name=f"vx-{i}", status=RaceStatus.FINISHED, organizer_id=veteran_id)
            db.add(race)
            await db.flush()
            db.add(
                Participant(race_id=race.id, user_id=veteran_id, status=ParticipantStatus.FINISHED)
            )

        for i in range(VETERAN_RACE_THRESHOLD - 1):
            race = Race(name=f"rx-{i}", status=RaceStatus.FINISHED, organizer_id=rookie_id)
            db.add(race)
            await db.flush()
            db.add(
                Participant(race_id=race.id, user_id=rookie_id, status=ParticipantStatus.FINISHED)
            )
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        template_unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "weathered"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(template_unlocks) == {veteran_id}

        skin_unlocks = (
            (
                await db.execute(
                    select(PhantomSkinUnlock.user_id).where(
                        PhantomSkinUnlock.skin_id == "crimson-aura"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(skin_unlocks) == {veteran_id}


async def test_backfill_veteran_extras_idempotent(async_session_maker):
    """Re-running does not duplicate weathered or crimson-aura grants."""
    async with async_session_maker() as db:
        u = User(twitch_id="t-vet-rerun", twitch_username="vetrerun")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        user_id = u.id
        for i in range(VETERAN_RACE_THRESHOLD):
            race = Race(name=f"vr-{i}", status=RaceStatus.FINISHED, organizer_id=user_id)
            db.add(race)
            await db.flush()
            db.add(Participant(race_id=race.id, user_id=user_id, status=ParticipantStatus.FINISHED))
        await db.commit()

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        template_rows = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.user_id == user_id,
                        NameTemplateUnlock.template_id == "weathered",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(template_rows) == 1

        skin_rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user_id,
                        PhantomSkinUnlock.skin_id == "crimson-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(skin_rows) == 1


async def test_backfill_grants_emerald_aura_to_early_adopters(async_session_maker):
    """Users created before cutoff get emerald-aura; newer ones don't."""
    async with async_session_maker() as db:
        old = User(twitch_id="t-old-em", twitch_username="oldem")
        new = User(twitch_id="t-new-em", twitch_username="newem")
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
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.skin_id == "emerald-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        unlocked_user_ids = {r.user_id for r in rows}
        assert old_id in unlocked_user_ids
        assert new_id not in unlocked_user_ids


async def test_backfill_emerald_aura_idempotent(async_session_maker):
    """Re-running the backfill does not duplicate emerald-aura unlocks."""
    async with async_session_maker() as db:
        u = User(twitch_id="t-rerun-em", twitch_username="rerun_em")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        user_id = u.id
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.commit()

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))
    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user_id,
                        PhantomSkinUnlock.skin_id == "emerald-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_backfill_grants_molten_aura_to_long_streakers(async_session_maker):
    """Users whose best daily streak meets the threshold receive molten-aura."""
    async with async_session_maker() as db:
        long_streaker = User(
            twitch_id="t-streak-long",
            twitch_username="longstreak",
            daily_best_streak=DAILY_STREAK_REWARD_THRESHOLD,
        )
        short_streaker = User(
            twitch_id="t-streak-short",
            twitch_username="shortstreak",
            daily_best_streak=DAILY_STREAK_REWARD_THRESHOLD - 1,
        )
        db.add_all([long_streaker, short_streaker])
        await db.commit()
        await db.refresh(long_streaker)
        await db.refresh(short_streaker)
        long_id = long_streaker.id
        short_id = short_streaker.id

    await backfill_rewards(async_session_maker, cutoff=date(2026, 4, 1))

    async with async_session_maker() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock.user_id).where(
                        PhantomSkinUnlock.skin_id == "molten-aura"
                    )
                )
            )
            .scalars()
            .all()
        )
        unlocked = set(rows)
        assert long_id in unlocked
        assert short_id not in unlocked


async def test_backfill_molten_aura_idempotent(async_session_maker):
    """Re-running the backfill does not duplicate molten-aura unlocks."""
    async with async_session_maker() as db:
        u = User(
            twitch_id="t-streak-rerun",
            twitch_username="streakrerun",
            daily_best_streak=DAILY_STREAK_REWARD_THRESHOLD + 3,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        user_id = u.id

    cutoff = date(2026, 4, 1)
    await backfill_rewards(async_session_maker, cutoff=cutoff)
    await backfill_rewards(async_session_maker, cutoff=cutoff)

    async with async_session_maker() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.user_id == user_id,
                        PhantomSkinUnlock.skin_id == "molten-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
