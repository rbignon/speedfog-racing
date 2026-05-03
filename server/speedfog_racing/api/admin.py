"""Admin API routes for seed and system management."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import (
    compute_race_stats,
    format_pool_display_name,
    race_date,
    user_response,
)
from speedfog_racing.auth import require_admin
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Caster,
    DailySeedSchedule,
    Feedback,
    FeedbackSource,
    Participant,
    Pool,
    Race,
    Seed,
    SeedStatus,
    TrainingSession,
    User,
    UserRole,
)
from speedfog_racing.rewards.service import (
    LifecycleMismatchError,
    RewardsService,
    UnknownRewardError,
)
from speedfog_racing.schemas import (
    ActivityItem,
    ActivityTimelineResponse,
    AdminFeedbackItem,
    AdminFeedbackListResponse,
    RaceCasterActivity,
    RaceOrganizerActivity,
    RaceParticipantActivity,
    TrainingActivity,
)
from speedfog_racing.services import (
    discard_pool,
    get_pool,
    get_pool_stats,
    list_pools,
    scan_pool,
    set_pool_enabled,
)
from speedfog_racing.services.analytics_service import compute_analytics
from speedfog_racing.services.stats_service import recalculate_all_stats
from speedfog_racing.websocket.race.manager import manager as race_manager
from speedfog_racing.websocket.training.manager import training_manager

router = APIRouter()


class ScanRequest(BaseModel):
    """Request body for seed pool scan."""

    pool_name: str = "standard"


class ScanResponse(BaseModel):
    """Response for seed pool scan."""

    added: int
    pool_name: str


class DiscardRequest(BaseModel):
    """Request body for discarding pool seeds."""

    pool_name: str


class DiscardResponse(BaseModel):
    """Response for pool discard."""

    discarded: int
    pool_name: str


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    discarded: int = 0
    reported: int = 0


class StatsResponse(BaseModel):
    """Response for seed pool statistics."""

    pools: dict[str, PoolStats]


@router.post("/seeds/scan", response_model=ScanResponse)
async def scan_seeds(
    request: ScanRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ScanResponse:
    """Scan a seed pool directory and sync with database.

    Requires admin role.
    """
    pool_name = request.pool_name if request else "standard"
    added = await scan_pool(db, pool_name)
    return ScanResponse(added=added, pool_name=pool_name)


@router.get("/seeds/stats", response_model=StatsResponse)
async def get_seeds_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> StatsResponse:
    """Get availability statistics for all seed pools.

    Requires admin role.
    """
    stats = await get_pool_stats(db)
    pools = {name: PoolStats(**counts) for name, counts in stats.items()}
    return StatsResponse(pools=pools)


@router.post("/seeds/discard", response_model=DiscardResponse)
async def discard_seeds(
    request: DiscardRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> DiscardResponse:
    """Mark all AVAILABLE seeds in a pool as DISCARDED.

    Requires admin role.
    """
    count = await discard_pool(db, request.pool_name)
    return DiscardResponse(discarded=count, pool_name=request.pool_name)


# =============================================================================
# Pool Management
# =============================================================================


class AdminPoolResponse(BaseModel):
    """Admin view of a pool row."""

    name: str
    enabled: bool
    last_scanned_at: datetime | None
    available: int = 0
    consumed: int = 0
    discarded: int = 0
    reported: int = 0


class UpdatePoolRequest(BaseModel):
    """Request body for PATCH ``/admin/pools/{name}``."""

    enabled: bool


@router.get("/pools", response_model=list[AdminPoolResponse])
async def admin_list_pools(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[AdminPoolResponse]:
    """List every pool (enabled and disabled) with seed counts."""
    pools = await list_pools(db, include_disabled=True)
    stats = await get_pool_stats(db)
    return [
        AdminPoolResponse(
            name=p.name,
            enabled=p.enabled,
            last_scanned_at=p.last_scanned_at,
            **stats.get(p.name, {}),
        )
        for p in pools
    ]


@router.patch("/pools/{name}", response_model=AdminPoolResponse)
async def admin_update_pool(
    name: str,
    request: UpdatePoolRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminPoolResponse:
    """Toggle the ``enabled`` flag on a pool."""
    try:
        pool = await set_pool_enabled(db, name, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    stats = (await get_pool_stats(db)).get(pool.name, {})
    return AdminPoolResponse(
        name=pool.name,
        enabled=pool.enabled,
        last_scanned_at=pool.last_scanned_at,
        **stats,
    )


# =============================================================================
# Daily Seed Schedule
# =============================================================================


class AdminDailyScheduleEntry(BaseModel):
    """One row of the weekday -> pool rotation used to create Daily Seeds."""

    weekday: int
    pool_name: str
    pool_display_name: str


class AdminDailySchedulePoolOption(BaseModel):
    """A pool eligible to be selected for a Daily Seed weekday slot."""

    name: str
    display_name: str


class AdminDailyScheduleResponse(BaseModel):
    """Combined payload for the Daily Seed schedule admin UI: the seven rows
    plus the list of pools an admin is allowed to assign to any weekday.

    ``available_pools`` covers pools that are enabled and not training pools,
    independently of whether they currently have any AVAILABLE seeds. The
    daily creation loop will fail later if the chosen pool runs out of
    seeds, but seedless pools should still be selectable here so admins can
    schedule a pool ahead of scanning its seeds.
    """

    schedule: list[AdminDailyScheduleEntry]
    available_pools: list[AdminDailySchedulePoolOption]


class UpdateDailyScheduleRequest(BaseModel):
    """Request body for PATCH ``/admin/daily-schedule/{weekday}``."""

    pool_name: str


def _is_training_pool(pool: Pool) -> bool:
    return pool.config.get("type") == "training"


@router.get("/daily-schedule", response_model=AdminDailyScheduleResponse)
async def admin_list_daily_schedule(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminDailyScheduleResponse:
    """Return the seven schedule rows (Mon=0 .. Sun=6) plus the list of pools
    an admin can assign to any weekday."""
    rows = (
        (await db.execute(select(DailySeedSchedule).order_by(DailySeedSchedule.weekday)))
        .scalars()
        .all()
    )
    schedule = [
        AdminDailyScheduleEntry(
            weekday=row.weekday,
            pool_name=row.pool_name,
            pool_display_name=format_pool_display_name(row.pool),
        )
        for row in rows
    ]

    pools = await list_pools(db, include_disabled=False)
    available_pools = sorted(
        (
            AdminDailySchedulePoolOption(
                name=pool.name,
                display_name=format_pool_display_name(pool),
            )
            for pool in pools
            if not _is_training_pool(pool)
        ),
        key=lambda opt: opt.display_name.lower(),
    )

    return AdminDailyScheduleResponse(schedule=schedule, available_pools=available_pools)


@router.patch("/daily-schedule/{weekday}", response_model=AdminDailyScheduleEntry)
async def admin_update_daily_schedule(
    request: UpdateDailyScheduleRequest,
    weekday: int = Path(..., ge=0, le=6),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminDailyScheduleEntry:
    """Set the pool used for the given weekday. The change applies to the next
    Daily Seed created for that weekday (i.e. next week if the weekday is
    today, since today's race has already been emitted)."""
    pool = await get_pool(db, request.pool_name)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pool {request.pool_name!r} does not exist",
        )
    if not pool.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pool {request.pool_name!r} is disabled",
        )
    if _is_training_pool(pool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pool {request.pool_name!r} is a training pool",
        )

    row = await db.get(DailySeedSchedule, weekday)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule row for weekday={weekday} is missing",
        )
    row.pool_name = pool.name
    await db.commit()
    return AdminDailyScheduleEntry(
        weekday=row.weekday,
        pool_name=pool.name,
        pool_display_name=format_pool_display_name(pool),
    )


