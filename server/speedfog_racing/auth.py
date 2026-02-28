"""Twitch OAuth authentication and user management."""

import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.database import get_db
from speedfog_racing.models import User


@dataclass
class TwitchUser:
    """Twitch user info from API."""

    id: str
    login: str
    display_name: str
    profile_image_url: str | None = None


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


def get_twitch_oauth_url(state: str) -> str:
    """Generate Twitch OAuth authorization URL."""
    return (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={settings.twitch_client_id}"
        f"&redirect_uri={settings.twitch_redirect_uri}"
        f"&response_type=code"
        f"&scope=user:read:email"
        f"&state={state}"
    )


async def exchange_code_for_token(code: str) -> str | None:
    """Exchange OAuth authorization code for access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.twitch_redirect_uri,
            },
        )
        if resp.status_code == 200:
            token: str | None = resp.json().get("access_token")
            return token
        return None


async def get_twitch_user(access_token: str) -> TwitchUser | None:
    """Get Twitch user info from access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": settings.twitch_client_id,
            },
        )
        if resp.status_code == 200:
            data_list = resp.json().get("data", [])
            if not data_list:
                return None
            data = data_list[0]
            return TwitchUser(
                id=data["id"],
                login=data["login"],
                display_name=data["display_name"],
                profile_image_url=data.get("profile_image_url"),
            )
        return None


async def get_or_create_user(
    db: AsyncSession,
    twitch_user: TwitchUser,
    *,
    browser_locale: str = "en",
) -> User:
    """Get existing user or create new one from Twitch info.

    *browser_locale* is applied to new users and existing users whose locale is
    still NULL (never explicitly set).
    """
    result = await db.execute(select(User).where(User.twitch_id == twitch_user.id))
    user = result.scalar_one_or_none()

    if user:
        # Update user info from Twitch
        user.twitch_username = twitch_user.login
        user.twitch_display_name = twitch_user.display_name
        user.twitch_avatar_url = twitch_user.profile_image_url
        user.last_seen = datetime.now(UTC)
        # Backfill locale for existing users who never set it
        if user.locale is None:
            user.locale = browser_locale
        return user

    # Create new user
    user = User(
        twitch_id=twitch_user.id,
        twitch_username=twitch_user.login,
        twitch_display_name=twitch_user.display_name,
        twitch_avatar_url=twitch_user.profile_image_url,
        api_token=generate_token(),
        last_seen=datetime.now(UTC),
        locale=browser_locale,
    )
    db.add(user)
    return user


async def get_user_by_token(db: AsyncSession, token: str) -> User | None:
    """Get user by API token."""
    result = await db.execute(select(User).where(User.api_token == token))
    return result.scalar_one_or_none()


async def get_user_by_twitch_username(db: AsyncSession, username: str) -> User | None:
    """Get user by Twitch username (case-insensitive)."""
    result = await db.execute(select(User).where(User.twitch_username.ilike(username)))
    return result.scalar_one_or_none()


@dataclass
class AppAccessToken:
    """Cached Twitch app access token."""

    token: str
    expires_at: float  # time.monotonic() timestamp


async def get_app_access_token() -> str:
    """Get a Twitch app access token (client credentials flow).

    Cached in memory; refreshes 60s before expiry.
    """
    cache: AppAccessToken | None = getattr(get_app_access_token, "_cache", None)
    if cache and time.monotonic() < cache.expires_at - 60:
        return cache.token

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)

        get_app_access_token._cache = AppAccessToken(  # type: ignore[attr-defined]
            token=token,
            expires_at=time.monotonic() + expires_in,
        )
        return token


# =============================================================================
# FastAPI Dependencies
# =============================================================================

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get the current authenticated user. Raises 401 if not authenticated."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_token(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Dependency to get current user if authenticated, None otherwise."""
    if not credentials:
        return None
    return await get_user_by_token(db, credentials.credentials)


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency to require admin role."""
    from speedfog_racing.models import UserRole

    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
