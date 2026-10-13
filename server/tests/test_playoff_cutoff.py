"""A playoff race's in-game cutoff: set by its finishes, enforced on its runs."""

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
from speedfog_racing.services.event_service import update_playoff_cutoff

from .event_fixtures import bracketed

START = datetime(2026, 10, 12, 19, tzinfo=UTC)
CONFIG = {
    "modes": [{"key": "standard", "label": "Standard"}],
    "stages": [{"key": "final", "label": "Final", "kind": "final", "races": 3, "seeds": [1, 2]}],
    "playoff_cutoff_minutes": 7,
}
CUTOFF = 7 * 60_000
# The first runner's in-game time, and the deadline it sets.
WINNER = 2_400_000
DEADLINE = WINNER + CUTOFF


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
    igt_cutoff_ms: int | None = None,
    chaser_igt_ms: int = 2_000_000,
) -> Race:
    """A running two-runner race: p0 finished in 40:00 of in-game time, p1 still playing."""
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
            config=bracketed(CONFIG),
        )
        db.add_all([seed, event])
        await db.flush()
        race = Race(
            name="race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=START,
            igt_cutoff_ms=igt_cutoff_ms,
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
                    igt_ms=WINNER,
                    finished_at=START + timedelta(minutes=40, seconds=20),
                ),
                Participant(
                    race_id=race.id,
                    user_id=runners[1].id,
                    status=ParticipantStatus.PLAYING,
                    igt_ms=chaser_igt_ms,
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


def _chaser(race: Race) -> Participant:
    return next(p for p in race.participants if p.status == ParticipantStatus.PLAYING)


async def _finish(db: AsyncSession, race: Race, igt_ms: int) -> Race:
    """The chaser finishes in ``igt_ms``: the race, reloaded."""
    chaser = _chaser(race)
    chaser.status = ParticipantStatus.FINISHED
    chaser.igt_ms = igt_ms
    chaser.finished_at = START + timedelta(minutes=45)
    await db.commit()
    return await _load(db, race)


async def test_the_first_finish_sets_the_cutoff_the_event_s_minutes_past_its_time(
    async_session,
):
    race = await _race(async_session, "final:1")
    async with async_session() as db:
        race = await _load(db, race)
        assert await update_playoff_cutoff(db, race) is True
        race = await _load(db, race)
        # The finish's in-game time plus the event's 7 minutes, to the millisecond.
        assert race.igt_cutoff_ms == DEADLINE
        assert race.race_duration_minutes is None


async def test_a_faster_later_finish_brings_the_cutoff_down(async_session):
    # The first runner home is not always the fastest in game.
    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE)
    async with async_session() as db:
        race = await _finish(db, await _load(db, race), 2_300_000)
        assert await update_playoff_cutoff(db, race) is True
        assert (await _load(db, race)).igt_cutoff_ms == 2_300_000 + CUTOFF


async def test_a_slower_later_finish_leaves_the_cutoff_alone(async_session):
    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE)
    async with async_session() as db:
        race = await _finish(db, await _load(db, race), 2_500_000)
        assert await update_playoff_cutoff(db, race) is False
        assert (await _load(db, race)).igt_cutoff_ms == DEADLINE


@pytest.mark.parametrize("slot", [None, "qualifier:standard:1"])
async def test_races_outside_the_playoffs_get_no_cutoff(async_session, slot):
    race = await _race(async_session, slot)
    async with async_session() as db:
        race = await _load(db, race)
        assert await update_playoff_cutoff(db, race) is False
        assert (await _load(db, race)).igt_cutoff_ms is None


async def test_a_race_finished_meanwhile_gets_no_cutoff(async_session):
    # The last runner's abandon can end the race between the finish and the cutoff.
    race = await _race(async_session, "final:1")
    async with async_session() as db:
        race = await _load(db, race)
        race.status = RaceStatus.FINISHED
        await db.commit()
        assert await update_playoff_cutoff(db, race) is False
        assert (await _load(db, race)).igt_cutoff_ms is None
