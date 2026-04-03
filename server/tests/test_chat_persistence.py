"""Tests for chat message persistence."""

import pytest

from speedfog_racing.models import ChatChannel


def test_chat_channel_enum():
    """ChatChannel enum has expected values."""
    assert ChatChannel.PARTICIPANTS == "participants"
    assert ChatChannel.PUBLIC == "public"
    assert len(ChatChannel) == 2


def test_send_chat_message_channel_validation():
    """SendChatMessage validates channel field."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    # Valid channels
    msg = SendChatMessage(channel="participants", message="test")
    assert msg.channel == "participants"

    msg = SendChatMessage(channel="public", message="test")
    assert msg.channel == "public"

    # Invalid channel
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SendChatMessage(channel="invalid", message="test")
