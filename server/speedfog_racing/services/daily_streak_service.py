"""Daily streak business logic.

Two surfaces:

- A *pure* algorithm (``apply_qualification``, ``apply_close_day``) over the
  immutable ``StreakState`` dataclass. Easy to unit-test, no DB dependency.
- Persistence helpers that read the live ``User`` and ``Participant`` rows,
  apply the algorithm, write back. Triggered by event_flag (Update A), the
  daily-creation tick (Update B), reroll, and the backfill in the Alembic
  migration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from speedfog_racing.models import Participant, Race, User

FREEZE_CAP = 2
FREEZE_GRANT_PERIOD = 7


def qualifies_for_streak(zone_history: Sequence[Any] | None) -> bool:
    """Single source of truth for the qualification predicate.

    A participant qualifies for their daily's streak credit once their
    ``zone_history`` has at least two entries (spawn plus first fog).
    Mirrored by ``buildLiveMyResult`` on the frontend and by the
    revision-pinned predicate in the Alembic migration's backfill.
    """
    return zone_history is not None and len(zone_history) >= 2


@dataclass(frozen=True)
class StreakState:
    """Snapshot of a user's streak state, mirrored on ``users`` columns."""

    current_streak: int
    best_streak: int
    freeze_count: int
    last_qualifying_date: date | None

    @classmethod
    def from_user(cls, user: User) -> StreakState:
        return cls(
            current_streak=user.daily_current_streak,
            best_streak=user.daily_best_streak,
            freeze_count=user.daily_freeze_count,
            last_qualifying_date=user.daily_last_qualifying_date,
        )

    def write_to(self, user: User) -> None:
        """Write the four streak fields back onto ``user``.

        Use ``write_close_day_to`` instead on the close-day branch, which
        intentionally leaves ``best_streak`` and ``last_qualifying_date``
        alone.
        """
        user.daily_current_streak = self.current_streak
        user.daily_best_streak = self.best_streak
        user.daily_freeze_count = self.freeze_count
        user.daily_last_qualifying_date = self.last_qualifying_date

    def write_close_day_to(self, user: User) -> None:
        """Write only the fields that change on a close-day transition.

        ``best_streak`` is a high water mark (never decreases) and
        ``last_qualifying_date`` is kept as the most recent qualifying
        date for debug and Update-B idempotency.
        """
        user.daily_current_streak = self.current_streak
        user.daily_freeze_count = self.freeze_count


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
    to ``today - 1``, deriving qualification from ``qualifies_for_streak``
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
        is_qualified = qualifies_for_streak(zone_history)
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
    state.write_to(user)

    await db.execute(delete(DailyStreakFreeze).where(DailyStreakFreeze.user_id == user_id))
    for d in frozen_dates:
        db.add(DailyStreakFreeze(user_id=user_id, daily_date=d))
    await db.flush()


async def apply_qualification_to_user(
    db: AsyncSession, *, user_id: UUID, daily_date: date
) -> StreakState | None:
    """Apply Update A for ``user_id`` on ``daily_date``.

    Returns the new ``StreakState`` when written, ``None`` if the user is
    already qualified for the date or does not exist. Caller is expected
    to have already verified the participant qualifies (e.g. via
    ``qualifies_for_streak`` on the live participant row).
    """
    from speedfog_racing.models import User

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return None

    state = StreakState.from_user(user)
    if state.last_qualifying_date is not None and state.last_qualifying_date >= daily_date:
        return None

    new_state = apply_qualification(state, qualified_for=daily_date)
    if new_state == state:
        return None

    new_state.write_to(user)
    await db.flush()
    return new_state


async def evaluate_qualification_for_participant(
    db: AsyncSession, participant: Participant
) -> StreakState | None:
    """Apply Update A for ``participant`` if a streak transition is due.

    Returns the new ``StreakState`` when persisted (so the caller can push
    it over WS), or ``None`` when nothing was changed (participant does
    not qualify yet, race is not a daily, or user already qualified for
    this date).

    Caller must already have ``participant.race`` loaded.
    """
    race = participant.race
    if race.daily_date is None:
        return None
    if not qualifies_for_streak(participant.zone_history):
        return None
    return await apply_qualification_to_user(
        db, user_id=participant.user_id, daily_date=race.daily_date
    )


async def apply_close_day_for_all_users(db: AsyncSession, *, missed: date) -> int:
    """For every user with an active streak who did not qualify on
    ``missed``, apply the close-day branch (freeze or break).

    Returns the number of users whose state changed. Idempotent on
    ``missed``: users already protected for this date are filtered out at
    the SQL level via ``NOT EXISTS`` on ``daily_streak_freezes``, so a
    re-tick within the same rotation day never double-consumes a freeze.
    """
    from speedfog_racing.models import DailyStreakFreeze, User

    already_protected = (
        select(DailyStreakFreeze.user_id)
        .where(DailyStreakFreeze.user_id == User.id)
        .where(DailyStreakFreeze.daily_date == missed)
    )
    candidates = (
        (
            await db.execute(
                select(User)
                .where(User.daily_current_streak > 0)
                .where(User.daily_last_qualifying_date < missed)
                .where(~already_protected.exists())
            )
        )
        .scalars()
        .all()
    )

    changed = 0
    for user in candidates:
        state = StreakState.from_user(user)
        new_state, used = apply_close_day(state, missed=missed)
        if new_state == state:
            continue
        new_state.write_close_day_to(user)
        if used:
            db.add(DailyStreakFreeze(user_id=user.id, daily_date=missed))
        changed += 1
    await db.flush()
    return changed


async def rollback_streak_for_reroll(
    db: AsyncSession, race: Race, *, today: date | None = None
) -> None:
    """After a daily reroll wipes participants' zone_history, re-derive
    the streak state of any user who had qualified for ``race.daily_date``
    before the reroll. Uses ``backfill_user`` for the recomputation so we
    do not maintain a separate inverse path.

    ``best_streak`` is treated as a high water mark and preserved across
    the rollback: a reroll undoes today's progress but never erases a
    user's all-time best.

    No-op for non-daily races. Caller is responsible for committing.

    ``today`` is forwarded to ``backfill_user`` for deterministic test
    behavior; production callers pass ``None`` so the helper uses the
    real rotation date.
    """
    from speedfog_racing.models import User

    if race.daily_date is None:
        return

    affected = [
        (p.user_id, p.user.daily_best_streak)
        for p in race.participants
        if p.user is not None and p.user.daily_last_qualifying_date == race.daily_date
    ]
    for user_id, prior_best in affected:
        await backfill_user(db, user_id, today=today)
        # Re-derivation starts from zero, which would discard the user's
        # all-time best. Restore it as a high water mark.
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        if user.daily_best_streak < prior_best:
            user.daily_best_streak = prior_best
    await db.flush()
