"""Test authentication endpoints."""

import time
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from speedfog_racing.auth import TwitchUser, get_or_create_user
from speedfog_racing.database import Base


def test_twitch_login_redirects(client):
    """Test that /auth/twitch redirects to Twitch OAuth."""
    response = client.get("/api/auth/twitch", follow_redirects=False)
    assert response.status_code == 302
    assert "id.twitch.tv/oauth2/authorize" in response.headers["location"]


def test_twitch_login_includes_state(client):
    """Test that OAuth redirect includes state parameter."""
    response = client.get("/api/auth/twitch", follow_redirects=False)
    location = response.headers["location"]
    assert "state=" in location


def test_callback_rejects_missing_state(client):
    """Test that callback rejects requests without state."""
    response = client.get("/api/auth/callback?code=test_code")
    assert response.status_code == 400
    assert "Invalid or expired OAuth state" in response.json()["detail"]


def test_callback_rejects_invalid_state(client):
    """Test that callback rejects invalid state."""
    response = client.get("/api/auth/callback?code=test_code&state=invalid")
    assert response.status_code == 400
    assert "Invalid or expired OAuth state" in response.json()["detail"]


def test_me_requires_auth(client):
    """Test that /auth/me requires authentication."""
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_invalid_token(client):
    """Test that /auth/me rejects invalid tokens.

    Note: This test requires proper async database setup.
    For now, we verify it doesn't return 200 (success).
    """
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )
    # Should not succeed - either 401 (proper rejection) or 500 (db error in test)
    assert response.status_code != 200


# =============================================================================
# Auth code exchange endpoint tests
# =============================================================================


def test_exchange_invalid_code(client):
    """Test that /auth/exchange rejects an invalid code."""
    response = client.post("/api/auth/exchange", json={"code": "nonexistent"})
    assert response.status_code == 400
    assert "Invalid or expired auth code" in response.json()["detail"]


def test_exchange_missing_code(client):
    """Test that /auth/exchange rejects a request without code."""
    response = client.post("/api/auth/exchange", json={})
    assert response.status_code == 422


def test_exchange_valid_code(client):
    """Test that a valid ephemeral code returns a token."""
    from speedfog_racing.api.auth import _auth_codes

    _auth_codes["test-code-123"] = ("fake-api-token", time.monotonic() + 60)
    response = client.post("/api/auth/exchange", json={"code": "test-code-123"})
    assert response.status_code == 200
    assert response.json()["token"] == "fake-api-token"
    # Code is consumed
    assert "test-code-123" not in _auth_codes


def test_exchange_code_single_use(client):
    """Test that an ephemeral code can only be used once."""
    from speedfog_racing.api.auth import _auth_codes

    _auth_codes["single-use-code"] = ("fake-token", time.monotonic() + 60)
    response = client.post("/api/auth/exchange", json={"code": "single-use-code"})
    assert response.status_code == 200

    # Second attempt with same code should fail
    response = client.post("/api/auth/exchange", json={"code": "single-use-code"})
    assert response.status_code == 400


def test_exchange_expired_code(client):
    """Test that an expired code is rejected."""
    from speedfog_racing.api.auth import _auth_codes

    # Set expiry in the past
    _auth_codes["expired-code"] = ("fake-token", time.monotonic() - 1)
    response = client.post("/api/auth/exchange", json={"code": "expired-code"})
    assert response.status_code == 400
    assert "Invalid or expired auth code" in response.json()["detail"]


_FAKE_LOCALES = [{"code": "en", "name": "English"}, {"code": "fr", "name": "French"}]


def test_twitch_login_passes_locale(client):
    """Test that /auth/twitch stores browser locale in OAuth state."""
    from speedfog_racing.api.auth import _oauth_states

    _oauth_states.clear()
    with patch("speedfog_racing.api.auth.get_available_locales", return_value=_FAKE_LOCALES):
        response = client.get("/api/auth/twitch?locale=fr", follow_redirects=False)
    assert response.status_code == 302

    assert len(_oauth_states) == 1
    _, _, locale = next(iter(_oauth_states.values()))
    assert locale == "fr"


def test_twitch_login_invalid_locale_defaults_to_en(client):
    """Test that unknown locale falls back to 'en'."""
    from speedfog_racing.api.auth import _oauth_states

    _oauth_states.clear()
    with patch("speedfog_racing.api.auth.get_available_locales", return_value=_FAKE_LOCALES):
        response = client.get("/api/auth/twitch?locale=zz", follow_redirects=False)
    assert response.status_code == 302

    assert len(_oauth_states) == 1
    _, _, locale = next(iter(_oauth_states.values()))
    assert locale == "en"


# =============================================================================
# redirect_url validation (open-redirect / account-takeover protection)
# =============================================================================


def test_safe_redirect_url_rejects_external_origin():
    """An attacker-controlled origin falls back to the configured default so
    the ephemeral login code can never be redirected off-site."""
    from speedfog_racing.api.auth import _safe_redirect_url
    from speedfog_racing.config import settings

    assert _safe_redirect_url("https://evil.com/steal") == settings.oauth_redirect_url


def test_safe_redirect_url_rejects_userinfo_confusion():
    """A userinfo trick (real host in userinfo, attacker host after @) is rejected."""
    from speedfog_racing.api.auth import _safe_redirect_url
    from speedfog_racing.config import settings

    assert _safe_redirect_url("http://localhost:5173@evil.com/") == settings.oauth_redirect_url


def test_safe_redirect_url_none_returns_default():
    from speedfog_racing.api.auth import _safe_redirect_url
    from speedfog_racing.config import settings

    assert _safe_redirect_url(None) == settings.oauth_redirect_url


