"""speedrun.fog: the /speedrun page, with Set Seed and Random Seed boards.

Every counted run is loaded once with light columns (no ``zone_history``);
boards, record histories and recent runs are derived from that list in
memory. Weapons need ``zone_history``, so they are decoded only for the runs
a response returns. See docs/SPEEDRUN.md.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    Seed,
    TrainingSession,
    TrainingSessionMode,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.schemas import (
    SpeedrunBoardResponse,
    SpeedrunCategory,
    SpeedrunOverviewResponse,
    SpeedrunRecentRun,
    SpeedrunRecordSeed,
    SpeedrunRun,
    UserResponse,
)
from speedfog_racing.services.pool_service import format_pool_display_name
from speedfog_racing.services.weapons import BASE_ROW_MODULUS

RunType = Literal["race", "daily", "event", "solo"]
RUN_TYPES: tuple[RunType, ...] = ("race", "daily", "event", "solo")
# Set Seed counts every run; Random Seed only blind ones.
SpeedrunSub = Literal["set", "random"]

RECENT_RUNS_COUNT = 5
_WEAPON_QUERY_CHUNK = 500


@dataclass(frozen=True, slots=True)
class CountedRun:
    # Participant id for a race run, session id for a solo run.
    run_id: UUID
    user: UserResponse
    pool: str
    # The board the run belongs to: the pool name, or "<pool>@<layers>" for a
    # run on an archived layer count of the pool.
    category: str
    deathless: bool
    run_type: RunType
    # False for a replay (Set Seed): the runner knew the seed beforehand.
    blind: bool
    igt_ms: int
    finished_at: datetime
    race_id: UUID | None
    race_name: str | None
    session_id: UUID | None
    daily_date: date | None
    seed_number: str
    deaths: int


def _pool_config(pool: Pool) -> dict[str, Any]:
    return pool.config if isinstance(pool.config, dict) else {}


def _is_training(config: dict[str, Any]) -> bool:
    return config.get("type") == "training"


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _layers_count(config: dict[str, Any]) -> int | None:
    """The pool's current layer count, None when its config does not say."""
    value = config.get("layers_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _archived_layers(config: dict[str, Any]) -> list[int]:
    """The layer counts the pool declares archived (ints only)."""
    value = config.get("archived_layers")
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


def _category_key(pool: str, layers: int) -> str:
    return f"{pool}@{layers}"


async def load_counted_runs(db: AsyncSession) -> list[CountedRun]:
    """Every run the boards count: finished participants of finished races and
    finished ranked solo sessions (speedrun or set_seed mode), banned users
    left out, races excluded from stats left out unless they are Daily Seeds
    or event races, training pools left out, and seeds from an older version
    of their pool (another layer count than its config) left out, unless that
    count is declared in the pool's ``archived_layers``: those runs count under
    the category ``"<pool>@<layers>"``."""
    pools = (await db.execute(select(Pool))).scalars().all()
    training_pools = {p.name for p in pools if _is_training(_pool_config(p))}
    layer_counts = {
        p.name: count for p in pools if (count := _layers_count(_pool_config(p))) is not None
    }

    stmt = (
        select(
            Participant.id.label("participant_id"),
            Participant.igt_ms,
            Participant.death_count,
            Participant.finished_at,
            Race.id.label("race_id"),
            Race.name.label("race_name"),
            Race.started_at,
            Race.created_at,
            Race.daily_date,
            Race.event_id,
            Race.deathless,
            Race.set_seed,
            Seed.pool_name,
            Seed.seed_number,
            Seed.total_layers,
            User.id.label("user_id"),
            User.twitch_username,
            User.twitch_display_name,
            User.twitch_avatar_url,
            User.equipped_badge_id,
            User.equipped_name_template_id,
        )
        .join(Race, Participant.race_id == Race.id)
        .join(Seed, Race.seed_id == Seed.id)
        .join(User, Participant.user_id == User.id)
        .where(
            Participant.status == ParticipantStatus.FINISHED,
            Race.status == RaceStatus.FINISHED,
            User.banned_at.is_(None),
            or_(
                Race.exclude_from_stats.is_(False),
                Race.daily_date.is_not(None),
                Race.event_id.is_not(None),
            ),
        )
    )
    users: dict[UUID, UserResponse] = {}
    runs: list[CountedRun] = []

    archives = {p.name: _archived_layers(_pool_config(p)) for p in pools}

    def category_of(row: Any) -> str | None:
        """The board a row's seed counts for, None when it counts for none."""
        if row.pool_name in training_pools:
            return None
        current_layers = layer_counts.get(row.pool_name)
        if current_layers is None or row.total_layers == current_layers:
            return str(row.pool_name)
        if row.total_layers in archives.get(row.pool_name, []):
            return _category_key(row.pool_name, row.total_layers)
        return None

    def user_of(row: Any) -> UserResponse:
        user = users.get(row.user_id)
        if user is None:
            user = UserResponse(
                id=row.user_id,
                twitch_username=row.twitch_username,
                twitch_display_name=row.twitch_display_name,
                twitch_avatar_url=row.twitch_avatar_url,
                equipped_badge_id=row.equipped_badge_id,
                equipped_name_template_id=row.equipped_name_template_id,
            )
            users[row.user_id] = user
        return user

    for row in (await db.execute(stmt)).all():
        category = category_of(row)
        if category is None:
            continue
        run_type: RunType = (
            "daily"
            if row.daily_date is not None
            else "event"
            if row.event_id is not None
            else "race"
        )
        runs.append(
            CountedRun(
                run_id=row.participant_id,
                user=user_of(row),
                pool=row.pool_name,
                category=category,
                deathless=bool(row.deathless),
                run_type=run_type,
                blind=not row.set_seed,
                igt_ms=row.igt_ms,
                # Old rows can lack a finish time; the race start is close enough.
                finished_at=row.finished_at or row.started_at or row.created_at,
                race_id=row.race_id,
                race_name=row.race_name,
                session_id=None,
                daily_date=row.daily_date,
                seed_number=row.seed_number,
                deaths=row.death_count,
            )
        )

    session_stmt = (
        select(
            TrainingSession.id.label("session_id"),
            TrainingSession.mode,
            TrainingSession.igt_ms,
            TrainingSession.death_count,
            TrainingSession.finished_at,
            TrainingSession.created_at,
            Seed.pool_name,
            Seed.seed_number,
            Seed.total_layers,
            User.id.label("user_id"),
            User.twitch_username,
            User.twitch_display_name,
            User.twitch_avatar_url,
            User.equipped_badge_id,
            User.equipped_name_template_id,
        )
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .join(User, TrainingSession.user_id == User.id)
        .where(
            TrainingSession.status == TrainingSessionStatus.FINISHED,
            TrainingSession.mode.in_([TrainingSessionMode.SPEEDRUN, TrainingSessionMode.SET_SEED]),
            User.banned_at.is_(None),
        )
    )
    for row in (await db.execute(session_stmt)).all():
        category = category_of(row)
        if category is None:
            continue
        runs.append(
            CountedRun(
                run_id=row.session_id,
                user=user_of(row),
                pool=row.pool_name,
                category=category,
                deathless=False,
                run_type="solo",
                blind=row.mode == TrainingSessionMode.SPEEDRUN,
                igt_ms=row.igt_ms,
                finished_at=row.finished_at or row.created_at,
                race_id=None,
                race_name=None,
                session_id=row.session_id,
                daily_date=None,
                seed_number=row.seed_number,
                deaths=row.death_count,
            )
        )
    return runs


async def load_categories(db: AsyncSession, runs: Sequence[CountedRun]) -> list[SpeedrunCategory]:
    """One category per pool with a counted run at its current layer count,
    plus one per archived layer count with counted runs (keyed
    ``"<pool>@<layers>"``, always retired). Enabled pools first, then retired
    ones, each group by ``sort_order`` (missing last)."""
    categories_with_runs = {run.category for run in runs}
    pools_with_runs = {run.pool for run in runs}
    if not pools_with_runs:
        return []
    pools = (await db.execute(select(Pool).where(Pool.name.in_(pools_with_runs)))).scalars().all()
    # Earliest seed per (pool, layer count); a category's release is the
    # earliest one at its layer count (any count for a pool whose config has none).
    first_seeds = await db.execute(
        select(Seed.pool_name, Seed.total_layers, func.min(Seed.created_at))
        .where(Seed.pool_name.in_(pools_with_runs))
        .group_by(Seed.pool_name, Seed.total_layers)
    )
    seed_dates: dict[str, list[tuple[int, datetime]]] = {}
    for pool_name, total_layers, created_at in first_seeds.all():
        seed_dates.setdefault(pool_name, []).append((total_layers, created_at))

    def order(entry: tuple[Pool, int | None]) -> tuple[bool, bool, float, str, int]:
        pool, archived = entry
        retired = archived is not None or not pool.enabled
        sort_order = _pool_config(pool).get("sort_order")
        layers = archived or 0
        if isinstance(sort_order, int | float):
            return (retired, False, float(sort_order), pool.name, layers)
        return (retired, True, 0.0, pool.name, layers)

    # (pool, None) is the pool's current category, (pool, n) its archive at n layers.
    entries: list[tuple[Pool, int | None]] = []
    for pool in pools:
        if pool.name in categories_with_runs:
            entries.append((pool, None))
        entries.extend(
            (pool, layers)
            for layers in _archived_layers(_pool_config(pool))
            if _category_key(pool.name, layers) in categories_with_runs
        )

    categories: list[SpeedrunCategory] = []
    for pool, archived in sorted(entries, key=order):
        config = _pool_config(pool)
        display_name = format_pool_display_name(pool)
        target_layers = archived if archived is not None else _layers_count(config)
        categories.append(
            SpeedrunCategory(
                pool=pool.name if archived is None else _category_key(pool.name, archived),
                name=display_name if archived is None else f"{display_name} ({archived} layers)",
                retired=archived is not None or not pool.enabled,
                description=_opt_str(config.get("description")),
                estimated_duration=_opt_str(config.get("estimated_duration")),
                rules=_opt_str(config.get("rules")),
                released_at=min(
                    (
                        created_at
                        for layers, created_at in seed_dates.get(pool.name, [])
                        if target_layers in (None, layers)
                    ),
                    default=None,
                ),
            )
        )
    return categories


def filter_board(
    runs: Sequence[CountedRun],
    *,
    category: str,
    sub: SpeedrunSub,
    deathless_only: bool,
    types: frozenset[RunType],
) -> list[CountedRun]:
    """Runs of one category's board: Random Seed keeps blind runs, Set Seed
    every run; ``deathless_only`` keeps runs of Deathless-mode races."""
    return [
        r
        for r in runs
        if r.category == category
        and (sub == "set" or r.blind)
        and (r.deathless or not deathless_only)
        and r.run_type in types
    ]


def _run_key(run: CountedRun) -> tuple[int, datetime]:
    return (run.igt_ms, run.finished_at)


def rank_board(
    runs: Sequence[CountedRun], *, include_obsolete: bool
) -> list[tuple[CountedRun, int | None]]:
    """Each player's best run (lowest IGT, earliest on a tie), ranked; equal
    IGT shares a rank and the next one skips (1, 2, 2, 4). With
    ``include_obsolete``, every run is listed and non-best runs get None."""
    best: dict[UUID, CountedRun] = {}
    for run in runs:
        current = best.get(run.user.id)
        if current is None or _run_key(run) < _run_key(current):
            best[run.user.id] = run
    personal_bests = sorted(best.values(), key=_run_key)

    ranks: dict[UUID, int] = {}
    previous_igt: int | None = None
    rank = 0
    for position, run in enumerate(personal_bests, start=1):
        if run.igt_ms != previous_igt:
            rank = position
            previous_igt = run.igt_ms
        ranks[run.run_id] = rank

    if not include_obsolete:
        return [(run, ranks[run.run_id]) for run in personal_bests]
    return [(run, ranks.get(run.run_id)) for run in sorted(runs, key=_run_key)]


def record_history(runs: Sequence[CountedRun]) -> list[CountedRun]:
    """The successive records in date order: each run strictly faster than
    every earlier one."""
    records: list[CountedRun] = []
    for run in sorted(runs, key=lambda r: (r.finished_at, r.igt_ms)):
        if not records or run.igt_ms < records[-1].igt_ms:
            records.append(run)
    return records


def record_seed(
    board: Sequence[CountedRun], ranked: Sequence[tuple[CountedRun, int | None]]
) -> SpeedrunRecordSeed | None:
    """The first ranked row's seed and how many runs of ``board`` (obsolete
    ones included) are on it."""
    if not ranked:
        return None
    seed_number = ranked[0][0].seed_number
    return SpeedrunRecordSeed(
        seed_number=seed_number, runs=sum(1 for r in board if r.seed_number == seed_number)
    )


def place_of(run: CountedRun, board: Sequence[CountedRun]) -> int:
    """1 + the number of other players whose best on ``board`` is strictly
    faster than ``run``."""
    best: dict[UUID, int] = {}
    for other in board:
        if other.user.id == run.user.id:
            continue
        best[other.user.id] = min(best.get(other.user.id, other.igt_ms), other.igt_ms)
    return 1 + sum(1 for igt in best.values() if igt < run.igt_ms)


def main_weapon(zone_history: list[dict[str, Any]] | None) -> list[int] | None:
    """The weapon combo held for the most ticks over the run (base ids), or
    None without weapon data. Same id coercion as the weapons stats endpoint:
    a malformed combo is skipped instead of failing."""
    totals: dict[tuple[int, ...], int] = {}
    for entry in zone_history or []:
        if not isinstance(entry, dict):
            continue
        for combo in entry.get("weapons") or []:
            if not isinstance(combo, dict):
                continue
            ids = combo.get("ids")
            ticks = combo.get("ticks", 0)
            if not isinstance(ids, list) or not isinstance(ticks, int) or ticks <= 0:
                continue
            try:
                key = tuple(int(i) - (int(i) % BASE_ROW_MODULUS) for i in ids)
            except (TypeError, ValueError, OverflowError):
                continue
            totals[key] = totals.get(key, 0) + ticks
    if not totals:
        return None
    # max() keeps the first combo seen on a tie.
    return list(max(totals.items(), key=lambda item: item[1])[0])


async def load_main_weapons(
    db: AsyncSession, participant_ids: Collection[UUID], session_ids: Collection[UUID]
) -> dict[UUID, list[int] | None]:
    """Main weapon per run id, from participants and solo sessions (same
    ``zone_history`` shape)."""
    weapons: dict[UUID, list[int] | None] = {}
    for model, all_ids in (
        (Participant, list(participant_ids)),
        (TrainingSession, list(session_ids)),
    ):
        for start in range(0, len(all_ids), _WEAPON_QUERY_CHUNK):
            chunk = all_ids[start : start + _WEAPON_QUERY_CHUNK]
            rows = await db.execute(select(model.id, model.zone_history).where(model.id.in_(chunk)))
            for run_id, zone_history in rows.all():
                weapons[run_id] = main_weapon(zone_history)
    return weapons


async def _weapons_for(
    db: AsyncSession, runs: Collection[CountedRun]
) -> dict[UUID, list[int] | None]:
    return await load_main_weapons(
        db,
        {r.run_id for r in runs if r.session_id is None},
        {r.run_id for r in runs if r.session_id is not None},
    )


def _run_fields(
    run: CountedRun, rank: int | None, weapons: dict[UUID, list[int] | None]
) -> dict[str, Any]:
    return {
        "user": run.user,
        "rank": rank,
        "igt_ms": run.igt_ms,
        "finished_at": run.finished_at,
        "race_id": run.race_id,
        "race_name": run.race_name,
        "session_id": run.session_id,
        "blind": run.blind,
        "daily_date": run.daily_date,
        "seed_number": run.seed_number,
        "deaths": run.deaths,
        "weapon": weapons.get(run.run_id),
    }


async def build_overview(db: AsyncSession, runs: Sequence[CountedRun]) -> SpeedrunOverviewResponse:
    categories = await load_categories(db, runs)
    names = {c.pool: c.name for c in categories}
    recent = sorted(runs, key=lambda r: r.finished_at, reverse=True)[:RECENT_RUNS_COUNT]
    weapons = await _weapons_for(db, recent)
    all_types = frozenset(RUN_TYPES)
    recent_runs = [
        SpeedrunRecentRun(
            **_run_fields(
                run,
                place_of(
                    run,
                    filter_board(
                        runs,
                        category=run.category,
                        sub="set",
                        deathless_only=False,
                        types=all_types,
                    ),
                ),
                weapons,
            ),
            pool=run.category,
            category=names[run.category],
            deathless=run.deathless,
        )
        for run in recent
    ]
    return SpeedrunOverviewResponse(
        categories=categories,
        runs=len(runs),
        players=len({r.user.id for r in runs}),
        recent_runs=recent_runs,
    )


async def build_board(
    db: AsyncSession,
    runs: Sequence[CountedRun],
    *,
    category: str,
    sub: SpeedrunSub,
    deathless_only: bool,
    types: frozenset[RunType],
    include_obsolete: bool,
) -> SpeedrunBoardResponse:
    board = filter_board(
        runs, category=category, sub=sub, deathless_only=deathless_only, types=types
    )
    ranked = rank_board(board, include_obsolete=include_obsolete)
    history = record_history(board)
    weapons = await _weapons_for(db, [r for r, _ in ranked] + history)
    return SpeedrunBoardResponse(
        runs=[SpeedrunRun(**_run_fields(run, rank, weapons)) for run, rank in ranked],
        history=[SpeedrunRun(**_run_fields(run, None, weapons)) for run in history],
        record_seed=record_seed(board, ranked),
    )
