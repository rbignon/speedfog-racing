"""Pure unit tests for the streak transition algorithm."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.services.daily_streak_service import (
    StreakState,
    apply_close_day,
    apply_qualification,
    evaluate_qualification_for_participant,
    walk_history,
)


@pytest.fixture
async def streak_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def streak_async_session(streak_async_engine):
    return async_sessionmaker(streak_async_engine, class_=AsyncSession, expire_on_commit=False)


def s(current: int = 0, best: int = 0, freezes: int = 0, last: date | None = None) -> StreakState:
    return StreakState(
        current_streak=current,
        best_streak=best,
        freeze_count=freezes,
        last_qualifying_date=last,
    )


# Qualification transitions ---------------------------------------------------


def test_first_qualification_starts_streak_at_one() -> None:
    new = apply_qualification(s(), qualified_for=date(2026, 5, 12))
    assert new == s(current=1, best=1, last=date(2026, 5, 12))


def test_consecutive_qualification_increments() -> None:
    prev = s(current=3, best=3, last=date(2026, 5, 11))
    new = apply_qualification(prev, qualified_for=date(2026, 5, 12))
    assert new == s(current=4, best=4, last=date(2026, 5, 12))


def test_qualification_grants_freeze_at_multiple_of_seven() -> None:
    prev = s(current=6, best=6, last=date(2026, 5, 11))
    new = apply_qualification(prev, qualified_for=date(2026, 5, 12))
    assert new == s(current=7, best=7, freezes=1, last=date(2026, 5, 12))


def test_qualification_freeze_cap_at_two() -> None:
    # Already at 2 freezes and qualifying for day 14 (multiple of 7).
    prev = s(current=13, best=13, freezes=2, last=date(2026, 5, 11))
    new = apply_qualification(prev, qualified_for=date(2026, 5, 12))
    assert new == s(current=14, best=14, freezes=2, last=date(2026, 5, 12))


def test_qualification_does_not_decrease_best() -> None:
    prev = s(current=2, best=99, last=date(2026, 5, 11))
    new = apply_qualification(prev, qualified_for=date(2026, 5, 12))
    assert new.best_streak == 99


def test_idempotent_qualification_for_same_date_is_noop() -> None:
    prev = s(current=3, best=3, last=date(2026, 5, 12))
    new = apply_qualification(prev, qualified_for=date(2026, 5, 12))
    assert new == prev


# Close-day transitions -------------------------------------------------------


def test_close_day_with_freeze_consumes_freeze_and_preserves_streak() -> None:
    prev = s(current=5, best=5, freezes=1, last=date(2026, 5, 10))
    new, freeze_used = apply_close_day(prev, missed=date(2026, 5, 11))
    assert new == s(current=5, best=5, freezes=0, last=date(2026, 5, 10))
    assert freeze_used is True


def test_close_day_without_freeze_breaks_streak() -> None:
    prev = s(current=5, best=10, freezes=0, last=date(2026, 5, 10))
    new, freeze_used = apply_close_day(prev, missed=date(2026, 5, 11))
    assert new == s(current=0, best=10, freezes=0, last=date(2026, 5, 10))
    assert freeze_used is False


def test_close_day_with_zero_streak_is_noop() -> None:
    prev = s(current=0, best=0, freezes=0, last=None)
    new, freeze_used = apply_close_day(prev, missed=date(2026, 5, 11))
    assert new == prev
    assert freeze_used is False


# Combined walk over a synthetic history --------------------------------------


def test_walk_two_freezes_absorb_two_misses_third_breaks() -> None:
    state = s()
    # Qualify days 1..14: freeze at day 7 and day 14, then capped.
    # Then miss 15, 16, 17.
    for d in range(1, 15):
        state = apply_qualification(state, qualified_for=date(2026, 1, d))
    assert state.current_streak == 14
    assert state.freeze_count == 2

    state, used = apply_close_day(state, missed=date(2026, 1, 15))
    assert used is True and state.freeze_count == 1 and state.current_streak == 14

    state, used = apply_close_day(state, missed=date(2026, 1, 16))
    assert used is True and state.freeze_count == 0 and state.current_streak == 14

    state, used = apply_close_day(state, missed=date(2026, 1, 17))
    assert used is False and state.current_streak == 0 and state.best_streak == 14


# Forward-walk helper --------------------------------------------------------


def test_walk_history_empty_returns_zero_state() -> None:
    state, frozen = walk_history([])
    assert state == StreakState(0, 0, 0, None)
    assert frozen == []


def test_walk_history_mixed_pattern_matches_step_by_step_simulation() -> None:
    # Seven qualifications -> day 7 grants a freeze.
    # Two misses -> freeze absorbs one, second one breaks.
    history = [(date(2026, 1, i), True) for i in range(1, 8)]
    history += [(date(2026, 1, 8), False), (date(2026, 1, 9), False)]
    history.append((date(2026, 1, 10), True))

    state, frozen = walk_history(history)
    # After break on day 9 the streak goes 7 -> ... -> 0 -> 1 on day 10.
    assert state.current_streak == 1
    assert state.best_streak == 7
    assert state.freeze_count == 0
    assert state.last_qualifying_date == date(2026, 1, 10)
    assert frozen == [date(2026, 1, 8)]  # only the freeze-absorbed miss


def test_walk_history_only_qualifications_does_not_emit_freezes() -> None:
    state, frozen = walk_history([(date(2026, 1, i), True) for i in range(1, 8)])
    assert state.current_streak == 7
    assert state.freeze_count == 1
    assert frozen == []


# Live participant evaluator -------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_qualification_triggers_on_crossing_two(streak_async_session) -> None:
    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )

    async with streak_async_session() as db:
        user = User(twitch_id="qt1", twitch_username="qt1")
        db.add(user)
        await db.flush()
        race = Race(
            name="Daily Seed - 2026-05-12",
            organizer_id=user.id,
            daily_date=date(2026, 5, 12),
            exclude_from_stats=True,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[
                {"node_id": "start", "igt_ms": 0, "type": "fog"},
                {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
            ],
        )
        db.add(participant)
        await db.commit()

        new_state = await evaluate_qualification_for_participant(db, participant)
        assert new_state is not None
        assert new_state.current_streak == 1
        await db.refresh(user)
        assert user.daily_current_streak == 1
        assert user.daily_last_qualifying_date == date(2026, 5, 12)


@pytest.mark.asyncio
async def test_evaluate_qualification_is_noop_when_under_two(streak_async_session) -> None:
    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )

    async with streak_async_session() as db:
        user = User(twitch_id="qt2", twitch_username="qt2")
        db.add(user)
        await db.flush()
        race = Race(
            name="Daily Seed - 2026-05-12",
            organizer_id=user.id,
            daily_date=date(2026, 5, 12),
            exclude_from_stats=True,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[{"node_id": "start", "igt_ms": 0, "type": "fog"}],
        )
        db.add(participant)
        await db.commit()

        result = await evaluate_qualification_for_participant(db, participant)
        assert result is None
        await db.refresh(user)
        assert user.daily_current_streak == 0


@pytest.mark.asyncio
async def test_evaluate_qualification_idempotent_for_same_day(streak_async_session) -> None:
    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )

    async with streak_async_session() as db:
        user = User(
            twitch_id="qt3",
            twitch_username="qt3",
            daily_current_streak=1,
            daily_best_streak=1,
            daily_last_qualifying_date=date(2026, 5, 12),
        )
        db.add(user)
        await db.flush()
        race = Race(
            name="Daily Seed - 2026-05-12",
            organizer_id=user.id,
            daily_date=date(2026, 5, 12),
            exclude_from_stats=True,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[
                {"node_id": "start", "igt_ms": 0, "type": "fog"},
                {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
                {"node_id": "n3", "igt_ms": 2000, "type": "fog"},
            ],
        )
        db.add(participant)
        await db.commit()

        result = await evaluate_qualification_for_participant(db, participant)
        assert result is None  # already qualified for this date


@pytest.mark.asyncio
async def test_evaluate_qualification_noop_for_non_daily_race(streak_async_session) -> None:
    """Non-daily races (daily_date is None) never feed the streak."""
    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        User,
    )

    async with streak_async_session() as db:
        user = User(twitch_id="qt4", twitch_username="qt4")
        db.add(user)
        await db.flush()
        race = Race(
            name="Regular race",
            organizer_id=user.id,
            daily_date=None,
            exclude_from_stats=False,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            zone_history=[
                {"node_id": "start", "igt_ms": 0, "type": "fog"},
                {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
            ],
        )
        db.add(participant)
        await db.commit()

        result = await evaluate_qualification_for_participant(db, participant)
        assert result is None
        await db.refresh(user)
        assert user.daily_current_streak == 0