# =============================================================================
# Stats Management
# =============================================================================


@router.post("/stats/recalculate")
async def recalculate_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Clear all ELO/trait data and replay from scratch. Requires admin role."""
    await recalculate_all_stats(db)
    return {"status": "ok"}


@router.get("/analytics")
async def get_analytics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """Get analytics dashboard data. Requires admin role."""
    return await compute_analytics(db)


# =============================================================================
# User Management
# =============================================================================


class AdminUserResponse(BaseModel):
    """User info for admin management."""

    id: uuid.UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str
    created_at: datetime
    last_seen: datetime | None
    training_count: int = 0
    race_count: int = 0

    model_config = {"from_attributes": True}


class UpdateUserRoleRequest(BaseModel):
    """Request body for updating a user's role."""

    role: str


_ALLOWED_ROLE_VALUES = {UserRole.USER.value, UserRole.ORGANIZER.value}


_training_count_sq = (
    select(func.count(TrainingSession.id))
    .where(TrainingSession.user_id == User.id)
    .correlate(User)
    .scalar_subquery()
)
_race_count_sq = (
    select(func.count(Participant.id))
    .where(Participant.user_id == User.id)
    .correlate(User)
    .scalar_subquery()
)


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[AdminUserResponse]:
    """List all users ordered by last_seen desc, then created_at desc.

    Requires admin role.
    """
    result = await db.execute(
        select(
            User,
            _training_count_sq.label("training_count"),
            _race_count_sq.label("race_count"),
        ).order_by(
            User.last_seen.desc().nulls_last(),
            User.created_at.desc(),
        )
    )
    return [
        AdminUserResponse(
            **{
                c.key: getattr(row.User, c.key)
                for c in User.__table__.columns
                if c.key in AdminUserResponse.model_fields
            },
            training_count=row.training_count,
            race_count=row.race_count,
        )
        for row in result.all()
    ]


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user_role(
    user_id: uuid.UUID,
    request: UpdateUserRoleRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminUserResponse:
    """Update a user's role. Cannot set admin via this endpoint.

    Requires admin role.
    """
    if request.role not in _ALLOWED_ROLE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {', '.join(sorted(_ALLOWED_ROLE_VALUES))}",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change an admin's role",
        )

    user.role = UserRole(request.role)
    await db.commit()
    await db.refresh(user)

    counts = await db.execute(
        select(
            _training_count_sq.label("training_count"),
            _race_count_sq.label("race_count"),
        ).where(User.id == user_id)
    )
    row = counts.one()
    return AdminUserResponse(
        **{
            c.key: getattr(user, c.key)
            for c in User.__table__.columns
            if c.key in AdminUserResponse.model_fields
        },
        training_count=row.training_count,
        race_count=row.race_count,
    )


