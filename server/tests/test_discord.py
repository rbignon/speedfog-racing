"""Test Discord webhook notifications."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from speedfog_racing.discord import (
    _discord_api_request,
    _format_igt,
    _send_webhook,
    build_podium,
    notify_race_created,
    notify_race_finished,
    notify_race_started,
)


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


@pytest.fixture
def created_kwargs():
    return {
        "race_name": "Sunday Sprint #3",
        "race_id": "abc-123",
        "pool_name": "sprint",
        "organizer_name": "TestOrganizer",
        "organizer_avatar_url": "https://example.com/avatar.png",
    }


@pytest.fixture
def finished_kwargs():
    return {
        "race_name": "Sunday Sprint #3",
        "race_id": "abc-123",
        "pool_name": "sprint",
        "participant_count": 4,
        "podium": [
            {"name": "Player1", "igt": "12:34"},
            {"name": "Player2", "igt": "15:00"},
            {"name": "Player3", "igt": "18:22"},
        ],
    }


# --- _send_webhook with content and allowed_mentions ---


@pytest.mark.asyncio
async def test_send_webhook_with_content_and_allowed_mentions():
    """Should include content and allowed_mentions alongside embeds."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        embed = {"title": "Test", "color": 0xF97316}
        await _send_webhook(
            embed,
            content="<@&123>",
            allowed_mentions={"roles": ["123"]},
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["content"] == "<@&123>"
        assert payload["allowed_mentions"] == {"roles": ["123"]}
        assert payload["embeds"] == [embed]


@pytest.mark.asyncio
async def test_send_webhook_without_content():
    """Should omit content and allowed_mentions when not provided."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        embed = {"title": "Test", "color": 0xF97316}
        await _send_webhook(embed)

        payload = mock_client.post.call_args[1]["json"]
        assert "content" not in payload
        assert "allowed_mentions" not in payload
        assert payload["embeds"] == [embed]


# --- _send_webhook / noop ---


@pytest.mark.asyncio
async def test_noop_when_no_webhook(race_kwargs):
    """Should return immediately when webhook URL is not configured."""
    with patch("speedfog_racing.discord.settings") as mock_settings:
        mock_settings.discord_webhook_url = None
        await notify_race_started(**race_kwargs)
        await notify_race_created(
            **{k: v for k, v in race_kwargs.items() if k != "participant_count"}
        )
        # No exception, no HTTP call


# --- notify_race_created (runner role mention) ---


@pytest.mark.asyncio
async def test_race_created_mentions_runner_role(created_kwargs):
    """Should include @Runner role mention when discord_runner_role_id is set."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"
        mock_settings.discord_runner_role_id = "999"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_created(**created_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["content"] == "<@&999>"
        assert payload["allowed_mentions"] == {"roles": ["999"]}


@pytest.mark.asyncio
async def test_race_created_no_mention_without_role(created_kwargs):
    """Should not include role mention when discord_runner_role_id is None."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"
        mock_settings.discord_runner_role_id = None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_created(**created_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        assert "content" not in payload
        assert "allowed_mentions" not in payload


# --- notify_race_created ---


@pytest.mark.asyncio
async def test_sends_created_notification(created_kwargs):
    """Should POST a Discord embed for race creation."""
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

        await notify_race_created(**created_kwargs)

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]

        embed = payload["embeds"][0]
        assert "New Race" in embed["title"]
        assert "Sunday Sprint #3" in embed["title"]
        assert embed["color"] == 0xF97316  # orange
        assert embed["url"] == "https://speedfog.malenia.win/race/abc-123"

        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["Pool"] == "Sprint"
        assert fields["Organizer"] == "TestOrganizer"
        assert "Scheduled" not in fields


@pytest.mark.asyncio
async def test_created_with_scheduled_at(created_kwargs):
    """Should include scheduled field when provided."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    created_kwargs["scheduled_at"] = "<t:1740070800:F>"

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_created(**created_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        assert fields["Scheduled"] == "<t:1740070800:F>"


@pytest.mark.asyncio
async def test_created_training_notification(created_kwargs):
    """Should use training styling for training pools."""
    mock_response = AsyncMock()
    mock_response.status_code = 204
    created_kwargs["pool_name"] = "training_hardcore"

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.base_url = "https://speedfog.malenia.win"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await notify_race_created(**created_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "New Solo" in embed["title"]
        assert embed["color"] == 0x3B82F6  # blue


# --- notify_race_started ---


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
        assert "Started" in embed["title"]
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
        assert "Solo Started" in embed["title"]
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


# --- notify_race_finished ---


@pytest.mark.asyncio
async def test_sends_finished_notification(finished_kwargs):
    """Should POST a Discord embed for race finish with podium."""
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

        await notify_race_finished(**finished_kwargs)

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]

        embed = payload["embeds"][0]
        assert "Finished" in embed["title"]
        assert embed["color"] == 0x22C55E  # green

        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "Player1" in fields["Podium"]
        assert "Player2" in fields["Podium"]
        assert "Player3" in fields["Podium"]
        assert fields["Participants"] == "4"


@pytest.mark.asyncio
async def test_finished_no_finishers(finished_kwargs):
    """Should show 'No finishers' when podium is empty."""
    finished_kwargs["podium"] = []
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

        await notify_race_finished(**finished_kwargs)

        payload = mock_client.post.call_args[1]["json"]
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        assert fields["Podium"] == "No finishers"


# --- Error handling ---


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


# --- Discord bot API helper ---


@pytest.mark.asyncio
async def test_discord_api_request_sends_with_bot_auth():
    """Should send authenticated request to Discord API."""
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "123"}

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_bot_token = "test-token"

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _discord_api_request(
            "POST", "/guilds/456/scheduled-events", json={"name": "Test"}
        )

        assert result == {"id": "123"}
        mock_client.request.assert_called_once_with(
            "POST",
            "https://discord.com/api/v10/guilds/456/scheduled-events",
            json={"name": "Test"},
            headers={"Authorization": "Bot test-token"},
        )


@pytest.mark.asyncio
async def test_discord_api_request_noop_without_token():
    """Should return None when bot token is not configured."""
    with patch("speedfog_racing.discord.settings") as mock_settings:
        mock_settings.discord_bot_token = None
        result = await _discord_api_request("GET", "/some/path")
        assert result is None


@pytest.mark.asyncio
async def test_discord_api_request_returns_none_on_error():
    """Should log and return None on HTTP errors."""
    mock_response = AsyncMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
        patch("speedfog_racing.discord.logger") as mock_logger,
    ):
        mock_settings.discord_bot_token = "test-token"

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _discord_api_request("POST", "/test")
        assert result is None
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_discord_api_request_returns_empty_on_204():
    """Should return empty dict on 204 No Content."""
    mock_response = AsyncMock()
    mock_response.status_code = 204

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.discord_bot_token = "test-token"

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _discord_api_request("DELETE", "/test")
        assert result == {}


@pytest.mark.asyncio
async def test_discord_api_request_handles_network_error():
    """Should log and return None on network error."""
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client_cls,
        patch("speedfog_racing.discord.logger") as mock_logger,
    ):
        mock_settings.discord_bot_token = "test-token"

        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await _discord_api_request("GET", "/test")
        assert result is None
        mock_logger.warning.assert_called_once()


# --- Helpers ---


def test_format_igt():
    """Should format IGT milliseconds correctly."""
    assert _format_igt(0) == "0:00"
    assert _format_igt(61000) == "1:01"
    assert _format_igt(754000) == "12:34"
    assert _format_igt(3661000) == "1:01:01"


def test_build_podium():
    """Should extract top 3 finishers sorted by IGT."""
    from unittest.mock import MagicMock

    from speedfog_racing.models import ParticipantStatus

    def make_participant(name: str, igt: int, finished: bool = True) -> MagicMock:
        p = MagicMock()
        p.status = ParticipantStatus.FINISHED if finished else ParticipantStatus.PLAYING
        p.igt_ms = igt
        p.user.twitch_display_name = name
        p.user.twitch_username = name.lower()
        return p

    participants = [
        make_participant("Third", 300000),
        make_participant("First", 100000),
        make_participant("NotFinished", 50000, finished=False),
        make_participant("Second", 200000),
        make_participant("Fourth", 400000),
    ]

    result = build_podium(participants)
    assert len(result) == 3
    assert result[0]["name"] == "First"
    assert result[1]["name"] == "Second"
    assert result[2]["name"] == "Third"
