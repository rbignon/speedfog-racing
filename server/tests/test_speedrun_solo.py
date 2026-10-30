"""Ranked solo runs: POST /api/speedrun/solo, fresh-seeds and the seed summary."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    _require_under_unfinished_limit,
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


async def test_expiry_never_overwrites_a_finished_session(async_session, pools):
    async with async_session() as db:
        user = await _user(db, "a")
        done = await _add_session(db, user, "sprint", RunMode.SPEEDRUN, 5000)
        done.created_at = BASE - timedelta(hours=40)
        await db.commit()
        ids = await expire_speedrun_sessions(db, now=BASE)

    assert ids == []
    async with async_session() as db:
        row = await db.get(TrainingSession, done.id)
        assert row is not None and row.status == TrainingSessionStatus.FINISHED


FINAL_BOSS_GRAPH: dict[str, Any] = {
    "nodes": {
        "start": {"type": "start", "layer": 0},
        "mid": {"type": "boss_arena", "layer": 1},
        "end": {"type": "final_boss", "layer": 2},
    }
}
# Older seed eras have no final_boss node type: the highest layer is the end.
OLD_ERA_GRAPH: dict[str, Any] = {
    "nodes": {
        "start": {"type": "start", "layer": 0},
        "mid": {"type": "boss_arena", "layer": 1},
        "end": {"type": "major_boss", "layer": 2},
    }
}


def _history(*nodes: str) -> list[dict[str, Any]]:
    return [
        {"node_id": node, "type": "fog" if i else "spawn", "igt_ms": i * 1000}
        for i, node in enumerate(nodes)
    ]


async def _graph_seed(db: AsyncSession, graph: dict[str, Any]) -> Seed:
    tag = uuid.uuid4().hex[:12]
    seed = Seed(
        seed_number=tag,
        pool_name="sprint",
        graph_json=graph,
        total_layers=3,
        folder_path=f"/t/{tag}",
        status=SeedStatus.CONSUMED,
        created_at=BASE,
    )
    db.add(seed)
    await db.flush()
    return seed


async def _finish(
    async_session: Any, session_id: uuid.UUID
) -> tuple[AsyncMock, MagicMock, MagicMock]:
    """Run the training mod's finish hook on a session loaded the way the
    mod handler loads it; returns the status-change broadcast, the
    record-check scheduler and the rejected-finish admin alert mocks."""
    from speedfog_racing.websocket.training import mod

    async with async_session() as db:
        entity = await mod._load_session(db, session_id)
    with (
        patch.object(mod, "_broadcast_status_change", new_callable=AsyncMock) as broadcast,
        patch.object(mod, "schedule_speedrun_record_check") as check,
        patch.object(mod, "fire_finish_dropped_notification") as alert,
    ):
        handler = mod.TrainingModHandler(MagicMock(), session_id, async_session)
        await handler._handle_finish_event(entity, entity.igt_ms, None)
    return broadcast, check, alert


async def _status(async_session: Any, session_id: uuid.UUID) -> TrainingSessionStatus:
    async with async_session() as db:
        row = await db.get(TrainingSession, session_id)
        assert row is not None
        return row.status


@pytest.mark.parametrize("mode", [RunMode.SPEEDRUN, RunMode.SET_SEED])
@pytest.mark.parametrize(
    ("graph", "path", "counted"),
    [
        (FINAL_BOSS_GRAPH, ("start", "mid", "end"), True),
        (FINAL_BOSS_GRAPH, ("start", "mid"), False),
        (OLD_ERA_GRAPH, ("start", "mid", "end"), True),
        (OLD_ERA_GRAPH, ("start", "mid"), False),
    ],
)
async def test_ranked_finish_needs_the_final_zone_in_the_history(
    async_session, pools, caplog, mode, graph, path, counted
):
    """A ranked solo finish counts only when the run's zone history reached
    the seed's final boss node (the highest layer on a graph without one).
    Otherwise it is dropped: the session stays ACTIVE, no broadcast, no
    record check, and a warning and an admin alert name it."""
    async with async_session() as db:
        seed = await _graph_seed(db, graph)
        session = await _add_session(
            db, await _user(db, "a"), "sprint", mode, 5000,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
            zone_history=_history(*path), seed=seed,
        )  # fmt: skip
        await db.commit()

    with caplog.at_level(logging.WARNING, logger="speedfog_racing.websocket.training.mod"):
        broadcast, check, alert = await _finish(async_session, session.id)

    assert await _status(async_session, session.id) == (
        TrainingSessionStatus.FINISHED if counted else TrainingSessionStatus.ACTIVE
    )
    assert broadcast.await_count == check.call_count == (1 if counted else 0)
    assert ("Finish dropped" in caplog.text) is not counted
    if counted:
        alert.assert_not_called()
    else:
        mode_label = "Speedrun" if mode == RunMode.SPEEDRUN else "Set Seed"
        alert.assert_called_once_with(
            run_name=f"Solo \u00b7 Sprint \u00b7 {mode_label}",
            session_id=str(session.id),
            player_name="a",
            seed_number=seed.seed_number,
            igt_ms=5000,
            reason="Final boss zone not reached",
        )


async def test_practice_finish_needs_no_final_zone(async_session, pools):
    """A practice session finishes on the finish flag alone, as before."""
    async with async_session() as db:
        session = await _add_session(
            db, await _user(db, "a"), "training_sprint", RunMode.NORMAL, 5000,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
            zone_history=_history("start", "mid"), seed=await _graph_seed(db, FINAL_BOSS_GRAPH),
        )  # fmt: skip
        await db.commit()

    broadcast, check, alert = await _finish(async_session, session.id)

    assert await _status(async_session, session.id) == TrainingSessionStatus.FINISHED
    broadcast.assert_awaited_once()
    check.assert_not_called()
    alert.assert_not_called()


async def test_finish_never_overwrites_an_abandoned_session(async_session, pools):
    """An expiry or an abandon landing between the mod's finish report and
    its handler wins: the session stays ABANDONED, with no broadcast and no
    record check. An ACTIVE session still finishes."""
    from speedfog_racing.websocket.training import mod

    async with async_session() as db:
        gone = await _add_session(
            db, await _user(db, "a"), "sprint", RunMode.SPEEDRUN, 5000,
            status=TrainingSessionStatus.ABANDONED,
            zone_history=_history("start", "mid", "end"),
            seed=await _graph_seed(db, FINAL_BOSS_GRAPH),
        )  # fmt: skip
        live = await _add_session(
            db, await _user(db, "b"), "sprint", RunMode.SPEEDRUN, 6000,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
            zone_history=_history("start", "mid", "end"),
            seed=await _graph_seed(db, FINAL_BOSS_GRAPH),
        )  # fmt: skip
        await db.commit()

    with (
        patch.object(mod, "_broadcast_status_change", new_callable=AsyncMock) as broadcast,
        patch.object(mod, "schedule_speedrun_record_check") as check,
    ):
        for session in (gone, live):
            async with async_session() as db:
                entity = await mod._load_session(db, session.id)
            handler = mod.TrainingModHandler(MagicMock(), session.id, async_session)
            await handler._handle_finish_event(entity, session.igt_ms, None)

    broadcast.assert_awaited_once_with(live.id, "finished")
    check.assert_called_once_with(session_id=live.id)
    async with async_session() as db:
        statuses = {
            row.id: row.status
            for row in (await db.execute(select(TrainingSession))).scalars().all()
        }
    assert statuses == {
        gone.id: TrainingSessionStatus.ABANDONED,
        live.id: TrainingSessionStatus.FINISHED,
    }


async def test_seed_lookups_keep_the_default_rate_limit(test_client, pools):
    """The Start a run window asks fresh-seeds on opening and the summary as
    the Seed ID is typed: both stay under the API's default per-client limit
    (60 a minute)."""
    for url, params in (
        ("/api/speedrun/fresh-seeds", {"pool": "sprint"}),
        ("/api/speedrun/seeds/zzzzzz/summary", None),
    ):
        statuses = [(await test_client.get(url, params=params)).status_code for _ in range(61)]
        assert 429 not in statuses[:60], url
        assert statuses[60] == 429, url


async def test_monitor_expires_and_broadcasts(async_session, pools):
    from speedfog_racing.services.inactivity_monitor import _expire_speedrun_sessions

    async with async_session() as db:
        user = await _user(db, "a")
        old = await _add_session(
            db, user, "sprint", RunMode.SPEEDRUN, 0,
            status=TrainingSessionStatus.ACTIVE, finished_at=None,
        )  # fmt: skip
        old.created_at = BASE - timedelta(hours=100)
        await db.commit()

    with patch(
        "speedfog_racing.websocket.training.mod._broadcast_status_change", new_callable=AsyncMock
    ) as broadcast:
        await _expire_speedrun_sessions(async_session)

    broadcast.assert_awaited_once_with(old.id, "abandoned")


async def _invalidation_setup(async_session):
    """A finished speedrun session of "a" on its own seed, an admin, and an owner."""
    async with async_session() as db:
        owner = await _user(db, "a")
        admin = await _user(db, "admin")
        admin.role = UserRole.ADMIN
        ranked = await _add_session(db, owner, "sprint", RunMode.SPEEDRUN, 5000)
        normal = await _add_session(db, owner, "training_sprint", RunMode.NORMAL, 5000)
        seed_number = (await db.get(Seed, ranked.seed_id)).seed_number  # type: ignore[union-attr]
        await db.commit()
        return ranked.id, normal.id, seed_number


async def test_invalidation_service_round_trip_and_errors(async_session, pools):
    from datetime import UTC, datetime

    from speedfog_racing.services.sanctions_service import (
        cancel_session_invalidation,
        invalidate_session,
    )

    async with async_session() as db:
        owner = await _user(db, "a")
        ranked = await _add_session(db, owner, "sprint", RunMode.SPEEDRUN, 5000)
        normal = await _add_session(db, owner, "training_sprint", RunMode.NORMAL, 5000)
        now = datetime.now(UTC)

        with pytest.raises(ValueError):
            invalidate_session(normal, by_id=owner.id, reason="x", now=now)
        with pytest.raises(ValueError):
            cancel_session_invalidation(ranked)

        invalidate_session(ranked, by_id=owner.id, reason="Cheat", now=now)
        assert (ranked.invalidated_at, ranked.invalidated_by_id) == (now, owner.id)
        with pytest.raises(ValueError):
            invalidate_session(ranked, by_id=owner.id, reason="again", now=now)

        cancel_session_invalidation(ranked)
        assert (ranked.invalidated_at, ranked.invalidated_by_id, ranked.invalidation_reason) == (
            None,
            None,
            None,
        )


async def test_invalidation_endpoint_guards(test_client, async_session, pools):
    ranked_id, normal_id, _ = await _invalidation_setup(async_session)
    url = "/api/admin/training/{}/invalidation"

    assert (
        await test_client.put(url.format(ranked_id), json={"reason": "x"}, headers=_auth("a"))
    ).status_code == 403
    assert (await test_client.put(url.format(ranked_id), json={"reason": "x"})).status_code in (
        401,
        403,
    )
    for reason in ("   ", "", "x" * 501):
        r = await test_client.put(
            url.format(ranked_id), json={"reason": reason}, headers=_auth("admin")
        )
        assert r.status_code == 422
    normal = await test_client.put(
        url.format(normal_id), json={"reason": "x"}, headers=_auth("admin")
    )
    assert (normal.status_code, normal.json()["detail"]) == (
        400,
        "Only a ranked solo run can be invalidated",
    )
    missing = await test_client.put(
        url.format("00000000-0000-0000-0000-000000000000"),
        json={"reason": "x"},
        headers=_auth("admin"),
    )
    assert missing.status_code == 404
    undo = await test_client.delete(url.format(ranked_id), headers=_auth("admin"))
    assert (undo.status_code, undo.json()["detail"]) == (400, "Not invalidated")


async def test_invalidated_run_leaves_board_and_seed_page_at_once(
    test_client, async_session, pools
):
    ranked_id, _, seed_number = await _invalidation_setup(async_session)
    url = f"/api/admin/training/{ranked_id}/invalidation"

    async def counts() -> tuple[int, int]:
        overview = (await test_client.get("/api/stats/speedrun")).json()
        page = (await test_client.get(f"/api/speedrun/seeds/{seed_number}")).json()
        return overview["runs"], len(page["runs"])

    assert await counts() == (1, 1)

    put = await test_client.put(url, json={"reason": "  Cheat tool  "}, headers=_auth("admin"))
    assert put.status_code == 200
    assert (put.json()["invalidated"], put.json()["invalidation_reason"]) == (True, "Cheat tool")
    assert (await test_client.put(url, json={"reason": "again"}, headers=_auth("admin"))).json()[
        "detail"
    ] == "Already invalidated"
    assert await counts() == (0, 0)

    delete = await test_client.delete(url, headers=_auth("admin"))
    assert (delete.status_code, delete.json()["invalidated"]) == (200, False)
    assert await counts() == (1, 1)


# --- Unfinished Speedrun solo limit ---


NOW = datetime.now(UTC).replace(microsecond=0)


async def _backdated(
    db: AsyncSession,
    user,
    hours_ago: float,
    *,
    status: TrainingSessionStatus = TrainingSessionStatus.ABANDONED,
    mode: RunMode = RunMode.SPEEDRUN,
) -> TrainingSession:
    session = await _add_session(db, user, "sprint", mode, 1000, status=status)
    session.created_at = NOW - timedelta(hours=hours_ago)
    return session


@pytest.fixture
def limit_3(monkeypatch):
    monkeypatch.setattr(settings, "speedrun_solo_unfinished_limit", 3)
    monkeypatch.setattr(settings, "speedrun_solo_unfinished_window_hours", 24)


async def _seed_states(db: AsyncSession) -> list[SeedStatus]:
    return list((await db.execute(select(Seed.status))).scalars())


async def test_unfinished_limit_refuses_and_consumes_no_seed(async_session, pools, limit_3):
    async with async_session() as db:
        user = await _user(db, "a")
        await _available(db, "sprint", 5)
        # Four counted sessions (more than the limit); the 2nd oldest frees the slot
        # (4 - 3 = index 1): 23 h 40 min old, so it leaves the window in 20 min.
        for hours, state in (
            (23.9, TrainingSessionStatus.ABANDONED),
            (23 + 40 / 60, TrainingSessionStatus.CANCELLED),
            (10, TrainingSessionStatus.ABANDONED),
            (1, TrainingSessionStatus.CANCELLED),
        ):
            await _backdated(db, user, hours, status=state)
        await db.commit()
        before = await _seed_states(db)
        with pytest.raises(SpeedrunStartError) as error:
            await _require_under_unfinished_limit(db, user.id, now=NOW)
        assert error.value.code == "unfinished_limit"
        assert error.value.message == (
            "You have 4 unfinished Random Seed runs in the last 24 hours (the limit is 3). "
            "Finish a run, or try again in 20 min."
        )
        assert await _seed_states(db) == before


async def test_unfinished_limit_wait_in_hours_rounds_minutes_up(async_session, pools, limit_3):
    async with async_session() as db:
        user = await _user(db, "a")
        for hours in (19, 5, 1):  # oldest leaves in 5 h; add 30 s to force the round up
            await _backdated(db, user, hours)
        sessions = (
            (await db.execute(select(TrainingSession).order_by(TrainingSession.created_at)))
            .scalars()
            .all()
        )
        sessions[0].created_at = NOW - timedelta(hours=18, minutes=47, seconds=30)
        await db.commit()
        with pytest.raises(SpeedrunStartError) as error:
            await _require_under_unfinished_limit(db, user.id, now=NOW)
        assert error.value.message.endswith("try again in 5 h 13 min.")


async def test_unfinished_limit_counts_an_active_session(async_session, pools, limit_3):
    async with async_session() as db:
        user = await _user(db, "a")
        await _backdated(db, user, 3)
        await _backdated(db, user, 2)
        await _backdated(db, user, 1, status=TrainingSessionStatus.ACTIVE)
        await db.commit()
        with pytest.raises(SpeedrunStartError) as error:
            await _require_under_unfinished_limit(db, user.id, now=NOW)
        assert error.value.code == "unfinished_limit"


async def test_unfinished_limit_counts_only_unfinished_own_speedrun_in_window(
    async_session, pools, limit_3
):
    async with async_session() as db:
        user = await _user(db, "a")
        other = await _user(db, "b")
        # limit - 1 counted sessions; each excluded row below would make it 3 if
        # its filter were dropped.
        await _backdated(db, user, 1, status=TrainingSessionStatus.ABANDONED)
        await _backdated(db, user, 2, status=TrainingSessionStatus.CANCELLED)
        await _backdated(db, user, 3, status=TrainingSessionStatus.FINISHED)
        await db.commit()
        await _require_under_unfinished_limit(db, user.id, now=NOW)
        for excluded in (
            dict(user=user, hours_ago=25),  # out of window
            dict(user=user, hours_ago=4, mode=RunMode.SET_SEED),  # other mode
            dict(user=other, hours_ago=4),  # other player
        ):
            row = await _backdated(db, **excluded)
            await db.commit()
            await _require_under_unfinished_limit(db, user.id, now=NOW)
            await db.delete(row)
            await db.commit()
        # A counted row on top does reach the limit.
        await _backdated(db, user, 4)
        await db.commit()
        with pytest.raises(SpeedrunStartError):
            await _require_under_unfinished_limit(db, user.id, now=NOW)


async def test_unfinished_limit_zero_disables(async_session, pools, monkeypatch):
    monkeypatch.setattr(settings, "speedrun_solo_unfinished_limit", 0)
    async with async_session() as db:
        user = await _user(db, "a")
        await _available(db, "sprint", 5)
        for hours in (1, 2, 3, 4):
            await _backdated(db, user, hours)
        await db.commit()
        session = await create_speedrun_session(db, user.id, "sprint")
        assert session.mode == RunMode.SPEEDRUN


async def test_unfinished_limit_does_not_apply_to_set_seed(async_session, pools, limit_3, seed_zip):
    async with async_session() as db:
        user = await _user(db, "a")
        for hours in (1, 2, 3):
            await _backdated(db, user, hours)
        seed = await _seed(db, "abcdef111111", folder_path=seed_zip)
        await _add_run(db, user=await _user(db, "b"), igt_ms=1000, minute=1, seed=seed)
        await db.commit()
        session = await create_set_seed_session(db, user.id, "abcdef111111")
        assert session.mode == RunMode.SET_SEED


async def test_unfinished_limit_is_429_with_its_own_detail(
    test_client, async_session, pools, limit_3
):
    async with async_session() as db:
        user = await _user(db, "a")
        await _available(db, "sprint", 5)
        for hours in (1, 2, 3):
            await _backdated(db, user, hours)
        await db.commit()
    response = await test_client.post(
        "/api/speedrun/solo", json={"pool": "sprint"}, headers=_auth("a")
    )
    assert response.status_code == 429
    assert "3 unfinished" in response.json()["detail"]
