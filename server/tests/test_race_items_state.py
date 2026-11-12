"""Held race items, their log table and the reset rule."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceItemEvent,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
)
from speedfog_racing.services.sanctions_service import reset_participant_progress

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def items_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _make_race(db) -> tuple[Race, Participant]:
    user = User(twitch_id="items_u", twitch_username="items_u", api_token="items_tok")
    seed = Seed(
        seed_number="items_seed",
        pool_name="standard",
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path="/test/items_seed",
        status=SeedStatus.CONSUMED,
    )
    db.add_all([user, seed])
    await db.flush()
    race = Race(name="Items", organizer_id=user.id, seed_id=seed.id, status=RaceStatus.RUNNING)
    db.add(race)
    await db.flush()
    participant = Participant(race_id=race.id, user_id=user.id, status=ParticipantStatus.PLAYING)
    db.add(participant)
    await db.flush()
    return race, participant


async def test_reset_clears_the_held_item_and_keeps_the_grant_count(items_session):
    async with items_session() as db:
        _, participant = await _make_race(db)
        participant.held_item = {"grant_id": 3, "item": "banana", "confirmed": True}
        participant.item_grant_count = 3
        await db.commit()

        reset_participant_progress(participant)
        await db.commit()
        await db.refresh(participant)

        assert participant.held_item is None
        assert participant.item_grant_count == 3


async def test_race_item_events_cascade_with_the_race(items_session):
    async with items_session() as db:
        race, participant = await _make_race(db)
        db.add(
            RaceItemEvent(
                race_id=race.id,
                participant_id=participant.id,
                kind="use",
                item="hammer",
                igt_ms=1234,
                targets=[{"participant_id": str(participant.id), "outcome": "hit"}],
            )
        )
        await db.commit()
        assert len((await db.execute(select(RaceItemEvent))).scalars().all()) == 1

        await db.execute(delete(Participant))
        await db.execute(delete(Race))
        await db.commit()
        assert (await db.execute(select(RaceItemEvent))).scalars().all() == []
