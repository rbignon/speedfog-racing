"""recalculate_all_stats rebuilds the traits of every player the race-end updates score."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    RunMode,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import recalculate_all_stats, update_player_traits


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


async def test_speedrun_race_feeds_no_traits(async_session):
    async with async_session() as db:
        player = User(twitch_id="p", twitch_username="p", api_token="tp", role=UserRole.USER)
        org = User(twitch_id="o", twitch_username="o", api_token="to", role=UserRole.USER)
        db.add_all([player, org])
        await db.flush()
        race = Race(
            name="speedrun",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            mode=RunMode.SPEEDRUN,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        db.add(
            Participant(
                race_id=race.id,
                user_id=player.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=1000,
                zone_history=[{"z": 1}, {"z": 2}],
            )
        )
        await db.commit()

        await recalculate_all_stats(db)

        rows = (await db.execute(select(PlayerTraitScores))).scalars().all()
        assert rows == []


async def test_rebuild_scores_finishers_and_playing_quitters_only(async_session):
    """The rebuild scores users who finished, or quit after starting (igt > 0),
    a finished normal-mode race; never-started quitters and players seen only
    in speedrun or Set Seed races get no row."""
    async with async_session() as db:
        users = {
            name: User(
                twitch_id=name, twitch_username=name, api_token=f"t{name}", role=UserRole.USER
            )
            for name in ("finisher", "quitter", "no_show", "speedrun_only", "org")
        }
        db.add_all(users.values())
        await db.flush()
        included = Race(
            name="included",
            organizer_id=users["org"].id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        speedrun = Race(
            name="speedrun",
            organizer_id=users["org"].id,
            status=RaceStatus.FINISHED,
            mode=RunMode.SPEEDRUN,
            started_at=datetime.now(UTC),
        )
        db.add_all([included, speedrun])
        await db.flush()
        for race, name, status, igt in (
            (included, "finisher", ParticipantStatus.FINISHED, 1000),
            (included, "quitter", ParticipantStatus.ABANDONED, 500),
            (included, "no_show", ParticipantStatus.ABANDONED, 0),
            (speedrun, "speedrun_only", ParticipantStatus.FINISHED, 1000),
        ):
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[name].id,
                    mod_token=f"m{name}",
                    status=status,
                    igt_ms=igt,
                )
            )
        await db.commit()

        await recalculate_all_stats(db)

        scored = set((await db.execute(select(PlayerTraitScores.user_id))).scalars().all())
        assert scored == {users["finisher"].id, users["quitter"].id}


def _scores(row: PlayerTraitScores) -> tuple[object, ...]:
    return (
        row.user_id,
        row.rusher,
        row.cautious,
        row.resilient,
        row.rage_quitter,
        row.explorer,
        row.pathfinder,
        row.boss_slayer,
    )


async def test_rebuild_scores_a_daily_only_player_like_the_race_end_update(async_session):
    """A Daily Seed feeds its finishers' traits when it ends, so the full
    rebuild scores a player seen only in Daily Seeds too."""
    async with async_session() as db:
        player = User(twitch_id="d", twitch_username="d", api_token="td", role=UserRole.USER)
        org = User(twitch_id="o", twitch_username="o", api_token="to", role=UserRole.USER)
        db.add_all([player, org])
        await db.flush()
        daily = Race(
            name="daily",
            organizer_id=org.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            daily_date=date(2026, 10, 1),
            started_at=datetime.now(UTC),
        )
        db.add(daily)
        await db.flush()
        db.add(
            Participant(
                race_id=daily.id,
                user_id=player.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=1000,
                zone_history=[{"z": 1}, {"z": 2}],
            )
        )
        await db.commit()
        player_id = player.id

        await update_player_traits(daily.id, db)
        after_race = [_scores(r) for r in (await db.execute(select(PlayerTraitScores))).scalars()]
        await recalculate_all_stats(db)
        db.expire_all()
        rebuilt = [_scores(r) for r in (await db.execute(select(PlayerTraitScores))).scalars()]

    assert [user_id for user_id, *_ in after_race] == [player_id]
    assert rebuilt == after_race
