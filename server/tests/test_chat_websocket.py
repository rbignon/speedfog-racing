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
    # Equipped reward ids default to None and round-trip into the payload so
    # the frontend can render name templates and badges without a separate
    # lookup.
    assert data["equipped_badge_id"] is None
    assert data["equipped_name_template_id"] is None


def test_chat_message_schema_carries_equipped_rewards():
    """ChatBroadcastMessage forwards equipped badge and template ids."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage

    msg = ChatBroadcastMessage(
        channel="public",
        username="champ",
        display_name="Champ",
        avatar_url=None,
        role="participant",
        dominant_trait=None,
        equipped_badge_id="early_adopter",
        equipped_name_template_id="daily_crown",
        message="gg",
        timestamp="2026-04-30T12:00:00+00:00",
    )
    data = msg.model_dump()
    assert data["equipped_badge_id"] == "early_adopter"
    assert data["equipped_name_template_id"] == "daily_crown"


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


def test_chat_reaction_message_rejects_unknown_emoji():
    """The emoji code is a closed set; anything else is a validation error."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import ChatReactionMessage

    with pytest.raises(ValidationError):
        ChatReactionMessage(
            channel="public",
            message_id="7c9c54d1-93f8-4f1b-9df5-8a4c4a1f0b1e",
            emoji="heart",
        )


def test_chat_reaction_message_rejects_invalid_channel():
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import ChatReactionMessage

    with pytest.raises(ValidationError):
        ChatReactionMessage(
            channel="spoiler",
            message_id="7c9c54d1-93f8-4f1b-9df5-8a4c4a1f0b1e",
            emoji="laugh",
        )


def test_send_chat_message_rejects_malformed_reply_to():
    """reply_to must parse as a UUID when present."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(channel="public", message="hi", reply_to="not-a-uuid")


def test_reaction_emojis_match_validation_pattern():
    """The pattern on ChatReactionMessage.emoji accepts exactly REACTION_EMOJIS."""
    from speedfog_racing.websocket.schemas import REACTION_EMOJIS, ChatReactionMessage

    for code in REACTION_EMOJIS:
        msg = ChatReactionMessage(
            channel="public",
            message_id="7c9c54d1-93f8-4f1b-9df5-8a4c4a1f0b1e",
            emoji=code,
        )
        assert msg.emoji == code
