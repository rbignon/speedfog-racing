"""User API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import (
    compute_race_stats,
    format_pool_display_name,
    race_date,
    race_response,
    user_response,
)
from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Caster,
    EloHistory,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    Seed,
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.schemas import (
    ActivityItem,
    ActivityTimelineResponse,
    PoolTypeStatsResponse,
    RaceCasterActivity,
    RaceListResponse,
    RaceOrganizerActivity,
    RaceParticipantActivity,
    TrainingActivity,
    TraitScoresDetail,
    UserPoolStatsEntry,
    UserPoolStatsResponse,
    UserProfileDetailResponse,
    UserResponse,
    UserStatsResponse,
    UserTraitsResponse,
)
from speedfog_racing.services.i18n import get_available_locales
from speedfog_racing.services.stats_service import MIN_RACES_FOR_TRAITS

router = APIRouter()


@router.get("/search", response_model=list[UserResponse])
async def search_users(
    q: str = Query(..., min_length=1, max_length=100),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    """Search users by Twitch username or display name prefix."""
    result = await db.execute(
        select(User)
        .where(
            or_(
                User.twitch_username.ilike(f"{q}%"),
                User.twitch_display_name.ilike(f"{q}%"),
            )
        )
        .limit(10)
    )
    users = result.scalars().all()
    return [user_response(u) for u in users]


class UpdateLocaleRequest(BaseModel):
    locale: str


class OverlaySettingsRequest(BaseModel):
    """Request to update overlay settings. Only provided fields are updated."""

    font_size: float | None = None

    @field_validator("font_size")
    @classmethod
    def validate_font_size(cls, v: float | None) -> float | None:
        if v is not None and not (8.0 <= v <= 72.0):
            raise ValueError("font_size must be between 8 and 72")
        return v


@router.patch("/me/locale")
async def update_locale(
    body: UpdateLocaleRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Set locale preference."""
    valid_codes = {loc["code"] for loc in get_available_locales()}
    if body.locale not in valid_codes:
        raise HTTPException(status_code=400, detail=f"Unknown locale: {body.locale}")
    user.locale = body.locale
    await db.commit()
    return {"locale": user.locale}


@router.patch("/me/settings")
async def update_overlay_settings(
    body: OverlaySettingsRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, dict[str, float] | None]:
    """Update overlay settings (merge with existing)."""
    current = dict(user.overlay_settings or {})
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    user.overlay_settings = current
    await db.commit()
    return {"overlay_settings": user.overlay_settings}


@router.get("/me/races", response_model=RaceListResponse)
async def get_my_races(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RaceListResponse:
    """Get races where the user is organizer or participant."""
    # Personal history intentionally includes Daily Seed participations so
    # users see every race they actually played; the listings under
    # /api/races/* are the surface that filters them out.
    participant_race_ids = select(Participant.race_id).where(Participant.user_id == user.id)
    query = (
        select(Race)
        .where(or_(Race.organizer_id == user.id, Race.id.in_(participant_race_ids)))
        .options(
            selectinload(Race.organizer),
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.casters).selectinload(Caster.user),
        )
        .order_by(func.coalesce(Race.started_at, Race.scheduled_at, Race.created_at).desc())
    )
    result = await db.execute(query)
    races = list(result.scalars().all())

    race_responses = []
    for r in races:
        resp = race_response(r, user)
        my_participant = next((p for p in r.participants if p.user_id == user.id), None)
        if my_participant:
            resp.my_current_layer = my_participant.current_layer
            resp.my_igt_ms = my_participant.igt_ms
            resp.my_death_count = my_participant.death_count
        if r.seed:
            resp.seed_total_layers = r.seed.total_layers
        race_responses.append(resp)

    return RaceListResponse(races=race_responses)


