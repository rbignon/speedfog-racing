"""Set Seed: seed lookup, whether a seed's page is public and its files
replayable, and what keeps its files from the purge.

A seed is known once it has been played: not AVAILABLE, not from a training
pool, with a race RUNNING or FINISHED on it or a ranked (speedrun or set_seed)
solo session. Every other seed stays secret: a lookup answers "unknown" for
it, and it never makes a prefix ambiguous. See docs/SPEEDRUN.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from speedfog_racing.config import settings
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedProtection,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
)
from speedfog_racing.schemas import NotReplayableCode, SpeedrunSeedOrigin, as_aware_utc
from speedfog_racing.services.pool_service import format_pool_display_name
from speedfog_racing.services.speedrun_service import (
    CountedRun,
    _is_training,
    _layers_count,
    _pool_config,
    _run_key,
    load_counted_runs,
    seed_category,
)

# The shortest seed ID prefix a lookup accepts.
SEED_PREFIX_MIN = 6
_SEED_QUERY_CHUNK = 500

SeedLookupErrorKind = Literal["unknown", "ambiguous"]
# A protection keeps nothing on a seed that fails one of these: its files are
# gone, or it can never be replayed again (the purge deletes a seed added
# before the game-version cutoff even when protected).
_UNPROTECTABLE: frozenset[NotReplayableCode] = frozenset(
    {"purged", "old_game_version", "old_category"}
)


class SeedLookupError(Exception):
    """No known seed matches the text ("unknown"), or a prefix matches
    several ("ambiguous")."""

    def __init__(self, kind: SeedLookupErrorKind) -> None:
        super().__init__(kind)
        self.kind: SeedLookupErrorKind = kind


@dataclass(frozen=True)
class Replayability:
    # The page shows the seed's map and runs: no blind run is in progress on it.
    public: bool
    # Why the seed cannot be replayed in Set Seed, None when it can.
    code: NotReplayableCode | None
    reason: str | None

    @property
    def replayable(self) -> bool:
        return self.code is None

    @property
    def protectable(self) -> bool:
        """A protection would keep something: the seed is replayable, or could
        become so again (an exclusion lifted, the blind runs over)."""
        return self.code not in _UNPROTECTABLE


def _played_seed() -> ColumnElement[bool]:
    """Condition on ``Seed`` rows that a race or a ranked session started.

    An IN over a UNION, not an OR of two correlated EXISTS: PostgreSQL costs
    that OR far above ``jit_above_cost`` and JIT-compiles the query, which
    then takes ~150 ms instead of a few milliseconds."""
    return Seed.id.in_(
        select(Race.seed_id)
        .where(Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]))
        .union(
            select(TrainingSession.seed_id).where(
                TrainingSession.mode.in_([RunMode.SPEEDRUN, RunMode.SET_SEED])
            )
        )
    )


async def resolve_seed(db: AsyncSession, text: str) -> Seed:
    """The known seed named by ``text`` (trimmed, any case): its full number,
    or a prefix of at least ``SEED_PREFIX_MIN`` characters matching one known
    seed only."""
    number = text.strip().lower()
    if not number:
        raise SeedLookupError("unknown")
    pools = (await db.execute(select(Pool))).scalars().all()
    training_pools = [p.name for p in pools if _is_training(_pool_config(p))]
    known = select(Seed).where(
        Seed.status != SeedStatus.AVAILABLE,
        Seed.pool_name.not_in(training_pools),
        _played_seed(),
    )

    # Two rows are enough to tell one match from several.
    found = (await db.execute(known.where(Seed.seed_number == number).limit(2))).scalars().all()
    if not found and len(number) >= SEED_PREFIX_MIN:
        prefixed = known.where(Seed.seed_number.startswith(number, autoescape=True))
        found = (await db.execute(prefixed.limit(2))).scalars().all()
    if not found:
        raise SeedLookupError("unknown")
    if len(found) > 1:
        raise SeedLookupError("ambiguous")
    return found[0]


async def seed_replayability(db: AsyncSession, seed: Seed) -> Replayability:
    """Whether a known seed's page is public, and whether it can be replayed in
    Set Seed or the first rule it fails: a blind run in progress (the page is
    not public), excluded by an admin, added (scanned) before the game-version
    cutoff, built for another layer count than its pool's, files purged."""
    blind_run_in_progress = await db.scalar(
        select(
            or_(
                exists().where(
                    Race.seed_id == seed.id,
                    Race.mode != RunMode.SET_SEED,
                    Race.status.in_([RaceStatus.SETUP, RaceStatus.RUNNING]),
                ),
                exists().where(
                    TrainingSession.seed_id == seed.id,
                    TrainingSession.mode == RunMode.SPEEDRUN,
                    TrainingSession.status == TrainingSessionStatus.ACTIVE,
                ),
            )
        )
    )
    if blind_run_in_progress:
        return Replayability(
            public=False,
            code="in_progress",
            reason="A blind run on this seed is still in progress.",
        )

    def not_replayable(code: NotReplayableCode, reason: str) -> Replayability:
        return Replayability(public=True, code=code, reason=reason)

    if seed.set_seed_excluded_at is not None:
        return not_replayable(
            "excluded",
            f"Excluded from Set Seed: {seed.set_seed_excluded_reason}"
            if seed.set_seed_excluded_reason
            else "Excluded from Set Seed.",
        )
    cutoff = as_aware_utc(settings.set_seed_min_seed_date)
    created_at = as_aware_utc(seed.created_at)
    if cutoff is not None and created_at is not None and created_at < cutoff:
        return not_replayable("old_game_version", "Built for an older game version.")
    pool = (await db.execute(select(Pool).where(Pool.name == seed.pool_name))).scalar_one_or_none()
    if pool is not None:
        current_layers = _layers_count(_pool_config(pool))
        if current_layers is not None and seed.total_layers != current_layers:
            return not_replayable(
                "old_category",
                f"Built for an older version of {format_pool_display_name(pool)}.",
            )
    if not Path(seed.folder_path).is_file():
        return not_replayable("purged", "Files purged.")
    return Replayability(public=True, code=None, reason=None)


