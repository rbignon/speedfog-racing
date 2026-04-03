"""Tests for chat WebSocket messages."""

import pytest


def test_chat_message_schema():
    """ChatBroadcastMessage serializes correctly with channel."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage

    msg = ChatBroadcastMessage(
        channel="participants",
        username="testuser",
        display_name="TestUser",
        avatar_url=None,
        role="participant",
        dominant_trait="rusher",
        message="Hello race!",
        timestamp="2026-03-23T12:00:00+00:00",
    )
    data = msg.model_dump()
    assert data["type"] == "chat_message"
    assert data["channel"] == "participants"
    assert data["username"] == "testuser"
    assert data["message"] == "Hello race!"
    assert data["role"] == "participant"
    assert data["dominant_trait"] == "rusher"


def test_send_chat_message_schema():
    """SendChatMessage validates correctly with channel."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    msg = SendChatMessage(channel="public", message="Hello!")
    assert msg.type == "chat"
    assert msg.channel == "public"
    assert msg.message == "Hello!"


def test_send_chat_message_max_length():
    """SendChatMessage rejects messages over 500 chars."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(channel="public", message="x" * 501)


def test_send_chat_message_invalid_channel():
    """SendChatMessage rejects invalid channel names."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(channel="spoiler", message="Hello!")


def test_chat_history_message_schema():
    """ChatHistoryMessage serializes correctly."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage, ChatHistoryMessage

    history = ChatHistoryMessage(
        channel="participants",
        messages=[
            ChatBroadcastMessage(
                channel="participants",
                username="user1",
                display_name="User 1",
                avatar_url=None,
                role="participant",
                dominant_trait=None,
                message="Ready!",
                timestamp="2026-04-03T12:00:00+00:00",
            )
        ],
    )
    data = history.model_dump()
    assert data["type"] == "chat_history"
    assert data["channel"] == "participants"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["username"] == "user1"
