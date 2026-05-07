"""Integration tests for the per-mod projected leaderboard on daily races.

Spec: docs/specs/2026-04-27-daily-seed-design.md (replay leaderboard).

The unit-level coverage on ``ConnectionManager.broadcast_leaderboard`` lives in
``tests/test_websocket.py`` (see the three ``test_broadcast_leaderboard_*``
cases). The unit-level coverage on the projector lives in
``tests/test_daily_replay_projection.py``.

This file fills the gaps those tests cannot reach: it exercises the full
``/ws/mod/{race_id}`` and ``/ws/race/{race_id}`` flow with a real FastAPI
``TestClient`` + a real (sqlite via aiosqlite) DB, and it specifically
covers the 1Hz heartbeat path through ``_maybe_unicast_daily_projection``
that the unit tests cannot trigger.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from speedfog_racing.database import Base
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
from speedfog_racing.websocket.race.manager import manager

from .test_integration import ModTestClient

# A unique sqlite file isolates this module from other integration tests so a
# fixture failure in one suite cannot leak rows into another.
_DB_PATH = os.path.join(tempfile.gettempdir(), "speedfog_daily_replay_lb_test.db")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Modeled on ``tests/test_integration.py::integration_db`` and
# ``integration_client``: file-backed sqlite (so the WS handler and the test
# share the same DB) plus the global ``manager.rooms`` reset between tests.
@pytest.fixture(scope="function")
def daily_db() -> Any:
    import speedfog_racing.database as db_module
    import speedfog_racing.main as main_module

    if os.path.exists(_DB_PATH):
        os.remove(_DB_PATH)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{_DB_PATH}",
        echo=False,
        poolclass=NullPool,
    )
    test_session_maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def init() -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init())

    original_engine = db_module.engine
    original_session_maker = db_module.async_session_maker
    db_module.engine = test_engine
    db_module.async_session_maker = test_session_maker
    main_module.async_session_maker = test_session_maker  # type: ignore[attr-defined]

    try:
        yield test_session_maker
    finally:
        db_module.engine = original_engine
        db_module.async_session_maker = original_session_maker
        main_module.async_session_maker = original_session_maker  # type: ignore[attr-defined]
        asyncio.run(test_engine.dispose())
        if os.path.exists(_DB_PATH):
            os.remove(_DB_PATH)


@pytest.fixture(scope="function")
def daily_client(daily_db: Any) -> Any:
    _ = daily_db
    manager.rooms.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    manager.rooms.clear()


# ---------------------------------------------------------------------------
# Race seeding helpers
# ---------------------------------------------------------------------------
# Graph used across all three tests: a tiny linear DAG with three layers so
# the projector has something to interpolate over.
_GRAPH_JSON: dict[str, Any] = {
    "version": "4.0",
    "total_layers": 3,
    "nodes": {
        "start": {"type": "start", "zones": ["start"], "layer": 0, "tier": 1},
        "fog_a": {"zones": ["zone_a"], "layer": 1, "tier": 1},
        "fog_b": {"zones": ["zone_b"], "layer": 2, "tier": 2},
        "end": {"zones": ["zone_end"], "layer": 3, "tier": 3},
    },
    "area_tiers": {"zone_a": 1, "zone_b": 2, "zone_end": 3},
    "event_map": {"9000000": "fog_a", "9000001": "fog_b", "9000002": "end"},
    "finish_event": 9000003,
}


async def _seed_race_with_finished_ghost(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    daily: bool,
) -> tuple[uuid.UUID, str, str]:
    """Insert a RUNNING race with a finished ghost A and a registered viewer B.

    Returns ``(race_id, a_mod_token, b_mod_token)``. ``daily=True`` sets a
    ``daily_date`` so the projection codepath fires; ``daily=False`` keeps
    ``daily_date=None`` for Test C.
    """
    started = datetime.now(UTC) - timedelta(hours=2)
    today = started.date()
    a_token = f"mod_a_{uuid.uuid4().hex[:8]}"
    b_token = f"mod_b_{uuid.uuid4().hex[:8]}"
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"sys-{uuid.uuid4().hex[:8]}",
            twitch_username="sys_replay",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        ghost_user = User(
            twitch_id=f"ghost-{uuid.uuid4().hex[:8]}",
            twitch_username="alpha",
            twitch_display_name="Alpha",
            api_token=f"tok-a-{uuid.uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        viewer_user = User(
            twitch_id=f"viewer-{uuid.uuid4().hex[:8]}",
            twitch_username="bravo",
            twitch_display_name="Bravo",
            api_token=f"tok-b-{uuid.uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        db.add_all([organizer, ghost_user, viewer_user])
        await db.flush()

        seed = Seed(
            seed_number=f"replay-{uuid.uuid4().hex[:6]}",
            pool_name="standard",
            graph_json=_GRAPH_JSON,
            total_layers=3,
            folder_path=f"/tmp/replay-{uuid.uuid4().hex[:6]}",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Replay LB Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            daily_date=today if daily else None,
            exclude_from_elo=daily,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.flush()

        # Ghost A: finished a 5 minute run with a real zone_history that the
        # projector can interpolate over for arbitrary viewer IGTs.
        ghost = Participant(
            race_id=race.id,
            user_id=ghost_user.id,
            mod_token=a_token,
            status=ParticipantStatus.FINISHED,
            current_zone="end",
            current_layer=3,
            igt_ms=300_000,
            death_count=0,
            finished_at=started + timedelta(minutes=5),
            zone_history=[
                {"node_id": "start", "igt_ms": 0, "type": "spawn"},
                {"node_id": "fog_a", "igt_ms": 100_000, "type": "fog"},
                {"node_id": "fog_b", "igt_ms": 200_000, "type": "fog"},
                {"node_id": "end", "igt_ms": 300_000, "type": "fog"},
            ],
        )
        # Viewer B: still REGISTERED, so they can transition to PLAYING via
        # the first status_update on the mod WS (mirrors the real flow).
        viewer = Participant(
            race_id=race.id,
            user_id=viewer_user.id,
            mod_token=b_token,
            status=ParticipantStatus.REGISTERED,
            current_zone=None,
            current_layer=0,
            igt_ms=0,
            death_count=0,
        )
        db.add_all([ghost, viewer])
        await db.commit()
        return race.id, a_token, b_token


def _receive_with_timeout(ws: Any, *, timeout: float = 2.0) -> dict[str, Any]:
    """Threaded receive_json so a quiet websocket cannot hang the test.

    Mirrors the executor pattern in
    ``tests/test_integration.py::ModTestClient.receive``: starlette's
    ``TestClient`` websocket has no built-in receive timeout, so a stuck
    socket would otherwise dead-end on the pytest 30s timeout.
    """
    from concurrent.futures import Future, ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout

    executor = ThreadPoolExecutor(max_workers=1)
    future: Future[dict[str, Any]] = executor.submit(ws.receive_json)
    executor.shutdown(wait=False)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        raise TimeoutError(f"No WebSocket message received within {timeout}s") from None


def _latest_leaderboard_within(
    mod: ModTestClient, *, max_messages: int = 20
) -> dict[str, Any] | None:
    """Drain up to ``max_messages`` messages, returning the last leaderboard_update.

    Returns None if no leaderboard_update arrived. Each ``receive`` call has
    its own timeout so a quiet socket cannot stall the test.
    """
    last: dict[str, Any] | None = None
    for _ in range(max_messages):
        try:
            msg = mod.receive(timeout=2)
        except TimeoutError:
            break
        if msg.get("type") == "leaderboard_update":
            last = msg
    return last


def _latest_spectator_leaderboard(ws: Any, *, max_messages: int = 20) -> dict[str, Any] | None:
    """Drain spectator websocket, returning the last leaderboard_update seen."""
    last: dict[str, Any] | None = None
    for _ in range(max_messages):
        try:
            msg = _receive_with_timeout(ws, timeout=2)
        except TimeoutError:
            break
        if msg.get("type") == "leaderboard_update":
            last = msg
    return last


def _participant_by_username(payload: dict[str, Any], username: str) -> dict[str, Any]:
    return next(p for p in payload["participants"] if p["twitch_username"] == username)


# ---------------------------------------------------------------------------
# Test A: end-to-end daily replay
# ---------------------------------------------------------------------------
def test_daily_mod_sees_projected_ghost_spectator_sees_real_finish(
    daily_client: TestClient, daily_db: async_sessionmaker[AsyncSession]
) -> None:
    """Daily race: mod (B, playing) sees A projected at B's IGT; spectator sees A finished."""
    race_id, _a_token, b_token = asyncio.run(_seed_race_with_finished_ghost(daily_db, daily=True))

    with daily_client.websocket_connect(f"/ws/race/{race_id}") as spec_ws:
        # Skip auth: an unauthenticated spectator still receives leaderboard_update.
        spec_ws.send_json({"type": "no_auth"})

        with daily_client.websocket_connect(f"/ws/mod/{race_id}") as mod_ws:
            mod = ModTestClient(mod_ws, b_token)
            assert mod.auth(drain=False)["type"] == "auth_ok"
            # Drain bootstrap leaderboard sent on connect.
            mod.receive_until_type("leaderboard_update")

            # First status_update transitions B from REGISTERED -> PLAYING
            # (became_active path), which broadcasts a fresh leaderboard.
            mod.send_status_update(igt_ms=0, death_count=0)
            mod.receive_until_type("leaderboard_update")

            # Heartbeat at IGT 60s. Triggers _maybe_unicast_daily_projection.
            mod.send_status_update(igt_ms=60_000, death_count=0)

            mod_lb = _latest_leaderboard_within(mod)
            assert mod_lb is not None, "mod did not receive a projected leaderboard_update"

            mod_alpha = _participant_by_username(mod_lb, "alpha")
            # From B's POV at 60s, A should be projected as still playing
            # at the start node (its history says fog_a is reached at 100s).
            assert mod_alpha["status"] == "playing"
            assert mod_alpha["current_zone"] == "start"
            assert mod_alpha["current_layer"] == 0
            assert mod_alpha["igt_ms"] <= 60_000
            assert mod_alpha["status"] != "finished"

        # Spectator should see A as truly finished at its real IGT.
        spec_lb = _latest_spectator_leaderboard(spec_ws)
        assert spec_lb is not None, "spectator received no leaderboard_update"
        spec_alpha = _participant_by_username(spec_lb, "alpha")
        assert spec_alpha["status"] == "finished"
        assert spec_alpha["igt_ms"] == 300_000


