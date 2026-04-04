"""Tests for training live Discord notifications."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedfog_racing.discord import (
    TRAINING_NOTIF_COOLDOWN_SECONDS,
    _training_notif_cooldowns,
    send_training_live_notification,
)


@pytest.fixture(autouse=True)
def clear_cooldowns():
    """Reset cooldown dict between tests."""
    _training_notif_cooldowns.clear()
    yield
    _training_notif_cooldowns.clear()


def _make_user(
    user_id: int = 1,
    username: str = "testplayer",
    avatar_url: str | None = "https://example.com/avatar.png",
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.twitch_username = username
    user.twitch_display_name = username.capitalize()
    user.twitch_avatar_url = avatar_url
    return user


@pytest.mark.asyncio
async def test_noop_when_no_training_webhook():
    """Should return immediately when training webhook URL is not configured."""
    user = _make_user()
    with patch("speedfog_racing.discord.settings") as mock_settings:
        mock_settings.discord_training_webhook_url = None
        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )
    # No exception, no HTTP call


@pytest.mark.asyncio
async def test_noop_when_user_not_live():
    """Should not send webhook when user is not live on Twitch."""
    user = _make_user()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook") as mock_send,
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_live.check_live_status = AsyncMock(return_value=set())

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_sends_notification_when_live():
    """Should send webhook when user is live on Twitch."""
    user = _make_user()
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_called_once()
        embed = mock_send.call_args[0][0]
        assert "testplayer" in embed["title"].lower() or "Testplayer" in embed["title"]
        assert embed["color"] == 0x3B82F6
        assert "session-123" in embed["url"]


@pytest.mark.asyncio
async def test_cooldown_blocks_duplicate():
    """Should not send when cooldown is active for user."""
    user = _make_user()
    _training_notif_cooldowns[user.id] = time.monotonic()

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook") as mock_send,
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_cooldown_allows_after_expiry():
    """Should send when cooldown has expired."""
    user = _make_user()
    _training_notif_cooldowns[user.id] = time.monotonic() - TRAINING_NOTIF_COOLDOWN_SECONDS - 1

    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_embed_contains_pool_and_links():
    """Should include pool name, stream URL, and spectator URL in embed."""
    user = _make_user()
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-456",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "Standard" in fields["Pool"]
        assert "twitch.tv/testplayer" in fields["Stream"]
        assert "session-456" in embed["url"]


@pytest.mark.asyncio
async def test_embed_has_avatar_thumbnail():
    """Should include avatar as thumbnail when available."""
    user = _make_user(avatar_url="https://example.com/avatar.png")
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        assert embed["thumbnail"]["url"] == "https://example.com/avatar.png"


@pytest.mark.asyncio
async def test_no_thumbnail_without_avatar():
    """Should omit thumbnail when user has no avatar."""
    user = _make_user(avatar_url=None)
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        assert "thumbnail" not in embed
