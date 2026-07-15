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
    current_layer: int = 0,
) -> QualifiedParticipant:
    return QualifiedParticipant(
        participant_id=uuid4(),
        user_id=user_id or uuid4(),
        status=status,
        igt_ms=igt_ms,
        current_layer=current_layer,
    )


def test_single_finisher_gets_max_points():
    qp = _qp(status=ParticipantStatus.FINISHED, igt_ms=1500)
    points = compute_daily_points([qp])
    assert points[qp.participant_id] == 100


def test_five_finishers_linear_ladder():
    qps = [_qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i) for i in range(5)]
    points = compute_daily_points(qps)
    expected = [100, 80, 60, 40, 20]
    for qp, exp in zip(qps, expected, strict=True):
        assert points[qp.participant_id] == exp


def test_only_first_place_reaches_max_on_large_field():
    """At n=200 the raw formula rounds rank 2 up to MAX (round(100*199/200) =
    round(99.5) = 100). The cap must keep MAX unique to the winner."""
    qps = [_qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i) for i in range(200)]
    points = compute_daily_points(qps)
    assert points[qps[0].participant_id] == 100
    assert points[qps[1].participant_id] == 99
    assert sum(1 for v in points.values() if v == 100) == 1


def test_large_field_last_place_floored_to_one():
    """At n=250 the raw last value is round(100/250) = round(0.4) = 0. The
    floor must keep every qualified runner strictly positive."""
    qps = [_qp(status=ParticipantStatus.FINISHED, igt_ms=100 + i) for i in range(250)]
    points = compute_daily_points(qps)
    assert points[qps[-1].participant_id] == 1
    assert min(points.values()) == 1


def test_finished_then_abandoned_ordering():
    finisher = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000)
    further_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=900, current_layer=12)
    earlier_abandon = _qp(status=ParticipantStatus.ABANDONED, igt_ms=500, current_layer=5)
    points = compute_daily_points([finisher, further_abandon, earlier_abandon])
    # n = 3. Ranks: finisher=1, further_abandon=2 (deeper layer), earlier_abandon=3.
    assert points[finisher.participant_id] == 100  # round(100 * 3/3) = 100
    assert points[further_abandon.participant_id] == 67  # round(100 * 2/3) = 67
    assert points[earlier_abandon.participant_id] == 33  # round(100 * 1/3) = 33


def test_abandoned_ranked_by_layer_then_igt():
    # Mirrors sort_leaderboard: deeper current_layer first, then faster igt.
    deep_slow = _qp(status=ParticipantStatus.ABANDONED, igt_ms=1200, current_layer=20)
    # same layer as deep_slow, reached it faster -> ranks above it
    deep_fast = _qp(status=ParticipantStatus.ABANDONED, igt_ms=800, current_layer=20)
    # shallower layer -> last, regardless of its (lower) igt
    shallow = _qp(status=ParticipantStatus.ABANDONED, igt_ms=500, current_layer=12)
    points = compute_daily_points([deep_slow, deep_fast, shallow])
    # n = 3. Ranks: deep_fast=1, deep_slow=2, shallow=3.
    assert points[deep_fast.participant_id] == 100
    assert points[deep_slow.participant_id] == 67
    assert points[shallow.participant_id] == 33


def test_deeper_layer_outranks_longer_history():
    """Regression: a direct run that reached a deeper layer must outscore a
    meandering run that visited more zones but stopped shallower. The old
    ranking keyed on len(zone_history), which inverted this whenever the
    deeper run took a more direct route (fewer logged zones)."""
    direct_deep = _qp(status=ParticipantStatus.ABANDONED, igt_ms=6000, current_layer=19)
    meander_shallow = _qp(status=ParticipantStatus.ABANDONED, igt_ms=2800, current_layer=18)
    points = compute_daily_points([direct_deep, meander_shallow])
    # n = 2. direct_deep=rank1, meander_shallow=rank2.
    assert points[direct_deep.participant_id] == 100
    assert points[meander_shallow.participant_id] == 50


def test_strict_igt_tie_uses_sport_convention():
    """Two finishers tied at the same IGT share rank 1, next rank skips to 3."""
    a = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000)
    b = _qp(status=ParticipantStatus.FINISHED, igt_ms=1000)
    c = _qp(status=ParticipantStatus.FINISHED, igt_ms=2000)
    points = compute_daily_points([a, b, c])
    # n = 3. Ranks: a=1, b=1, c=3.
    assert points[a.participant_id] == 100
    assert points[b.participant_id] == 100
    assert points[c.participant_id] == 33  # round(100 * 1/3) = 33


