"""Test Discord interaction endpoint (signature verification + handlers)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from nacl.signing import SigningKey


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
