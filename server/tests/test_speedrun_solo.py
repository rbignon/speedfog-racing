"""Ranked solo runs: POST /api/speedrun/solo, fresh-seeds and the seed summary."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Pool,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    UserRole,
)
from speedfog_racing.services.seed_service import SpeedrunFloorError
from speedfog_racing.services.set_seed_service import seed_replayability
from speedfog_racing.services.training_service import (
    SpeedrunStartError,
    create_set_seed_session,
    create_speedrun_session,
    expire_speedrun_sessions,
)

from .test_set_seed_service import _seed
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
def test_client(async_session):
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", None)
    monkeypatch.setattr(settings, "speedrun_default_floor", 2)


@pytest.fixture
async def pools(async_session):
    async with async_session() as db:
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race", "layers_count": 15}))
        db.add(
            Pool(
                name="training_sprint",
                config={"name": "Sprint", "type": "training", "layers_count": 15},
            )
        )
        db.add(Pool(name="off", enabled=False, config={"name": "Off", "type": "race"}))
        await db.commit()


@pytest.fixture
def seed_zip(tmp_path) -> str:
    path = tmp_path / "seed.zip"
    path.write_bytes(b"zip")
    return str(path)


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer tok-{name}"}


async def _available(db: AsyncSession, pool: str, count: int) -> list[Seed]:
    return [
        await _seed(db, f"{pool}{i:08d}", pool=pool, status=SeedStatus.AVAILABLE)
        for i in range(count)
    ]


async def test_speedrun_session_draws_and_consumes_a_race_pool_seed(async_session, pools):
    async with async_session() as db:
        user = await _user(db, "a")
        race_seeds = await _available(db, "sprint", 3)
        training_seeds = await _available(db, "training_sprint", 5)
        session = await create_speedrun_session(db, user.id, "sprint")
        await db.commit()
        race_ids = {s.id for s in race_seeds}
        training_ids = {s.id for s in training_seeds}

        assert session.mode == RunMode.SPEEDRUN
        assert session.seed_id in race_ids and session.seed_id not in training_ids
        assert session.seed.status == SeedStatus.CONSUMED
        statuses = [s.status for s in race_seeds]
        assert statuses.count(SeedStatus.CONSUMED) == 1


async def test_speedrun_session_refused_at_floor(async_session, pools):
    async with async_session() as db:
        user = await _user(db, "a")
        await _available(db, "sprint", 2)  # floor is 2: needs more than 2
        with pytest.raises(SpeedrunStartError) as error:
            await create_speedrun_session(db, user.id, "sprint")
        assert (error.value.code, error.value.message) == (
            "no_fresh_seed",
            str(SpeedrunFloorError()),
        )


@pytest.mark.parametrize("pool", ["training_sprint", "off", "missing"])
async def test_speedrun_session_needs_an_enabled_race_pool(async_session, pools, pool):
    async with async_session() as db:
        user = await _user(db, "a")
        await _available(db, pool, 5)
        with pytest.raises(SpeedrunStartError) as error:
            await create_speedrun_session(db, user.id, pool)
        assert error.value.code == "unknown_pool"


async def test_cancelled_speedrun_session_keeps_seed(test_client, async_session, pools):
    async with async_session() as db:
        await _user(db, "a")
        await _available(db, "sprint", 4)
        await db.commit()

    created = await test_client.post(
        "/api/speedrun/solo", json={"pool": "sprint"}, headers=_auth("a")
    )
    assert created.status_code == 201
    assert created.json()["mode"] == "speedrun"
    cancelled = await test_client.post(
        f"/api/training/{created.json()['id']}/abandon", headers=_auth("a")
    )

    assert cancelled.json()["status"] == "cancelled"
    async with async_session() as db:
        session = (await db.execute(select(TrainingSession))).scalar_one()
        seed = await db.get(Seed, session.seed_id)
        assert seed is not None and seed.status == SeedStatus.CONSUMED


async def test_set_seed_session_requires_replayable(async_session, pools, seed_zip):
    async with async_session() as db:
        user = await _user(db, "a")
        other = await _user(db, "b")
        replayable = await _seed(db, "5eed00000001", folder_path=seed_zip)
        await _add_run(db, user=other, igt_ms=1000, minute=1, seed=replayable)
        blind = await _seed(db, "b11d00000001", folder_path=seed_zip)
        await _add_run(
            db, user=other, igt_ms=1000, minute=2, seed=blind, race_status=RaceStatus.RUNNING
        )
        fresh = await _seed(db, "fe5400000001", folder_path=seed_zip, status=SeedStatus.AVAILABLE)

        session = await create_set_seed_session(db, user.id, "5eed00000001")
        assert (session.mode, session.seed_id) == (RunMode.SET_SEED, replayable.id)
        assert replayable.status == SeedStatus.CONSUMED
        session.status = TrainingSessionStatus.ABANDONED
        await db.flush()

        with pytest.raises(SpeedrunStartError) as in_progress:
            await create_set_seed_session(db, user.id, "b11d00000001")
        with pytest.raises(SpeedrunStartError) as unknown:
            await create_set_seed_session(db, user.id, fresh.seed_number)
        assert in_progress.value.code == "not_replayable"
        assert in_progress.value.message == "A blind run on this seed is still in progress."
        assert unknown.value.code == "unknown_seed"
        assert fresh.status == SeedStatus.AVAILABLE


async def test_one_active_session_across_modes(async_session, pools, seed_zip):
    async with async_session() as db:
        user = await _user(db, "a")
        other = await _user(db, "b")
        await _available(db, "sprint", 4)
        replayable = await _seed(db, "5eed00000001", folder_path=seed_zip)
        await _add_run(db, user=other, igt_ms=1000, minute=1, seed=replayable)
        await _add_session(
            db, user, "sprint", RunMode.NORMAL, 0, status=TrainingSessionStatus.ACTIVE
        )
        for start in (
            create_speedrun_session(db, user.id, "sprint"),
            create_set_seed_session(db, user.id, "5eed00000001"),
        ):
            with pytest.raises(SpeedrunStartError) as error:
                await start
            assert error.value.code == "active_session"


async def test_solo_endpoint_mapping(test_client, async_session, pools, seed_zip):
    async with async_session() as db:
        user = await _user(db, "a")
        other = await _user(db, "b")
        await _user(db, "banned", banned=True)
        await _available(db, "sprint", 2)
        for number, igt in (("abcdef111111", 1000), ("abcdef222222", 1100)):
            seed = await _seed(db, number, folder_path=seed_zip)
            await _add_run(db, user=other, igt_ms=igt, minute=1, seed=seed)
        blind = await _seed(db, "b11d00000001", folder_path=seed_zip)
        await _add_run(
            db, user=other, igt_ms=1, minute=2, seed=blind, race_status=RaceStatus.RUNNING
        )
        user_id = user.id
        await db.commit()

    async def post(body: dict[str, Any], who: str = "a") -> Any:
        return await test_client.post("/api/speedrun/solo", json=body, headers=_auth(who))

    for body in ({}, {"pool": "sprint", "seed": "abcdef111111"}):
        assert (await post(body)).status_code == 422
    unknown_pool = await post({"pool": "nope"})
    floor = await post({"pool": "sprint"})
    unknown_seed = await post({"seed": "zzzzzz"})
    ambiguous = await post({"seed": "abcdef"})
    in_progress = await post({"seed": "b11d00000001"})
    banned = await post({"pool": "sprint"}, "banned")
    ok = await post({"seed": "abcdef111111"})
    active = await post({"seed": "abcdef222222"})

    assert (unknown_pool.status_code, unknown_pool.json()["detail"]) == (404, "Unknown pool")
    assert (floor.status_code, floor.json()["detail"]) == (409, "No fresh seed right now")
    assert (unknown_seed.status_code, unknown_seed.json()["detail"]) == (404, "Unknown seed")
    assert (ambiguous.status_code, ambiguous.json()["detail"]) == (409, "Ambiguous seed ID")
    assert (in_progress.status_code, in_progress.json()["detail"]) == (
        409,
        "A blind run on this seed is still in progress.",
    )
    assert banned.status_code == 403
    assert (ok.status_code, ok.json()["mode"], ok.json()["user"]["id"]) == (
        201,
        "set_seed",
        str(user_id),
    )
    assert ok.json()["invalidated"] is False
    assert (active.status_code, active.json()["detail"]) == (
        409,
        "You already have an active solo session",
    )


async def test_fresh_seeds(test_client, async_session, pools):
    async with async_session() as db:
        await _available(db, "sprint", 3)
        await _available(db, "training_sprint", 9)
        await _available(db, "off", 9)
        await db.commit()

    fresh = await test_client.get("/api/speedrun/fresh-seeds", params={"pool": "sprint"})
    training = await test_client.get(
        "/api/speedrun/fresh-seeds", params={"pool": "training_sprint"}
    )
    missing = await test_client.get("/api/speedrun/fresh-seeds", params={"pool": "nope"})
    # /solo refuses a disabled pool: so does the window's freshness check.
    disabled = await test_client.get("/api/speedrun/fresh-seeds", params={"pool": "off"})

    assert (fresh.status_code, fresh.json()) == (200, {"fresh": True})
    assert (training.status_code, missing.status_code) == (404, 404)
    assert (disabled.status_code, disabled.json()["detail"]) == (404, "Unknown pool")

    async with async_session() as db:
        pool = (await db.execute(select(Pool).where(Pool.name == "sprint"))).scalar_one()
        pool.speedrun_floor = 3
        await db.commit()
    assert (
        await test_client.get("/api/speedrun/fresh-seeds", params={"pool": "sprint"})
    ).json() == {"fresh": False}


async def test_debug_flags_only_for_admins(test_client, async_session, pools):
    flags = {"no_death": {"seen": 1}}
    async with async_session() as db:
        owner = await _user(db, "a")
        admin = await _user(db, "admin")
        admin.role = UserRole.ADMIN
        session = await _add_session(
            db, owner, "sprint", RunMode.SPEEDRUN, 5, status=TrainingSessionStatus.ACTIVE
        )
        session.debug_flags = flags
        session.invalidated_at = session.created_at
        session.invalidation_reason = "Cheat"
        session_id = session.id
        await db.commit()

    as_owner = (await test_client.get(f"/api/training/{session_id}", headers=_auth("a"))).json()
    as_admin = (await test_client.get(f"/api/training/{session_id}", headers=_auth("admin"))).json()
    anonymous = (await test_client.get(f"/api/training/{session_id}")).json()

    assert [d["debug_flags"] for d in (as_owner, as_admin, anonymous)] == [None, flags, None]
    assert (anonymous["invalidated"], anonymous["invalidation_reason"]) == (True, "Cheat")


async def test_seed_summary(test_client, async_session, pools, seed_zip):
    graph = {"nodes": {"start": {"layer": 0}}}
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "5eed00000001", folder_path=seed_zip)
        seed.graph_json = graph
        await _add_run(db, user=a, igt_ms=1500, minute=1, seed=seed)
        await _add_run(db, user=b, igt_ms=1200, minute=2, seed=seed)
        running = await _seed(db, "b11d00000001", folder_path=seed_zip)
        await _add_run(
            db, user=a, igt_ms=900, minute=3, seed=running, race_status=RaceStatus.RUNNING
        )
        await _seed(db, "fe5400000001", status=SeedStatus.AVAILABLE)
        await _seed(db, "fe5400000002", status=SeedStatus.AVAILABLE)
        await db.commit()

    ok = await test_client.get("/api/speedrun/seeds/5eed00/summary")
    hidden = await test_client.get("/api/speedrun/seeds/b11d00000001/summary")
    unplayed = await test_client.get("/api/speedrun/seeds/fe5400000001/summary")
    typo = await test_client.get("/api/speedrun/seeds/zzzzzzzzzzzz/summary")

    body = ok.json()
    assert "graph_json" not in body
    assert (body["seed_number"], body["category"], body["category_name"]) == (
        "5eed00000001",
        "sprint",
        "Sprint",
    )
    assert (body["replayable"], body["not_replayable_reason"]) == (True, None)
    assert (body["record"]["igt_ms"], body["record"]["user"]["twitch_username"]) == (1200, "b")
    assert hidden.status_code == 200
    assert (hidden.json()["replayable"], hidden.json()["record"]) == (False, None)
    assert hidden.json()["not_replayable_reason"]
    assert (unplayed.status_code, unplayed.json()) == (404, typo.json() | {})
    assert typo.json()["detail"] == "Unknown seed"
    assert (await test_client.get("/api/speedrun/seeds/5eed/summary")).status_code == 404
    assert Path(seed_zip).is_file()


async def test_expired_speedrun_session_frees_the_seed_page(async_session, pools):
    async with async_session() as db:
        user = await _user(db, "a")
        expired = await _add_session(
            db, user, "sprint", RunMode.SPEEDRUN, 5000, status=TrainingSessionStatus.ACTIVE,
            finished_at=None, zone_history=[{"node_id": "start", "igt_ms": 0}],
        )  # fmt: skip
        recent = await _add_session(
            db, await _user(db, "b"), "sprint", RunMode.SPEEDRUN, 0,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
        )  # fmt: skip
        normal = await _add_session(
            db, await _user(db, "c"), "sprint", RunMode.NORMAL, 0,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
        )  # fmt: skip
        set_seed = await _add_session(
            db, await _user(db, "d"), "sprint", RunMode.SET_SEED, 0,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
        )  # fmt: skip
        expired.created_at = BASE - timedelta(hours=25)
        recent.created_at = BASE - timedelta(hours=23)
        normal.created_at = BASE - timedelta(hours=30)
        set_seed.created_at = BASE - timedelta(hours=30)
        seed = expired.seed_id
        await db.commit()
        before = await seed_replayability(db, await db.get(Seed, seed))
        assert before.public is False

        ids = await expire_speedrun_sessions(db, now=BASE)

    assert ids == [expired.id]
    async with async_session() as db:
        rows = {row.id: row for row in (await db.execute(select(TrainingSession))).scalars().all()}
        assert rows[expired.id].status == TrainingSessionStatus.ABANDONED
        assert rows[expired.id].finished_at is not None
        assert rows[expired.id].zone_history == [{"node_id": "start", "igt_ms": 0}]
        for untouched in (recent, normal, set_seed):
            assert rows[untouched.id].status == TrainingSessionStatus.ACTIVE
        assert (await seed_replayability(db, await db.get(Seed, seed))).public is True
