"""Speedrun and Set Seed races stay out of the statistics that describe blind play.

Activity and history (race lists, played-run counts) keep every race; zone, boss
and weapon stats, traits and the per-pool profile stats count the races that
satisfy ``counts_for_community_stats`` only.
"""

import os
from datetime import UTC, date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.api import stats as stats_api
from speedfog_racing.api.stats import _load_zone_stats_inputs
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import resolve_dominant_traits, update_player_traits

# (name, mode, exclude_from_stats, igt_ms, counts)
_RACES = [
    ("normal", RunMode.NORMAL, False, 300_000, True),
    ("speedrun", RunMode.SPEEDRUN, True, 100_000, False),
    ("set_seed", RunMode.SET_SEED, True, 90_000, False),
    # Finished before the mode existed: backfilled as speedrun, flag left off.
    ("backfilled", RunMode.SPEEDRUN, False, 200_000, True),
    # Daily Seeds are excluded from the speedrun boards but still feed zone stats.
    ("daily", RunMode.NORMAL, True, 250_000, True),
]


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    stats_api._stats_cache.clear()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    stats_api._stats_cache.clear()
    app.dependency_overrides.clear()


async def _user(db, name: str) -> User:
    user = User(twitch_id=name, twitch_username=name, api_token=f"tok-{name}", role=UserRole.USER)
    db.add(user)
    await db.flush()
    return user


async def _race(db, organizer, player, name, mode, excluded, igt, daily=False) -> Race:
    seed = Seed(
        seed_number=f"seed-{name}-{player.twitch_username}",
        pool_name="standard",
        graph_json={"nodes": {}, "total_layers": 1},
        total_layers=1,
        folder_path=f"/t/{name}",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    race = Race(
        name=f"{name}-{player.twitch_username}",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=RaceStatus.FINISHED,
        is_public=True,
        started_at=datetime.now(UTC),
        mode=mode,
        exclude_from_stats=excluded,
        daily_date=date.today() if daily else None,
    )
    db.add(race)
    await db.flush()
    db.add(
        Participant(
            race_id=race.id,
            user_id=player.id,
            mod_token=f"mt-{race.name}",
            status=ParticipantStatus.FINISHED,
            igt_ms=igt,
            death_count=0,
            zone_history=[
                {"node_id": "z1", "igt_ms": 0, "weapons": [{"ids": [2000025], "ticks": 1}]}
            ],
        )
    )
    return race


@pytest.fixture
async def world(async_session):
    async with async_session() as db:
        organizer = await _user(db, "org")
        player = await _user(db, "alice")
        races = {}
        for name, mode, excluded, igt, _counts in _RACES:
            races[name] = await _race(
                db, organizer, player, name, mode, excluded, igt, daily=name == "daily"
            )
        await db.commit()
        return {name: race.id for name, race in races.items()}


async def test_zone_stats_loader_keeps_only_counted_races(async_session, world):
    async with async_session() as db:
        participants, _ = await _load_zone_stats_inputs(None, 3650, db)
    counted = {world[name] for name, *_rest, counts in _RACES if counts}
    assert {row.race_id for row in participants} == counted


async def test_weapon_stats_count_only_counted_races(test_client, world):
    async with test_client as client:
        response = await client.get("/api/stats/weapons")
    assert response.status_code == 200
    (combo,) = response.json()["combos"]
    # normal, backfilled and daily: one tick each
    assert combo["total_ticks"] == 3


async def test_pool_stats_best_time_ignores_ranked_races(test_client, world):
    async with test_client as client:
        response = await client.get("/api/users/alice/pool-stats")
    assert response.status_code == 200
    standard = next(p for p in response.json()["pools"] if p["pool_name"] == "standard")
    # daily is excluded by daily_date; speedrun and set_seed by the predicate
    assert standard["race"]["runs"] == 2
    assert standard["race"]["best_time_ms"] == 200_000


async def test_pool_stats_training_block_ignores_ranked_solo_sessions(
    test_client, async_session, world
):
    async with async_session() as db:
        alice = (await db.execute(select(User).where(User.twitch_username == "alice"))).scalar_one()
        seed = (await db.execute(select(Seed).limit(1))).scalars().first()
        for mode, igt in (
            (RunMode.SET_SEED, 1_000),
            (RunMode.SPEEDRUN, 2_000),
            (RunMode.NORMAL, 50_000),
        ):
            db.add(
                TrainingSession(
                    user_id=alice.id,
                    seed_id=seed.id,
                    mode=mode,
                    status=TrainingSessionStatus.FINISHED,
                    igt_ms=igt,
                    finished_at=datetime.now(UTC),
                )
            )
        await db.commit()
    async with test_client as client:
        response = await client.get("/api/users/alice/pool-stats")
    standard = next(p for p in response.json()["pools"] if p["pool_name"] == "standard")
    # Only the practice session feeds the profile's solo numbers.
    assert standard["training"]["runs"] == 1
    assert standard["training"]["best_time_ms"] == 50_000


async def test_traits_finished_race_count_ignores_ranked_races(test_client, world):
    async with test_client as client:
        response = await client.get("/api/users/alice/traits")
    assert response.status_code == 200
    assert response.json()["finished_races"] == 3


async def test_race_history_still_lists_every_race(test_client, world):
    async with test_client as client:
        response = await client.get("/api/users/alice/activity")
    assert response.status_code == 200
    assert response.json()["total"] == len(_RACES)


async def test_finishing_a_ranked_race_changes_no_traits(async_session, world):
    async with async_session() as db:
        await update_player_traits(world["speedrun"], db)
        await update_player_traits(world["set_seed"], db)
        assert (await db.execute(select(PlayerTraitScores))).scalars().all() == []
        await update_player_traits(world["normal"], db)
        assert len((await db.execute(select(PlayerTraitScores))).scalars().all()) == 1


async def test_ranked_finishes_do_not_qualify_for_a_dominant_trait(async_session):
    """Three finished races qualify a player; ranked ones are not among them."""
    async with async_session() as db:
        organizer = await _user(db, "org")
        qualified = [await _user(db, "q1"), await _user(db, "q2")]
        ranked_heavy = await _user(db, "r1")
        for user in qualified:
            for i in range(3):
                await _race(db, organizer, user, f"n{i}", RunMode.NORMAL, False, 1000)
        for i in range(2):
            await _race(db, organizer, ranked_heavy, f"n{i}", RunMode.NORMAL, False, 1000)
        for i in range(3):
            await _race(db, organizer, ranked_heavy, f"s{i}", RunMode.SPEEDRUN, True, 1000)
        for user in [*qualified, ranked_heavy]:
            db.add(PlayerTraitScores(user_id=user.id, rusher=50))
        await db.commit()

        await resolve_dominant_traits(db)

        rows = {r.user_id: r for r in (await db.execute(select(PlayerTraitScores))).scalars()}
        assert all(rows[u.id].dominant_trait == "rusher" for u in qualified)
        assert rows[ranked_heavy.id].dominant_trait is None