@router.get("/{username}/pool-stats", response_model=UserPoolStatsResponse)
async def get_user_pool_stats(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserPoolStatsResponse:
    """Get per-pool aggregated stats for a user."""
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id

    # Race stats: aggregate participations (FINISHED + ABANDONED with igt > 0)
    # Time metrics only use FINISHED (abandoned times are incomplete).
    finished_case = case(
        (Participant.status == ParticipantStatus.FINISHED, Participant.igt_ms),
    )
    race_stats_q = await db.execute(
        select(
            Seed.pool_name,
            func.count().label("runs"),
            func.avg(finished_case).label("avg_time_ms"),
            func.avg(Participant.death_count).label("avg_deaths"),
            func.min(finished_case).label("best_time_ms"),
        )
        .select_from(Participant)
        .join(Race, Participant.race_id == Race.id)
        .join(Seed, Race.seed_id == Seed.id)
        .where(
            Participant.user_id == user_id,
            or_(
                Participant.status == ParticipantStatus.FINISHED,
                (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
            ),
        )
        .group_by(Seed.pool_name)
    )
    race_stats = {
        row.pool_name: PoolTypeStatsResponse(
            runs=row.runs,
            avg_time_ms=int(row.avg_time_ms) if row.avg_time_ms else None,
            avg_deaths=round(float(row.avg_deaths), 1),
            best_time_ms=row.best_time_ms,
        )
        for row in race_stats_q.all()
    }

    # Training stats: aggregate sessions (FINISHED + ABANDONED with igt > 0)
    # Time metrics only use FINISHED (abandoned times are incomplete).
    training_finished_case = case(
        (TrainingSession.status == TrainingSessionStatus.FINISHED, TrainingSession.igt_ms),
    )
    training_stats_q = await db.execute(
        select(
            Seed.pool_name,
            func.count().label("runs"),
            func.avg(training_finished_case).label("avg_time_ms"),
            func.avg(TrainingSession.death_count).label("avg_deaths"),
            func.min(training_finished_case).label("best_time_ms"),
        )
        .select_from(TrainingSession)
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            TrainingSession.user_id == user_id,
            or_(
                TrainingSession.status == TrainingSessionStatus.FINISHED,
                (TrainingSession.status == TrainingSessionStatus.ABANDONED)
                & (TrainingSession.igt_ms > 0),
            ),
            TrainingSession.exclude_from_stats == False,  # noqa: E712
        )
        .group_by(Seed.pool_name)
    )
    training_stats = {}
    for row in training_stats_q.all():
        # Normalize "training_X" → "X" so training merges with its race pool
        pool = row.pool_name.removeprefix("training_")
        training_stats[pool] = PoolTypeStatsResponse(
            runs=row.runs,
            avg_time_ms=int(row.avg_time_ms) if row.avg_time_ms else None,
            avg_deaths=round(float(row.avg_deaths), 1),
            best_time_ms=row.best_time_ms,
        )

    # Merge all pool names
    all_pools = set(race_stats.keys()) | set(training_stats.keys())
    entries = []
    for pool_name in all_pools:
        race = race_stats.get(pool_name)
        training = training_stats.get(pool_name)
        # Note: training.runs excludes slow runs (exclude_from_stats=True),
        # so total_runs reflects "counted runs", not all sessions.
        total_runs = (race.runs if race else 0) + (training.runs if training else 0)
        entries.append(
            UserPoolStatsEntry(
                pool_name=pool_name,
                race=race,
                training=training,
                total_runs=total_runs,
            )
        )

    entries.sort(key=lambda e: e.total_runs, reverse=True)

    return UserPoolStatsResponse(pools=entries)


@router.get(
    "/{username}/activity",
    response_model=ActivityTimelineResponse,
    response_model_exclude_none=True,
)
async def get_user_activity(
    username: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ActivityTimelineResponse:
    """Get a user's activity timeline with pagination."""
    # Look up user by twitch_username
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id
    items: list[ActivityItem] = []

    # 1. Race participations (no Race.participants loaded, use batch stats)
    part_q = await db.execute(
        select(Participant)
        .where(Participant.user_id == user_id)
        .options(selectinload(Participant.race))
    )
    participations = part_q.scalars().all()

    # 2. Organized races
    org_q = await db.execute(select(Race).where(Race.organizer_id == user_id))
    organized_races = org_q.scalars().all()

    # Batch-compute counts and placements for all relevant races
    all_race_ids = list({p.race_id for p in participations} | {r.id for r in organized_races})
    total_by_race, placements = await compute_race_stats(db, all_race_ids)

    # Race ids the user also participated in: merge the organizer entry into
    # the participant entry instead of producing two cards.
    participated_race_ids = {p.race_id for p in participations}

    for p in participations:
        race = p.race
        items.append(
            RaceParticipantActivity(
                date=race_date(race),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                placement=placements.get((race.id, p.id)),
                total_participants=total_by_race.get(race.id, 0),
                igt_ms=p.igt_ms,
                death_count=p.death_count,
                is_organizer=race.organizer_id == user_id,
            )
        )

    for race in organized_races:
        if race.id in participated_race_ids:
            continue
        items.append(
            RaceOrganizerActivity(
                date=race_date(race),
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                participant_count=total_by_race.get(race.id, 0),
            )
        )

    # 3. Caster roles
    caster_q = await db.execute(
        select(Caster).where(Caster.user_id == user_id).options(selectinload(Caster.race))
    )
    caster_roles = caster_q.scalars().all()

    for c in caster_roles:
        items.append(
            RaceCasterActivity(
                date=race_date(c.race),
                race_id=c.race.id,
                race_name=c.race.name,
                status=c.race.status.value,
            )
        )

    # 4. Training sessions (exclude cancelled, player never started)
    training_q = await db.execute(
        select(TrainingSession)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.status != TrainingSessionStatus.CANCELLED,
        )
        .options(selectinload(TrainingSession.seed))
    )
    trainings = training_q.scalars().all()

    for t in trainings:
        items.append(
            TrainingActivity(
                date=t.created_at,
                session_id=t.id,
                pool_name=t.seed.pool_name,
                pool_display_name=format_pool_display_name(t.seed.pool),
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


@router.get("/{username}", response_model=UserProfileDetailResponse)
async def get_user_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserProfileDetailResponse:
    """Get a public user profile with aggregated stats."""
    # Look up user by twitch_username
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id

    # Race count: finished + abandoned with igt > 0 (actually played)
    race_count_q = await db.execute(
        select(func.count())
        .select_from(Participant)
        .where(
            Participant.user_id == user_id,
            or_(
                Participant.status == ParticipantStatus.FINISHED,
                (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
            ),
        )
    )
    race_count = race_count_q.scalar_one()

    # Training count (exclude cancelled, player never started)
    training_count_q = await db.execute(
        select(func.count())
        .select_from(TrainingSession)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.status != TrainingSessionStatus.CANCELLED,
        )
    )
    training_count = training_count_q.scalar_one()

    # Organized count
    organized_count_q = await db.execute(
        select(func.count()).select_from(Race).where(Race.organizer_id == user_id)
    )
    organized_count = organized_count_q.scalar_one()

    # Casted count
    casted_count_q = await db.execute(
        select(func.count()).select_from(Caster).where(Caster.user_id == user_id)
    )
    casted_count = casted_count_q.scalar_one()

    stats = UserStatsResponse(
        race_count=race_count,
        training_count=training_count,
        organized_count=organized_count,
        casted_count=casted_count,
    )

    return UserProfileDetailResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        created_at=user.created_at,
        stats=stats,
    )


@router.get("/{username}/traits", response_model=UserTraitsResponse)
async def get_user_traits(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserTraitsResponse:
    """Get ELO and trait data for a user."""
    user = (
        await db.execute(select(User).where(User.twitch_username == username))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    scores = await db.get(PlayerTraitScores, user.id)

    finished_races = (
        await db.execute(
            select(func.count()).where(
                Participant.user_id == user.id,
                Participant.status == ParticipantStatus.FINISHED,
            )
        )
    ).scalar() or 0

    # ELO rank (only for non-provisional: 3+ races participated)
    elo_rank = None
    if user.elo_races >= 3:
        rank_count = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.elo_races >= 3, User.elo_rating > user.elo_rating)
            )
        ).scalar() or 0
        elo_rank = rank_count + 1

    # Trend: sum of last 3 deltas
    recent_deltas = (
        (
            await db.execute(
                select(EloHistory.delta)
                .where(EloHistory.user_id == user.id)
                .order_by(EloHistory.created_at.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    trend_delta = round(sum(recent_deltas))

    scores_detail = None
    dominant_trait = None
    dominant_description = None
    if scores and user.elo_races >= 3:
        has_nonzero = any(
            [
                scores.rusher,
                scores.cautious,
                scores.resilient,
                scores.rage_quitter,
                scores.explorer,
                scores.pathfinder,
                scores.boss_slayer,
            ]
        )
        if has_nonzero:
            dominant_trait = scores.dominant_trait
            dominant_description = scores.dominant_description
            scores_detail = TraitScoresDetail(
                rusher=scores.rusher,
                cautious=scores.cautious,
                resilient=scores.resilient,
                rage_quitter=scores.rage_quitter,
                explorer=scores.explorer,
                pathfinder=scores.pathfinder,
                boss_slayer=scores.boss_slayer,
            )

    return UserTraitsResponse(
        dominant_trait=dominant_trait,
        dominant_description=dominant_description,
        scores=scores_detail,
        finished_races=finished_races,
        races_required=MIN_RACES_FOR_TRAITS,
        elo_rating=round(user.elo_rating),
        elo_rank=elo_rank,
        elo_trend_delta=trend_delta,
    )
