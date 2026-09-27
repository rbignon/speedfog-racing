"""The cutoff a playoff race's first finisher sets on the rest of the field."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.event_service import start_playoff_cutoff

START = datetime(2026, 10, 12, 19, tzinfo=UTC)
CONFIG = {
    "modes": [{"key": "standard", "label": "Standard"}],
    "stages": [{"key": "final", "label": "Final", "kind": "final", "races": 3, "seeds": [1, 2]}],
    "playoff_cutoff_minutes": 7,
}


@pytest.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _race(
    session_maker: async_sessionmaker[AsyncSession],
    slot: str | None,
    race_duration_minutes: int | None = None,
) -> Race:
    """A running two-runner race: the first finished 40:20 in, the second still playing."""
    async with session_maker() as db:
        organizer = User(
            twitch_id="org", twitch_username="org", api_token="t0", role=UserRole.ORGANIZER
        )
        runners = [
            User(twitch_id=f"u{i}", twitch_username=f"p{i}", api_token=f"t{i + 1}")
            for i in range(2)
        ]
        db.add_all([organizer, *runners])
        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        event = Event(
            slug="season-one",
            name="Season One",
            starts_at=START - timedelta(days=30),
            qualifier_ends_at=START - timedelta(days=10),
            ends_at=START + timedelta(days=20),
            config=CONFIG,
        )
        db.add_all([seed, event])
        await db.flush()
        race = Race(
            name="race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=START,
            race_duration_minutes=race_duration_minutes,
            event_id=event.id if slot else None,
            event_slot=slot,
        )
        db.add(race)
        await db.flush()
        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=runners[0].id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_400_000,
                    finished_at=START + timedelta(minutes=40, seconds=20),
                ),
                Participant(
                    race_id=race.id,
                    user_id=runners[1].id,
                    status=ParticipantStatus.PLAYING,
                    igt_ms=2_000_000,
                ),
            ]
        )
        await db.commit()
        return await _load(db, race)


async def _load(db: AsyncSession, race: Race) -> Race:
    return (
        await db.execute(
            select(Race)
            .where(Race.id == race.id)
            .options(selectinload(Race.participants))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


def _finisher(race: Race) -> Participant:
    return next(p for p in race.participants if p.status == ParticipantStatus.FINISHED)


async def test_the_first_finisher_closes_the_race_the_event_s_cutoff_later(async_session):
    race = await _race(async_session, "final:1")
    async with async_session() as db:
        race = await _load(db, race)
        assert await start_playoff_cutoff(db, race, _finisher(race)) is True
        # 40:20 in, rounded up to the race clock's next minute, plus the event's 7.
        assert (await _load(db, race)).race_duration_minutes == 48


async def test_a_later_finisher_leaves_the_organizer_s_extension_alone(async_session):
    race = await _race(async_session, "final:1", race_duration_minutes=90)
    async with async_session() as db:
        race = await _load(db, race)
        chaser = next(p for p in race.participants if p.status == ParticipantStatus.PLAYING)
        chaser.status = ParticipantStatus.FINISHED
        chaser.finished_at = START + timedelta(minutes=45)
        await db.commit()
        assert await start_playoff_cutoff(db, race, chaser) is False
        assert (await _load(db, race)).race_duration_minutes == 90


async def test_an_earlier_deadline_already_set_stands(async_session):
    race = await _race(async_session, "final:1", race_duration_minutes=45)
    async with async_session() as db:
        race = await _load(db, race)
        assert await start_playoff_cutoff(db, race, _finisher(race)) is False
        assert (await _load(db, race)).race_duration_minutes == 45


@pytest.mark.parametrize("slot", [None, "qualifier:standard:1"])
async def test_races_outside_the_playoffs_get_no_cutoff(async_session, slot):
    race = await _race(async_session, slot)
    async with async_session() as db:
        race = await _load(db, race)
        assert await start_playoff_cutoff(db, race, _finisher(race)) is False
        assert (await _load(db, race)).race_duration_minutes is None


async def test_a_race_finished_meanwhile_gets_no_deadline(async_session):
    # The last runner's abandon can end the race between the finish and the cutoff.
    race = await _race(async_session, "final:1")
    async with async_session() as db:
        race = await _load(db, race)
        race.status = RaceStatus.FINISHED
        await db.commit()
        assert await start_playoff_cutoff(db, race, _finisher(race)) is False
        assert (await _load(db, race)).race_duration_minutes is None
