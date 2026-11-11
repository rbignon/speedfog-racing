"""The migration that raises the daily freeze cap to 7 and replays streaks."""

from __future__ import annotations

import importlib.util
import logging
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    DailyStreakFreeze,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
)

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "051608e6d0ba_raise_daily_freeze_cap_to_7.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeze_cap_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()

D1 = date(2026, 1, 1)


def day(n: int) -> date:
    """The n-th day of the synthetic history, D1 being day(1)."""
    return D1 + timedelta(days=n - 1)


def history(*qualified_days: range, played_unqualified: tuple[int, ...] = ()) -> dict[date, bool]:
    days = {day(n): True for days in qualified_days for n in days}
    days.update({day(n): False for n in played_unqualified})
    return days


# Replay ---------------------------------------------------------------------


def test_replay_new_cap_keeps_a_streak_the_old_cap_broke() -> None:
    # 21 days earn 3 freezes, the old cap kept 2: the third miss breaks only there.
    days = history(range(1, 22), range(25, 35))
    kwargs = {"skipped": set(), "abandoned_today": False, "today": day(35)}

    old = migration.replay(days, cap=2, **kwargs)
    new = migration.replay(days, cap=7, **kwargs)

    assert old == ((10, 21, 1, day(34)), [day(22), day(23)])
    assert new == ((31, 31, 1, day(34)), [day(22), day(23), day(24)])


def test_replay_skips_hand_inserted_days() -> None:
    days = history(range(1, 8), range(13, 14))
    vacation = {day(n) for n in range(8, 13)}

    state, consumed = migration.replay(
        days, skipped=vacation, abandoned_today=False, today=day(14), cap=7
    )

    assert state == (8, 8, 1, day(13))
    assert consumed == []


def test_replay_settles_today_only_on_abandon() -> None:
    days = history(range(1, 8), played_unqualified=(8,))
    kwargs = {"skipped": set(), "today": day(8), "cap": 7}

    assert migration.replay(days, abandoned_today=True, **kwargs) == (
        (7, 7, 0, day(7)),
        [day(8)],
    )
    # Still running (or not started) today: the 08:00 tick settles it later.
    assert migration.replay(days, abandoned_today=False, **kwargs) == ((7, 7, 1, day(7)), [])


def test_new_cap_replay_is_never_worse_than_the_old_one() -> None:
    """The migration only adds ledger rows: it relies on this."""
    rng = random.Random(1234)
    for _ in range(500):
        rate = rng.uniform(0.5, 1.0)
        days = {day(n): rng.random() < rate for n in range(1, 122)}
        days[day(1)] = True
        skipped = {day(n) for n in range(1, 122) if not days[day(n)] and rng.random() < 0.1}
        kwargs = {
            "skipped": skipped,
            "abandoned_today": not days[day(121)] and rng.random() < 0.5,
            "today": day(121),
        }

        (old_cur, old_best, old_held, old_last), old_rows = migration.replay(days, cap=2, **kwargs)
        (new_cur, new_best, new_held, new_last), new_rows = migration.replay(days, cap=7, **kwargs)

        assert new_cur >= old_cur
        assert new_best >= old_best
        assert new_held >= old_held
        assert new_last == old_last
        assert set(old_rows) <= set(new_rows)


def test_hand_inserted_takes_the_whole_batch_of_a_row_written_ahead() -> None:
    batch_at = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)  # day 1 already under way
    rows = [
        (day(1), batch_at),
        (day(2), batch_at),
        (day(3), batch_at),
        (day(5), datetime(2026, 1, 6, 8, 0, 13, tzinfo=UTC)),  # 08:00 tick
        (day(7), datetime(2026, 1, 7, 10, 0, tzinfo=UTC)),  # abandon
    ]

    assert migration.hand_inserted(rows) == {day(1), day(2), day(3)}


# Recompute against a database ----------------------------------------------


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


TWO_ZONES = [
    {"node_id": "start", "igt_ms": 0, "type": "fog"},
    {"node_id": "n2", "igt_ms": 1000, "type": "fog"},
]


ONE_ZONE = TWO_ZONES[:1]


