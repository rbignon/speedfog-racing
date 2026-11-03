"""References a LiveSplit file is built from (see docs/SPEEDRUN.md): the Random
Seed record of a category and the viewer's own best run, with the IGT of their
first arrival on each layer."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import Seed
from speedfog_racing.services.set_seed_service import seed_replayability
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    CountedRun,
    _run_key,
    filter_board,
    load_zone_histories,
)
from speedfog_racing.websocket.race.manager import build_leader_splits


def pick_references(
    runs: Sequence[CountedRun], *, category: str, viewer_id: UUID | None
) -> tuple[CountedRun | None, CountedRun | None]:
    """The (WR, PB) of a category's Random Seed board, every run type and
    deathless or not: the fastest run, and the viewer's fastest (None for a
    logged-out viewer or one without a run)."""
    board = filter_board(
        runs,
        category=category,
        sub="random",
        deathless_only=False,
        types=frozenset(RUN_TYPES),
    )
    wr = min(board, key=_run_key, default=None)
    pb = min((r for r in board if r.user.id == viewer_id), key=_run_key, default=None)
    return wr, pb


async def reference_arrivals(db: AsyncSession, run: CountedRun) -> dict[int, int] | None:
    """Layer -> IGT of the run's first arrival on it, plus the finish IGT under
    the seed's last layer. None when the seed's page is not public (a blind
    run on it is in progress, which the run's pacing would spoil) or the seed
    is gone."""
    # Seed numbers are unique per pool only.
    seed = (
        await db.execute(
            select(Seed).where(Seed.seed_number == run.seed_number, Seed.pool_name == run.pool)
        )
    ).scalar_one_or_none()
    if seed is None or not (await seed_replayability(db, seed)).public:
        return None
    histories = await load_zone_histories(
        db,
        {run.run_id} if run.session_id is None else set(),
        {run.run_id} if run.session_id is not None else set(),
    )
    arrivals = build_leader_splits(histories.get(run.run_id), seed.graph_json)
    return {**arrivals, seed.total_layers: run.igt_ms}
