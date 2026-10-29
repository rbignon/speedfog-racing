"""Set Seed: seed lookup, the public and replayable rules, the top seeds."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base
from speedfog_racing.models import (
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedProtection,
    SeedStatus,
    TrainingSessionStatus,
)
from speedfog_racing.services.set_seed_service import (
    SeedLookupError,
    purgeable_seeds,
    resolve_seed,
    seed_replayability,
    top_seed_numbers,
)
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    filter_board,
    load_counted_runs,
    seed_category,
)

from .test_speedrun_service import BASE, _add_run, _add_session, _user


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


@pytest.fixture
async def pools(async_session):
    async with async_session() as db:
        # conftest creates "standard" with every pools table; give it a layer count.
        standard = (await db.execute(select(Pool).where(Pool.name == "standard"))).scalar_one()
        standard.config = {"name": "Standard", "type": "race", "layers_count": 30}
        db.add_all(
            [
                Pool(name="sprint", config={"name": "Sprint", "type": "race", "layers_count": 15}),
                Pool(name="training_sprint", config={"name": "Sprint", "type": "training"}),
            ]
        )
        await db.commit()


@pytest.fixture(autouse=True)
def _no_cutoff(monkeypatch):
    """No game-version cutoff unless a test sets one, whatever the local .env says."""
    monkeypatch.setattr(settings, "set_seed_min_seed_date", None)


async def _seed(
    db: AsyncSession,
    number: str,
    *,
    pool: str = "sprint",
    status: SeedStatus = SeedStatus.CONSUMED,
    layers: int = 15,
    folder_path: str = "/nonexistent/seed.zip",
) -> Seed:
    seed = Seed(
        seed_number=number,
        pool_name=pool,
        graph_json={"nodes": {}},
        total_layers=layers,
        folder_path=folder_path,
        status=status,
        created_at=BASE - timedelta(days=1),
    )
    db.add(seed)
    await db.flush()
    return seed


async def _unknown(db: AsyncSession, text: str) -> bool:
    with pytest.raises(SeedLookupError) as error:
        await resolve_seed(db, text)
    return error.value.kind == "unknown"


async def test_resolve_seed_full_and_prefix(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        seed = await _seed(db, "363096a4243f")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await db.commit()

        assert (await resolve_seed(db, "363096A4243F ")).id == seed.id
        assert (await resolve_seed(db, "363096")).id == seed.id
        assert await _unknown(db, "36309")
        assert await _unknown(db, "")


async def test_unplayed_seeds_are_unknown(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        available = await _seed(db, "aaaaaa000001", status=SeedStatus.AVAILABLE)
        await _add_session(
            db,
            a,
            "sprint",
            RunMode.SPEEDRUN,
            0,
            status=TrainingSessionStatus.CANCELLED,
            seed=available,
        )
        setup_only = await _seed(db, "bbbbbb000001")
        await _add_run(
            db,
            user=a,
            igt_ms=0,
            minute=1,
            race_status=RaceStatus.SETUP,
            status=ParticipantStatus.REGISTERED,
            finished=False,
            seed=setup_only,
        )
        training = await _seed(db, "cccccc000001", pool="training_sprint")
        await _add_session(db, a, "training_sprint", RunMode.NORMAL, 1000, seed=training)
        # Each rule on its own: a training seed with a finished race on it, and
        # a race pool seed with only an unranked session on it.
        raced_training = await _seed(db, "dddddd000001", pool="training_sprint")
        await _add_run(db, user=a, igt_ms=1000, minute=2, seed=raced_training)
        unranked_only = await _seed(db, "eeeeee000001")
        await _add_session(db, a, "sprint", RunMode.NORMAL, 1000, seed=unranked_only)
        await db.commit()

        for seed in (available, setup_only, training, raced_training, unranked_only):
            assert await _unknown(db, seed.seed_number)
            assert await _unknown(db, seed.seed_number[:6])


async def test_prefix_ambiguity_counts_known_seeds_only(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        first = await _seed(db, "abcdef111111")
        second = await _seed(db, "abcdef211111")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=first)
        await _add_session(db, a, "sprint", RunMode.SET_SEED, 900, seed=second)
        played = await _seed(db, "123456aaaaaa")
        await _add_run(db, user=a, igt_ms=1000, minute=2, seed=played)
        unplayed = await _seed(db, "123456bbbbbb", status=SeedStatus.AVAILABLE)
        await _add_session(
            db,
            a,
            "sprint",
            RunMode.SPEEDRUN,
            0,
            status=TrainingSessionStatus.CANCELLED,
            seed=unplayed,
        )
        await db.commit()

        with pytest.raises(SeedLookupError) as error:
            await resolve_seed(db, "abcdef")
        assert error.value.kind == "ambiguous"
        assert (await resolve_seed(db, "abcdef1")).id == first.id
        assert (await resolve_seed(db, "abcdef2")).id == second.id
        assert (await resolve_seed(db, "123456")).id == played.id


async def test_replayability_precedence(async_session, pools, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", BASE)
    zip_path = tmp_path / "seed.zip"
    async with async_session() as db:
        a = await _user(db, "a")
        admin = await _user(db, "admin")
        # Every rule fails at once: a blind run in progress, excluded, built
        # before the cutoff, at an older layer count, files gone.
        seed = await _seed(db, "deadbeef0001", layers=12, folder_path=str(zip_path))
        seed.set_seed_excluded_at = BASE
        seed.set_seed_excluded_reason = "Broken warp"
        seed.set_seed_excluded_by_id = admin.id
        blind = await _add_run(
            db,
            user=a,
            igt_ms=0,
            minute=1,
            race_status=RaceStatus.RUNNING,
            status=ParticipantStatus.PLAYING,
            finished=False,
            seed=seed,
        )
        await db.commit()

        steps: list[tuple[bool, str | None, str | None]] = []

        async def check() -> None:
            result = await seed_replayability(db, seed)
            steps.append((result.public, result.code, result.reason))

        await check()
        race = await db.get(Race, blind.race_id)
        assert race is not None
        race.status = RaceStatus.FINISHED
        await db.flush()
        await check()
        seed.set_seed_excluded_at = None
        await db.flush()
        await check()
        seed.created_at = BASE
        await db.flush()
        await check()
        seed.total_layers = 15
        await db.flush()
        await check()
        zip_path.write_bytes(b"zip")
        await check()

    assert steps == [
        (False, "in_progress", "A blind run on this seed is still in progress."),
        (True, "excluded", "Excluded from Set Seed: Broken warp"),
        (True, "old_game_version", "Built for an older game version."),
        (True, "old_category", "Built for an older version of Sprint."),
        (True, "purged", "Files purged."),
        (True, None, None),
    ]


async def test_running_set_seed_race_does_not_block(async_session, pools, tmp_path):
    zip_path = tmp_path / "seed.zip"
    zip_path.write_bytes(b"zip")
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "feedface0001", folder_path=str(zip_path))
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await _add_run(
            db,
            user=b,
            igt_ms=0,
            minute=2,
            mode=RunMode.SET_SEED,
            race_status=RaceStatus.RUNNING,
            status=ParticipantStatus.PLAYING,
            finished=False,
            seed=seed,
        )
        await _add_session(
            db,
            b,
            "sprint",
            RunMode.SET_SEED,
            0,
            status=TrainingSessionStatus.ACTIVE,
            finished_at=None,
            seed=seed,
        )
        await db.commit()

        replay_only = await seed_replayability(db, seed)

        await _add_session(
            db,
            b,
            "sprint",
            RunMode.SPEEDRUN,
            0,
            status=TrainingSessionStatus.ACTIVE,
            finished_at=None,
            seed=seed,
        )
        await db.flush()
        blind_solo = await seed_replayability(db, seed)

    assert (replay_only.public, replay_only.replayable) == (True, True)
    assert (blind_solo.public, blind_solo.code) == (False, "in_progress")


async def test_setup_blind_race_hides_the_page(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        seed = await _seed(db, "facade000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await _add_run(
            db,
            user=a,
            igt_ms=0,
            minute=2,
            mode=RunMode.NORMAL,
            race_status=RaceStatus.SETUP,
            status=ParticipantStatus.REGISTERED,
            finished=False,
            seed=seed,
        )
        await db.commit()

        result = await seed_replayability(db, seed)

    assert (result.public, result.code) == (False, "in_progress")


async def test_excluded_seed_leaves_set_board_only(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        seed = await _seed(db, "c0ffee000001")
        seed.set_seed_excluded_at = BASE
        seed.set_seed_excluded_reason = "Softlock"
        blind = await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await db.commit()

        runs = await load_counted_runs(db)

    every = frozenset(RUN_TYPES)
    random_board = filter_board(
        runs, category="sprint", sub="random", deathless_only=False, types=every
    )
    set_board = filter_board(runs, category="sprint", sub="set", deathless_only=False, types=every)
    assert [r.run_id for r in random_board] == [blind.id]
    assert set_board == []


async def test_top_seed_numbers_orders_by_best_time(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        slow_then_fast = await _seed(db, "aaaa00000001")
        await _add_run(db, user=a, igt_ms=3000, minute=1, seed=slow_then_fast)
        await _add_run(db, user=b, igt_ms=1500, minute=2, seed=slow_then_fast)
        replayed = await _seed(db, "aaaa00000002")
        await _add_session(db, a, "sprint", RunMode.SET_SEED, 2000, seed=replayed)
        third = await _seed(db, "aaaa00000003")
        await _add_run(db, user=a, igt_ms=2500, minute=3, seed=third)
        excluded = await _seed(db, "aaaa00000004")
        excluded.set_seed_excluded_at = BASE
        await _add_run(db, user=a, igt_ms=1000, minute=4, seed=excluded)
        other_category = await _seed(db, "aaaa00000005", pool="standard", layers=30)
        await _add_run(db, user=a, igt_ms=500, minute=5, seed=other_category)
        await db.commit()

        runs = await load_counted_runs(db)

    assert top_seed_numbers(runs, "sprint", 10) == [
        "aaaa00000001",
        "aaaa00000002",
        "aaaa00000003",
    ]
    assert top_seed_numbers(runs, "sprint", 2) == ["aaaa00000001", "aaaa00000002"]


async def test_counted_runs_of_one_seed_keep_unlisted_layer_counts(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        old = await _seed(db, "01d000000001", pool="standard", layers=25)
        race_run = await _add_run(db, user=a, igt_ms=1000, minute=1, seed=old)
        solo_run = await _add_session(db, a, "standard", RunMode.SPEEDRUN, 1100, seed=old)
        current = await _seed(db, "01d000000002", pool="standard", layers=30)
        current_run = await _add_run(db, user=a, igt_ms=900, minute=2, seed=current)
        await db.commit()

        of_old = await load_counted_runs(db, seed_id=old.id)
        of_current = await load_counted_runs(db, seed_id=current.id)
        everything = await load_counted_runs(db)

    assert {(r.run_id, r.category) for r in of_old} == {
        (race_run.id, "standard@25"),
        (solo_run.id, "standard@25"),
    }
    assert [(r.run_id, r.category) for r in of_current] == [(current_run.id, "standard")]
    assert [r.run_id for r in everything] == [current_run.id]


def test_seed_category_names_an_old_layer_count():
    standard = Pool(name="standard", config={"name": "Standard", "layers_count": 30})
    unversioned = Pool(name="casual", config={"name": "Casual"})

    assert seed_category(standard, 30) == ("standard", "Standard")
    assert seed_category(standard, 25) == ("standard@25", "Standard (25 layers)")
    assert seed_category(unversioned, 17) == ("casual", "Casual")


NOW = BASE + timedelta(days=60)


async def _played(db: AsyncSession, seed: Seed, user, igt_ms: int, days_ago: int) -> None:
    """A finished run on ``seed`` whose race last moved ``days_ago`` days before NOW."""
    await _add_run(db, user=user, igt_ms=igt_ms, minute=1, seed=seed)
    race = (await db.execute(select(Race).where(Race.seed_id == seed.id))).scalar_one()
    race.started_at = NOW - timedelta(days=days_ago)


async def _purgeable(async_session, **kwargs) -> set[str]:
    async with async_session() as db:
        return {s.seed_number for s in await purgeable_seeds(db, now=NOW, **kwargs)}


async def test_purgeable_seeds_keeps_protected_top_and_recent(async_session, pools, monkeypatch):
    monkeypatch.setattr(settings, "set_seed_kept_top_seeds", 1)
    async with async_session() as db:
        user = await _user(db, "a")
        top = await _seed(db, "aaaa00000001", status=SeedStatus.DISCARDED)
        await _played(db, top, user, 1000, 40)
        protected = await _seed(db, "aaaa00000002", status=SeedStatus.DISCARDED)
        await _played(db, protected, user, 2000, 40)
        db.add(SeedProtection(user_id=user.id, seed_id=protected.id))
        recent = await _seed(db, "aaaa00000003", status=SeedStatus.DISCARDED)
        await _played(db, recent, user, 3000, 10)
        stale = await _seed(db, "aaaa00000004", status=SeedStatus.DISCARDED)
        await _played(db, stale, user, 4000, 40)
        consumed = await _seed(db, "aaaa00000005", status=SeedStatus.CONSUMED)
        await _played(db, consumed, user, 5000, 40)
        await db.commit()

    assert await _purgeable(async_session) == {"aaaa00000004"}


async def test_purgeable_seeds_lists_pre_cutoff_seeds_even_protected(
    async_session, pools, monkeypatch
):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", BASE)
    async with async_session() as db:
        user = await _user(db, "a")
        old = await _seed(db, "aaaa00000001", status=SeedStatus.DISCARDED)
        old.created_at = BASE - timedelta(days=5)
        await _played(db, old, user, 1000, 1)
        db.add(SeedProtection(user_id=user.id, seed_id=old.id))
        fresh = await _seed(db, "aaaa00000002", status=SeedStatus.DISCARDED)
        fresh.created_at = BASE + timedelta(days=1)
        await _played(db, fresh, user, 2000, 1)
        await db.commit()

    assert await _purgeable(async_session) == {"aaaa00000001"}


async def test_purgeable_seeds_filters_pool_and_age(async_session, pools):
    async with async_session() as db:
        sprint = await _seed(db, "aaaa00000001", status=SeedStatus.DISCARDED)
        sprint.created_at = NOW - timedelta(days=50)
        young = await _seed(db, "aaaa00000002", status=SeedStatus.DISCARDED)
        young.created_at = NOW - timedelta(days=5)
        standard = await _seed(
            db, "bbbb00000001", pool="standard", layers=30, status=SeedStatus.DISCARDED
        )
        standard.created_at = NOW - timedelta(days=50)
        await db.commit()

    assert await _purgeable(async_session) == {"aaaa00000001", "aaaa00000002", "bbbb00000001"}
    assert await _purgeable(async_session, pool="sprint") == {"aaaa00000001", "aaaa00000002"}
    assert await _purgeable(async_session, pool="sprint", older_than_days=30) == {"aaaa00000001"}


async def test_purgeable_seeds_never_played_discarded_seed_is_listed(async_session, pools):
    async with async_session() as db:
        await _seed(db, "aaaa00000001", status=SeedStatus.DISCARDED)
        await db.commit()

    assert await _purgeable(async_session) == {"aaaa00000001"}
