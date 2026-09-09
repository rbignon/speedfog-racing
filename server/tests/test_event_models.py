"""Invariants of the events schema that the database must enforce."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Event, Race, User, UserRole


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _event() -> Event:
    now = datetime.now(UTC)
    return Event(
        slug="season-one",
        name="Season One",
        starts_at=now,
        qualifier_ends_at=now + timedelta(days=7),
        ends_at=now + timedelta(days=40),
        config={},
    )


async def test_two_races_cannot_share_a_slot(session_factory):
    async with session_factory() as db:
        user = User(twitch_id="u1", twitch_username="orga", role=UserRole.ORGANIZER)
        event = _event()
        db.add_all([user, event])
        await db.flush()
        db.add(
            Race(
                name="A", organizer_id=user.id, event_id=event.id, event_slot="qualifier:standard:1"
            )
        )
        db.add(
            Race(
                name="B", organizer_id=user.id, event_id=event.id, event_slot="qualifier:standard:1"
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_unslotted_races_do_not_collide(session_factory):
    async with session_factory() as db:
        user = User(twitch_id="u1", twitch_username="orga", role=UserRole.ORGANIZER)
        event = _event()
        db.add_all([user, event])
        await db.flush()
        db.add(Race(name="A", organizer_id=user.id, event_id=event.id))
        db.add(Race(name="B", organizer_id=user.id, event_id=event.id))
        db.add(Race(name="C", organizer_id=user.id))
        await db.commit()
        await db.refresh(event, attribute_names=["races"])
        assert len(event.races) == 2