# =============================================================================
# Global Activity Feed
# =============================================================================


@router.get(
    "/activity",
    response_model=ActivityTimelineResponse,
    response_model_exclude_none=True,
)
async def get_global_activity(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ActivityTimelineResponse:
    """Get a global activity feed across all users.

    Requires admin role.
    """
    # TODO: optimize with SQL-level pagination when dataset grows
    items: list[ActivityItem] = []

    # 1. Race participations (all users, no Race.participants loaded)
    part_q = await db.execute(
        select(Participant).options(
            selectinload(Participant.user),
            selectinload(Participant.race),
        )
    )
    all_participants = part_q.scalars().all()

    # 2. Organized races (all users)
    org_q = await db.execute(select(Race).options(selectinload(Race.organizer)))
    all_races = org_q.scalars().all()

    # Batch-compute counts and placements for all races
    all_race_ids = list({p.race_id for p in all_participants} | {r.id for r in all_races})
    total_by_race, placements = await compute_race_stats(db, all_race_ids)

    # Pairs of (race_id, user_id) where the user participated in the race. Used
    # to merge the organizer entry into the participant entry when they are the
    # same person, instead of producing two cards.
    participant_pairs = {(p.race_id, p.user_id) for p in all_participants}

    for p in all_participants:
        race = p.race
        items.append(
            RaceParticipantActivity(
                date=race_date(race),
                user=user_response(p.user),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                placement=placements.get((race.id, p.id)),
                total_participants=total_by_race.get(race.id, 0),
                igt_ms=p.igt_ms,
                death_count=p.death_count,
                is_mod_connected=race_manager.is_mod_connected(race.id, p.id),
                is_organizer=p.user_id == race.organizer_id,
            )
        )

    for race in all_races:
        if (race.id, race.organizer_id) in participant_pairs:
            continue
        items.append(
            RaceOrganizerActivity(
                date=race_date(race),
                user=user_response(race.organizer),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                participant_count=total_by_race.get(race.id, 0),
            )
        )

    # 3. Caster roles (all users)
    caster_q = await db.execute(
        select(Caster).options(
            selectinload(Caster.user),
            selectinload(Caster.race),
        )
    )
    for c in caster_q.scalars().all():
        items.append(
            RaceCasterActivity(
                date=race_date(c.race),
                user=user_response(c.user),
                race_id=c.race.id,
                race_name=c.race.name,
                status=c.race.status.value,
            )
        )

    # 4. Training sessions (all users)
    training_q = await db.execute(
        select(TrainingSession).options(
            selectinload(TrainingSession.user),
            selectinload(TrainingSession.seed),
        )
    )
    for t in training_q.scalars().all():
        items.append(
            TrainingActivity(
                date=t.created_at,
                user=user_response(t.user),
                session_id=t.id,
                pool_name=t.seed.pool_name,
                pool_display_name=format_pool_display_name(t.seed.pool),
                status=t.status.value,
                igt_ms=t.igt_ms,
                death_count=t.death_count,
                exclude_from_stats=t.exclude_from_stats,
                is_mod_connected=training_manager.is_mod_connected(t.id),
            )
        )

    # Sort by date descending
    items.sort(key=lambda item: item.date, reverse=True)

    total = len(items)
    paginated = items[offset : offset + limit]
    has_more = (offset + limit) < total

    return ActivityTimelineResponse(items=paginated, total=total, has_more=has_more)


# =============================================================================
# Reported Seed Management
# =============================================================================


class ReportedSeedResponse(BaseModel):
    """A reported seed for admin review."""

    id: uuid.UUID
    seed_number: str
    pool_name: str
    difficulty_score: float
    reported_by: str
    reported_reason: str | None
    reported_at: datetime | None


class ResolveSeedRequest(BaseModel):
    """Request to resolve a reported seed."""

    action: Literal["discard", "restore"]


@router.get("/reported-seeds", response_model=list[ReportedSeedResponse])
async def list_reported_seeds(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[ReportedSeedResponse]:
    """List all seeds with REPORTED status. Requires admin role."""
    result = await db.execute(
        select(Seed)
        .where(Seed.status == SeedStatus.REPORTED)
        .options(selectinload(Seed.reported_by))
        .order_by(Seed.reported_at.desc())
    )
    seeds = result.scalars().all()
    return [
        ReportedSeedResponse(
            id=s.id,
            seed_number=s.seed_number,
            pool_name=s.pool_name,
            difficulty_score=s.difficulty_score,
            reported_by=s.reported_by.twitch_username if s.reported_by else "unknown",
            reported_reason=s.reported_reason,
            reported_at=s.reported_at,
        )
        for s in seeds
    ]


@router.post("/seeds/{seed_id}/resolve")
async def resolve_reported_seed(
    seed_id: uuid.UUID,
    request: ResolveSeedRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Discard or restore a reported seed. Requires admin role."""
    result = await db.execute(select(Seed).where(Seed.id == seed_id))
    seed = result.scalar_one_or_none()
    if not seed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    if seed.status != SeedStatus.REPORTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seed is not in REPORTED status",
        )

    if request.action == "discard":
        seed.status = SeedStatus.DISCARDED
    else:
        seed.status = SeedStatus.AVAILABLE
        seed.reported_by_id = None
        seed.reported_reason = None
        seed.reported_at = None

    await db.commit()
    return {"status": "ok"}


# =============================================================================
# Feedback Management
# =============================================================================


@router.get("/feedback", response_model=AdminFeedbackListResponse)
async def admin_list_feedback(
    source: FeedbackSource | None = None,
    rating_min: int | None = Query(default=None, ge=1, le=5),
    rating_max: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AdminFeedbackListResponse:
    """List feedback rows (paginated) with aggregate stats, for admin panel."""
    stmt = select(Feedback).options(
        selectinload(Feedback.user),
        selectinload(Feedback.race),
    )
    if source is not None:
        stmt = stmt.where(Feedback.source == source)
    if rating_min is not None:
        stmt = stmt.where(Feedback.rating >= rating_min)
    if rating_max is not None:
        stmt = stmt.where(Feedback.rating <= rating_max)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))

    page_stmt = (
        stmt.order_by(Feedback.created_at.desc(), Feedback.id.desc()).limit(limit).offset(offset)
    )
    items = list((await db.execute(page_stmt)).scalars().all())

    avg = await db.scalar(select(func.avg(Feedback.rating)))

    distribution: dict[int, int] = {i: 0 for i in range(1, 6)}
    dist_rows = await db.execute(select(Feedback.rating, func.count()).group_by(Feedback.rating))
    for rating, count in dist_rows.all():
        distribution[int(rating)] = int(count)

    return AdminFeedbackListResponse(
        items=[AdminFeedbackItem.model_validate(it) for it in items],
        total=int(total or 0),
        average_rating=float(avg) if avg is not None else None,
        distribution=distribution,
    )


# =============================================================================
# Rewards Management
# =============================================================================


class AdminGrantBadgePayload(BaseModel):
    """Request body for granting a badge to a user."""

    badge_id: str
    reason: str | None = None


class AdminGrantTemplatePayload(BaseModel):
    """Request body for granting a name template to a user."""

    template_id: str
    reason: str | None = None


class AdminGrantSkinPayload(BaseModel):
    """Request body for granting a phantom skin to a user."""

    skin_id: str
    reason: str | None = None


@router.post("/users/{user_id}/badges", status_code=201)
async def admin_grant_badge(
    user_id: uuid.UUID,
    payload: AdminGrantBadgePayload,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Grant a permanent badge to a user. Requires admin role."""
    svc = RewardsService(db)
    try:
        grant = await svc.grant_permanent_badge(
            user_id, payload.badge_id, granted_by=admin.id, reason=payload.reason
        )
    except (UnknownRewardError, LifecycleMismatchError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return {"granted": grant is not None, "badge_id": payload.badge_id}


@router.delete("/users/{user_id}/badges/{badge_id}", status_code=204)
async def admin_revoke_badge(
    user_id: uuid.UUID,
    badge_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a badge from a user (soft-delete). Requires admin role."""
    svc = RewardsService(db)
    try:
        await svc.revoke_badge(user_id, badge_id)
    except UnknownRewardError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return Response(status_code=204)


@router.post("/users/{user_id}/templates", status_code=201)
async def admin_grant_template(
    user_id: uuid.UUID,
    payload: AdminGrantTemplatePayload,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Grant a name template to a user. Requires admin role."""
    svc = RewardsService(db)
    try:
        unlock = await svc.grant_name_template(
            user_id, payload.template_id, granted_by=admin.id, reason=payload.reason
        )
    except UnknownRewardError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return {"granted": unlock is not None, "template_id": payload.template_id}


@router.delete("/users/{user_id}/templates/{template_id}", status_code=204)
async def admin_revoke_template(
    user_id: uuid.UUID,
    template_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a name template from a user. Requires admin role."""
    svc = RewardsService(db)
    try:
        await svc.revoke_name_template(user_id, template_id)
    except UnknownRewardError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return Response(status_code=204)


@router.post("/users/{user_id}/skins", status_code=201)
async def admin_grant_phantom_skin(
    user_id: uuid.UUID,
    payload: AdminGrantSkinPayload,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Grant a phantom skin to a user. Requires admin role."""
    svc = RewardsService(db)
    try:
        unlock = await svc.grant_phantom_skin(
            user_id, payload.skin_id, granted_by=admin.id, reason=payload.reason
        )
    except UnknownRewardError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return {"granted": unlock is not None, "skin_id": payload.skin_id}


@router.delete("/users/{user_id}/skins/{skin_id}", status_code=204)
async def admin_revoke_phantom_skin(
    user_id: uuid.UUID,
    skin_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a phantom skin from a user. Requires admin role."""
    svc = RewardsService(db)
    try:
        await svc.revoke_phantom_skin(user_id, skin_id)
    except UnknownRewardError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    await db.commit()
    return Response(status_code=204)
