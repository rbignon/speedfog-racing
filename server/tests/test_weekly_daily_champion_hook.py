"""On Monday daily creation, the weekly_daily_champion badge transitions to
last week's top winner(s) by total points."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    DailySeedSchedule,
    NameTemplateUnlock,
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
from speedfog_racing.rewards.service import RewardsService
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


@pytest.fixture
async def ds_session(ds_async_engine):
    factory = async_sessionmaker(ds_async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


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
    """Create a finished daily race on `daily_day` where `winner` finishes first.

    Both participants have zone_history with 2 entries so they qualify for
    the points formula.
    """
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
            exclude_from_stats=True,
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
                    zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                    finished_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=1),
                ),
                Participant(
                    race_id=race.id,
                    user_id=other_attached.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=600_000,
                    zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                    finished_at=datetime.combine(daily_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(hours=2),
                ),
            ]
        )
        await db.commit()


async def _holders_of(session: AsyncSession, badge_id: str) -> set:
    rows = (
        (
            await session.execute(
                select(BadgeGrant.user_id).where(
                    BadgeGrant.badge_id == badge_id,
                    BadgeGrant.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


# ---------------------------------------------------------------------------
# Integration tests: create_daily_seed_if_needed triggers the rollup
# ---------------------------------------------------------------------------


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

    # Assert the badge transitioned to user A (highest total points).
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


async def test_monday_creation_grants_weekly_daily_winner_to_all_day_winners(
    ds_async_session_maker,
) -> None:
    """Tier 2: every user who won at least one daily last week gets the
    transient weekly_daily_winner badge, which is broader than the points
    champion."""
    await _seed_pool_and_system_user(ds_async_session_maker)
    user_a = await _make_user(ds_async_session_maker, "uaw", "alice_w")
    user_b = await _make_user(ds_async_session_maker, "ubw", "bob_w")

    # Previous week: A wins 04-22 and 04-23, B wins 04-24.
    # Points: A = 100 + 100 + 50 = 250 (champion); B = 50 + 50 + 100 = 200.
    # Daily winners (>=1 win): {A, B}.
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 22), winner=user_a, other=user_b
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 23), winner=user_a, other=user_b
    )
    await _create_past_daily_with_winner(
        ds_async_session_maker, daily_day=date(2026, 4, 24), winner=user_b, other=user_a
    )

    created = await create_daily_seed_if_needed(ds_async_session_maker, now=TICK_TIME)
    assert created is not None

    async with ds_async_session_maker() as db:
        champions = await _holders_of(db, "weekly_daily_champion")
        winners = await _holders_of(db, "weekly_daily_winner")
    assert champions == {user_a.id}
    assert winners == {user_a.id, user_b.id}


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


async def test_monday_creation_grants_gold_aura_to_champion(
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
                        PhantomSkinUnlock.skin_id == "gold-aura",
                    )
                )
            )
            .scalars()
            .all()
        )
        unlocked_user_ids = {r.user_id for r in rows}
        assert user_a.id in unlocked_user_ids
        assert user_b.id not in unlocked_user_ids

        crown_rows = (
            (
                await db.execute(
                    select(NameTemplateUnlock).where(
                        NameTemplateUnlock.template_id == "daily_crown",
                    )
                )
            )
            .scalars()
            .all()
        )
        crown_user_ids = {r.user_id for r in crown_rows}
        assert user_a.id in crown_user_ids


async def test_gold_aura_persists_when_next_week_has_different_champion(
    ds_async_session_maker,
) -> None:
    """Permanent souvenir: a later weekly rollup does not revoke an earlier
    champion's gold-aura, even though the transient badge transitions away."""
    await _seed_pool_and_system_user(ds_async_session_maker, seeds=10)
    user_a = await _make_user(ds_async_session_maker, "ua_p1", "alice_p1")
    user_b = await _make_user(ds_async_session_maker, "ub_p1", "bob_p1")

    # Week 1: A wins twice, B zero. After Monday rollup, A gets gold-aura.
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
                        PhantomSkinUnlock.skin_id == "gold-aura",
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


# ---------------------------------------------------------------------------
# Direct unit tests for refresh_weekly_daily_rewards (points-based)
# ---------------------------------------------------------------------------


async def _make_user_direct(db: AsyncSession, twitch_id: str, username: str) -> User:
    u = User(twitch_id=twitch_id, twitch_username=username, role=UserRole.USER)
    db.add(u)
    await db.flush()
    return u


async def _make_daily_direct(db: AsyncSession, *, organizer: User, daily_date: date) -> Race:
    started = datetime.combine(daily_date, datetime.min.time(), tzinfo=UTC).replace(hour=8)
    race = Race(
        name=f"daily-{daily_date}",
        organizer_id=organizer.id,
        status=RaceStatus.FINISHED,
        daily_date=daily_date,
        exclude_from_stats=True,
        is_public=True,
        open_registration=True,
        late_join_window_minutes=1440,
        race_duration_minutes=1440,
        started_at=started,
        finished_at=started + timedelta(hours=2),
        seeds_released_at=started,
    )
    db.add(race)
    await db.flush()
    return race