def test_single_abandoned_gets_max_points():
    qp = _qp(status=ParticipantStatus.ABANDONED, igt_ms=300, current_layer=4)
    points = compute_daily_points([qp])
    assert points[qp.participant_id] == 100


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
        exclude_from_stats=True,
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
    current_layer: int = 0,
) -> Participant:
    p = Participant(
        race_id=race.id,
        user_id=user.id,
        status=status,
        igt_ms=igt_ms,
        zone_history=zone_history,
        death_count=death_count,
        current_layer=current_layer,
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
    assert points[a.id] == 100  # rank 1 of n=2
    assert points[b.id] == 50  # rank 2 of n=2 -> round(100 * 1/2)
    assert c.id not in points  # non-qualified gets no entry


async def test_daily_points_for_race_ranks_abandoned_by_layer(db_session: AsyncSession) -> None:
    """daily_points_for_race must rank abandoned runs by current_layer, not by
    zone_history length. The deeper run wins even though it logged fewer zones."""
    organizer = await _make_user(db_session, "dpfr-l-org")
    deep = await _make_user(db_session, "dpfr-l-deep")
    shallow = await _make_user(db_session, "dpfr-l-shallow")
    race = await _make_daily(
        db_session, organizer=organizer, daily_date=date(2026, 5, 25), status=RaceStatus.FINISHED
    )
    # Deeper layer, shorter history (direct route).
    d = await _make_participant(
        db_session,
        race=race,
        user=deep,
        status=ParticipantStatus.ABANDONED,
        igt_ms=6000,
        current_layer=19,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}],
    )
    # Shallower layer, longer history (meandering + backtracks).
    s = await _make_participant(
        db_session,
        race=race,
        user=shallow,
        status=ParticipantStatus.ABANDONED,
        igt_ms=2800,
        current_layer=18,
        zone_history=[{"node_id": str(i)} for i in range(8)],
    )

    points = daily_points_for_race(await _reload_race(db_session, race.id))
    assert points[d.id] == 100  # rank 1 of n=2: deeper layer
    assert points[s.id] == 50  # rank 2 of n=2: shallower despite longer history


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
    assert entry.total_points == 100
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
    assert by_user["alice3"].total_points == 150  # 100 (win) + 50 (2nd of 2)
    assert by_user["alice3"].dailies_played == 2
    assert by_user["bob3"].total_points == 150  # 50 (2nd of 2) + 100 (win)
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
    # Tied at IGT -> both rank 1 -> both 100 pts.
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
        assert w.total_points == 100


# --- compute_weekly_daily_winners ------------------------------------------


async def test_daily_winners_returns_none_for_current_week(db_session, monkeypatch):
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 5, 27))
    result = await svc.compute_weekly_daily_winners(db_session, date(2026, 5, 25))
    assert result is None


async def test_daily_winners_empty_for_past_week_no_dailies(db_session, monkeypatch):
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))
    result = await svc.compute_weekly_daily_winners(db_session, date(2026, 5, 25))
    assert result == set()


async def test_daily_winners_union_across_days_with_ties(db_session, monkeypatch):
    """Anyone ranked 1st on any closed daily of the week is a winner; ties on a
    single day pull all tied users in."""
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))
    org = await _make_user(db_session, "dw-org")
    alice = await _make_user(db_session, "dw-alice")
    bob = await _make_user(db_session, "dw-bob")
    carol = await _make_user(db_session, "dw-carol")
    dave = await _make_user(db_session, "dw-dave")

    day1 = await _make_daily(
        db_session, organizer=org, daily_date=date(2026, 5, 25), status=RaceStatus.FINISHED
    )
    await _make_participant(
        db_session,
        race=day1,
        user=alice,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=day1,
        user=bob,
        status=ParticipantStatus.FINISHED,
        igt_ms=2000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    day2 = await _make_daily(
        db_session, organizer=org, daily_date=date(2026, 5, 27), status=RaceStatus.FINISHED
    )
    # carol and dave tie at IGT -> both rank 1 on day 2.
    await _make_participant(
        db_session,
        race=day2,
        user=carol,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )
    await _make_participant(
        db_session,
        race=day2,
        user=dave,
        status=ParticipantStatus.FINISHED,
        igt_ms=1000,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )

    result = await svc.compute_weekly_daily_winners(db_session, date(2026, 5, 25))
    assert result == {alice.id, carol.id, dave.id}


async def test_daily_winners_differ_from_points_champion(db_session, monkeypatch):
    """A consistent 2nd-place racer can be the weekly points champion without
    ever winning a daily; the daily-winner set must exclude them and include the
    actual day winners."""
    from speedfog_racing.services import daily_points_service as svc

    monkeypatch.setattr(svc, "_today", lambda: date(2026, 6, 8))
    org = await _make_user(db_session, "dwc-org")
    alice = await _make_user(db_session, "dwc-alice")
    bob = await _make_user(db_session, "dwc-bob")
    carol = await _make_user(db_session, "dwc-carol")
    dave = await _make_user(db_session, "dwc-dave")

    for day, winner in [
        (date(2026, 5, 25), alice),
        (date(2026, 5, 27), carol),
        (date(2026, 5, 29), dave),
    ]:
        race = await _make_daily(
            db_session, organizer=org, daily_date=day, status=RaceStatus.FINISHED
        )
        await _make_participant(
            db_session,
            race=race,
            user=winner,
            status=ParticipantStatus.FINISHED,
            igt_ms=1000,
            zone_history=[{"node_id": "a"}, {"node_id": "b"}],
        )
        await _make_participant(
            db_session,
            race=race,
            user=bob,
            status=ParticipantStatus.FINISHED,
            igt_ms=2000,
            zone_history=[{"node_id": "a"}, {"node_id": "b"}],
        )

    daily_winners = await svc.compute_weekly_daily_winners(db_session, date(2026, 5, 25))
    assert daily_winners == {alice.id, carol.id, dave.id}

    points_champions = await compute_weekly_winners(db_session, date(2026, 5, 25))
    assert points_champions is not None
    assert {w.user.id for w in points_champions} == {bob.id}
