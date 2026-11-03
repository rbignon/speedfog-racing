"""Discord announcements of new speedrun.fog records (see docs/SPEEDRUN.md).

A finished race or ranked solo session is checked once, off the request path:
its runs are compared with every other counted run of the boards of its pool
(a finish cannot change the boards of another pool, so those are not loaded).
The same load refreshes that pool's runs in the cached boards, so a finish
shows on /speedrun without waiting for the stats cache TTL.
"""

import asyncio
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from speedfog_racing import discord
from speedfog_racing.database import async_session_maker
from speedfog_racing.models import Race, Seed, TrainingSession
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    CountedRun,
    SpeedrunSub,
    filter_board,
    load_categories,
    load_counted_runs,
)

logger = logging.getLogger(__name__)

SUBS: tuple[SpeedrunSub, ...] = ("set", "random")

# Announced (category, sub, run_id), so a repeated finish notification stays
# silent. Process memory: a restart between two checks of one finish may
# announce again. Cleared when it grows past the cap, which only risks a repeat
# for a very old finish.
_announced: set[tuple[str, str, UUID]] = set()
_ANNOUNCED_CAP = 5000

_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class RecordChange:
    category: str
    category_name: str
    sub: SpeedrunSub
    run: CountedRun
    previous: CountedRun | None


def _key(run: CountedRun) -> tuple[int, object]:
    return (run.igt_ms, run.finished_at)


def new_records(
    runs: Sequence[CountedRun],
    new_run_ids: Collection[UUID],
    category_names: dict[str, str] | None = None,
) -> list[RecordChange]:
    """One change per board where the fastest new run is strictly faster than
    every other counted run of it (all run types, Deathless filter off). A
    first run on an empty board is a record; a tie is not."""
    names = category_names or {}
    new_ids = set(new_run_ids)
    changes: list[RecordChange] = []
    for category in sorted({r.category for r in runs if r.run_id in new_ids}):
        for sub in SUBS:
            board = filter_board(
                runs,
                category=category,
                sub=sub,
                deathless_only=False,
                types=frozenset(RUN_TYPES),
            )
            fresh = [r for r in board if r.run_id in new_ids]
            if not fresh:
                continue
            best = min(fresh, key=_key)
            others = [r for r in board if r.run_id not in new_ids]
            previous = min(others, key=_key) if others else None
            if previous is not None and best.igt_ms >= previous.igt_ms:
                continue
            changes.append(
                RecordChange(
                    category=category,
                    category_name=names.get(category, category),
                    sub=sub,
                    run=best,
                    previous=previous,
                )
            )
    return changes


async def check_speedrun_records(
    *, race_id: UUID | None = None, session_id: UUID | None = None
) -> None:
    """Put a finished race's or session's runs on the cached boards and
    announce the records they set."""
    # Local import: the API layer imports the services.
    from speedfog_racing.api.stats import replace_speedrun_pool_runs, speedrun_cache_generation

    async with async_session_maker() as db:
        if race_id is not None:
            pool_stmt = select(Seed.pool_name).join(Race, Race.seed_id == Seed.id)
            pool_stmt = pool_stmt.where(Race.id == race_id)
        elif session_id is not None:
            pool_stmt = select(Seed.pool_name).join(
                TrainingSession, TrainingSession.seed_id == Seed.id
            )
            pool_stmt = pool_stmt.where(TrainingSession.id == session_id)
        else:
            return
        pool = (await db.execute(pool_stmt)).scalar_one_or_none()
        if pool is None:
            return
        generation = speedrun_cache_generation()
        runs = await load_counted_runs(db, pool=pool)
        new_ids = {
            r.run_id
            for r in runs
            if (race_id is not None and r.race_id == race_id)
            or (session_id is not None and r.session_id == session_id)
        }
        if not new_ids:
            return
        replace_speedrun_pool_runs(pool, runs, generation=generation)
        categories = await load_categories(db, runs)
    names = {c.pool: c.name for c in categories}
    if len(_announced) > _ANNOUNCED_CAP:
        _announced.clear()
    for change in new_records(runs, new_ids, names):
        key = (change.category, change.sub, change.run.run_id)
        if key in _announced:
            continue
        _announced.add(key)
        await discord.notify_speedrun_record(change)


async def _check_safely(*, race_id: UUID | None, session_id: UUID | None) -> None:
    try:
        await check_speedrun_records(race_id=race_id, session_id=session_id)
    except Exception:
        logger.exception("Speedrun record check failed")


def schedule_speedrun_record_check(
    *, race_id: UUID | None = None, session_id: UUID | None = None
) -> None:
    """Fire-and-forget check, kept off the request path."""
    task = asyncio.create_task(_check_safely(race_id=race_id, session_id=session_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