# ---------------------------------------------------------------------------
# Test B: 1Hz heartbeat unicasts a fresh projection
# ---------------------------------------------------------------------------
def test_daily_heartbeat_unicasts_fresh_projection_to_mod(
    daily_client: TestClient, daily_db: async_sessionmaker[AsyncSession]
) -> None:
    """A heartbeat that does not change other state still re-sends the projection."""
    race_id, _a_token, b_token = asyncio.run(_seed_race_with_finished_ghost(daily_db, daily=True))

    with daily_client.websocket_connect(f"/ws/mod/{race_id}") as mod_ws:
        mod = ModTestClient(mod_ws, b_token)
        assert mod.auth(drain=False)["type"] == "auth_ok"
        mod.receive_until_type("leaderboard_update")  # connect broadcast

        # First status_update: REGISTERED -> PLAYING (became_active path).
        mod.send_status_update(igt_ms=0, death_count=0)
        boot_lb = mod.receive_until_type("leaderboard_update")
        boot_alpha = _participant_by_username(boot_lb, "alpha")
        # Sanity: at IGT 0, A is projected at spawn.
        assert boot_alpha["status"] == "playing"
        assert boot_alpha["current_zone"] == "start"

        # Pure heartbeat: B's IGT advances to 60s. No other participant
        # changed. The non-active path runs broadcast_player_update +
        # _maybe_unicast_daily_projection; only the latter sends a
        # leaderboard_update, and only to this mod.
        mod.send_status_update(igt_ms=60_000, death_count=0)

        heartbeat_lb = _latest_leaderboard_within(mod)
        assert heartbeat_lb is not None, (
            "heartbeat did not unicast a leaderboard_update to the playing daily mod"
        )
        # Confirm this is a fresh projection (not the cached boot payload):
        # at viewer_igt=60_000 A is still at start (fog_a is at 100s) but B
        # itself, the viewer, must reflect the new IGT.
        bravo = _participant_by_username(heartbeat_lb, "bravo")
        assert bravo["igt_ms"] == 60_000
        assert bravo["status"] == "playing"
        alpha = _participant_by_username(heartbeat_lb, "alpha")
        assert alpha["status"] == "playing"
        assert alpha["status"] != "finished"


