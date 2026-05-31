"""Unit tests for daily_points_service pure helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus, User
from speedfog_racing.services.daily_points_service import (
    QualifiedParticipant,
    compute_daily_points,
    compute_weekly_leaderboard,
    compute_weekly_winners,
    daily_points_for_race,
)


@pytest.fixture
async def _async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(_async_engine):
    factory = async_sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


def _qp(
    *,
    user_id: UUID | None = None,
    status: ParticipantStatus,
    igt_ms: int,
    zone_history_len: int,
) -> QualifiedParticipant:
    return QualifiedParticipant(
        participant_id=uuid4(),
        user_id=user_id or uuid4(),
        status=status,
        igt_ms=igt_ms,
        zone_history_len=zone_history_len,
    )


def test_single_finisher_gets_50_points():
    qp = _qp(status=ParticipantStatus.FINISHED, igt_ms=1500, zone_history_len=10)
    points = compute_daily_points([qp])
    assert points[qp.participant_id] == 50


def test_five_finishers_linear_ladder():
    qps = [
        _qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i, zone_history_len=10)
        for i in range(5)
    ]
    points = compute_daily_points(qps)
    expected = [50, 40, 30, 20, 10]
    for qp, exp in zip(qps, expected, strict=True):
        assert points[qp.participant_id] == exp


def test_fifty_finishers_last_gets_1_point():
    qps = [
        _qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i, zone_history_len=10)
        for i in range(50)
    ]
    points = compute_daily_points(qps)
    assert points[qps[0].participant_id] == 50
    assert points[qps[-1].participant_id] == 1


def test_finished_then_abandoned_ordering():
    finisher = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=15)
    further_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=900, zone_history_len=12)
    earlier_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=500, zone_history_len=5)
    points = compute_daily_points([finisher, further_abandon, earlier_abandon])
    # n = 3. Ranks: finisher=1, further_abandon=2, earlier_abandon=3.
    assert points[finisher.participant_id] == 50  # round(50 * 3/3) = 50
    assert points[further_abandon.participant_id] == 33  # round(50 * 2/3) = 33
    assert points[earlier_abandon.participant_id] == 17  # round(50 * 1/3) = 17


def test_abandoned_tiebreak_uses_zone_history_then_igt():
    a = _qp(status=ParticipantStatus.ABANDONED, igt_ms=800, zone_history_len=10)
    # same zone_history_len as a, higher igt -> ranks above a
    b = _qp(status=ParticipantStatus.ABANDONED, igt_ms=1200, zone_history_len=10)
    # fewer zones -> last
    c = _qp(status=ParticipantStatus.ABANDONED, igt_ms=900, zone_history_len=5)
    points = compute_daily_points([a, b, c])
    # n = 3. Ranks: b=1, a=2, c=3.
    assert points[b.participant_id] == 50
    assert points[a.participant_id] == 33
    assert points[c.participant_id] == 17


def test_strict_igt_tie_uses_sport_convention():
    """Two finishers tied at the same IGT share rank 1, next rank skips to 3."""
    a = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=10)
    b = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000, zone_history_len=10)
    c = _qp(status=ParticipantStatus.FINISHED, igt_ms=2000, zone_history_len=10)
    points = compute_daily_points([a, b, c])
    # n = 3. Ranks: a=1, b=1, c=3.
    assert points[a.participant_id] == 50
    assert points[b.participant_id] == 50
    assert points[c.participant_id] == 17  # round(50 * 1/3) = 17


def test_single_abandoned_gets_50_points():
    qp = _qp(status=ParticipantStatus.ABANDONED, igt_ms=300, zone_history_len=4)
    points = compute_daily_points([qp])
    assert points[qp.participant_id] == 50


def test_empty_input_returns_empty_dict():
    assert compute_daily_points([]) == {}


# --- compute_weekly_leaderboard (DB-backed) -------------------------------


async def _make_user(db: AsyncSession, username: str) -> User:
    user = User(
        twitch_id=f"id-{username}",
        twitch_username=username,
        twitch_display_name=username.title(),
    )
    db.add(user)
    await db.flush()
    return user


async def _make_daily(
    db: AsyncSession, *, organizer: User, daily_date: date, status: RaceStatus
) -> Race:
    started = datetime.combine(daily_date, datetime.min.time(), tzinfo=UTC).replace(hour=8)
    race = Race(
        name=f"daily-{daily_date}",
        organizer_id=organizer.id,
        status=status,
        daily_date=daily_date,
        exclude_from_elo=True,
        is_public=True,
        open_registration=True,
        late_join_window_minutes=1440,
        race_duration_minutes=1440,
        started_at=started,
        seeds_released_at=started,
    )
    db.add(race)
    await db.flush()
    return race


async def _make_participant(
    db: AsyncSession,
    *,
    race: Race,
    user: User,
    status: ParticipantStatus,
    igt_ms: int,
    zone_history: list[dict],  # type: ignore[type-arg]
    death_count: int = 0,
) -> Participant:
    p = Participant(
        race_id=race.id,
        user_id=user.id,
        status=status,
        igt_ms=igt_ms,
        zone_history=zone_history,
        death_count=death_count,
    )
    db.add(p)
    await db.flush()
    return p


async def _reload_race(db: AsyncSession, race_id) -> Race:  # type: ignore[no-untyped-def]
    return (
        await db.execute(
            select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
        )
    ).scalar_one()


async def test_daily_points_for_race_scores_finished_daily(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "dpfr-org")
    alice = await _make_user(db_session, "dpfr-alice")
    bob = await _make_user(db_session, "dpfr-bob")
    carol = await _make_user(db_session, "dpfr-carol")
    race = await _make_daily(
        db_session, organizer=organizer, daily_date=date(2026, 5, 25), status=RaceStatus.FINISHED
    )
    a = await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    b = await _make_participant(
        db_session,
        race=race,
        user=bob,
        status=ParticipantStatus.FINISHED,
        igt_ms=2000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    # Single zone -> non-qualified, excluded from ranking and from n.
    c = await _make_participant(
        db_session,
        race=race,
        user=carol,
        status=ParticipantStatus.ABANDONED,
        igt_ms=0,
        zone_history=[{"node_id": "a"}],
    )

    points = daily_points_for_race(await _reload_race(db_session, race.id))
    assert points[a.id] == 50  # rank 1 of n=2
    assert points[b.id] == 25  # rank 2 of n=2 -> round(50 * 1/2)
    assert c.id not in points  # non-qualified gets no entry


async def test_daily_points_for_race_empty_while_running(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "dpfr-org2")
    alice = await _make_user(db_session, "dpfr-alice2")
    race = await _make_daily(
        db_session, organizer=organizer, daily_date=date(2026, 5, 25), status=RaceStatus.RUNNING
    )
    await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    assert daily_points_for_race(await _reload_race(db_session, race.id)) == {}


async def test_daily_points_for_race_empty_for_non_daily(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "dpfr-org3")
    alice = await _make_user(db_session, "dpfr-alice3")
    race = Race(
        name="regular",
        organizer_id=organizer.id,
        status=RaceStatus.FINISHED,
        is_public=True,
    )
    db_session.add(race)
    await db_session.flush()
    await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    assert daily_points_for_race(await _reload_race(db_session, race.id)) == {}


async def test_weekly_leaderboard_only_counts_finished_dailies(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "sysd")
    alice = await _make_user(db_session, "alice")
    monday = date(2026, 5, 25)

    closed = await _make_daily(
        db_session, organizer=organizer, daily_date=monday, status=RaceStatus.FINISHED
    )
    running = await _make_daily(
        db_session,
        organizer=organizer,
        daily_date=monday + timedelta(days=1),
        status=RaceStatus.RUNNING,
    )
    await _make_participant(
        db_session,
        race=closed,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=running,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=900,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    data = await compute_weekly_leaderboard(db_session, monday)
    assert data.dailies_total == 1
    assert len(data.entries) == 1
    entry = data.entries[0]
    assert entry.user.twitch_username == "alice"
    assert entry.total_points == 50
    assert entry.dailies_played == 1


async def test_weekly_leaderboard_excludes_non_qualified(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "sysd2")
    alice = await _make_user(db_session, "alice2")
    bob = await _make_user(db_session, "bob2")
    monday = date(2026, 5, 25)
    race = await _make_daily(
        db_session, organizer=organizer, daily_date=monday, status=RaceStatus.FINISHED
    )
    await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=race,
        user=bob,
        status=ParticipantStatus.ABANDONED,
        igt_ms=0,
        zone_history=[{"node_id": "a"}],
    )

    data = await compute_weekly_leaderboard(db_session, monday)
    assert len(data.entries) == 1
    assert data.entries[0].user.twitch_username == "alice2"


async def test_weekly_leaderboard_aggregates_across_days(db_session: AsyncSession) -> None:
    organizer = await _make_user(db_session, "sysd3")
    alice = await _make_user(db_session, "alice3")
    bob = await _make_user(db_session, "bob3")
    monday = date(2026, 5, 25)
    tuesday = monday + timedelta(days=1)

    mon = await _make_daily(
        db_session, organizer=organizer, daily_date=monday, status=RaceStatus.FINISHED
    )
    tue = await _make_daily(
        db_session, organizer=organizer, daily_date=tuesday, status=RaceStatus.FINISHED
    )
    await _make_participant(
        db_session,
        race=mon,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=mon,
        user=bob,
        status=ParticipantStatus.FINISHED,
        igt_ms=2000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=tue,
        user=bob,
        status=ParticipantStatus.FINISHED,
        igt_ms=900,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=tue,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1500,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    data = await compute_weekly_leaderboard(db_session, monday)
    by_user = {e.user.twitch_username: e for e in data.entries}
    assert by_user["alice3"].total_points == 75
    assert by_user["alice3"].dailies_played == 2
    assert by_user["bob3"].total_points == 75
    assert by_user["bob3"].dailies_played == 2
    assert by_user["alice3"].rank == 1
    assert by_user["bob3"].rank == 1
    assert data.dailies_total == 2


# --- compute_weekly_winners ------------------------------------------------


async def test_winners_returns_none_for_current_week(db_session, monkeypatch):
    """Current week: not yet decided -> None."""
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 5, 27))
    # 2026-05-27 is Wednesday inside week starting 2026-05-25.
    winners = await compute_weekly_winners(db_session, date(2026, 5, 25))
    assert winners is None


async def test_winners_returns_empty_for_past_week_no_qualified(db_session, monkeypatch):
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))
    winners = await compute_weekly_winners(db_session, date(2026, 5, 25))
    assert winners == []


async def test_winners_uses_rotation_date_at_monday_boundary(db_session, monkeypatch):
    """At Monday 04:00 UTC the rotation date is still Sunday, so the prior
    week (Mon to Sun) is still 'current' and winners must be None."""
    from speedfog_racing.services import daily_points_service as svc

    # Build a finished daily in the prior week so that, under raw UTC today,
    # the winners would be visible at Monday 04:00 UTC.
    organizer = await _make_user(db_session, "syswr")
    alice = await _make_user(db_session, "alicewr")
    prev_monday = date(2026, 5, 18)  # week to test
    race = await _make_daily(
        db_session,
        organizer=organizer,
        daily_date=prev_monday,
        status=RaceStatus.FINISHED,
    )
    await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    # Freeze "now" at Monday 2026-05-25 04:00 UTC. daily_date_for returns Sunday.
    monkeypatch.setattr(
        svc,
        "_today",
        lambda: date(2026, 5, 24),  # the rotation date at that instant
    )
    winners = await compute_weekly_winners(db_session, prev_monday)
    assert winners is None  # week ending 2026-05-25 is still "current"

    # Same wall time but raw UTC date -> would have flipped past.
    monkeypatch.setattr(svc, "_today", lambda: date(2026, 5, 25))
    winners = await compute_weekly_winners(db_session, prev_monday)
    assert winners is not None  # week is now fully past


async def test_winners_returns_all_tied_for_past_week(db_session, monkeypatch):
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))

    organizer = await _make_user(db_session, "sysw")
    alice = await _make_user(db_session, "alicew")
    bob = await _make_user(db_session, "bobw")
    monday = date(2026, 5, 25)

    race = await _make_daily(
        db_session, organizer=organizer, daily_date=monday, status=RaceStatus.FINISHED
    )
    # Tied at IGT -> both rank 1 -> both 50 pts.
    await _make_participant(
        db_session,
        race=race,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=race,
        user=bob,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    winners = await compute_weekly_winners(db_session, monday)
    assert winners is not None
    names = {w.user.twitch_username for w in winners}
    assert names == {"alicew", "bobw"}
    for w in winners:
        assert w.total_points == 50
