"""Set Seed: seed lookup, and whether a seed's page is public and its files
replayable.

A seed is known once it has been played: not AVAILABLE, not from a training
pool, with a race RUNNING or FINISHED on it or a ranked (speedrun or set_seed)
solo session. Every other seed stays secret: a lookup answers "unknown" for
it, and it never makes a prefix ambiguous. See docs/SPEEDRUN.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.models import (
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
)
from speedfog_racing.schemas import as_aware_utc
from speedfog_racing.services.pool_service import format_pool_display_name
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    CountedRun,
    _is_training,
    _layers_count,
    _pool_config,
    _run_key,
    filter_board,
)

# The shortest seed ID prefix a lookup accepts.
SEED_PREFIX_MIN = 6

SeedLookupErrorKind = Literal["unknown", "ambiguous"]
NotReplayableCode = Literal["in_progress", "excluded", "old_game_version", "old_category", "purged"]


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


def _played_seed() -> ColumnElement[bool]:
    """Condition on ``Seed`` rows that a race or a ranked session started."""
    return or_(
        exists().where(
            Race.seed_id == Seed.id,
            Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]),
        ),
        exists().where(
            TrainingSession.seed_id == Seed.id,
            TrainingSession.mode.in_([RunMode.SPEEDRUN, RunMode.SET_SEED]),
        ),
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
    not public), excluded by an admin, built before the game-version cutoff,
    built for another layer count than its pool's, files purged."""
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


def top_seed_numbers(runs: Sequence[CountedRun], category: str, n: int) -> list[str]:
    """The seed numbers of ``category``'s Set Seed board (every run type,
    Deathless or not, excluded seeds left out), fastest best run first, the
    first ``n``."""
    best: dict[str, CountedRun] = {}
    board = filter_board(
        runs, category=category, sub="set", deathless_only=False, types=frozenset(RUN_TYPES)
    )
    for run in board:
        current = best.get(run.seed_number)
        if current is None or _run_key(run) < _run_key(current):
            best[run.seed_number] = run
    return [run.seed_number for run in sorted(best.values(), key=_run_key)][:n]