# ---------------------------------------------------------------------------
# Test C: non-daily heartbeat does NOT unicast
# ---------------------------------------------------------------------------
def test_non_daily_heartbeat_does_not_unicast_leaderboard(
    daily_client: TestClient, daily_db: async_sessionmaker[AsyncSession]
) -> None:
    """Non-daily race: a pure heartbeat sends only player_update, no leaderboard_update."""
    race_id, _a_token, b_token = asyncio.run(_seed_race_with_finished_ghost(daily_db, daily=False))

    # Sanity: confirm the seed really wrote daily_date=None. Otherwise this
    # test would silently pass for the wrong reason.
    async def _check_daily_none() -> None:
        async with daily_db() as db:
            race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
            assert race.daily_date is None

    asyncio.run(_check_daily_none())

    with daily_client.websocket_connect(f"/ws/mod/{race_id}") as mod_ws:
        mod = ModTestClient(mod_ws, b_token)
        assert mod.auth(drain=False)["type"] == "auth_ok"
        mod.receive_until_type("leaderboard_update")

        mod.send_status_update(igt_ms=0, death_count=0)
        mod.receive_until_type("leaderboard_update")  # became_active broadcast

        # Pure heartbeat. Daily-only gate in _maybe_unicast_daily_projection
        # plus the perf hoist must keep this from emitting leaderboard_update.
        mod.send_status_update(igt_ms=60_000, death_count=0)

        saw_player_update = False
        # Drain everything pending. If daily-projection were leaking on
        # non-daily races, a leaderboard_update would arrive here.
        for _ in range(10):
            try:
                msg = mod.receive(timeout=2)
            except TimeoutError:
                break
            assert msg.get("type") != "leaderboard_update", (
                f"non-daily heartbeat unexpectedly sent leaderboard_update: {msg}"
            )
            if msg.get("type") == "player_update":
                saw_player_update = True
                assert msg["player"]["igt_ms"] == 60_000

        # The heartbeat path must still broadcast a player_update; if not,
        # this test is asserting nothing useful about the heartbeat.
        assert saw_player_update, "expected at least one player_update from the heartbeat"


# Marker so date import is not flagged unused if we ever stop using ``today``
# directly. The seeded race uses ``datetime.now(UTC).date()`` indirectly.
_ = date
