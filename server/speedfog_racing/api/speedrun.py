"""speedrun.fog seed pages and seed protections (see docs/SPEEDRUN.md).

The boards live under /api/stats/speedrun (cached); a seed page is not
cached, so a finished solo run or a protection shows at once.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.api.stats import _cached
from speedfog_racing.api.training import _build_detail_response
from speedfog_racing.auth import get_current_user_optional, require_not_banned
from speedfog_racing.config import settings
from speedfog_racing.database import get_db
from speedfog_racing.models import Seed, SeedProtection, User
from speedfog_racing.rate_limit import limiter
from speedfog_racing.schemas import (
    PoolConfig,
    SpeedrunRecordHolder,
    SpeedrunSeedResponse,
    SpeedrunSeedSummary,
    SpeedrunSeedViewer,
    StartSpeedrunSoloRequest,
    TrainingSessionDetailResponse,
)
from speedfog_racing.services import get_pool
from speedfog_racing.services.seed_service import has_fresh_speedrun_seed
from speedfog_racing.services.set_seed_service import (
    SeedLookupError,
    has_finished_run,
    load_retention_facts,
    resolve_seed,
    retention_reasons,
    seed_origin,
    seed_replayability,
)
from speedfog_racing.services.speedrun_service import (
    build_seed_runs,
    load_counted_runs,
    seed_category,
    seed_stats,
)
from speedfog_racing.services.training_service import (
    SpeedrunStartError,
    create_set_seed_session,
    create_speedrun_session,
)

router = APIRouter()


async def resolve_seed_or_404(db: AsyncSession, text: str) -> Seed:
    """The known seed named by ``text`` (full number or 6+ character prefix):
    404 "Unknown seed" (unplayed seeds included), 409 when a prefix matches
    several."""
    try:
        return await resolve_seed(db, text)
    except SeedLookupError as error:
        if error.kind == "ambiguous":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Ambiguous seed ID"
            ) from error
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown seed") from error


async def _viewer(
    db: AsyncSession, seed_id: UUID, user_id: UUID, *, banned: bool = False
) -> SpeedrunSeedViewer:
    """``user_id``'s protection state on a seed (a banned user can protect none)."""
    protected = (
        await db.execute(
            select(SeedProtection.seed_id, Seed.seed_number)
            .join(Seed, Seed.id == SeedProtection.seed_id)
            .where(SeedProtection.user_id == user_id)
            .order_by(SeedProtection.created_at, SeedProtection.id)
        )
    ).all()
    return SpeedrunSeedViewer(
        can_protect=not banned and await has_finished_run(db, seed_id, user_id),
        protected=any(protected_id == seed_id for protected_id, _ in protected),
        protected_seeds=[number for _, number in protected],
        protection_limit=settings.seed_protection_limit,
    )


