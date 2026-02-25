"""Test Discord interaction endpoint (signature verification + handlers)."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from nacl.signing import SigningKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.models import User, UserRole


@pytest.fixture
def signing_key():
    """Generate a real Ed25519 keypair for testing."""
    return SigningKey.generate()


@pytest.fixture
def public_key_hex(signing_key):
    """Return the public key as hex string."""
    return signing_key.verify_key.encode().hex()


def _sign_request(signing_key: SigningKey, timestamp: str, body: str) -> str:
    """Sign a request body with the given signing key."""
    message = f"{timestamp}{body}".encode()
    signed = signing_key.sign(message)
    return signed.signature.hex()


# =============================================================================
# Signature verification
# =============================================================================


def test_verify_signature_valid(signing_key, public_key_hex):
    """Valid signature should pass verification."""
    from speedfog_racing.api.discord import _verify_signature

    timestamp = "1234567890"
    body = '{"type": 1}'

    signature = _sign_request(signing_key, timestamp, body)

    with patch("speedfog_racing.api.discord.settings") as mock_settings:
        mock_settings.discord_public_key = public_key_hex
        assert _verify_signature(signature, timestamp, body) is True


def test_verify_signature_invalid(signing_key, public_key_hex):
    """Tampered body should fail verification."""
    from speedfog_racing.api.discord import _verify_signature

    timestamp = "1234567890"
    body = '{"type": 1}'

    signature = _sign_request(signing_key, timestamp, body)

    with patch("speedfog_racing.api.discord.settings") as mock_settings:
        mock_settings.discord_public_key = public_key_hex
        assert _verify_signature(signature, timestamp, '{"type": 2}') is False


def test_verify_signature_missing_key():
    """Should return False when discord_public_key is None."""
    from speedfog_racing.api.discord import _verify_signature

    with patch("speedfog_racing.api.discord.settings") as mock_settings:
        mock_settings.discord_public_key = None
        assert _verify_signature("abc", "123", "body") is False


# =============================================================================
# PING interaction
# =============================================================================


@pytest.mark.asyncio
async def test_ping_interaction_returns_pong(signing_key, public_key_hex):
    """PING interaction (type=1) should return PONG (type=1)."""
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.main import app

    body = json.dumps({"type": 1})
    timestamp = "1234567890"
    signature = _sign_request(signing_key, timestamp, body)

    with patch("speedfog_racing.api.discord.settings") as mock_settings:
        mock_settings.discord_public_key = public_key_hex

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/discord/interactions",
                content=body,
                headers={
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": timestamp,
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"type": 1}


@pytest.mark.asyncio
async def test_interaction_rejects_invalid_signature():
    """Invalid signature should return 401."""
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.main import app

    body = json.dumps({"type": 1})

    # Use a valid-looking but wrong public key
    wrong_key = SigningKey.generate()
    wrong_pub_hex = wrong_key.verify_key.encode().hex()

    # Sign with a different key
    other_key = SigningKey.generate()
    signature = _sign_request(other_key, "1234567890", body)

    with patch("speedfog_racing.api.discord.settings") as mock_settings:
        mock_settings.discord_public_key = wrong_pub_hex

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/discord/interactions",
                content=body,
                headers={
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": "1234567890",
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 401


# =============================================================================
# Runner button interactions
# =============================================================================


@pytest.mark.asyncio
async def test_become_runner_button_assigns_role(signing_key, public_key_hex):
    """Clicking 'Become a Runner' should assign the role and return ephemeral message."""
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.main import app

    body = json.dumps(
        {
            "type": 3,
            "data": {"custom_id": "become_runner"},
            "member": {"user": {"id": "user-12345"}},
        }
    )
    timestamp = "1234567890"
    signature = _sign_request(signing_key, timestamp, body)

    with (
        patch("speedfog_racing.api.discord.settings") as mock_settings,
        patch(
            "speedfog_racing.api.discord.assign_runner_role", new_callable=AsyncMock
        ) as mock_assign,
    ):
        mock_settings.discord_public_key = public_key_hex
        mock_assign.return_value = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/discord/interactions",
                content=body,
                headers={
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": timestamp,
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["type"] == 4
            assert "Runner" in data["data"]["content"]
            assert data["data"]["flags"] == 64  # ephemeral
            mock_assign.assert_called_once_with("user-12345")


@pytest.mark.asyncio
async def test_remove_runner_button_removes_role(signing_key, public_key_hex):
    """Clicking 'Remove Runner' should remove the role."""
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.main import app

    body = json.dumps(
        {
            "type": 3,
            "data": {"custom_id": "remove_runner"},
            "member": {"user": {"id": "user-12345"}},
        }
    )
    timestamp = "1234567890"
    signature = _sign_request(signing_key, timestamp, body)

    with (
        patch("speedfog_racing.api.discord.settings") as mock_settings,
        patch(
            "speedfog_racing.api.discord.remove_runner_role", new_callable=AsyncMock
        ) as mock_remove,
    ):
        mock_settings.discord_public_key = public_key_hex
        mock_remove.return_value = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/discord/interactions",
                content=body,
                headers={
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": timestamp,
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["type"] == 4
            assert "removed" in data["data"]["content"].lower()
            mock_remove.assert_called_once_with("user-12345")


# =============================================================================
# Admin setup-runner-message endpoint
# =============================================================================


@pytest.fixture
async def admin_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin_async_session(admin_async_engine):
    return async_sessionmaker(admin_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def admin_user(admin_async_session):
    async with admin_async_session() as db:
        user = User(
            twitch_id=f"admin-{uuid4().hex[:8]}",
            twitch_username="adminuser",
            twitch_display_name="AdminUser",
            api_token=f"admin-token-{uuid4().hex[:8]}",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
def admin_test_client(admin_async_session):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.main import app

    async def override_get_db():
        async with admin_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_setup_runner_endpoint_requires_auth(admin_test_client):
    """POST /api/discord/setup-runner-message without auth should return 401."""
    async with admin_test_client as client:
        resp = await client.post("/api/discord/setup-runner-message")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_setup_runner_endpoint_requires_admin(admin_test_client, admin_async_session):
    """POST /api/discord/setup-runner-message with non-admin should return 403."""
    async with admin_async_session() as db:
        user = User(
            twitch_id=f"user-{uuid4().hex[:8]}",
            twitch_username="regularuser",
            twitch_display_name="RegularUser",
            api_token="regular-user-token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()

    async with admin_test_client as client:
        resp = await client.post(
            "/api/discord/setup-runner-message",
            headers={"Authorization": "Bearer regular-user-token"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_setup_runner_endpoint_success(admin_test_client, admin_user):
    """Admin should be able to post runner message."""
    with patch(
        "speedfog_racing.api.discord.post_runner_message", new_callable=AsyncMock
    ) as mock_post:
        mock_post.return_value = True
        async with admin_test_client as client:
            resp = await client.post(
                "/api/discord/setup-runner-message",
                headers={"Authorization": f"Bearer {admin_user.api_token}"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            mock_post.assert_called_once()