async def has_finished_run(db: AsyncSession, seed_id: UUID, user_id: UUID) -> bool:
    """Whether the user finished a run on the seed: a FINISHED participant of
    a FINISHED race of any mode, or a FINISHED ranked (speedrun or set_seed)
    solo session."""
    race_run = (
        select(Participant.id)
        .join(Race, Participant.race_id == Race.id)
        .where(
            Race.seed_id == seed_id,
            Race.status == RaceStatus.FINISHED,
            Participant.user_id == user_id,
            Participant.status == ParticipantStatus.FINISHED,
        )
    )
    solo_run = select(TrainingSession.id).where(
        TrainingSession.seed_id == seed_id,
        TrainingSession.user_id == user_id,
        TrainingSession.status == TrainingSessionStatus.FINISHED,
        TrainingSession.mode.in_([RunMode.SPEEDRUN, RunMode.SET_SEED]),
    )
    return bool(await db.scalar(select(or_(race_run.exists(), solo_run.exists()))))


def top_seed_numbers(runs: Sequence[CountedRun], category: str, n: int) -> list[str]:
    """The seed numbers of ``category``'s seeds by their best counted run
    (every run type, blind or replay, Deathless or not), fastest first, the
    first ``n``: the Set Seed board's seeds, excluded seeds included (an admin
    may restore one, and a purged zip cannot be rebuilt)."""
    best: dict[str, CountedRun] = {}
    for run in runs:
        if run.category != category:
            continue
        current = best.get(run.seed_number)
        if current is None or _run_key(run) < _run_key(current):
            best[run.seed_number] = run
    return [run.seed_number for run in sorted(best.values(), key=_run_key)][:n]


async def seed_origin(db: AsyncSession, seed: Seed) -> SpeedrunSeedOrigin | None:
    """Where a seed was first played: its earliest blind race (any mode but
    set_seed, RUNNING or FINISHED, by start, else creation), else its earliest
    Speedrun-mode solo session; None when only replays were run on it."""
    race_played_at = func.coalesce(Race.started_at, Race.created_at)
    race = (
        await db.execute(
            select(Race.id, Race.name, Race.daily_date, race_played_at.label("played_at"))
            .where(
                Race.seed_id == seed.id,
                Race.mode != RunMode.SET_SEED,
                Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]),
            )
            .order_by(race_played_at, Race.id)
            .limit(1)
        )
    ).first()
    if race is not None:
        return SpeedrunSeedOrigin(
            race_id=race.id,
            race_name=race.name,
            daily_date=race.daily_date,
            played_at=race.played_at,
        )
    session_at = await db.scalar(
        select(func.min(TrainingSession.created_at)).where(
            TrainingSession.seed_id == seed.id, TrainingSession.mode == RunMode.SPEEDRUN
        )
    )
    if session_at is None:
        return None
    return SpeedrunSeedOrigin(race_id=None, race_name=None, daily_date=None, played_at=session_at)


@dataclass(frozen=True, slots=True)
class RetentionFacts:
    """What decides whether a seed's files are kept (see ``retention_reasons``)."""

    # Not DISCARDED: the seed still belongs to its pool.
    in_current_pool: bool
    pool_display_name: str
    # The seed's category name when it is among the category's top seeds, else None.
    top_of: str | None
    protections: int
    # Latest race (finish, else start, else creation) or solo session (finish,
    # else creation) on the seed; None when there is none.
    last_played_at: datetime | None
    # A race in SETUP or RUNNING, or an ACTIVE solo session, is on the seed:
    # it is being played now.
    in_use: bool


def retention_reasons(facts: RetentionFacts, *, now: datetime) -> list[str]:
    """Why a seed's files are kept, in display order; empty when nothing
    keeps them, which only a DISCARDED seed can be."""
    reasons: list[str] = []
    if facts.in_current_pool:
        reasons.append(f"Seed of the current {facts.pool_display_name} pool")
    if facts.top_of is not None:
        reasons.append(f"Top {settings.set_seed_kept_top_seeds} seed of {facts.top_of}")
    if facts.protections:
        players = "player" if facts.protections == 1 else "players"
        reasons.append(f"Protected by {facts.protections} {players}")
    last_played_at = as_aware_utc(facts.last_played_at)
    grace_days = settings.seed_purge_grace_days
    if facts.in_use or (
        last_played_at is not None and now - last_played_at < timedelta(days=grace_days)
    ):
        reasons.append(f"Played in the last {grace_days} days")
    return reasons


