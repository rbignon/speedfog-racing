"""User API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import race_response, user_response
from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Caster,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    TrainingSession,
    User,
)
from speedfog_racing.schemas import (
    ActivityItem,
    ActivityTimelineResponse,
    RaceCasterActivity,
    RaceListResponse,
    RaceOrganizerActivity,
    RaceParticipantActivity,
    TrainingActivity,
    UserProfileDetailResponse,
    UserResponse,
    UserStatsResponse,
)
from speedfog_racing.services.i18n import get_available_locales

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


class MyProfileResponse(BaseModel):
    """Current user's profile response (used by /me)."""

    id: str
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str
    overlay_settings: dict[str, float] | None = None

    model_config = {"from_attributes": True}


@router.get("/me", response_model=MyProfileResponse)
async def get_my_profile(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user's profile."""
    return user


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
        .order_by(Race.created_at.desc())
    )
    result = await db.execute(query)
    races = list(result.scalars().all())

    race_responses = []
    for r in races:
        resp = race_response(r)
        my_participant = next((p for p in r.participants if p.user_id == user.id), None)
        if my_participant:
            resp.my_current_layer = my_participant.current_layer
            resp.my_igt_ms = my_participant.igt_ms
            resp.my_death_count = my_participant.death_count
        if r.seed:
            resp.seed_total_layers = r.seed.total_layers
        race_responses.append(resp)

    return RaceListResponse(races=race_responses)


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

    # 1. Race participations
    part_q = await db.execute(
        select(Participant)
        .where(Participant.user_id == user_id)
        .options(
            selectinload(Participant.race).selectinload(Race.participants),
        )
        .join(Race, Participant.race_id == Race.id)
    )
    participations = part_q.scalars().all()

    for p in participations:
        race = p.race
        # Compute placement: rank finished participants by IGT
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
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                placement=placement,
                total_participants=len(race.participants),
                igt_ms=p.igt_ms,
                death_count=p.death_count,
            )
        )

    # 2. Organized races
    org_q = await db.execute(
        select(Race).where(Race.organizer_id == user_id).options(selectinload(Race.participants))
    )
    organized_races = org_q.scalars().all()

    for race in organized_races:
        items.append(
            RaceOrganizerActivity(
                date=race.created_at,
                race_id=race.id,
                race_name=race.name,
                status=race.status.value,
                participant_count=len(race.participants),
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
                date=c.race.created_at,
                race_id=c.race.id,
                race_name=c.race.name,
                status=c.race.status.value,
            )
        )

    # 4. Training sessions
    training_q = await db.execute(
        select(TrainingSession)
        .where(TrainingSession.user_id == user_id)
        .options(selectinload(TrainingSession.seed))
    )
    trainings = training_q.scalars().all()

    for t in trainings:
        items.append(
            TrainingActivity(
                date=t.created_at,
                session_id=t.id,
                pool_name=t.seed.pool_name,
                status=t.status.value,
                igt_ms=t.igt_ms,
                death_count=t.death_count,
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

    # Race count: participations in started races
    race_count_q = await db.execute(
        select(func.count())
        .select_from(Participant)
        .join(Race, Participant.race_id == Race.id)
        .where(
            Participant.user_id == user_id,
            Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]),
        )
    )
    race_count = race_count_q.scalar_one()

    # Training count
    training_count_q = await db.execute(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user_id)
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
