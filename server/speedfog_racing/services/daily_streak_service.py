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

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def walk_history(
    history: list[tuple[date, bool]],
) -> tuple[StreakState, list[date]]:
    """Replay a chronologically ordered history of (date, qualified) pairs.

    Returns the final ``StreakState`` and the list of dates where a freeze
    was consumed (in encounter order). Caller is responsible for ordering
    by date; this function does not sort.
    """
    state = StreakState(0, 0, 0, None)
    frozen_dates: list[date] = []
    for d, qualified in history:
        if qualified:
            state = apply_qualification(state, qualified_for=d)
        else:
            state, used = apply_close_day(state, missed=d)
            if used:
                frozen_dates.append(d)
    return state, frozen_dates


async def backfill_user(db: AsyncSession, user_id: UUID, *, today: date | None = None) -> None:
    """Recompute the user's streak state from participation history.

    Walks chronologically from the user's earliest daily participation up
    to ``today - 1``, deriving qualification from ``len(zone_history) >= 2``
    per day. Today itself counts only if the user already qualified for it
    (mirrors the live trigger). Untouched days inside the window are
    misses, evaluated by ``apply_close_day``.

    ``today`` defaults to ``daily_date_for(datetime.now(UTC))``; pass an
    explicit value in tests to pin wall-clock semantics.

    Idempotent: prior ``daily_streak_freezes`` rows for the user are wiped
    before re-emission, and the four user columns are overwritten.
    """
    from speedfog_racing.models import Participant, Race
    from speedfog_racing.services.daily_seed_loop import daily_date_for

    rows = (
        await db.execute(
            select(Race.daily_date, Participant.zone_history)
            .join(Participant, Participant.race_id == Race.id)
            .where(Participant.user_id == user_id)
            .where(Race.daily_date.is_not(None))
            .order_by(Race.daily_date)
        )
    ).all()

    qualified_by_date: dict[date, bool] = {}
    for daily_date_value, zone_history in rows:
        is_qualified = bool(zone_history) and len(zone_history) >= 2
        qualified_by_date[daily_date_value] = (
            qualified_by_date.get(daily_date_value, False) or is_qualified
        )

    if not qualified_by_date:
        await _persist_state(db, user_id, StreakState(0, 0, 0, None), [])
        return

    today_value = today if today is not None else daily_date_for(datetime.now(UTC))

    earliest = min(qualified_by_date)
    walk: list[tuple[date, bool]] = []
    cursor = earliest
    while cursor < today_value:
        walk.append((cursor, qualified_by_date.get(cursor, False)))
        cursor = date.fromordinal(cursor.toordinal() + 1)
    if qualified_by_date.get(today_value, False):
        walk.append((today_value, True))

    state, frozen = walk_history(walk)
    await _persist_state(db, user_id, state, frozen)


async def _persist_state(
    db: AsyncSession,
    user_id: UUID,
    state: StreakState,
    frozen_dates: Iterable[date],
) -> None:
    """Write ``state`` to the user row and refresh freeze rows."""
    from speedfog_racing.models import DailyStreakFreeze, User

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    user.daily_current_streak = state.current_streak
    user.daily_best_streak = state.best_streak
    user.daily_freeze_count = state.freeze_count
    user.daily_last_qualifying_date = state.last_qualifying_date

    await db.execute(delete(DailyStreakFreeze).where(DailyStreakFreeze.user_id == user_id))
    for d in frozen_dates:
        db.add(DailyStreakFreeze(user_id=user_id, daily_date=d))
    await db.flush()
