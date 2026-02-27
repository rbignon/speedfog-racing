"""Admin API routes for seed and system management."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import user_response
from speedfog_racing.auth import require_admin
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Caster,
    Participant,
    ParticipantStatus,
    Race,
    TrainingSession,
    User,
    UserRole,
)
from speedfog_racing.schemas import (
    ActivityItem,
    ActivityTimelineResponse,
    RaceCasterActivity,
    RaceOrganizerActivity,
    RaceParticipantActivity,
    TrainingActivity,
)
from speedfog_racing.services import discard_pool, get_pool_stats, scan_pool

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

    # 1. Race participations (all users)
    part_q = await db.execute(
        select(Participant).options(
            selectinload(Participant.user),
            selectinload(Participant.race).selectinload(Race.participants),
        )
    )
    for p in part_q.scalars().all():
        race = p.race
        finished_participants = sorted(
            [pp for pp in race.participants if pp.status == ParticipantStatus.FINISHED],
            key=lambda pp: pp.igt_ms,
        )
        placement = None
        for idx, fp in enumerate(finished_participants):
            if fp.id == p.id:
                placement = idx + 1
                break

        items.append(
            RaceParticipantActivity(
                date=race.created_at,
                user=user_response(p.user),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                placement=placement,
                total_participants=len(race.participants),
                igt_ms=p.igt_ms,
                death_count=p.death_count,
            )
        )

    # 2. Organized races (all users)
    org_q = await db.execute(
        select(Race).options(
            selectinload(Race.organizer),
            selectinload(Race.participants),
        )
    )
    for race in org_q.scalars().all():
        items.append(
            RaceOrganizerActivity(
                date=race.created_at,
                user=user_response(race.organizer),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                participant_count=len(race.participants),
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
                date=c.race.created_at,
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
                status=t.status.value,
                igt_ms=t.igt_ms,
                death_count=t.death_count,
                exclude_from_stats=t.exclude_from_stats,
            )
        )

    # Sort by date descending
    items.sort(key=lambda item: item.date, reverse=True)

    total = len(items)
    paginated = items[offset : offset + limit]
    has_more = (offset + limit) < total

    return ActivityTimelineResponse(items=paginated, total=total, has_more=has_more)
