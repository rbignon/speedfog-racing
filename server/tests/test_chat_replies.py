"""Tests for reply-to-message on the chat send path and history."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import RaceRoom, SpectatorConnection, manager
from speedfog_racing.websocket.race.spectator import (
    MAX_CHAT_HISTORY_MESSAGES,
    RaceSpectatorHandler,
    load_chat_history,
)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


CHAT_INFO = {
    "username": "alice",
    "display_name": "Alice",
    "avatar_url": None,
    "role": "participant",
    "dominant_trait": None,
    "equipped_badge_id": None,
    "equipped_name_template_id": None,
}


async def _seed_race(session_maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Race + organizer + one participant user.

    Returns ``(race_id, organizer_id, participant_user_id)``.
    """
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"org-{uuid.uuid4()}",
            twitch_username=f"org-{uuid.uuid4().hex[:6]}",
            twitch_display_name="Org",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id=f"p-{uuid.uuid4()}",
            twitch_username="alice",
            twitch_display_name="Alice",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()
        race = Race(
            name="R",
            organizer_id=organizer.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            late_join_window_minutes=30,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=player.id, status=ParticipantStatus.PLAYING))
        await db.commit()
        return race.id, organizer.id, player.id


async def _add_message(
    session_maker,
    race_id: uuid.UUID,
    user_id: uuid.UUID | None,
    text: str,
    channel: ChatChannel = ChatChannel.PARTICIPANTS,
    created_at: datetime | None = None,
) -> uuid.UUID:
    async with session_maker() as db:
        msg = ChatMessage(
            race_id=race_id,
            channel=channel,
            user_id=user_id,
            message=text,
            created_at=created_at or datetime.now(UTC),
        )
        db.add(msg)
        await db.commit()
        return msg.id


