"""Tests for Twitch live detection service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedfog_racing.auth import get_app_access_token
from speedfog_racing.services.twitch_live import TwitchLiveService


@pytest.mark.asyncio
async def test_get_app_access_token(monkeypatch):
    """App access token is fetched and cached."""

    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"access_token": "test_token_123", "expires_in": 3600}

        return MockResponse()

    monkeypatch.setattr("speedfog_racing.auth.httpx.AsyncClient.post", mock_post)

    # Clear cache
    get_app_access_token._cache = None

    token = await get_app_access_token()
    assert token == "test_token_123"


@pytest.mark.asyncio
async def test_app_access_token_cached(monkeypatch):
    """Cached token is returned without re-fetching."""
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"access_token": f"token_{call_count}", "expires_in": 3600}

        return MockResponse()

    monkeypatch.setattr("speedfog_racing.auth.httpx.AsyncClient.post", mock_post)

    # Clear cache
    get_app_access_token._cache = None

    token1 = await get_app_access_token()
    token2 = await get_app_access_token()
    assert token1 == token2
    assert call_count == 1


# --- TwitchLiveService ---


@pytest.mark.asyncio
async def test_check_live_status_detects_live():
    """Service detects live users from Twitch API response."""
    service = TwitchLiveService()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"user_login": "player1", "type": "live"},
            {"user_login": "player2", "type": "live"},
        ]
    }

    with patch("speedfog_racing.services.twitch_live.get_app_access_token", return_value="tok"):
        with patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            live_set = await service.check_live_status(["player1", "player2", "player3"])

    assert live_set == {"player1", "player2"}


@pytest.mark.asyncio
async def test_check_live_status_batches_over_100():
    """Usernames are batched in groups of 100."""
    service = TwitchLiveService()

    usernames = [f"user{i}" for i in range(150)]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}

    with patch("speedfog_racing.services.twitch_live.get_app_access_token", return_value="tok"):
        with patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await service.check_live_status(usernames)

    # Should have been called twice: 100 + 50
    assert mock_client.get.call_count == 2