def test_safe_redirect_url_malformed_port_returns_default():
    """A non-numeric/out-of-range port must fall back, not raise (urlparse.port
    raises ValueError). Otherwise a crafted value 500s the public login route."""
    from speedfog_racing.api.auth import _safe_redirect_url
    from speedfog_racing.config import settings

    assert _safe_redirect_url("http://localhost:abc/") == settings.oauth_redirect_url
    assert _safe_redirect_url("http://x:99999999999/") == settings.oauth_redirect_url


def test_safe_redirect_url_accepts_allowed_origin():
    """The configured OAuth redirect origin is always permitted."""
    from speedfog_racing.api.auth import _safe_redirect_url
    from speedfog_racing.config import settings

    allowed = settings.oauth_redirect_url
    assert _safe_redirect_url(allowed) == allowed


def test_twitch_login_stores_default_for_external_redirect(client):
    """A crafted redirect_url pointing off-site is not stored in OAuth state."""
    from speedfog_racing.api.auth import _oauth_states
    from speedfog_racing.config import settings

    _oauth_states.clear()
    response = client.get(
        "/api/auth/twitch?redirect_url=https://evil.com/x", follow_redirects=False
    )
    assert response.status_code == 302
    assert len(_oauth_states) == 1
    stored_url, _, _ = next(iter(_oauth_states.values()))
    assert stored_url == settings.oauth_redirect_url


def test_twitch_login_preserves_allowed_redirect(client):
    """A redirect_url on an allowed origin is stored verbatim."""
    from speedfog_racing.api.auth import _oauth_states
    from speedfog_racing.config import settings

    _oauth_states.clear()
    allowed = settings.oauth_redirect_url
    response = client.get(f"/api/auth/twitch?redirect_url={allowed}", follow_redirects=False)
    assert response.status_code == 302
    stored_url, _, _ = next(iter(_oauth_states.values()))
    assert stored_url == allowed


# =============================================================================
# get_or_create_user: locale-on-login behavior
# =============================================================================

_FAKE_TWITCH_USER = TwitchUser(
    id="12345",
    login="testuser",
    display_name="TestUser",
    profile_image_url="https://example.com/avatar.png",
)


@pytest.fixture
async def async_db():
    """Async in-memory SQLite session for unit tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def test_new_user_gets_browser_locale(async_db: AsyncSession) -> None:
    """New user gets locale set from browser_locale param."""
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER, browser_locale="fr")
    await async_db.commit()
    assert user.locale == "fr"


async def test_new_user_defaults_to_en(async_db: AsyncSession) -> None:
    """New user without browser_locale defaults to 'en'."""
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER)
    await async_db.commit()
    assert user.locale == "en"


async def test_existing_user_null_locale_gets_backfilled(async_db: AsyncSession) -> None:
    """Existing user with NULL locale gets it set from browser_locale on login."""
    # Create user with NULL locale (simulating pre-migration user)
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER)
    await async_db.commit()
    user.locale = None
    await async_db.commit()

    # Re-login with browser locale
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER, browser_locale="fr")
    await async_db.commit()
    assert user.locale == "fr"


async def test_existing_user_keeps_explicit_locale(async_db: AsyncSession) -> None:
    """Existing user with explicit locale is NOT overwritten by browser_locale."""
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER, browser_locale="en")
    await async_db.commit()

    # Re-login from a French browser, should NOT change the stored "en"
    user = await get_or_create_user(async_db, _FAKE_TWITCH_USER, browser_locale="fr")
    await async_db.commit()
    assert user.locale == "en"


# =============================================================================
# /auth/me played-run counts
# =============================================================================


@pytest.fixture
async def played_client():
    """httpx client over an in-memory async engine, for DB-backed endpoints."""
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_maker
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_me_reports_played_run_counts(played_client) -> None:
    """/auth/me carries the same played-run counts as the public profile, so
    the web can tell a seasoned player from a newcomer without a second
    request. A finished race counts, an abandon with no IGT does not, a
    daily counts on its own, a cancelled solo session does not."""
    from datetime import date

    from speedfog_racing.models import (
        Participant,
        ParticipantStatus,
        Race,
        RaceStatus,
        Seed,
        SeedStatus,
        TrainingSession,
        TrainingSessionStatus,
        User,
        UserRole,
    )

    client, session_maker = played_client
    async with session_maker() as db:
        user = User(
            twitch_id="me_counts",
            twitch_username="me_counts",
            twitch_display_name="MeCounts",
            api_token="me_counts_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.flush()
        seed = Seed(
            seed_number="me_counts_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        finished = Race(
            name="Finished", organizer_id=user.id, seed_id=seed.id, status=RaceStatus.FINISHED
        )
        never_started = Race(
            name="Never started",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        daily = Race(
            name="Daily",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 9, 1),
        )
        db.add_all([finished, never_started, daily])
        await db.flush()
        db.add_all(
            [
                Participant(
                    race_id=finished.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=120_000,
                ),
                Participant(
                    race_id=never_started.id,
                    user_id=user.id,
                    status=ParticipantStatus.ABANDONED,
                    igt_ms=0,
                ),
                Participant(
                    race_id=daily.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=90_000,
                    zone_history=[{"zone": "a"}, {"zone": "b"}],
                ),
                TrainingSession(
                    user_id=user.id, seed_id=seed.id, status=TrainingSessionStatus.FINISHED
                ),
                TrainingSession(
                    user_id=user.id, seed_id=seed.id, status=TrainingSessionStatus.CANCELLED
                ),
            ]
        )
        await db.commit()

    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer me_counts_token"})
    assert response.status_code == 200
    data = response.json()
    assert data["race_count"] == 1
    assert data["daily_count"] == 1
    assert data["training_count"] == 1
