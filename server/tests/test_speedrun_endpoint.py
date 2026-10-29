"""GET /api/stats/speedrun and /api/stats/speedrun/{pool}."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionMode,
    TrainingSessionStatus,
    User,
    UserRole,
)

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


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
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _add_run(
    db: AsyncSession,
    user: User,
    igt_ms: int,
    minute: int,
    *,
    daily: bool = False,
    set_seed: bool = False,
    deathless: bool = False,
) -> None:
    tag = uuid.uuid4().hex[:10]
    seed = Seed(
        seed_number=f"seed{tag}",
        pool_name="sprint",
        graph_json={"nodes": {}},
        total_layers=15,
        folder_path=f"/t/{tag}",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    race = Race(
        name=f"Race {tag}",
        organizer_id=user.id,
        seed_id=seed.id,
        status=RaceStatus.FINISHED,
        started_at=BASE,
        set_seed=set_seed,
        deathless=deathless,
        exclude_from_stats=daily,
        daily_date=date(2026, 10, 1) + timedelta(days=minute) if daily else None,
    )
    db.add(race)
    await db.flush()
    db.add(
        Participant(
            race_id=race.id,
            user_id=user.id,
            mod_token=f"mt-{tag}",
            status=ParticipantStatus.FINISHED,
            igt_ms=igt_ms,
            finished_at=BASE + timedelta(minutes=minute),
        )
    )
    await db.flush()


@pytest.fixture
async def sprint_runs(async_session) -> dict[str, User]:
    """A finishes a sprint race at 1000 ms, B a sprint Daily Seed at 1100 ms."""
    async with async_session() as db:
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race", "sort_order": 20}))
        users = {}
        for name in ("a", "b"):
            users[name] = User(
                twitch_id=f"id-{name}",
                twitch_username=name,
                api_token=f"tok-{name}",
                role=UserRole.USER,
            )
            db.add(users[name])
        await db.flush()
        await _add_run(db, users["a"], 1000, 1)
        await _add_run(db, users["b"], 1100, 2, daily=True)
        await db.commit()
    return users


async def test_overview_lists_categories_and_counts(test_client, sprint_runs):
    data = (await test_client.get("/api/stats/speedrun")).json()

    assert [c["pool"] for c in data["categories"]] == ["sprint"]
    assert (data["runs"], data["players"]) == (2, 2)
    assert [r["user"]["twitch_username"] for r in data["recent_runs"]] == ["b", "a"]


async def test_board_types_filter(test_client, sprint_runs):
    data = (await test_client.get("/api/stats/speedrun/sprint?types=daily")).json()

    assert [r["user"]["twitch_username"] for r in data["runs"]] == ["b"]


async def test_board_obsolete_rows_have_null_rank(test_client, async_session, sprint_runs):
    async with async_session() as db:
        await _add_run(db, sprint_runs["a"], 1200, 3)
        await db.commit()

    data = (await test_client.get("/api/stats/speedrun/sprint?obsolete=true")).json()

    assert [(r["igt_ms"], r["rank"]) for r in data["runs"]] == [(1000, 1), (1100, 2), (1200, None)]


@pytest.mark.parametrize("types", ["", "bogus", "race,bogus"])
async def test_board_rejects_bad_types(test_client, sprint_runs, types):
    response = await test_client.get(f"/api/stats/speedrun/sprint?types={types}")

    assert response.status_code == 422


async def test_board_unknown_pool_404(test_client, sprint_runs):
    response = await test_client.get("/api/stats/speedrun/nope")

    assert response.status_code == 404


async def test_board_cache_holds_serialized_json(test_client, sprint_runs):
    """A board can hold thousands of rows (obsolete runs) and lives in the
    cache for good: kept as one JSON bytes object, it adds nothing to the GC's
    tracked objects, unlike a model graph."""
    from speedfog_racing.api.stats import _stats_cache

    response = await test_client.get("/api/stats/speedrun/sprint?obsolete=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert [r["rank"] for r in response.json()["runs"]] == [1, 2]
    boards = [
        value for key, (_, value) in _stats_cache.items() if key.startswith("speedrun:board:")
    ]
    assert boards and all(isinstance(value, bytes) for value in boards)


async def test_board_sub_defaults_to_set_and_rejects_others(test_client, sprint_runs):
    default = await test_client.get("/api/stats/speedrun/sprint")
    explicit = await test_client.get("/api/stats/speedrun/sprint?sub=set")
    bad = await test_client.get("/api/stats/speedrun/sprint?sub=any")

    assert bad.status_code == 422
    assert default.json() == explicit.json()


async def test_board_random_seed_empty_when_only_replays(test_client, async_session, sprint_runs):
    async with async_session() as db:
        await db.execute(Race.__table__.update().values(set_seed=True))
        await db.commit()

    response = await test_client.get("/api/stats/speedrun/sprint?sub=random")

    assert response.status_code == 200
    assert response.json()["runs"] == []
    assert response.json()["record_seed"] is None


async def test_board_types_accept_solo(test_client, async_session, sprint_runs):
    async with async_session() as db:
        seed = Seed(
            seed_number="solo-seed",
            pool_name="sprint",
            graph_json={"nodes": {}},
            total_layers=15,
            folder_path="/t/solo",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        db.add(
            TrainingSession(
                user_id=sprint_runs["a"].id,
                seed_id=seed.id,
                mode=TrainingSessionMode.SPEEDRUN,
                status=TrainingSessionStatus.FINISHED,
                igt_ms=500,
                finished_at=BASE,
            )
        )
        await db.commit()

    solo = (await test_client.get("/api/stats/speedrun/sprint?types=solo")).json()
    races = (await test_client.get("/api/stats/speedrun/sprint?types=race,daily")).json()

    assert [(r["igt_ms"], r["race_id"], r["blind"]) for r in solo["runs"]] == [(500, None, True)]
    assert solo["runs"][0]["session_id"] is not None
    assert solo["record_seed"] == {"seed_number": "solo-seed", "runs": 1}
    assert [r["igt_ms"] for r in races["runs"]] == [1000, 1100]


async def test_board_cache_keys_split_by_sub_and_deathless(test_client, async_session, sprint_runs):
    from speedfog_racing.api.stats import _stats_cache

    async with async_session() as db:
        await _add_run(db, sprint_runs["a"], 700, 6, deathless=True)
        await db.commit()

    base = "/api/stats/speedrun/sprint"
    set_board = (await test_client.get(base)).json()
    random_board = (await test_client.get(f"{base}?sub=random")).json()
    deathless = (await test_client.get(f"{base}?deathless=true")).json()

    assert [r["igt_ms"] for r in set_board["runs"]] == [700, 1100]
    assert [r["igt_ms"] for r in deathless["runs"]] == [700]
    assert random_board["runs"] == set_board["runs"]
    keys = [k for k in _stats_cache if k.startswith("speedrun:board:")]
    assert len(keys) == 3