@router.get("/seeds/{seed}", response_model=SpeedrunSeedResponse)
async def get_seed_page(
    seed: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> SpeedrunSeedResponse:
    """A played seed's page: its runs and map once no blind run on it is in
    progress, whether it is replayable, and what keeps its files."""
    found = await resolve_seed_or_404(db, seed)
    replayability = await seed_replayability(db, found)
    every_run = await _cached("speedrun:runs", load_counted_runs, db)
    retention = (await load_retention_facts(db, [found], every_run))[found.id]
    seed_runs = await load_counted_runs(db, seed_id=found.id)
    shown_runs = seed_runs if replayability.public else []
    category, category_name = seed_category(found.pool, found.total_layers)
    raw_config = found.pool.config or None
    return SpeedrunSeedResponse(
        seed_number=found.seed_number,
        category=category,
        category_name=category_name,
        pool_config=PoolConfig(**raw_config) if raw_config else None,
        total_layers=found.total_layers,
        origin=await seed_origin(db, found),
        public=replayability.public,
        replayable=replayability.replayable,
        not_replayable_code=replayability.code,
        not_replayable_reason=replayability.reason,
        protectable=replayability.protectable,
        kept_reasons=retention_reasons(retention, now=datetime.now(UTC)),
        protected_by=retention.protections,
        excluded_reason=(
            found.set_seed_excluded_reason if found.set_seed_excluded_at is not None else None
        ),
        viewer=(
            await _viewer(db, found.id, user.id, banned=user.banned_at is not None)
            if user is not None
            else None
        ),
        graph_json=found.graph_json if replayability.public else None,
        runs=await build_seed_runs(db, shown_runs),
        stats=seed_stats(shown_runs),
    )


@router.get("/seeds/{seed}/summary", response_model=SpeedrunSeedSummary)
async def get_seed_summary(seed: str, db: AsyncSession = Depends(get_db)) -> SpeedrunSeedSummary:
    """What the Set Seed field shows while a player types: the seed's category,
    whether it can be replayed and its record. No map. An unplayed seed answers
    like a typo; a seed with a blind run in progress shows no record."""
    found = await resolve_seed_or_404(db, seed)
    replayability = await seed_replayability(db, found)
    category, category_name = seed_category(found.pool, found.total_layers)
    record = None
    if replayability.public:
        runs = await load_counted_runs(db, seed_id=found.id)
        if runs:
            best = min(runs, key=lambda r: (r.igt_ms, r.finished_at))
            record = SpeedrunRecordHolder(igt_ms=best.igt_ms, user=best.user)
    return SpeedrunSeedSummary(
        seed_number=found.seed_number,
        category=category,
        category_name=category_name,
        replayable=replayability.replayable,
        not_replayable_reason=replayability.reason,
        record=record,
    )


@router.get("/fresh-seeds")
async def get_fresh_seeds(
    pool: str = Query(...), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    """Whether a Speedrun-mode run could start on ``pool`` now (404 for the
    pools ``/solo`` refuses: missing, disabled or training)."""
    found = await get_pool(db, pool)
    if found is None or not found.enabled or (found.config or {}).get("type", "race") == "training":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown pool")
    return {"fresh": await has_fresh_speedrun_seed(db, pool)}


_START_ERROR_STATUS = {
    "unknown_pool": status.HTTP_404_NOT_FOUND,
    "unknown_seed": status.HTTP_404_NOT_FOUND,
    "unfinished_limit": status.HTTP_429_TOO_MANY_REQUESTS,
}


@router.post(
    "/solo", response_model=TrainingSessionDetailResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/minute")
async def start_solo_run(
    request: Request,
    body: StartSpeedrunSoloRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> TrainingSessionDetailResponse:
    """Start a ranked solo run: Speedrun mode on a fresh seed of ``pool``, or
    Set Seed on a replayable ``seed``."""
    try:
        if body.pool is not None:
            session = await create_speedrun_session(db, user.id, body.pool)
        else:
            assert body.seed is not None  # the schema guarantees exactly one
            session = await create_set_seed_session(db, user.id, body.seed)
    except SpeedrunStartError as error:
        raise HTTPException(
            status_code=_START_ERROR_STATUS.get(error.code, status.HTTP_409_CONFLICT),
            detail=error.message,
        ) from error
    await db.commit()
    return _build_detail_response(session)


@router.put("/seeds/{seed}/protection", response_model=SpeedrunSeedViewer)
async def protect_seed(
    seed: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> SpeedrunSeedViewer:
    """Keep a seed's files from the purge. Idempotent: protecting a seed again
    takes no second slot. Refused (409, the reason) on a seed whose files a
    protection would not keep: purged, or never replayable again."""
    found = await resolve_seed_or_404(db, seed)
    # Ids read up front: a rollback below expires the ORM objects.
    seed_id, user_id = found.id, user.id
    already = await db.scalar(
        select(SeedProtection.id).where(
            SeedProtection.user_id == user_id, SeedProtection.seed_id == seed_id
        )
    )
    if already is None:
        replayability = await seed_replayability(db, found)
        if not replayability.protectable:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=replayability.reason)
        if not await has_finished_run(db, seed_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only players with a finished run on this seed can protect it",
            )
        # SAFETY: two concurrent requests on different seeds can both pass
        # this count and go one over the limit. Acceptable: a player gains at
        # most a seed or two by racing their own clicks.
        protected_count = await db.scalar(
            select(func.count()).where(SeedProtection.user_id == user_id)
        )
        limit = settings.seed_protection_limit
        if (protected_count or 0) >= limit:
            seeds = "seed" if limit == 1 else "seeds"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You already protect {limit} {seeds}",
            )
        db.add(SeedProtection(user_id=user_id, seed_id=seed_id))
        try:
            await db.commit()
        except IntegrityError:
            # Already protected: two clicks racing each other.
            await db.rollback()
    return await _viewer(db, seed_id, user_id)


@router.delete("/seeds/{seed}/protection", response_model=SpeedrunSeedViewer)
async def unprotect_seed(
    seed: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_not_banned),
) -> SpeedrunSeedViewer:
    """Stop protecting a seed, which frees the slot. Idempotent."""
    found = await resolve_seed_or_404(db, seed)
    seed_id, user_id = found.id, user.id
    await db.execute(
        delete(SeedProtection).where(
            SeedProtection.user_id == user_id, SeedProtection.seed_id == seed_id
        )
    )
    await db.commit()
    return await _viewer(db, seed_id, user_id)
