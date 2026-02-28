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


@pytest.mark.asyncio
async def test_poll_once_broadcasts_on_change():
    """poll_once broadcasts leaderboard_update when live status changes."""
    import uuid

    service = TwitchLiveService()
    service.live_usernames = set()  # start with nobody live

    race_id = uuid.uuid4()

    # Mock session_maker that returns race data
    mock_session = AsyncMock()
    mock_result = MagicMock()

    mock_user = MagicMock()
    mock_user.twitch_username = "streamer1"

    mock_participant = MagicMock()
    mock_participant.user = mock_user

    mock_race = MagicMock()
    mock_race.id = race_id
    mock_race.participants = [mock_participant]
    mock_race.casters = []
    mock_race.seed = None

    mock_result.scalars.return_value.all.return_value = [mock_race]
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    # Mock ws_manager
    mock_ws_manager = AsyncMock()

    # Mock check_live_status to return streamer1 as live
    with patch.object(service, "check_live_status", return_value={"streamer1"}):
        await service.poll_once(mock_session_maker, ws_manager=mock_ws_manager)

    # Should have broadcast because streamer1 went from offline to live
    assert mock_ws_manager.broadcast_leaderboard.call_count == 1


@pytest.mark.asyncio
async def test_poll_once_no_broadcast_when_unchanged():
    """poll_once does not broadcast when live status is unchanged."""
    service = TwitchLiveService()
    service.live_usernames = {"streamer1"}  # already live

    mock_session = AsyncMock()
    mock_result = MagicMock()

    mock_user = MagicMock()
    mock_user.twitch_username = "streamer1"

    mock_participant = MagicMock()
    mock_participant.user = mock_user

    mock_race = MagicMock()
    mock_race.id = __import__("uuid").uuid4()
    mock_race.participants = [mock_participant]
    mock_race.casters = []

    mock_result.scalars.return_value.all.return_value = [mock_race]
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_ws_manager = AsyncMock()

    with patch.object(service, "check_live_status", return_value={"streamer1"}):
        await service.poll_once(mock_session_maker, ws_manager=mock_ws_manager)

    # No change, so no broadcast
    mock_ws_manager.broadcast_leaderboard.assert_not_called()
