"""Tests for Twitch live detection service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedfog_racing.auth import get_app_access_token, invalidate_app_access_token
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


# --- Token invalidation ---


@pytest.mark.asyncio
async def test_invalidate_app_access_token(monkeypatch):
    """Invalidating the cache forces a fresh fetch on next call."""
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

    get_app_access_token._cache = None

    token1 = await get_app_access_token()
    assert token1 == "token_1"

    invalidate_app_access_token()

    token2 = await get_app_access_token()
    assert token2 == "token_2"
    assert call_count == 2


# --- 401 retry in check_live_status ---


def _make_mock_response(status_code, data=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"data": data or []}
    return resp


@pytest.mark.asyncio
async def test_check_live_status_retries_on_401():
    """On 401, the token is refreshed and the batch is retried successfully."""
    service = TwitchLiveService()

    resp_401 = _make_mock_response(401)
    resp_200 = _make_mock_response(200, [{"user_login": "player1", "type": "live"}])

    token_calls = []

    async def mock_get_token():
        token_calls.append(1)
        return f"token_{len(token_calls)}"

    with (
        patch(
            "speedfog_racing.services.twitch_live.get_app_access_token", side_effect=mock_get_token
        ),
        patch(
            "speedfog_racing.services.twitch_live.invalidate_app_access_token"
        ) as mock_invalidate,
        patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.get.side_effect = [resp_401, resp_200]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        live = await service.check_live_status(["player1"])

    assert live == {"player1"}
    mock_invalidate.assert_called_once()
    assert mock_client.get.call_count == 2
    # First call used token_1, retry used token_2
    assert len(token_calls) == 2


@pytest.mark.asyncio
async def test_check_live_status_401_retry_also_fails():
    """If the retry after 401 also fails, no crash, empty result."""
    service = TwitchLiveService()

    resp_401_a = _make_mock_response(401)
    resp_401_b = _make_mock_response(401)

    async def mock_get_token():
        return "token"

    with (
        patch(
            "speedfog_racing.services.twitch_live.get_app_access_token", side_effect=mock_get_token
        ),
        patch("speedfog_racing.services.twitch_live.invalidate_app_access_token"),
        patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.get.side_effect = [resp_401_a, resp_401_b]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        live = await service.check_live_status(["player1"])

    assert live == set()
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_check_live_status_401_retries_only_once():
    """A second batch hitting 401 after a retry already happened is not retried."""
    service = TwitchLiveService()

    resp_401 = _make_mock_response(401)
    resp_200_empty = _make_mock_response(200, [])

    usernames = [f"user{i}" for i in range(150)]  # 2 batches: 100 + 50

    async def mock_get_token():
        return "token"

    with (
        patch(
            "speedfog_racing.services.twitch_live.get_app_access_token", side_effect=mock_get_token
        ),
        patch("speedfog_racing.services.twitch_live.invalidate_app_access_token"),
        patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        # Batch 1: 401 -> retry succeeds (200)
        # Batch 2: 401 -> no retry (already retried)
        mock_client.get.side_effect = [resp_401, resp_200_empty, resp_401]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        live = await service.check_live_status(usernames)

    assert live == set()
    # 3 calls: batch1 (401) + batch1 retry (200) + batch2 (401, no retry)
    assert mock_client.get.call_count == 3
