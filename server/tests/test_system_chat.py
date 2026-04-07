"""Tests for persisted system chat messages."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.schemas import persist_system_chat
from speedfog_racing.websocket.spectator import load_chat_history


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="org_sys",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="organizer_token_sys",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="sys_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/sys_seed.zip",
            status=SeedStatus.CONSUMED,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
async def race(async_session, organizer, seed):
    async with async_session() as db:
        r = Race(
            name="System Chat Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r


@pytest.mark.asyncio
async def test_system_chat_message_persists_with_null_user(async_session, race):
    """A ChatMessage with user_id=None can be created and queried."""
    async with async_session() as db:
        msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PARTICIPANTS,
            user_id=None,
            message="Seed has been rerolled",
        )
        db.add(msg)
        await db.commit()

        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race.id))
        row = result.scalar_one()
        assert row.user_id is None
        assert row.message == "Seed has been rerolled"
        assert row.channel == ChatChannel.PARTICIPANTS


@pytest.mark.asyncio
async def test_persist_system_chat_creates_db_row(async_session, race):
    """persist_system_chat stores the message in the database."""
    async with async_session() as db:
        await persist_system_chat(
            db=db,
            race_id=race.id,
            channel=ChatChannel.PARTICIPANTS,
            message="Seeds have been released",
        )
        await db.commit()

    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race.id))
        row = result.scalar_one()
        assert row.user_id is None
        assert row.message == "Seeds have been released"
        assert row.channel == ChatChannel.PARTICIPANTS


@pytest.fixture
async def race_with_relationships(async_session, organizer, seed):
    """Create a race with eagerly loaded relationships for load_chat_history."""
    async with async_session() as db:
        r = Race(
            name="History Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(r)
        await db.commit()
        # Re-query with relationships eagerly loaded so they are available after detach
        result = await db.execute(
            select(Race)
            .options(
                selectinload(Race.participants),
                selectinload(Race.casters),
            )
            .where(Race.id == r.id)
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_load_chat_history_includes_system_messages(
    async_session, race_with_relationships, organizer
):
    """System messages (user_id=None) appear in chat history."""
    race = race_with_relationships

    # Insert a user message and a system message
    async with async_session() as db:
        user_msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PARTICIPANTS,
            user_id=organizer.id,
            message="Hello everyone",
        )
        sys_msg = ChatMessage(
            race_id=race.id,
            channel=ChatChannel.PARTICIPANTS,
            user_id=None,
            message="Seed has been rerolled",
        )
        db.add_all([user_msg, sys_msg])
        await db.commit()

    history = await load_chat_history(async_session, race.id, race, ChatChannel.PARTICIPANTS)
    assert len(history.messages) == 2

    # First message is the user message
    assert history.messages[0].message == "Hello everyone"
    assert history.messages[0].role != "system"

    # Second message is the system message
    assert history.messages[1].message == "Seed has been rerolled"
    assert history.messages[1].role == "system"
    assert history.messages[1].username == ""
    assert history.messages[1].display_name is None
