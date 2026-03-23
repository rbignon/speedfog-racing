"""Tests for chat WebSocket messages."""

import pytest


@pytest.mark.asyncio
async def test_chat_message_schema():
    """ChatBroadcastMessage serializes correctly."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage

    msg = ChatBroadcastMessage(
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
    assert data["username"] == "testuser"
    assert data["message"] == "Hello race!"
    assert data["role"] == "participant"
    assert data["dominant_trait"] == "rusher"


@pytest.mark.asyncio
async def test_send_chat_message_schema():
    """SendChatMessage validates correctly."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    msg = SendChatMessage(message="Hello!")
    assert msg.type == "chat"
    assert msg.message == "Hello!"


@pytest.mark.asyncio
async def test_send_chat_message_max_length():
    """SendChatMessage rejects messages over 500 chars."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(message="x" * 501)