async def _make_participant_direct(
    db: AsyncSession,
    *,
    race: Race,
    user: User,
    igt_ms: int,
) -> Participant:
    p = Participant(
        race_id=race.id,
        user_id=user.id,
        status=ParticipantStatus.FINISHED,
        igt_ms=igt_ms,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    db.add(p)
    await db.flush()
    return p


async def test_champion_is_user_with_highest_total_points(ds_session: AsyncSession) -> None:
    """Highest total points across the week wins the badge.

    Daily 1 (3 finishers, n=3):
      alice rank 1 -> round(100 * 3/3) = 100
      bob   rank 2 -> round(100 * 2/3) = 67
      carol rank 3 -> round(100 * 1/3) = 33

    Daily 2 (3 finishers):
      bob   rank 1 -> 100
      carol rank 2 -> 67
      alice rank 3 -> 33

    Daily 3 (3 finishers):
      bob   rank 1 -> 100
      alice rank 2 -> 67
      carol rank 3 -> 33

    Totals: alice = 100 + 33 + 67 = 200, bob = 67 + 100 + 100 = 267, carol = 33 + 67 + 33 = 133
    Expected: bob holds weekly_daily_champion alone.
    """
    monday = date(2024, 1, 1)  # Far in the past so the week is closed.
    organizer = await _make_user_direct(ds_session, "sys", "system")
    alice = await _make_user_direct(ds_session, "alice", "alice")
    bob = await _make_user_direct(ds_session, "bob", "bob")
    carol = await _make_user_direct(ds_session, "carol", "carol")

    d1 = await _make_daily_direct(ds_session, organizer=organizer, daily_date=monday)
    d2 = await _make_daily_direct(
        ds_session, organizer=organizer, daily_date=monday + timedelta(days=1)
    )
    d3 = await _make_daily_direct(
        ds_session, organizer=organizer, daily_date=monday + timedelta(days=2)
    )

    # Daily 1: alice 1st, bob 2nd, carol 3rd.
    await _make_participant_direct(ds_session, race=d1, user=alice, igt_ms=100_000)
    await _make_participant_direct(ds_session, race=d1, user=bob, igt_ms=200_000)
    await _make_participant_direct(ds_session, race=d1, user=carol, igt_ms=300_000)

    # Daily 2: bob 1st, carol 2nd, alice 3rd.
    await _make_participant_direct(ds_session, race=d2, user=bob, igt_ms=100_000)
    await _make_participant_direct(ds_session, race=d2, user=carol, igt_ms=200_000)
    await _make_participant_direct(ds_session, race=d2, user=alice, igt_ms=300_000)

    # Daily 3: bob 1st, alice 2nd, carol 3rd.
    await _make_participant_direct(ds_session, race=d3, user=bob, igt_ms=100_000)
    await _make_participant_direct(ds_session, race=d3, user=alice, igt_ms=200_000)
    await _make_participant_direct(ds_session, race=d3, user=carol, igt_ms=300_000)

    await ds_session.flush()

    await RewardsService(ds_session).refresh_weekly_daily_rewards(week_starting=monday)
    await ds_session.flush()

    holders = await _holders_of(ds_session, "weekly_daily_champion")
    assert holders == {bob.id}


async def test_champion_handles_ties(ds_session: AsyncSession) -> None:
    """Two users tied at max total points both hold the badge."""
    monday = date(2024, 1, 8)
    organizer = await _make_user_direct(ds_session, "sys2", "system2")
    alice = await _make_user_direct(ds_session, "alice2", "alice2")
    bob = await _make_user_direct(ds_session, "bob2", "bob2")

    # Single daily with alice and bob tied (same igt_ms -> same rank -> same points).
    d1 = await _make_daily_direct(ds_session, organizer=organizer, daily_date=monday)
    await _make_participant_direct(ds_session, race=d1, user=alice, igt_ms=1000)
    await _make_participant_direct(ds_session, race=d1, user=bob, igt_ms=1000)
    await ds_session.flush()

    await RewardsService(ds_session).refresh_weekly_daily_rewards(week_starting=monday)
    await ds_session.flush()

    holders = await _holders_of(ds_session, "weekly_daily_champion")
    assert alice.id in holders
    assert bob.id in holders


async def test_no_qualified_participations_clears_holders(ds_session: AsyncSession) -> None:
    """Empty week: holder set is reset to empty."""
    monday = date(2024, 1, 15)
    organizer = await _make_user_direct(ds_session, "sys3", "system3")
    alice = await _make_user_direct(ds_session, "alice3", "alice3")

    # Daily race with a participant who has zone_history too short to qualify.
    d1 = await _make_daily_direct(ds_session, organizer=organizer, daily_date=monday)
    p = Participant(
        race_id=d1.id,
        user_id=alice.id,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}],  # Only 1 entry: below the 2-entry threshold.
    )
    ds_session.add(p)
    await ds_session.flush()

    await RewardsService(ds_session).refresh_weekly_daily_rewards(week_starting=monday)
    await ds_session.flush()

    holders = await _holders_of(ds_session, "weekly_daily_champion")
    assert holders == set()
