"""On Monday daily creation, the weekly_daily_champion badge transitions to
last week's top winner(s)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    DailySeedSchedule,
    Participant,
    ParticipantStatus,
    PhantomSkinUnlock,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.daily_seed_loop import create_daily_seed_if_needed

TICK_TIME = datetime(2026, 4, 27, 8, 3, tzinfo=UTC)  # Monday


@pytest.fixture
async def ds_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def ds_async_session_maker(ds_async_engine):
    return async_sessionmaker(ds_async_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_pool_and_system_user(session_maker, *, seeds: int = 5) -> None:
    async with session_maker() as db:
        for weekday in range(7):
            db.add(DailySeedSchedule(weekday=weekday, pool_name="standard"))
        db.add(
            User(
                twitch_id="system:daily",
                twitch_username="speedfog_daily",
                role=UserRole.SYSTEM,
            )
        )
        for i in range(seeds):
            db.add(
                Seed(
                    seed_number=f"daily-{i}",
                    pool_name="standard",
                    graph_json={"total_layers": 5, "nodes": []},
                    total_layers=5,
                    folder_path=f"/test/daily-{i}",
                    status=SeedStatus.AVAILABLE,
                )
            )
        await db.commit()


async def _make_user(session_maker, twitch_id: str, username: str) -> User:
    async with session_maker() as db:
        u = User(twitch_id=twitch_id, twitch_username=username, role=UserRole.USER)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def _create_past_daily_with_winner(
    session_maker,
    *,
    daily_day: date,
    winner: User,
    other: User,
) -> None:
    """Create a finished daily race on `daily_day` where `winner` finishes first."""
    async with session_maker() as db:
        # Need a separate Seed row with CONSUMED status for the past race.
        seed = Seed(
            seed_number=f"past-{daily_day.isoformat()}",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path=f"/test/past-{daily_day}",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        # Need the system user as organizer.
        org_q = await db.execute(select(User).where(User.twitch_id == "system:daily"))
        organizer = org_q.scalar_one()
        await db.flush()

        race = Race(
            name=f"Daily Seed - {daily_day.isoformat()}",
            organizer_id=organizer.id,
            seed_id=seed.id,
            daily_date=daily_day,
            exclude_from_elo=True,
            status=RaceStatus.FINISHED,
            started_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC),
            finished_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=2),
        )
        db.add(race)
        await db.flush()

        # Re-attach detached User objects passed from earlier sessions.
        winner_attached = await db.merge(winner)
        other_attached = await db.merge(other)
        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=winner_attached.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=300_000,
                    finished_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=1),
                ),
                Participant(
                    race_id=race.id,
                    user_id=other_attached.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=600_000,
                    finished_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=2),
                ),
            ]
        )
        await db.commit()


async def test_monday_creation_grants_weekly_daily_champion_to_top_winner(
    ds_async_session_maker,
) -> None:
    await _seed_pool_and_system_user(ds_async_session_maker)
    user_a = await _make_user(ds_async_session_maker, "ua", "alice")
    user_b = await _make_user(ds_async_session_maker, "ub", "bob")

    # Previous week (Mon 2026-04-20 .. Sun 2026-04-26): A wins 2 dailies, B wins 0.
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 22), winner=user_a, other=user_b
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 24), winner=user_a, other=user_b
    )

    # Trigger: create the Monday 2026-04-27 daily.
    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None
    assert created.daily_date == date(2026, 4, 27)

    # Assert the badge transitioned to user A.
    async with ds_async_session_maker() as db:
        holders = (
            (
                await db.execute(
                    select(BadgeGrant.user_id).where(
                        BadgeGrant.badge_id == "weekly_daily_champion",
                        BadgeGrant.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(holders) == {user_a.id}


async def test_non_monday_creation_does_not_touch_weekly_badge(
    ds_async_session_maker,
) -> None:
    """A daily creation on a non-Monday must not modify weekly_daily_champion holders."""
    await _seed_pool_and_system_user(ds_async_session_maker)

    # Tuesday 2026-04-28 08:03 UTC -> daily_date is 2026-04-28 (Tuesday).
    tuesday_tick = datetime(2026, 4, 28, 8, 3, tzinfo=UTC)
    created = await create_daily_seed_if_needed(ds_async_session_maker, now=tuesday_tick)
    assert created is not None
    assert created.daily_date == date(2026, 4, 28)

    async with ds_async_session_maker() as db:
        holders = (
            (
                await db.execute(
                    select(BadgeGrant.user_id).where(
                        BadgeGrant.badge_id == "weekly_daily_champion",
                    )
                )
            )
            .scalars()
            .all()
        )
        # No grants because no rollup ran (and no winners pre-seeded for Tuesday's prior week).
        assert holders == []


async def test_monday_creation_grants_cyan_aura_to_top_winner(
    ds_async_session_maker,
) -> None:
    await _seed_pool_and_system_user(ds_async_session_maker)
    user_a = await _make_user(ds_async_session_maker, "ua_cyan", "alice_cyan")
    user_b = await _make_user(ds_async_session_maker, "ub_cyan", "bob_cyan")
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 22), winner=user_a, other=user_b
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 24), winner=user_a, other=user_b
    )
    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None

    async with ds_async_session_maker() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.skin_id == "cyan-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        unlocked_user_ids = {r.user_id for r in rows}
        assert user_a.id in unlocked_user_ids
        assert user_b.id not in unlocked_user_ids


async def test_cyan_aura_persists_when_next_week_has_different_champion(
    ds_async_session_maker,
) -> None:
    """Permanent souvenir: a later weekly rollup does not revoke an earlier
    champion's cyan-aura, even though the transient badge transitions away."""
    await _seed_pool_and_system_user(ds_async_session_maker, seeds=10)
    user_a = await _make_user(ds_async_session_maker, "ua_p1", "alice_p1")
    user_b = await _make_user(ds_async_session_maker, "ub_p1", "bob_p1")

    # Week 1: A wins twice, B zero. After Monday rollup, A gets cyan-aura.
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 22), winner=user_a, other=user_b
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 24), winner=user_a, other=user_b
    )
    await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)

    # Week 2: B wins twice, A zero. Trigger the next Monday rollup.
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 29), winner=user_b, other=user_a
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 5, 1), winner=user_b, other=user_a
    )
    next_monday = datetime(2026, 5, 4, 8, 3, tzinfo=UTC)
    await create_daily_seed_if_needed(ds_async_session_maker, now=next_monday)

    async with ds_async_session_maker() as db:
        rows = (
            (
                await db.execute(
                    select(PhantomSkinUnlock).where(
                        PhantomSkinUnlock.skin_id == "cyan-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        unlocked_user_ids = {r.user_id for r in rows}
        # Both A (week 1 champion) and B (week 2 champion) keep the souvenir.
        assert user_a.id in unlocked_user_ids
        assert user_b.id in unlocked_user_ids