def _handler_with_room(
    session_maker, race_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[RaceSpectatorHandler, SpectatorConnection]:
    """Authenticated participant handler + a listening room spectator.

    The caller must ``manager.rooms.pop(race_id, None)`` when done.
    """
    handler = RaceSpectatorHandler(AsyncMock(), race_id, session_maker)
    handler._conn.user_id = user_id
    handler._conn.role = "participant"
    handler._chat_info = dict(CHAT_INFO)

    room = RaceRoom(race_id=race_id)
    listener = SpectatorConnection(websocket=AsyncMock(), user_id=uuid.uuid4(), role="participant")
    room.spectators[listener.connection_id] = listener
    manager.rooms[race_id] = room
    return handler, listener


def _sent_chat_messages(listener: SpectatorConnection) -> list[dict]:
    return [
        json.loads(call.args[0])
        for call in listener.websocket.send_text.await_args_list
        if json.loads(call.args[0]).get("type") == "chat_message"
    ]


@pytest.mark.asyncio
async def test_reply_broadcasts_context_and_persists_link(session_maker):
    race_id, organizer_id, player_id = await _seed_race(session_maker)
    original_id = await _add_message(session_maker, race_id, organizer_id, "first!")
    handler, listener = _handler_with_room(session_maker, race_id, player_id)
    try:
        await handler._handle_chat(
            {
                "type": "chat",
                "channel": "participants",
                "message": "answering",
                "reply_to": str(original_id),
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    sent = _sent_chat_messages(listener)
    assert len(sent) == 1
    msg = sent[0]
    assert msg["id"] is not None
    assert msg["reply_to"]["id"] == str(original_id)
    assert msg["reply_to"]["snippet"] == "first!"

    async with session_maker() as db:
        row = (
            await db.execute(select(ChatMessage).where(ChatMessage.message == "answering"))
        ).scalar_one()
        assert row.reply_to_id == original_id


@pytest.mark.asyncio
async def test_reply_snippet_truncated_to_120_chars(session_maker):
    race_id, organizer_id, player_id = await _seed_race(session_maker)
    original_id = await _add_message(session_maker, race_id, organizer_id, "x" * 500)
    handler, listener = _handler_with_room(session_maker, race_id, player_id)
    try:
        await handler._handle_chat(
            {
                "type": "chat",
                "channel": "participants",
                "message": "long quote",
                "reply_to": str(original_id),
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    msg = _sent_chat_messages(listener)[0]
    assert msg["reply_to"]["snippet"] == "x" * 120


@pytest.mark.asyncio
async def test_reply_to_other_channel_drops_link_but_delivers(session_maker):
    race_id, organizer_id, player_id = await _seed_race(session_maker)
    original_id = await _add_message(
        session_maker, race_id, organizer_id, "public msg", channel=ChatChannel.PUBLIC
    )
    handler, listener = _handler_with_room(session_maker, race_id, player_id)
    try:
        await handler._handle_chat(
            {
                "type": "chat",
                "channel": "participants",
                "message": "cross-channel",
                "reply_to": str(original_id),
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    msg = _sent_chat_messages(listener)[0]
    assert msg["reply_to"] is None
    async with session_maker() as db:
        row = (
            await db.execute(select(ChatMessage).where(ChatMessage.message == "cross-channel"))
        ).scalar_one()
        assert row.reply_to_id is None


@pytest.mark.asyncio
async def test_reply_to_system_message_drops_link(session_maker):
    race_id, _, player_id = await _seed_race(session_maker)
    system_id = await _add_message(session_maker, race_id, None, "Race started")
    handler, listener = _handler_with_room(session_maker, race_id, player_id)
    try:
        await handler._handle_chat(
            {
                "type": "chat",
                "channel": "participants",
                "message": "to system",
                "reply_to": str(system_id),
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    assert _sent_chat_messages(listener)[0]["reply_to"] is None


@pytest.mark.asyncio
async def test_history_rebuilds_reply_context_for_original_outside_window(session_maker):
    """The quoted original is older than the history window: the reply's
    context must still be present while the original itself is not."""
    race_id, organizer_id, _ = await _seed_race(session_maker)
    base = datetime.now(UTC) - timedelta(hours=1)
    original_id = await _add_message(
        session_maker, race_id, organizer_id, "ancient", created_at=base
    )
    for i in range(MAX_CHAT_HISTORY_MESSAGES):
        await _add_message(
            session_maker,
            race_id,
            organizer_id,
            f"filler {i}",
            created_at=base + timedelta(seconds=i + 1),
        )
    async with session_maker() as db:
        reply = ChatMessage(
            race_id=race_id,
            channel=ChatChannel.PARTICIPANTS,
            user_id=organizer_id,
            message="late reply",
            reply_to_id=original_id,
            created_at=base + timedelta(seconds=MAX_CHAT_HISTORY_MESSAGES + 2),
        )
        db.add(reply)
        await db.commit()
        race = await db.get(Race, race_id)

    history = await load_chat_history(session_maker, race_id, race, ChatChannel.PARTICIPANTS)
    payload = json.loads(history.model_dump_json())
    ids = [m["id"] for m in payload["messages"]]
    assert str(original_id) not in ids  # outside the window
    reply_msg = next(m for m in payload["messages"] if m["message"] == "late reply")
    assert reply_msg["reply_to"]["id"] == str(original_id)
    assert reply_msg["reply_to"]["snippet"] == "ancient"
    assert all(m["id"] is not None for m in payload["messages"])


@pytest.mark.asyncio
async def test_history_caps_at_most_recent_messages(session_maker):
    """More messages than the cap: history keeps the most recent cap-sized
    window, in chronological order (oldest of the kept set first)."""
    race_id, organizer_id, _ = await _seed_race(session_maker)
    total = MAX_CHAT_HISTORY_MESSAGES + 10
    base = datetime.now(UTC) - timedelta(seconds=total)
    for i in range(total):
        await _add_message(
            session_maker,
            race_id,
            organizer_id,
            f"msg-{i:03d}",
            created_at=base + timedelta(seconds=i),
        )
    async with session_maker() as db:
        race = await db.get(Race, race_id)

    history = await load_chat_history(session_maker, race_id, race, ChatChannel.PARTICIPANTS)
    assert len(history.messages) == MAX_CHAT_HISTORY_MESSAGES
    assert history.messages[0].message == f"msg-{total - MAX_CHAT_HISTORY_MESSAGES:03d}"
    assert history.messages[-1].message == f"msg-{total - 1:03d}"
