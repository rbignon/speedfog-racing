"""Invariants of the events schema that the database must enforce."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.api.helpers import not_event_qualifier
from speedfog_racing.database import Base
from speedfog_racing.models import Event, EventSignup, Race, User, UserRole


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


async def test_a_runner_signs_up_for_an_event_once(session_factory):
    async with session_factory() as db:
        user = User(twitch_id="u1", twitch_username="ana", role=UserRole.USER)
        event = _event()
        db.add_all([user, event])
        await db.flush()
        db.add(EventSignup(event_id=event.id, user_id=user.id))
        db.add(EventSignup(event_id=event.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_qualifier_listing_filter_mirrors_the_model_predicate(session_factory):
    """``not_event_qualifier()`` (SQL) and ``Race.is_event_qualifier`` (Python)
    state one rule twice; the listing filter must keep exactly the races the
    property rejects, whatever slot shapes exist."""
    async with session_factory() as db:
        user = User(twitch_id="u1", twitch_username="orga", role=UserRole.ORGANIZER)
        event = _event()
        db.add_all([user, event])
        await db.flush()
        races = [
            Race(name="plain", organizer_id=user.id),
            Race(name="stage", organizer_id=user.id, event_id=event.id, event_slot="semi:1"),
            Race(
                name="qualifier",
                organizer_id=user.id,
                event_id=event.id,
                event_slot="qualifier:standard:1",
            ),
        ]
        db.add_all(races)
        await db.commit()

        listed = set((await db.execute(select(Race.id).where(not_event_qualifier()))).scalars())

    assert listed == {r.id for r in races if not r.is_event_qualifier}
    # Guard against both definitions drifting to "everything" or "nothing".
    assert 0 < len(listed) < len(races)
