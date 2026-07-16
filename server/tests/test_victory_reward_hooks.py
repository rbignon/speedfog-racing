"""Victory reward hooks: silver-aura on first public race win, cyan-aura +
dawnrunner on daily-seed wins, gold-aura + daily_crown on weekly championship."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    NameTemplateUnlock,
    Participant,
    ParticipantStatus,
    PhantomSkinUnlock,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.services.race_lifecycle import check_race_auto_finish


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


def _user(i: int) -> User:
    return User(
        twitch_id=f"u{i}", twitch_username=f"user{i}", api_token=f"t{i}", role=UserRole.USER
    )


async def _make_race(db, organizer, *, is_public=True, daily_date=None) -> Race:
    race = Race(
        name="R",
        organizer_id=organizer.id,
        status=RaceStatus.FINISHED,
        is_public=is_public,
        daily_date=daily_date,
        exclude_from_stats=daily_date is not None,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db.add(race)
    await db.flush()
    return race


def _participant(race, user, *, status, igt_ms, zones=2, layer=0) -> Participant:
    return Participant(
        race_id=race.id,
        user_id=user.id,
        status=status,
        igt_ms=igt_ms,
        current_layer=layer,
        zone_history=[{"z": i} for i in range(zones)],
    )


async def _skin_holders(db, skin_id: str) -> set:
    rows = await db.execute(
        select(PhantomSkinUnlock.user_id).where(PhantomSkinUnlock.skin_id == skin_id)
    )
    return {r[0] for r in rows.all()}


async def _template_holders(db, template_id: str) -> set:
    rows = await db.execute(
        select(NameTemplateUnlock.user_id).where(NameTemplateUnlock.template_id == template_id)
    )
    return {r[0] for r in rows.all()}


async def test_race_win_grants_silver_to_winner_only(async_session):
    async with async_session() as db:
        winner, loser, org = _user(1), _user(2), _user(99)
        db.add_all([winner, loser, org])
        await db.flush()
        race = await _make_race(db, org)
        db.add_all(
            [
                _participant(race, winner, status=ParticipantStatus.FINISHED, igt_ms=1000),
                _participant(race, loser, status=ParticipantStatus.FINISHED, igt_ms=2000),
            ]
        )
        await db.commit()
        race = (await db.execute(select(Race).where(Race.id == race.id))).scalar_one()
        await db.refresh(race, ["participants"])
        await RewardsService(db).grant_race_win_rewards(race)
        await db.commit()
        assert await _skin_holders(db, "silver-aura") == {winner.id}


async def test_race_win_skips_daily_private_and_solo(async_session):
    async with async_session() as db:
        a, org = _user(1), _user(99)
        db.add_all([a, org])
        await db.flush()

        daily = await _make_race(db, org, daily_date=date(2026, 7, 14))
        db.add(_participant(daily, a, status=ParticipantStatus.FINISHED, igt_ms=1000))
        db.add(_participant(daily, org, status=ParticipantStatus.FINISHED, igt_ms=2000))

        private = await _make_race(db, org, is_public=False)
        db.add(_participant(private, a, status=ParticipantStatus.FINISHED, igt_ms=1000))
        db.add(_participant(private, org, status=ParticipantStatus.FINISHED, igt_ms=2000))

        solo = await _make_race(db, org)
        db.add(_participant(solo, a, status=ParticipantStatus.FINISHED, igt_ms=1000))
        await db.commit()

        svc = RewardsService(db)
        for race_id in (daily.id, private.id, solo.id):
            race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
            await db.refresh(race, ["participants"])
            await svc.grant_race_win_rewards(race)
        await db.commit()
        assert await _skin_holders(db, "silver-aura") == set()


async def test_race_win_no_finisher_grants_nothing(async_session):
    async with async_session() as db:
        a, b, org = _user(1), _user(2), _user(99)
        db.add_all([a, b, org])
        await db.flush()
        race = await _make_race(db, org)
        db.add_all(
            [
                _participant(race, a, status=ParticipantStatus.ABANDONED, igt_ms=1000),
                _participant(race, b, status=ParticipantStatus.ABANDONED, igt_ms=2000),
            ]
        )
        await db.commit()
        race = (await db.execute(select(Race).where(Race.id == race.id))).scalar_one()
        await db.refresh(race, ["participants"])
        await RewardsService(db).grant_race_win_rewards(race)
        await db.commit()
        assert await _skin_holders(db, "silver-aura") == set()


async def test_daily_win_grants_cyan_and_dawnrunner_with_ties(async_session):
    day = date(2026, 7, 14)
    async with async_session() as db:
        a, b, c, org = _user(1), _user(2), _user(3), _user(99)
        db.add_all([a, b, c, org])
        await db.flush()
        race = await _make_race(db, org, daily_date=day)
        db.add_all(
            [
                # a and b tie at the top (same igt), c is slower.
                _participant(race, a, status=ParticipantStatus.FINISHED, igt_ms=1000),
                _participant(race, b, status=ParticipantStatus.FINISHED, igt_ms=1000),
                _participant(race, c, status=ParticipantStatus.FINISHED, igt_ms=5000),
            ]
        )
        await db.commit()
        svc = RewardsService(db)
        await svc.grant_daily_win_rewards(day)
        await svc.grant_daily_win_rewards(day)  # idempotent re-run
        await db.commit()
        assert await _skin_holders(db, "cyan-aura") == {a.id, b.id}
        assert await _template_holders(db, "dawnrunner") == {a.id, b.id}


async def test_daily_win_noop_when_no_finished_daily(async_session):
    async with async_session() as db:
        svc = RewardsService(db)
        await svc.grant_daily_win_rewards(date(2026, 7, 14))
        await db.commit()
        assert await _skin_holders(db, "cyan-aura") == set()


async def test_check_race_auto_finish_grants_silver_aura_to_winner(async_session):
    """End-to-end through the real finalization seam: check_race_auto_finish
    (not grant_race_win_rewards directly) must trigger the silver-aura grant
    when a public non-daily race auto-finishes."""
    async with async_session() as db:
        winner, loser, org = _user(1), _user(2), _user(99)
        db.add_all([winner, loser, org])
        await db.flush()

        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Race",
            organizer_id=org.id,
            seed_id=seed.id,
            is_public=True,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=race.id,
                    user_id=winner.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1000,
                    finished_at=datetime.now(UTC),
                ),
                Participant(
                    race_id=race.id,
                    user_id=loser.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2000,
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()

        loaded_race = (
            await db.execute(
                select(Race).where(Race.id == race.id).options(selectinload(Race.participants))
            )
        ).scalar_one()
        ok = await check_race_auto_finish(db, loaded_race)
        assert ok is True

    async with async_session() as db:
        assert await _skin_holders(db, "silver-aura") == {winner.id}
        assert loser.id not in await _skin_holders(db, "silver-aura")
