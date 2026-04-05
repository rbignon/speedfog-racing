"""Tests for chat message cleanup."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Race,
    RaceStatus,
    User,
    UserRole,
)
from speedfog_racing.services.chat_cleanup import cleanup_old_chat_messages


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_cleanup_deletes_old_messages(async_session):
    """Messages from races finished more than 24h ago are deleted."""
    async with async_session() as db:
        organizer = User(
            twitch_id="cleanup_org",
            twitch_username="cleanup_organizer",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id="cleanup_player",
            twitch_username="cleanup_player",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()

        race = Race(
            name="Cleanup Test Race",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            finished_at=datetime.now(UTC) - timedelta(hours=25),
        )
        db.add(race)
        await db.flush()

        msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PUBLIC,
            user_id=player.id,
            message="Old message to be cleaned up",
        )
        db.add(msg)
        await db.commit()
        race_id = race.id

    # Verify message exists before cleanup
    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 1

    count = await cleanup_old_chat_messages(async_session)
    assert count >= 1

    # Verify message is gone after cleanup
    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 0


@pytest.mark.asyncio
async def test_cleanup_preserves_recent_messages(async_session):
    """Messages from races finished less than 24h ago are NOT deleted."""
    async with async_session() as db:
        organizer = User(
            twitch_id="recent_org",
            twitch_username="recent_organizer",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id="recent_player",
            twitch_username="recent_player",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()

        race = Race(
            name="Recent Finished Race",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            finished_at=datetime.now(UTC) - timedelta(hours=12),
        )
        db.add(race)
        await db.flush()

        msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PUBLIC,
            user_id=player.id,
            message="Recent message to keep",
        )
        db.add(msg)
        await db.commit()
        race_id = race.id

    count = await cleanup_old_chat_messages(async_session)
    assert count == 0

    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_cleanup_skips_races_without_finished_at(async_session):
    """Races with no finished_at are never cleaned up even if status is FINISHED."""
    async with async_session() as db:
        organizer = User(
            twitch_id="notime_org",
            twitch_username="notime_organizer",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id="notime_player",
            twitch_username="notime_player",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()

        race = Race(
            name="No Finished-At Race",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            finished_at=None,
        )
        db.add(race)
        await db.flush()

        msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PUBLIC,
            user_id=player.id,
            message="Message in race with no finished_at",
        )
        db.add(msg)
        await db.commit()
        race_id = race.id

    count = await cleanup_old_chat_messages(async_session)
    assert count == 0

    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_cleanup_returns_zero_when_nothing_to_clean(async_session):
    """Returns 0 when there are no races matching the cleanup criteria."""
    count = await cleanup_old_chat_messages(async_session)
    assert count == 0


@pytest.mark.asyncio
async def test_load_chat_history_caps_at_most_recent_messages(async_session):
    """load_chat_history returns at most MAX_CHAT_HISTORY_MESSAGES, most recent first wins."""
    from sqlalchemy.orm import selectinload

    from speedfog_racing.websocket.common import MAX_CHAT_HISTORY_MESSAGES
    from speedfog_racing.websocket.spectator import load_chat_history

    async with async_session() as db:
        organizer = User(
            twitch_id="cap_org",
            twitch_username="cap_organizer",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        player = User(
            twitch_id="cap_player",
            twitch_username="cap_player",
            api_token=uuid.uuid4().hex,
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()

        race = Race(name="Chat Cap Race", organizer_id=organizer.id, status=RaceStatus.RUNNING)
        db.add(race)
        await db.flush()

        # Insert MAX + 10 messages with explicit increasing timestamps so the
        # DESC ordering is unambiguous (SQLite has seconds granularity).
        total = MAX_CHAT_HISTORY_MESSAGES + 10
        base = datetime.now(UTC) - timedelta(seconds=total)
        for i in range(total):
            db.add(
                ChatMessage(
                    race_id=race.id,
                    channel=ChatChannel.PUBLIC,
                    user_id=player.id,
                    message=f"msg-{i:03d}",
                    created_at=base + timedelta(seconds=i),
                )
            )
        await db.commit()
        race_id = race.id

    # Re-fetch with relationships needed by load_chat_history
    async with async_session() as db:
        loaded_race = (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(selectinload(Race.participants), selectinload(Race.casters))
            )
        ).scalar_one()

    hist = await load_chat_history(async_session, race_id, loaded_race, ChatChannel.PUBLIC)

    assert len(hist.messages) == MAX_CHAT_HISTORY_MESSAGES
    # Chronological order preserved (oldest-of-the-kept-set first)
    assert hist.messages[0].message == f"msg-{total - MAX_CHAT_HISTORY_MESSAGES:03d}"
    assert hist.messages[-1].message == f"msg-{total - 1:03d}"
