"""Tests for chat message reactions (model + WebSocket handler)."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    ChatMessageReaction,
    Race,
    RaceStatus,
    User,
    UserRole,
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
