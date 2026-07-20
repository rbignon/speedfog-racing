"""Tests for chat message reactions (model + WebSocket handler)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    ChatMessageReaction,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import RaceRoom, SpectatorConnection, manager
from speedfog_racing.websocket.race.spectator import (
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


async def _seed_message(session_maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert organizer + race + one public message.

    Returns ``(race_id, user_id, message_id)``.
    """
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"org-{uuid.uuid4()}",
            twitch_username=f"org-{uuid.uuid4().hex[:6]}",
            twitch_display_name="Org",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        db.add(organizer)
        await db.flush()
        race = Race(
            name="R",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.flush()
        msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PUBLIC,
            user_id=organizer.id,
            message="gg",
        )
        db.add(msg)
        await db.commit()
        return race.id, organizer.id, msg.id


@pytest.mark.asyncio
async def test_duplicate_reaction_rejected_by_composite_pk(session_maker):
    """The (message_id, user_id, emoji) PK enforces one reaction per user/emoji."""
    _, user_id, message_id = await _seed_message(session_maker)

    async with session_maker() as db:
        db.add(ChatMessageReaction(message_id=message_id, user_id=user_id, emoji="laugh"))
        await db.commit()

    async with session_maker() as db:
        db.add(ChatMessageReaction(message_id=message_id, user_id=user_id, emoji="laugh"))
        with pytest.raises(IntegrityError):
            await db.commit()


def _reaction_handler(
    session_maker, race_id: uuid.UUID, user_id: uuid.UUID | None
) -> tuple[RaceSpectatorHandler, SpectatorConnection]:
    """Handler + listening room spectator for reaction tests.

    The caller must ``manager.rooms.pop(race_id, None)`` when done.
    """
    handler = RaceSpectatorHandler(AsyncMock(), race_id, session_maker)
    handler._conn.user_id = user_id
    room = RaceRoom(race_id=race_id)
    listener = SpectatorConnection(websocket=AsyncMock(), user_id=uuid.uuid4())
    room.spectators[listener.connection_id] = listener
    manager.rooms[race_id] = room
    return handler, listener


def _sent_reaction_updates(listener: SpectatorConnection) -> list[dict]:
    return [
        json.loads(call.args[0])
        for call in listener.websocket.send_text.await_args_list
        if json.loads(call.args[0]).get("type") == "chat_reaction_update"
    ]


@pytest.mark.asyncio
async def test_reaction_toggle_on_then_off(session_maker):
    """First chat_reaction inserts and broadcasts; the same one removes."""
    race_id, user_id, message_id = await _seed_message(session_maker)
    handler, listener = _reaction_handler(session_maker, race_id, user_id)
    payload = {
        "type": "chat_reaction",
        "channel": "public",
        "message_id": str(message_id),
        "emoji": "laugh",
    }
    try:
        await handler._handle_chat_reaction(payload)
        await handler._handle_chat_reaction(payload)
    finally:
        manager.rooms.pop(race_id, None)

    updates = _sent_reaction_updates(listener)
    assert len(updates) == 2
    assert updates[0]["message_id"] == str(message_id)
    first = updates[0]["reactions"]
    assert len(first) == 1
    assert first[0]["emoji"] == "laugh"
    assert len(first[0]["usernames"]) == 1
    assert updates[1]["reactions"] == []

    async with session_maker() as db:
        rows = (await db.execute(select(ChatMessageReaction))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_reaction_anonymous_ignored(session_maker):
    race_id, _, message_id = await _seed_message(session_maker)
    handler, listener = _reaction_handler(session_maker, race_id, None)
    try:
        await handler._handle_chat_reaction(
            {
                "type": "chat_reaction",
                "channel": "public",
                "message_id": str(message_id),
                "emoji": "laugh",
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    assert _sent_reaction_updates(listener) == []


@pytest.mark.asyncio
async def test_reaction_rejected_for_active_racer_on_public(session_maker):
    """Active participant: public channel is locked, reaction ignored."""
    race_id, organizer_id, message_id = await _seed_message(session_maker)
    async with session_maker() as db:
        race = await db.get(Race, race_id)
        race.status = RaceStatus.RUNNING
        race.started_at = datetime.now(UTC) - timedelta(minutes=5)
        race.late_join_window_minutes = 30
        racer = User(
            twitch_id=f"racer-{uuid.uuid4()}",
            twitch_username="racer",
            twitch_display_name="Racer",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add(racer)
        await db.flush()
        db.add(Participant(race_id=race_id, user_id=racer.id, status=ParticipantStatus.PLAYING))
        await db.commit()
        racer_id = racer.id

    handler, listener = _reaction_handler(session_maker, race_id, racer_id)
    handler._conn.role = "participant"
    handler._conn.participant_status = ParticipantStatus.PLAYING
    try:
        await handler._handle_chat_reaction(
            {
                "type": "chat_reaction",
                "channel": "public",
                "message_id": str(message_id),
                "emoji": "thumbs_up",
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    assert _sent_reaction_updates(listener) == []


@pytest.mark.asyncio
async def test_reaction_on_foreign_race_message_ignored(session_maker):
    race_id, user_id, _ = await _seed_message(session_maker)
    _, _, other_message_id = await _seed_message(session_maker)  # different race
    handler, listener = _reaction_handler(session_maker, race_id, user_id)
    try:
        await handler._handle_chat_reaction(
            {
                "type": "chat_reaction",
                "channel": "public",
                "message_id": str(other_message_id),
                "emoji": "cry",
            }
        )
    finally:
        manager.rooms.pop(race_id, None)

    assert _sent_reaction_updates(listener) == []
    async with session_maker() as db:
        assert (await db.execute(select(ChatMessageReaction))).scalars().all() == []


@pytest.mark.asyncio
async def test_history_carries_reaction_aggregates_in_emoji_order(session_maker):
    race_id, user_id, message_id = await _seed_message(session_maker)
    async with session_maker() as db:
        other = User(
            twitch_id=f"u2-{uuid.uuid4()}",
            twitch_username="bob",
            twitch_display_name="Bob",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add(other)
        await db.flush()
        db.add_all(
            [
                ChatMessageReaction(message_id=message_id, user_id=user_id, emoji="cry"),
                ChatMessageReaction(message_id=message_id, user_id=other.id, emoji="cry"),
                ChatMessageReaction(message_id=message_id, user_id=other.id, emoji="thumbs_up"),
            ]
        )
        await db.commit()
        race = await db.get(Race, race_id)

    history = await load_chat_history(session_maker, race_id, race, ChatChannel.PUBLIC)
    payload = json.loads(history.model_dump_json())
    msg = next(m for m in payload["messages"] if m["id"] == str(message_id))
    # Fixed REACTION_EMOJIS order: thumbs_up before cry.
    assert [r["emoji"] for r in msg["reactions"]] == ["thumbs_up", "cry"]
    cry = msg["reactions"][1]
    assert sorted(cry["usernames"]) == cry["usernames"]  # alphabetical
    assert len(cry["usernames"]) == 2
