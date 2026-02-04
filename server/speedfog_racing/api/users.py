"""User API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from speedfog_racing.auth import get_current_user
from speedfog_racing.models import User

router = APIRouter()


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