async def _seed(engine: AsyncEngine) -> dict[str, UUID]:
    """Four players, the migration running on day 27.

    - vacation: plays 1..21 (3 freezes earned, 2 kept), hand-inserted rows on
      22-23, misses 24-26. The old cap broke the streak on 26.
    - edited: same history, stored state hand-edited (best 95).
    - casual: plays 1..10 only, the cap never mattered.
    - abandoner: plays 1..21, misses 22, is disqualified on 23, plays 24..26,
      abandons today's daily. The old cap broke the streak on that abandon.
    """
    async with AsyncSession(engine, expire_on_commit=False) as db:

        def player(name: str, current: int, best: int, last: int) -> User:
            return User(
                twitch_id=name,
                twitch_username=name,
                daily_current_streak=current,
                daily_best_streak=best,
                daily_freeze_count=0,
                daily_last_qualifying_date=day(last),
            )

        vacation = player("vacation", 0, 21, 21)
        edited = player("edited", 0, 95, 21)
        casual = player("casual", 0, 10, 10)
        abandoner = player("abandoner", 0, 24, 26)
        db.add_all([vacation, edited, casual, abandoner])
        await db.flush()

        finished = (ParticipantStatus.FINISHED, TWO_ZONES)
        runs: dict[int, list[tuple[User, tuple[ParticipantStatus, list[dict]]]]] = {
            n: [(vacation, finished), (edited, finished), (abandoner, finished)]
            + ([(casual, finished)] if n <= 10 else [])
            for n in range(1, 22)
        }
        runs[23] = [(abandoner, (ParticipantStatus.DISQUALIFIED, TWO_ZONES))]
        for n in (24, 25, 26):
            runs[n] = [(abandoner, finished)]
        runs[27] = [(abandoner, (ParticipantStatus.ABANDONED, ONE_ZONE))]
        for n, entries in runs.items():
            race = Race(
                name=f"Daily {n}",
                organizer_id=casual.id,
                daily_date=day(n),
                status=RaceStatus.RUNNING if n == 27 else RaceStatus.FINISHED,
            )
            db.add(race)
            await db.flush()
            db.add_all(
                Participant(race_id=race.id, user_id=p.id, status=status, zone_history=zones)
                for p, (status, zones) in entries
            )

        def tick(n: int) -> datetime:
            return datetime.combine(day(n + 1), datetime.min.time(), UTC) + timedelta(hours=8)

        ahead = datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
        db.add_all(
            [
                DailyStreakFreeze(user_id=vacation.id, daily_date=day(22), consumed_at=ahead),
                DailyStreakFreeze(user_id=vacation.id, daily_date=day(23), consumed_at=ahead),
                DailyStreakFreeze(user_id=vacation.id, daily_date=day(24), consumed_at=tick(24)),
                DailyStreakFreeze(user_id=vacation.id, daily_date=day(25), consumed_at=tick(25)),
                DailyStreakFreeze(user_id=edited.id, daily_date=day(22), consumed_at=tick(22)),
                DailyStreakFreeze(user_id=edited.id, daily_date=day(23), consumed_at=tick(23)),
                DailyStreakFreeze(user_id=casual.id, daily_date=day(11), consumed_at=tick(11)),
                DailyStreakFreeze(user_id=abandoner.id, daily_date=day(22), consumed_at=tick(22)),
                DailyStreakFreeze(user_id=abandoner.id, daily_date=day(23), consumed_at=tick(23)),
            ]
        )
        await db.commit()
        return {
            "vacation": vacation.id,
            "edited": edited.id,
            "casual": casual.id,
            "abandoner": abandoner.id,
        }


async def _state(
    engine: AsyncEngine, user_id: UUID
) -> tuple[tuple[int, int, int, date | None], set[date]]:
    async with engine.connect() as conn:
        user = (
            await conn.execute(
                select(
                    User.daily_current_streak,
                    User.daily_best_streak,
                    User.daily_freeze_count,
                    User.daily_last_qualifying_date,
                ).where(User.id == user_id)
            )
        ).one()
        rows = (
            await conn.execute(
                select(DailyStreakFreeze.daily_date).where(DailyStreakFreeze.user_id == user_id)
            )
        ).all()
    return tuple(user), {d for (d,) in rows}


async def test_recompute_replays_held_back_players_only(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    ids = await _seed(engine)
    edited_before = await _state(engine, ids["edited"])
    casual_before = await _state(engine, ids["casual"])

    with caplog.at_level(logging.WARNING, logger="alembic.migration"):
        async with engine.begin() as conn:
            updated = await conn.run_sync(lambda c: migration.recompute_streaks(c, today=day(27)))

    assert updated == 2
    # The third freeze covers day 26, the hand-inserted days stay skipped.
    assert await _state(engine, ids["vacation"]) == (
        (21, 21, 0, day(21)),
        {day(22), day(23), day(24), day(25), day(26)},
    )
    # The disqualified run is a miss; the third freeze covers today's abandon.
    assert await _state(engine, ids["abandoner"]) == (
        (24, 24, 0, day(26)),
        {day(22), day(23), day(27)},
    )
    assert await _state(engine, ids["edited"]) == edited_before
    assert await _state(engine, ids["casual"]) == casual_before
    assert [r.getMessage() for r in caplog.records if "edited" in r.getMessage()]
