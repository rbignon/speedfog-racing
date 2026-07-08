"""Authentication API routes."""

import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

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
from speedfog_racing.services.i18n import get_available_locales

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory state storage for OAuth: state → (redirect_url, expiry_timestamp, browser_locale)
_oauth_states: dict[str, tuple[str, float, str]] = {}

_OAUTH_STATE_TTL = 600  # 10 minutes


def _origin_of(url: str) -> tuple[str, str | None, int | None] | None:
    """(scheme, host, port) for a URL, or None if it is not a usable http(s) origin.

    Returns None for relative URLs (no scheme/host) and for a malformed port
    (``urlparse().port`` raises ValueError), so callers fail closed.
    """
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    return (parsed.scheme, parsed.hostname, port)


def _allowed_redirect_origins() -> set[tuple[str, str | None, int | None]]:
    """(scheme, host, port) origins the OAuth flow may redirect back to."""
    origins = set(settings.cors_origins) | {settings.oauth_redirect_url}
    return {origin for url in origins if (origin := _origin_of(url)) is not None}


def _safe_redirect_url(redirect_url: str | None) -> str:
    """Return ``redirect_url`` only if it targets an allowed origin, else the default.

    The OAuth callback appends the ephemeral login code to this URL and 302s
    the browser there. An attacker-controlled value would leak the code (and
    thus the account's long-lived api_token) to an external site, so anything
    off an allowed origin is replaced by the configured default. Comparison is
    on (scheme, host, port) to defeat userinfo tricks like
    ``http://good-host@evil.com``.
    """
    if not redirect_url:
        return settings.oauth_redirect_url
    origin = _origin_of(redirect_url)
    if origin is not None and origin in _allowed_redirect_origins():
        return redirect_url
    logger.warning("Rejected OAuth redirect_url to disallowed origin: %s", redirect_url)
    return settings.oauth_redirect_url


# Ephemeral auth codes: code → (api_token, expiry_timestamp)
_auth_codes: dict[str, tuple[str, float]] = {}

_AUTH_CODE_TTL = 60  # seconds


def _cleanup_expired_states() -> None:
    """Remove expired OAuth states and auth codes to prevent memory leaks."""
    now = time.monotonic()
    expired_states = [s for s, (_, expiry, _loc) in _oauth_states.items() if expiry < now]
    for s in expired_states:
        del _oauth_states[s]
    expired_codes = [c for c, (_, expiry) in _auth_codes.items() if expiry < now]
    for c in expired_codes:
        del _auth_codes[c]


class UserPublicResponse(BaseModel):
    """User info response (public, no api_token)."""

    id: uuid.UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str
    locale: str | None = None
    overlay_settings: dict[str, float] | None = None
    feedback_prompted_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    """User info response (internal, includes api_token)."""

    id: uuid.UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    api_token: str
    role: str
    locale: str | None = None

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
    locale: Annotated[str | None, Query(description="Browser language code (e.g. 'fr')")] = None,
) -> RedirectResponse:
    """Redirect to Twitch OAuth authorization page."""
    # Validate browser locale against available translations, default to "en"
    valid_codes = {loc["code"] for loc in get_available_locales()}
    browser_locale = locale if locale in valid_codes else "en"

    # Generate state for CSRF protection
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (
        _safe_redirect_url(redirect_url),
        time.monotonic() + _OAUTH_STATE_TTL,
        browser_locale,
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

    redirect_url, state_expiry, browser_locale = _oauth_states.pop(state)
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

    # Get or create user in our database (set locale from browser on first login)
    user = await get_or_create_user(db, twitch_user, browser_locale=browser_locale)
    await db.commit()

    # Generate ephemeral code instead of leaking the API token in the URL.
    # api_token is nullable only for system users, which have no Twitch OAuth
    # path; reaching here without a token would be a programming error rather
    # than a user-facing failure mode.
    assert user.api_token is not None, "Twitch-authenticated user must have an api_token"
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
    db: AsyncSession = Depends(get_db),
    timezone: Annotated[str | None, Query(max_length=50)] = None,
) -> User:
    """Get current authenticated user info. Optionally updates timezone."""
    if timezone is not None:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(timezone)
        except (KeyError, Exception):
            pass
        else:
            user.timezone = timezone
            await db.commit()
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
