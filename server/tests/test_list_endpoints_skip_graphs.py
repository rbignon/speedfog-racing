"""List endpoints must not read the heavy JSON columns they never render.

A seed's graph_json averages ~120 KB and a zone_history several KB; decoding
them for every row of a list blocked the event loop for over a second on a
veteran's dashboard. These tests watch the SQL each endpoint emits.
"""

import os
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
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
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)

ZONE_HISTORY = [
    {"node_id": "start", "igt_ms": 0, "type": "spawn"},
    {"node_id": "stormveil", "igt_ms": 60_000, "type": "fog"},
]


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def data(async_session, sample_graph_json):
    """A player with a finished race, an organized race still in setup, an
    open race by someone else, and a training session, each on its own seed."""
    async with async_session() as db:
        player = User(
            twitch_id="lp", twitch_username="lp", api_token="lp_token", role=UserRole.ORGANIZER
        )
        other = User(
            twitch_id="lo", twitch_username="lo", api_token="lo_token", role=UserRole.ORGANIZER
        )
        db.add_all([player, other])
        await db.flush()

        seeds = []
        for i in range(4):
            seed = Seed(
                seed_number=f"ls{i}",
                pool_name="standard",
                graph_json=sample_graph_json,
                total_layers=5,
                folder_path=f"/t/ls{i}",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            seeds.append(seed)
        await db.flush()

        finished = Race(
            name="Finished",
            organizer_id=other.id,
            seed_id=seeds[0].id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        organized = Race(
            name="Organized",
            organizer_id=player.id,
            seed_id=seeds[1].id,
            status=RaceStatus.SETUP,
        )
        open_race = Race(
            name="Open",
            organizer_id=other.id,
            seed_id=seeds[2].id,
            status=RaceStatus.SETUP,
            open_registration=True,
            scheduled_at=datetime.now(UTC),
        )
        db.add_all([finished, organized, open_race])
        await db.flush()
        for race, user, status in (
            (finished, player, ParticipantStatus.FINISHED),
            (finished, other, ParticipantStatus.FINISHED),
            (open_race, other, ParticipantStatus.REGISTERED),
        ):
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    mod_token=f"lm-{race.name}-{user.twitch_username}",
                    status=status,
                    igt_ms=100_000,
                    zone_history=ZONE_HISTORY,
                )
            )
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seeds[3].id,
                mod_token="lt",
                status=TrainingSessionStatus.ACTIVE,
                zone_history=ZONE_HISTORY,
                current_zone="stormveil",
            )
        )
        await db.commit()


@pytest.fixture
async def client(async_session):
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer lp_token"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def statements(async_engine):
    captured: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        captured.append(statement)

    event.listen(async_engine.sync_engine, "before_cursor_execute", capture)
    yield captured
    event.remove(async_engine.sync_engine, "before_cursor_execute", capture)


def _count(body: dict | list) -> int:
    if isinstance(body, list):
        return len(body)
    return len(body.get("races", body.get("items", [])))


@pytest.mark.parametrize(
    "path",
    [
        "/api/users/lp/activity",
        "/api/races",
        "/api/races?status=finished&offset=0&limit=10",
        "/api/races/joinable",
        "/api/users/me/races",
    ],
)
async def test_list_skips_graph_and_history(data, client, statements, path):
    response = await client.get(path)

    assert response.status_code == 200
    assert _count(response.json()) > 0  # rows were listed, the check is not vacuous
    offending = [s for s in statements if "graph_json" in s or "zone_history" in s]
    assert offending == []


async def test_training_list_reads_each_graph_once(data, client, statements):
    """The list derives layers from the process-wide seed projection, so a
    seed's graph is read on first sight only."""
    first = await client.get("/api/training")
    assert first.status_code == 200
    assert _count(first.json()) > 0
    statements.clear()

    second = await client.get("/api/training")

    assert second.json() == first.json()
    assert [s for s in statements if "graph_json" in s] == []


async def test_training_list_derives_progress_from_the_graph(
    async_session, client, sample_graph_json
):
    """current_layer is the deepest layer visited (the last layer once
    finished) and seed_total_nodes the graph's own node count."""
    async with async_session() as db:
        user = User(twitch_id="tp", twitch_username="tp", api_token="tp_token")
        db.add(user)
        await db.flush()
        for i, status in enumerate((TrainingSessionStatus.ACTIVE, TrainingSessionStatus.FINISHED)):
            seed = Seed(
                seed_number=f"tps{i}",
                pool_name="standard",
                graph_json=sample_graph_json,
                total_layers=13,
                folder_path=f"/t/tps{i}",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            db.add(
                TrainingSession(
                    user_id=user.id,
                    seed_id=seed.id,
                    mod_token=f"tpm{i}",
                    status=status,
                    # Revisiting a shallower node must not lower the layer.
                    zone_history=[
                        {"node_id": "chapel_start_4f96", "igt_ms": 0},
                        {"node_id": "siofra_nokron_gargoyles_fd23", "igt_ms": 10},
                        {"node_id": "academy_d5a9", "igt_ms": 20},
                    ],
                )
            )
        await db.commit()

    response = await client.get("/api/training", headers={"Authorization": "Bearer tp_token"})

    by_status = {s["status"]: s for s in response.json()}
    assert by_status["active"]["current_layer"] == 2
    assert by_status["finished"]["current_layer"] == 13
    assert by_status["active"]["seed_total_nodes"] == sample_graph_json["total_nodes"]
