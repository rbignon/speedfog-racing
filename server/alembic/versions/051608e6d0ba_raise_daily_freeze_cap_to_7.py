"""raise daily freeze cap to 7

Revision ID: 051608e6d0ba
Revises: 433da75a5542
Create Date: 2026-11-11 12:37:07.028298

The streak freeze cap goes from 2 to 7 (FREEZE_CAP in daily_streak_service),
retroactively: every player whose history earned freezes the old cap withheld
is replayed at cap 7. The replay can raise their freeze count, keep alive a
streak a missed day broke (raising the best streak with it), and add the
matching ``daily_streak_freezes`` rows. Without it, the first daily reroll or
disqualification would replay its own runners at the new cap through
``backfill_user`` and leave everyone else at the old one.

A cap-7 replay is never worse than a cap-2 one (it holds at least as many
freezes at every step, so it never breaks a streak the old cap kept), so the
migration only adds ledger rows. Rows inserted by hand ahead of an absence
(docs/DAILY_SEED.md, "Extended protection") are honored as the 08:00 tick
honors them: their days are skipped, not missed. A player whose stored state
the cap-2 replay does not reproduce, for any reason (a hand edit, a missed
08:00 tick, a best streak kept through a reroll), is left untouched and logged.

Do not deploy in the first minutes after 08:00 UTC: until the daily loop's
tick has settled yesterday's misses, every player who missed it reads as
drifted and keeps the old cap.

The downgrade restores the cap-2 constraint, clamping counts to 2; it does not
undo the replayed streaks.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "051608e6d0ba"
down_revision: str | None = "433da75a5542"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger(f"alembic.migration.{revision}")

# Pinned to this revision: the live service may evolve these values.
OLD_FREEZE_CAP = 2
NEW_FREEZE_CAP = 7
FREEZE_PERIOD = 7
DAILY_ROTATION_HOUR = 8

users = sa.table(
    "users",
    sa.column("id", sa.Uuid),
    sa.column("twitch_username", sa.String),
    sa.column("daily_current_streak", sa.Integer),
    sa.column("daily_best_streak", sa.Integer),
    sa.column("daily_freeze_count", sa.Integer),
    sa.column("daily_last_qualifying_date", sa.Date),
)
races = sa.table("races", sa.column("id", sa.Uuid), sa.column("daily_date", sa.Date))
participants = sa.table(
    "participants",
    sa.column("race_id", sa.Uuid),
    sa.column("user_id", sa.Uuid),
    sa.column("zone_history", sa.JSON),
    sa.column("status", sa.String),
)
freezes = sa.table(
    "daily_streak_freezes",
    sa.column("user_id", sa.Uuid),
    sa.column("daily_date", sa.Date),
    sa.column("consumed_at", sa.DateTime(timezone=True)),
)

# (current_streak, best_streak, freeze_count, last_qualifying_date)
StreakState = tuple[int, int, int, date | None]


def replay(
    qualified: dict[date, bool],
    *,
    skipped: set[date],
    abandoned_today: bool,
    today: date,
    cap: int,
) -> tuple[StreakState, list[date]]:
    """Replay one player's daily history the way ``backfill_user`` does.

    ``qualified`` maps every daily the player took part in to whether the run
    earned streak credit. Days before ``today`` without credit are misses,
    except the ``skipped`` ones (a hand-inserted ledger row). Today counts
    only once settled: a qualification, or an abandon without one, which the
    abandon trigger settles at once. Returns the final state and the days a
    freeze was consumed on.
    """
    current = best = held = 0
    last: date | None = None
    consumed: list[date] = []

    def qualify(day: date) -> None:
        nonlocal current, best, held, last
        current += 1
        best = max(best, current)
        if current % FREEZE_PERIOD == 0 and held < cap:
            held += 1
        last = day

    def miss(day: date) -> None:
        nonlocal current, held
        if day in skipped or current == 0:
            return
        if held > 0:
            held -= 1
            consumed.append(day)
        else:
            current = 0

    day = min(qualified)
    while day < today:
        if qualified.get(day, False):
            qualify(day)
        else:
            miss(day)
        day += timedelta(days=1)
    if qualified.get(today, False):
        qualify(today)
    elif abandoned_today:
        miss(today)
    return (current, best, held, last), consumed


def hand_inserted(rows: list[tuple[date, datetime]]) -> set[date]:
    """The days of a player's ledger rows that were inserted by hand.

    The server writes a row on its day (abandon) or later (08:00 tick,
    backfill), never before the day starts. A hand-inserted range is one
    statement, so its rows share a ``consumed_at``: one row written ahead of
    its day marks the whole batch, including a first day already under way.
    """
    batches = {
        at
        for day, at in rows
        if at < datetime.combine(day, time(hour=DAILY_ROTATION_HOUR), tzinfo=UTC)
    }
    return {day for day, at in rows if at in batches}


def recompute_streaks(connection: Any, *, today: date) -> int:
    """Replay at the new cap every player the old cap held back.

    Returns the number of players updated.
    """
    qualified: dict[Any, dict[date, bool]] = defaultdict(dict)
    abandoned_today: set[Any] = set()
    history = connection.execute(
        sa.select(
            participants.c.user_id,
            races.c.daily_date,
            participants.c.zone_history,
            participants.c.status,
        )
        .select_from(participants.join(races, races.c.id == participants.c.race_id))
        .where(races.c.daily_date.is_not(None))
    )
    for user_id, daily_date, zone_history, status in history:
        earned = (
            isinstance(zone_history, list) and len(zone_history) >= 2 and status != "DISQUALIFIED"
        )
        qualified[user_id][daily_date] = qualified[user_id].get(daily_date, False) or earned
        if daily_date == today and status == "ABANDONED" and not earned:
            abandoned_today.add(user_id)

    ledger: dict[Any, list[tuple[date, datetime]]] = defaultdict(list)
    for user_id, daily_date, consumed_at in connection.execute(
        sa.select(freezes.c.user_id, freezes.c.daily_date, freezes.c.consumed_at)
    ):
        # SQLite hands the column back naive; it is stored as UTC.
        if consumed_at.tzinfo is None:
            consumed_at = consumed_at.replace(tzinfo=UTC)
        ledger[user_id].append((daily_date, consumed_at))

    names: dict[Any, str] = {}
    stored: dict[Any, StreakState] = {}
    for user_id, name, *state in connection.execute(
        sa.select(
            users.c.id,
            users.c.twitch_username,
            users.c.daily_current_streak,
            users.c.daily_best_streak,
            users.c.daily_freeze_count,
            users.c.daily_last_qualifying_date,
        )
    ):
        names[user_id] = name
        stored[user_id] = tuple(state)

    updated = 0
    for user_id, days in qualified.items():
        if user_id not in stored:
            continue
        rows = ledger[user_id]
        skipped = hand_inserted(rows)
        abandoned = user_id in abandoned_today
        old_state, old_consumed = replay(
            days, skipped=skipped, abandoned_today=abandoned, today=today, cap=OLD_FREEZE_CAP
        )
        new_state, new_consumed = replay(
            days, skipped=skipped, abandoned_today=abandoned, today=today, cap=NEW_FREEZE_CAP
        )
        # A streak the old cap broke may still break later at the new one:
        # same final state, more freeze-protected days.
        if new_state == old_state and new_consumed == old_consumed:
            continue
        if stored[user_id] != old_state:
            log.warning(
                "User %s (%s) left at the old freeze cap: stored streak %s, replay %s",
                names[user_id],
                user_id,
                stored[user_id],
                old_state,
            )
            continue
        current, best, held, last = new_state
        connection.execute(
            sa.update(users)
            .where(users.c.id == user_id)
            .values(
                daily_current_streak=current,
                daily_best_streak=best,
                daily_freeze_count=held,
                daily_last_qualifying_date=last,
            )
        )
        existing = {day for day, _ in rows}
        missing = [day for day in new_consumed if day not in existing]
        if missing:
            connection.execute(
                sa.insert(freezes),
                [{"user_id": user_id, "daily_date": day} for day in missing],
            )
        updated += 1
    return updated


def upgrade() -> None:
    op.drop_constraint("ck_users_daily_freeze_count_range", "users", type_="check")
    op.create_check_constraint(
        "ck_users_daily_freeze_count_range",
        "users",
        "daily_freeze_count >= 0 AND daily_freeze_count <= 7",
    )
    today = (datetime.now(UTC) - timedelta(hours=DAILY_ROTATION_HOUR)).date()
    updated = recompute_streaks(op.get_bind(), today=today)
    log.info("Replayed %d daily streaks at freeze cap %d", updated, NEW_FREEZE_CAP)


def downgrade() -> None:
    op.drop_constraint("ck_users_daily_freeze_count_range", "users", type_="check")
    op.execute("UPDATE users SET daily_freeze_count = 2 WHERE daily_freeze_count > 2")
    op.create_check_constraint(
        "ck_users_daily_freeze_count_range",
        "users",
        "daily_freeze_count >= 0 AND daily_freeze_count <= 2",
    )