async def load_retention_facts(
    db: AsyncSession, seeds: Sequence[Seed], runs: Sequence[CountedRun]
) -> dict[UUID, RetentionFacts]:
    """The retention facts of ``seeds``, by seed id. ``runs`` are every
    counted run (``load_counted_runs`` without a seed): a seed is a top seed
    when it is among the ``settings.set_seed_kept_top_seeds`` best seeds of
    its category (``top_seed_numbers``)."""
    pools = {
        pool.name: pool
        for pool in (
            await db.execute(select(Pool).where(Pool.name.in_({s.pool_name for s in seeds})))
        ).scalars()
    }
    ids = [seed.id for seed in seeds]
    protections: dict[UUID, int] = {}
    last_played: dict[UUID, datetime] = {}
    in_use: set[UUID] = set()
    for start in range(0, len(ids), _SEED_QUERY_CHUNK):
        chunk = ids[start : start + _SEED_QUERY_CHUNK]
        counts = await db.execute(
            select(SeedProtection.seed_id, func.count())
            .where(SeedProtection.seed_id.in_(chunk))
            .group_by(SeedProtection.seed_id)
        )
        protections.update({seed_id: count for seed_id, count in counts.all()})
        playing = select(Race.seed_id).where(
            Race.seed_id.in_(chunk), Race.status.in_([RaceStatus.SETUP, RaceStatus.RUNNING])
        )
        playing_solo = select(TrainingSession.seed_id).where(
            TrainingSession.seed_id.in_(chunk),
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
        )
        playing_ids = (await db.execute(playing.union(playing_solo))).scalars()
        in_use.update(seed_id for seed_id in playing_ids if seed_id is not None)
        for seed_id_column, played_at in (
            (Race.seed_id, func.coalesce(Race.finished_at, Race.started_at, Race.created_at)),
            (
                TrainingSession.seed_id,
                func.coalesce(TrainingSession.finished_at, TrainingSession.created_at),
            ),
        ):
            latest = await db.execute(
                select(seed_id_column, func.max(played_at))
                .where(seed_id_column.in_(chunk))
                .group_by(seed_id_column)
            )
            for seed_id, at in latest.all():
                at = as_aware_utc(at)
                if at is not None and (seed_id not in last_played or at > last_played[seed_id]):
                    last_played[seed_id] = at

    top_seeds: dict[str, frozenset[str]] = {}
    facts: dict[UUID, RetentionFacts] = {}
    for seed in seeds:
        pool = pools[seed.pool_name]
        category, category_name = seed_category(pool, seed.total_layers)
        if category not in top_seeds:
            top_seeds[category] = frozenset(
                top_seed_numbers(runs, category, settings.set_seed_kept_top_seeds)
            )
        facts[seed.id] = RetentionFacts(
            in_current_pool=seed.status != SeedStatus.DISCARDED,
            pool_display_name=format_pool_display_name(pool),
            top_of=category_name if seed.seed_number in top_seeds[category] else None,
            protections=protections.get(seed.id, 0),
            last_played_at=last_played.get(seed.id),
            in_use=seed.id in in_use,
        )
    return facts


async def purgeable_seeds(
    db: AsyncSession,
    *,
    now: datetime,
    pool: str | None = None,
    older_than_days: int | None = None,
) -> list[Seed]:
    """The DISCARDED seeds with a zip whose files may be purged: added before
    ``settings.set_seed_min_seed_date`` whatever else holds, else with no
    retention reason (top seed, protected, played recently or now). ``pool``
    and ``older_than_days`` (on ``Seed.created_at``) narrow the candidates.
    The seeds come without their ``graph_json``, never decoded here."""
    query = (
        select(Seed)
        .options(defer(Seed.graph_json))
        .where(Seed.status == SeedStatus.DISCARDED, Seed.folder_path.is_not(None))
    )
    if pool is not None:
        query = query.where(Seed.pool_name == pool)
    candidates = (
        (await db.execute(query.order_by(Seed.pool_name, Seed.seed_number))).scalars().all()
    )
    if older_than_days is not None:
        limit = now - timedelta(days=older_than_days)
        candidates = [
            s for s in candidates if (c := as_aware_utc(s.created_at)) is not None and c < limit
        ]
    if not candidates:
        return []
    cutoff = as_aware_utc(settings.set_seed_min_seed_date)
    facts = await load_retention_facts(db, candidates, await load_counted_runs(db))
    purgeable: list[Seed] = []
    for seed in candidates:
        created_at = as_aware_utc(seed.created_at)
        pre_cutoff = cutoff is not None and created_at is not None and created_at < cutoff
        if pre_cutoff or not retention_reasons(facts[seed.id], now=now):
            purgeable.append(seed)
    return purgeable
