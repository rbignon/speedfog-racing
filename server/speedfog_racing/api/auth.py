"""Authentication API routes."""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import (
    exchange_code_for_token,
    get_current_user,
    get_or_create_user,
    get_twitch_oauth_url,
    get_twitch_user,
)
from speedfog_racing.config import settings
from speedfog_racing.database import get_db
from speedfog_racing.models import User

router = APIRouter()

# In-memory state storage for OAuth (in production, use Redis or similar)
_oauth_states: dict[str, str] = {}


class UserResponse(BaseModel):
    """User info response."""

    id: uuid.UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    api_token: str
    role: str

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Authentication response with token."""

    user: UserResponse
    token: str


@router.get("/twitch")
async def twitch_login(
    redirect_url: Annotated[str | None, Query(description="URL to redirect after login")] = None,
) -> RedirectResponse:
    """Redirect to Twitch OAuth authorization page."""
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store redirect URL in state (in production, encrypt or use session)
    _oauth_states[state] = redirect_url or settings.oauth_redirect_url

    oauth_url = get_twitch_oauth_url(state)
    return RedirectResponse(url=oauth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def twitch_callback(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Twitch OAuth callback."""
    # Check for errors from Twitch
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Twitch OAuth error: {error_description or error}",
        )

    # Validate state
    if not state or state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    redirect_url = _oauth_states.pop(state)

    # Validate code
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    # Exchange code for token
    access_token = await exchange_code_for_token(code)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code",
        )

    # Get Twitch user info
    twitch_user = await get_twitch_user(access_token)
    if not twitch_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get Twitch user info",
        )

    # Get or create user in our database
    user = await get_or_create_user(db, twitch_user)
    await db.commit()

    # Redirect to frontend with token
    # The frontend will store this token for API calls
    separator = "&" if "?" in redirect_url else "?"
    return RedirectResponse(
        url=f"{redirect_url}{separator}token={user.api_token}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current authenticated user info."""
    return user


@router.post("/logout")
async def logout(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate API token to invalidate current sessions."""
    from speedfog_racing.auth import generate_token

    user.api_token = generate_token()
    await db.commit()
    return {"message": "Logged out successfully"}
