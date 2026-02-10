"""Authentication API routes."""

import secrets
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
from speedfog_racing.rate_limit import limiter

router = APIRouter()

# In-memory state storage for OAuth: state → (redirect_url, expiry_timestamp)
_oauth_states: dict[str, tuple[str, float]] = {}

_OAUTH_STATE_TTL = 600  # 10 minutes

# Ephemeral auth codes: code → (api_token, expiry_timestamp)
_auth_codes: dict[str, tuple[str, float]] = {}

_AUTH_CODE_TTL = 60  # seconds


def _cleanup_expired_states() -> None:
    """Remove expired OAuth states and auth codes to prevent memory leaks."""
    now = time.monotonic()
    expired_states = [s for s, (_, expiry) in _oauth_states.items() if expiry < now]
    for s in expired_states:
        del _oauth_states[s]
    expired_codes = [c for c, (_, expiry) in _auth_codes.items() if expiry < now]
    for c in expired_codes:
        del _auth_codes[c]


class UserPublicResponse(BaseModel):
    """User info response (public — no api_token)."""

    id: uuid.UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    """User info response (internal — includes api_token)."""

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


class CodeExchangeRequest(BaseModel):
    """Request body for auth code exchange."""

    code: str


class CodeExchangeResponse(BaseModel):
    """Response from auth code exchange."""

    token: str


@router.get("/twitch")
@limiter.limit("10/minute")
async def twitch_login(
    request: Request,
    redirect_url: Annotated[str | None, Query(description="URL to redirect after login")] = None,
) -> RedirectResponse:
    """Redirect to Twitch OAuth authorization page."""
    # Generate state for CSRF protection
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (
        redirect_url or settings.oauth_redirect_url,
        time.monotonic() + _OAUTH_STATE_TTL,
    )

    oauth_url = get_twitch_oauth_url(state)
    return RedirectResponse(url=oauth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
@limiter.limit("10/minute")
async def twitch_callback(
    request: Request,
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

    redirect_url, state_expiry = _oauth_states.pop(state)
    if time.monotonic() > state_expiry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

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

    # Generate ephemeral code instead of leaking the API token in the URL
    ephemeral_code = secrets.token_urlsafe(32)
    _auth_codes[ephemeral_code] = (user.api_token, time.monotonic() + _AUTH_CODE_TTL)

    separator = "&" if "?" in redirect_url else "?"
    return RedirectResponse(
        url=f"{redirect_url}{separator}code={ephemeral_code}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/exchange", response_model=CodeExchangeResponse)
@limiter.limit("10/minute")
async def exchange_auth_code(request: Request, body: CodeExchangeRequest) -> CodeExchangeResponse:
    """Exchange an ephemeral auth code for an API token."""
    entry = _auth_codes.pop(body.code, None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired auth code",
        )

    api_token, expiry = entry
    if time.monotonic() > expiry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired auth code",
        )

    return CodeExchangeResponse(token=api_token)


@router.get("/me", response_model=UserPublicResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current authenticated user info."""
    return user


@router.post("/logout")
async def logout(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Regenerate API token to invalidate current sessions."""
    from speedfog_racing.auth import generate_token

    user.api_token = generate_token()
    await db.commit()
    return {"message": "Logged out successfully"}
