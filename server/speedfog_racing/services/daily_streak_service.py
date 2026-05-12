"""Daily streak business logic.

Two surfaces:

- A *pure* algorithm (``apply_qualification``, ``apply_close_day``) over the
  immutable ``StreakState`` dataclass. Easy to unit-test, no DB dependency.
- Persistence helpers (added in later tasks) that read the live ``User``
  and ``Participant`` rows, apply the algorithm, write back. Triggered by
  event_flag (Update A), the daily-creation tick (Update B), reroll, and
  the backfill in the Alembic migration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

FREEZE_CAP = 2
FREEZE_GRANT_PERIOD = 7


@dataclass(frozen=True)
class StreakState:
    """Snapshot of a user's streak state, mirrored on ``users`` columns."""

    current_streak: int
    best_streak: int
    freeze_count: int
    last_qualifying_date: date | None


def apply_qualification(state: StreakState, *, qualified_for: date) -> StreakState:
    """Return the state after a qualifying participation on ``qualified_for``.

    Idempotent on the date: re-applying for the same date is a no-op.
    Assumes the caller has already filled missed-day gaps (via
    ``apply_close_day``) before reaching this date.
    """
    if state.last_qualifying_date is not None and state.last_qualifying_date >= qualified_for:
        return state

    new_current = state.current_streak + 1
    new_best = max(state.best_streak, new_current)
    new_freezes = state.freeze_count
    if new_current % FREEZE_GRANT_PERIOD == 0 and new_freezes < FREEZE_CAP:
        new_freezes += 1

    return replace(
        state,
        current_streak=new_current,
        best_streak=new_best,
        freeze_count=new_freezes,
        last_qualifying_date=qualified_for,
    )


def apply_close_day(state: StreakState, *, missed: date) -> tuple[StreakState, bool]:
    """Apply the daily-close branch for ``missed`` (a non-qualifying day).

    Returns ``(new_state, freeze_used)``. ``freeze_used`` is true iff a
    freeze was consumed (caller should write a ``daily_streak_freezes`` row
    for ``(user, missed)``).

    Caller invariant: ``missed`` is the day to evaluate; it is **not**
    written into ``last_qualifying_date`` regardless of branch taken.
    """
    if state.current_streak == 0:
        return state, False

    if state.freeze_count > 0:
        return (
            replace(state, freeze_count=state.freeze_count - 1),
            True,
        )

    return (
        replace(state, current_streak=0),
        False,
    )
