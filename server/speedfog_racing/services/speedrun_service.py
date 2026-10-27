"""speedrun.fog: the speedrun.com parody tab of /stats.

Every counted run is loaded once with light columns (no ``zone_history``);
boards, record histories and recent runs are derived from that list in
memory. Weapons need ``zone_history``, so they are decoded only for the runs
a response returns. See the "speedrun.fog" section of docs/STATS.md.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    Seed,
    User,
)
from speedfog_racing.schemas import (
    SpeedrunBoardResponse,
    SpeedrunCategory,
    SpeedrunOverviewResponse,
    SpeedrunRecentRun,
    SpeedrunRun,
    UserResponse,
)
from speedfog_racing.services.pool_service import format_pool_display_name
from speedfog_racing.services.weapons import BASE_ROW_MODULUS

RunType = Literal["race", "daily", "event"]
RUN_TYPES: tuple[RunType, ...] = ("race", "daily", "event")

RECENT_RUNS_COUNT = 5
_WEAPON_QUERY_CHUNK = 500


@dataclass(frozen=True, slots=True)
class CountedRun:
    participant_id: UUID
    user: UserResponse
    pool: str
    deathless: bool
    run_type: RunType
    igt_ms: int
    finished_at: datetime
    race_id: UUID
    race_name: str
    daily_date: date | None
    seed_number: str
    layers: int
    deaths: int


def _pool_config(pool: Pool) -> dict[str, Any]:
    return pool.config if isinstance(pool.config, dict) else {}


def _is_training(config: dict[str, Any]) -> bool:
    return config.get("type") == "training"


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


async def load_counted_runs(db: AsyncSession) -> list[CountedRun]:
    """Every run the boards count: finished participants of finished races,
    banned users left out, races excluded from stats left out unless they are
    Daily Seeds or event races, training pools left out."""
    pools = (await db.execute(select(Pool))).scalars().all()
    training_pools = {p.name for p in pools if _is_training(_pool_config(p))}

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
    for row in (await db.execute(stmt)).all():
        if row.pool_name in training_pools:
            continue
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
        run_type: RunType = (
            "daily"
            if row.daily_date is not None
            else "event"
            if row.event_id is not None
            else "race"
        )
        runs.append(
            CountedRun(
                participant_id=row.participant_id,
                user=user,
                pool=row.pool_name,
                deathless=bool(row.deathless),
                run_type=run_type,
                igt_ms=row.igt_ms,
                # Old rows can lack a finish time; the race start is close enough.
                finished_at=row.finished_at or row.started_at or row.created_at,
                race_id=row.race_id,
                race_name=row.race_name,
                daily_date=row.daily_date,
                seed_number=row.seed_number,
                layers=row.total_layers,
                deaths=row.death_count,
            )
        )
    return runs


async def load_categories(db: AsyncSession, runs: Sequence[CountedRun]) -> list[SpeedrunCategory]:
    """One category per pool with at least one counted run: enabled pools
    first, then retired ones, each group by ``sort_order`` (missing last)."""
    flags: dict[str, set[bool]] = {}
    for run in runs:
        flags.setdefault(run.pool, set()).add(run.deathless)
    if not flags:
        return []
    pools = (await db.execute(select(Pool).where(Pool.name.in_(flags)))).scalars().all()

    def order(pool: Pool) -> tuple[bool, bool, float, str]:
        sort_order = _pool_config(pool).get("sort_order")
        if isinstance(sort_order, int | float):
            return (not pool.enabled, False, float(sort_order), pool.name)
        return (not pool.enabled, True, 0.0, pool.name)

    categories: list[SpeedrunCategory] = []
    for pool in sorted(pools, key=order):
        config = _pool_config(pool)
        subcategories: list[Literal["any", "deathless"]] = []
        if False in flags[pool.name]:
            subcategories.append("any")
        if True in flags[pool.name]:
            subcategories.append("deathless")
        categories.append(
            SpeedrunCategory(
                pool=pool.name,
                name=format_pool_display_name(pool),
                retired=not pool.enabled,
                subcategories=subcategories,
                description=_opt_str(config.get("description")),
                estimated_duration=_opt_str(config.get("estimated_duration")),
                rules=_opt_str(config.get("rules")),
            )
        )
    return categories


def filter_board(
    runs: Sequence[CountedRun], *, pool: str, deathless: bool, types: frozenset[RunType]
) -> list[CountedRun]:
    return [r for r in runs if r.pool == pool and r.deathless == deathless and r.run_type in types]


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
        ranks[run.participant_id] = rank

    if not include_obsolete:
        return [(run, ranks[run.participant_id]) for run in personal_bests]
    return [(run, ranks.get(run.participant_id)) for run in sorted(runs, key=_run_key)]


def record_history(runs: Sequence[CountedRun]) -> list[CountedRun]:
    """The successive records in date order: each run strictly faster than
    every earlier one."""
    records: list[CountedRun] = []
    for run in sorted(runs, key=lambda r: (r.finished_at, r.igt_ms)):
        if not records or run.igt_ms < records[-1].igt_ms:
            records.append(run)
    return records


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
    db: AsyncSession, participant_ids: Collection[UUID]
) -> dict[UUID, list[int] | None]:
    ids = list(participant_ids)
    weapons: dict[UUID, list[int] | None] = {}
    for start in range(0, len(ids), _WEAPON_QUERY_CHUNK):
        chunk = ids[start : start + _WEAPON_QUERY_CHUNK]
        rows = await db.execute(
            select(Participant.id, Participant.zone_history).where(Participant.id.in_(chunk))
        )
        for participant_id, zone_history in rows.all():
            weapons[participant_id] = main_weapon(zone_history)
    return weapons


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
        "daily_date": run.daily_date,
        "seed_number": run.seed_number,
        "layers": run.layers,
        "deaths": run.deaths,
        "weapon": weapons.get(run.participant_id),
    }


async def build_overview(db: AsyncSession, runs: Sequence[CountedRun]) -> SpeedrunOverviewResponse:
    categories = await load_categories(db, runs)
    names = {c.pool: c.name for c in categories}
    recent = sorted(runs, key=lambda r: r.finished_at, reverse=True)[:RECENT_RUNS_COUNT]
    weapons = await load_main_weapons(db, {r.participant_id for r in recent})
    all_types = frozenset(RUN_TYPES)
    recent_runs = [
        SpeedrunRecentRun(
            **_run_fields(
                run,
                place_of(
                    run,
                    filter_board(runs, pool=run.pool, deathless=run.deathless, types=all_types),
                ),
                weapons,
            ),
            pool=run.pool,
            category=names[run.pool],
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
    pool: str,
    deathless: bool,
    types: frozenset[RunType],
    include_obsolete: bool,
) -> SpeedrunBoardResponse:
    board = filter_board(runs, pool=pool, deathless=deathless, types=types)
    ranked = rank_board(board, include_obsolete=include_obsolete)
    history = record_history(board)
    weapons = await load_main_weapons(
        db, {r.participant_id for r, _ in ranked} | {r.participant_id for r in history}
    )
    return SpeedrunBoardResponse(
        runs=[SpeedrunRun(**_run_fields(run, rank, weapons)) for run, rank in ranked],
        history=[SpeedrunRun(**_run_fields(run, None, weapons)) for run in history],
    )
