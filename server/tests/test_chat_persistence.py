"""Tests for chat message persistence."""

import pytest

from speedfog_racing.models import ChatChannel


@pytest.mark.asyncio
async def test_chat_channel_enum():
    """ChatChannel enum has expected values."""
    assert ChatChannel.PARTICIPANTS == "participants"
    assert ChatChannel.PUBLIC == "public"
    assert len(ChatChannel) == 2
