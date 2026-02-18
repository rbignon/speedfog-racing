"""Test Discord webhook notifications."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from speedfog_racing.discord import notify_race_started


@pytest.fixture
def race_kwargs():
    return {
        "race_name": "Sunday Sprint #3",
        "race_id": "abc-123",
        "pool_name": "sprint",
        "participant_count": 4,
        "organizer_name": "TestOrganizer",
        "organizer_avatar_url": "https://example.com/avatar.png",
    }


@pytest.mark.asyncio
async def test_noop_when_no_webhook(race_kwargs):
    """Should return immediately when webhook URL is not configured."""
    with patch("speedfog_racing.discord.settings") as mock_settings:
        mock_settings.discord_webhook_url = None
        await notify_race_started(**race_kwargs)
        # No exception, no HTTP call


@pytest.mark.asyncio
async def test_sends_race_notification(race_kwargs):
    """Should POST a Discord embed for a race."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_started(**race_kwargs)

        mock_client.post.assert_called_once()
        url, kwargs = mock_client.post.call_args
        payload = kwargs["json"]

        embed = payload["embeds"][0]
        assert embed["title"] == "Race: Sunday Sprint #3"
        assert embed["color"] == 0xF97316  # orange
        assert embed["url"] == "https://speedfog.malenia.win/race/abc-123"
        assert embed["thumbnail"]["url"] == "https://example.com/avatar.png"

        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["Pool"] == "Sprint"
        assert fields["Participants"] == "4"
        assert fields["Organizer"] == "TestOrganizer"


@pytest.mark.asyncio
async def test_sends_training_notification(race_kwargs):
    """Should POST a Discord embed with training styling."""
    race_kwargs["pool_name"] = "training_hardcore"
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_started(**race_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert embed["title"] == "Training: Sunday Sprint #3"
        assert embed["color"] == 0x3B82F6  # blue
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["Pool"] == "Hardcore"


@pytest.mark.asyncio
async def test_no_avatar(race_kwargs):
    """Should omit thumbnail when no avatar URL."""
    race_kwargs["organizer_avatar_url"] = None
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_started(**race_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "thumbnail" not in embed


@pytest.mark.asyncio
async def test_rate_limit_logged(race_kwargs):
    """Should log retry-after on 429 response."""
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "60"}

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
        patch("speedfog_racing.discord.logger") as mock_logger,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_started(**race_kwargs)

        mock_logger.warning.assert_called_once()
        assert "rate limited" in mock_logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_http_error_suppressed(race_kwargs):
    """Should log but not raise on HTTP errors."""
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # Should not raise
        await notify_race_started(**race_kwargs)
