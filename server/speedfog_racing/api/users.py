"""User API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import race_response, user_response
from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import Participant, Race, User
from speedfog_racing.schemas import RaceListResponse, UserResponse

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


class UserProfileResponse(BaseModel):
    """User profile response."""

    id: str
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str

    model_config = {"from_attributes": True}


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user's profile."""
    return user


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
            selectinload(Race.participants),
        )
        .order_by(Race.created_at.desc())
    )
    result = await db.execute(query)
    races = list(result.scalars().all())

    return RaceListResponse(races=[race_response(r) for r in races])
