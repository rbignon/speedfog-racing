"""Integration tests for the GET /api/stats/weapons endpoint."""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)


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
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _seed_finished_race(
    session_factory,
    pool_name: str,
    started_at: datetime,
    histories: list[list[dict]],
) -> None:
    """Insert a finished public race with N participants, each carrying one of
    the provided crafted zone_history JSON arrays. Returns nothing; callers
    only need the data to be in the DB."""
    async with session_factory() as db:
        organizer = User(
            twitch_id=f"o-{pool_name}-{started_at.timestamp()}",
            twitch_username=f"org-{pool_name}",
            api_token=f"tok-org-{pool_name}-{started_at.timestamp()}",
            role=UserRole.ORGANIZER,
        )
        db.add(organizer)
        await db.flush()

        seed = Seed(
            seed_number=f"s-{pool_name}-{started_at.timestamp()}",
            pool_name=pool_name,
            graph_json={"nodes": {}, "total_layers": 1},
            total_layers=1,
            folder_path=f"/t/{pool_name}",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name=f"R-{pool_name}",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=started_at,
        )
        db.add(race)
        await db.flush()

        for i, history in enumerate(histories):
            u = User(
                twitch_id=f"u-{pool_name}-{started_at.timestamp()}-{i}",
                twitch_username=f"p-{pool_name}-{i}-{started_at.timestamp()}",
                api_token=f"tok-{pool_name}-{i}-{started_at.timestamp()}",
                role=UserRole.USER,
            )
            db.add(u)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=u.id,
                    mod_token=f"mt-{pool_name}-{i}-{started_at.timestamp()}",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1_000_000,
                    death_count=0,
                    zone_history=history,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_weapon_stats_aggregates_ticks_across_participants(test_client, async_session):
    """Two participants on the same race with overlapping combos aggregate by ids."""
    now = datetime.now(UTC)
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [{"ids": [2000025], "ticks": 4}],
                }
            ],
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [{"ids": [2000025], "ticks": 3}],
                }
            ],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons")

    assert response.status_code == 200
    combos = response.json()["combos"]
    by_ids = {tuple(c["ids"]): c for c in combos}
    assert (2000000,) in by_ids
    assert by_ids[(2000000,)]["total_ticks"] == 7
    assert by_ids[(2000000,)]["race_count"] == 1
    assert by_ids[(2000000,)]["player_count"] == 2


@pytest.mark.asyncio
async def test_weapon_stats_distinguishes_swapped_dual_combos(test_client, async_session):
    """``[X, Y]`` and ``[Y, X]`` show up as two separate combos."""
    now = datetime.now(UTC)
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [3070000, 2000025], "ticks": 2},
                        {"ids": [2000025, 3070000], "ticks": 1},
                    ],
                }
            ],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons")

    assert response.status_code == 200
    pairs = {tuple(c["ids"]) for c in response.json()["combos"]}
    assert (3070000, 2000000) in pairs
    assert (2000000, 3070000) in pairs


@pytest.mark.asyncio
async def test_weapon_stats_pool_filter(test_client, async_session):
    """Pool filter excludes races from other pools."""
    now = datetime.now(UTC)
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [{"node_id": "z1", "igt_ms": 0, "weapons": [{"ids": [2000025], "ticks": 1}]}],
        ],
    )
    await _seed_finished_race(
        async_session,
        pool_name="other",
        started_at=now,
        histories=[
            [{"node_id": "z1", "igt_ms": 0, "weapons": [{"ids": [1000000], "ticks": 1}]}],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons?pool=standard")

    assert response.status_code == 200
    pairs = {tuple(c["ids"]) for c in response.json()["combos"]}
    assert (2000000,) in pairs
    assert (1000000,) not in pairs


@pytest.mark.asyncio
async def test_weapon_stats_days_filter(test_client, async_session):
    """``days`` excludes races started before the cutoff."""
    now = datetime.now(UTC)
    old = now - timedelta(days=10)
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [{"node_id": "z1", "igt_ms": 0, "weapons": [{"ids": [2000025], "ticks": 1}]}],
        ],
    )
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=old,
        histories=[
            [{"node_id": "z1", "igt_ms": 0, "weapons": [{"ids": [5000000], "ticks": 1}]}],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons?days=1")

    assert response.status_code == 200
    pairs = {tuple(c["ids"]) for c in response.json()["combos"]}
    assert (2000000,) in pairs
    assert (5000000,) not in pairs


@pytest.mark.asyncio
async def test_weapon_stats_merges_affinity_variants_of_same_base(test_client, async_session):
    """Standard and Cold Rotten Greataxe (same base 23150000) aggregate into one combo."""
    now = datetime.now(UTC)
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [23150025], "ticks": 51},
                        {"ids": [23150925], "ticks": 200},
                    ],
                }
            ],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons")

    assert response.status_code == 200
    combos = response.json()["combos"]
    by_ids = {tuple(c["ids"]): c for c in combos}
    assert (23150000,) in by_ids
    assert by_ids[(23150000,)]["total_ticks"] == 251


@pytest.mark.asyncio
async def test_weapon_stats_top_player_is_user_with_most_ticks_on_combo(test_client, async_session):
    """The top player for a combo is the user with the most ticks on it,
    regardless of whether it is their personal dominant."""
    now = datetime.now(UTC)
    # Player 0: X=100 ticks, Y=20 ticks. Player 1: Y=80 ticks.
    # X top = Player 0 (100 > nobody), Y top = Player 1 (80 > 20).
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [2000025], "ticks": 100},
                        {"ids": [3070000], "ticks": 20},
                    ],
                }
            ],
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [3070000], "ticks": 80},
                    ],
                }
            ],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons")

    assert response.status_code == 200
    combos = response.json()["combos"]
    by_ids = {tuple(c["ids"]): c for c in combos}

    x = by_ids[(2000000,)]
    y = by_ids[(3070000,)]
    # Player 0 has the most ticks on X (100).
    assert x["top_player_username"] is not None
    # Player 1 has the most ticks on Y (80 > 20).
    assert y["top_player_username"] is not None
    # The two top players are different users.
    assert x["top_player_username"] != y["top_player_username"]
    # Player counts unchanged.
    assert x["player_count"] == 1
    assert y["player_count"] == 2
    # Avatar URL key must be present in the response (seed helper sets no avatar, so None).
    assert "top_player_avatar_url" in x
    assert "top_player_avatar_url" in y


@pytest.mark.asyncio
async def test_weapon_stats_same_user_can_be_top_of_multiple_combos(test_client, async_session):
    """A user can be the top player on more than one combo when they out-tick
    everyone else on each."""
    now = datetime.now(UTC)
    # Player 0: X=100, Y=50. Player 1: Y=10. Player 0 is top on both.
    await _seed_finished_race(
        async_session,
        pool_name="standard",
        started_at=now,
        histories=[
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [2000025], "ticks": 100},
                        {"ids": [3070000], "ticks": 50},
                    ],
                }
            ],
            [
                {
                    "node_id": "z1",
                    "igt_ms": 0,
                    "weapons": [
                        {"ids": [3070000], "ticks": 10},
                    ],
                }
            ],
        ],
    )

    async with test_client as client:
        response = await client.get("/api/stats/weapons")

    assert response.status_code == 200
    by_ids = {tuple(c["ids"]): c for c in response.json()["combos"]}
    x = by_ids[(2000000,)]
    y = by_ids[(3070000,)]
    # Same user tops both.
    assert x["top_player_username"] is not None
    assert y["top_player_username"] is not None
    assert x["top_player_username"] == y["top_player_username"]
