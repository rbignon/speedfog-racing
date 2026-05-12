"""Pure unit tests for the streak transition algorithm."""

from __future__ import annotations

from datetime import date

from speedfog_racing.services.daily_streak_service import (
    StreakState,
    apply_close_day,
    apply_qualification,
    walk_history,
)


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
