"""A playoff race's in-game cutoff: set by its finishes, enforced on its runs."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    ChatMessage,
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
    finishers: tuple[int, ...] = (WINNER,),
) -> Race:
    """A running race: p0.. finished in ``finishers`` (40:00 of in-game time by
    default), the last runner still playing."""
    async with session_maker() as db:
        organizer = User(
            twitch_id="org", twitch_username="org", api_token="t0", role=UserRole.ORGANIZER
        )
        runners = [
            User(twitch_id=f"u{i}", twitch_username=f"p{i}", api_token=f"t{i + 1}")
            for i in range(len(finishers) + 1)
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
                *(
                    Participant(
                        race_id=race.id,
                        user_id=runner.id,
                        status=ParticipantStatus.FINISHED,
                        igt_ms=igt_ms,
                        finished_at=START + timedelta(milliseconds=igt_ms + 20_000),
                    )
                    for runner, igt_ms in zip(runners, finishers, strict=False)
                ),
                Participant(
                    race_id=race.id,
                    user_id=runners[-1].id,
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


async def _loaded_chaser(
    session_maker: async_sessionmaker[AsyncSession], race: Race
) -> Participant:
    """The playing runner, loaded the way the status_update handler holds it."""
    async with session_maker() as db:
        return (
            await db.execute(
                select(Participant)
                .where(
                    Participant.race_id == race.id,
                    Participant.status == ParticipantStatus.PLAYING,
                )
                .options(
                    selectinload(Participant.race).selectinload(Race.seed),
                    selectinload(Participant.race).selectinload(Race.participants),
                )
            )
        ).scalar_one()


async def test_a_run_past_the_cutoff_runs_out_of_time_and_the_last_one_out_ends_the_race(
    async_session,
):
    from speedfog_racing.websocket.race.mod import handle_igt_cutoff

    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE, chaser_igt_ms=DEADLINE + 1)
    chaser_id = _chaser(race).id
    await handle_igt_cutoff(async_session, chaser_id)

    async with async_session() as db:
        race = await _load(db, race)
        messages = (
            (await db.execute(select(ChatMessage.message).where(ChatMessage.race_id == race.id)))
            .scalars()
            .all()
        )
    assert next(p for p in race.participants if p.id == chaser_id).status == (
        ParticipantStatus.ABANDONED
    )
    assert race.status == RaceStatus.FINISHED
    assert "p1 ran out of time." in messages


async def test_a_run_at_the_cutoff_to_the_millisecond_keeps_racing(async_session):
    from speedfog_racing.websocket.race.mod import handle_igt_cutoff

    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE, chaser_igt_ms=DEADLINE)
    chaser_id = _chaser(race).id
    await handle_igt_cutoff(async_session, chaser_id)

    async with async_session() as db:
        race = await _load(db, race)
    assert _chaser(race).id == chaser_id
    assert race.status == RaceStatus.RUNNING


async def test_a_status_update_past_the_cutoff_eliminates_the_run(async_session, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from speedfog_racing.websocket.race import mod as race_mod

    out_of_time = AsyncMock()
    monkeypatch.setattr(race_mod, "handle_igt_cutoff", out_of_time)
    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE, chaser_igt_ms=DEADLINE)
    chaser = await _loaded_chaser(async_session, race)
    handler = race_mod.RaceModHandler(MagicMock(), race.id, async_session)
    handler._participant_id = chaser.id

    await handler._broadcast_after_status_update(
        chaser, became_active=False, death_delta=0, history_changed=False, weapons=None
    )
    out_of_time.assert_not_awaited()

    # The recorded IGT (already clamped non-decreasing), one millisecond past.
    chaser.igt_ms += 1
    await handler._broadcast_after_status_update(
        chaser, became_active=False, death_delta=0, history_changed=False, weapons=None
    )
    out_of_time.assert_awaited_once_with(async_session, chaser.id)


async def test_a_deathless_death_past_the_cutoff_is_one_elimination(async_session, monkeypatch):
    # Dying on the very update that crosses the cutoff: the death eliminates, once.
    from unittest.mock import AsyncMock, MagicMock

    from speedfog_racing.websocket.race import mod as race_mod

    died, out_of_time = AsyncMock(), AsyncMock()
    monkeypatch.setattr(race_mod, "handle_deathless_death", died)
    monkeypatch.setattr(race_mod, "handle_igt_cutoff", out_of_time)
    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE, chaser_igt_ms=DEADLINE + 1)
    chaser = await _loaded_chaser(async_session, race)
    chaser.race.deathless = True
    handler = race_mod.RaceModHandler(MagicMock(), race.id, async_session)
    handler._participant_id = chaser.id

    await handler._broadcast_after_status_update(
        chaser, became_active=False, death_delta=1, history_changed=False, weapons=None
    )
    died.assert_awaited_once_with(async_session, chaser.id)
    out_of_time.assert_not_awaited()


@pytest.fixture
def client(async_session):
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_a_disqualified_best_time_hands_the_cutoff_to_the_next_best(async_session, client):
    # The deadline runs from the best time still standing: a disqualified
    # winner's time stops counting, and a cancel brings it back.
    race = await _race(
        async_session, "final:1", igt_cutoff_ms=DEADLINE, finishers=(WINNER, 2_500_000)
    )
    best = next(p for p in race.participants if p.igt_ms == WINNER)
    url = f"/api/races/{race.id}/participants/{best.id}/disqualify"
    organizer = {"Authorization": "Bearer t0"}
    async with client:
        resp = await client.post(url, json={"reason": "Cheat tool detected"}, headers=organizer)
        assert resp.status_code == 200, resp.text
        assert resp.json()["igt_cutoff_ms"] == 2_500_000 + CUTOFF
        resp = await client.delete(url, headers=organizer)
        assert resp.status_code == 200, resp.text
        assert resp.json()["igt_cutoff_ms"] == DEADLINE


async def test_a_recompute_drops_the_cutoff_once_no_finish_stands(async_session):
    race = await _race(async_session, "final:1", igt_cutoff_ms=DEADLINE)
    async with async_session() as db:
        race = await _load(db, race)
        winner = next(p for p in race.participants if p.status == ParticipantStatus.FINISHED)
        winner.status = ParticipantStatus.DISQUALIFIED
        await db.commit()
        race = await _load(db, race)
        assert await update_playoff_cutoff(db, race, only_lower=False) is True
        assert (await _load(db, race)).igt_cutoff_ms is None
