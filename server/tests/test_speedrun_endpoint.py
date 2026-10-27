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
    db: AsyncSession, user: User, igt_ms: int, minute: int, *, daily: bool = False
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
