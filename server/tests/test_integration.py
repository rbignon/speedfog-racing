"""Integration tests for complete race flow."""

import io
import json
import os
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from speedfog_racing.database import Base
from speedfog_racing.main import app
from speedfog_racing.models import (
    Invite,
    Participant,
    ParticipantStatus,
    Race,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.manager import manager
from tests.asgi_testclient import TestClient
from tests.sqlite_async_shim import create_sqlite_async_shim

# =============================================================================
# Helper Classes
# =============================================================================


class ModTestClient:
    """Simulates a mod connecting to the race WebSocket."""

    def __init__(self, websocket, mod_token: str):
        self.ws = websocket
        self.mod_token = mod_token

    def auth(self, *, drain: bool = True) -> dict[str, Any]:
        """Send auth and return response.

        When *drain* is True (default), also consumes the connect broadcast
        (leaderboard_update) and any zone_update sent on reconnect. Set
        drain=False when a test needs to inspect those messages.
        """
        self.ws.send_json({"type": "auth", "mod_token": self.mod_token})
        response = self.receive()
        if response.get("type") == "auth_ok" and drain:
            # Server sends zone_update (if running) + leaderboard_update (connect broadcast)
            self.receive_until_type("leaderboard_update")
        return response

    def send_ready(self) -> None:
        """Send ready signal."""
        self.ws.send_json({"type": "ready"})

    def send_status_update(self, igt_ms: int, death_count: int) -> None:
        """Send periodic status update."""
        self.ws.send_json(
            {
                "type": "status_update",
                "igt_ms": igt_ms,
                "death_count": death_count,
            }
        )

    def send_event_flag(self, flag_id: int, igt_ms: int, *, message_id: int | None = None) -> None:
        """Send event flag trigger."""
        payload = {
            "type": "event_flag",
            "flag_id": flag_id,
            "igt_ms": igt_ms,
        }
        if message_id is not None:
            payload["message_id"] = message_id
        self.ws.send_json(payload)

    def send_finished(self, igt_ms: int) -> None:
        """Send finish event."""
        self.ws.send_json({"type": "finished", "igt_ms": igt_ms})

    def send_zone_query(
        self,
        grace_entity_id: int | None = None,
        *,
        map_id: str | None = None,
        position: list[float] | None = None,
        play_region_id: int | None = None,
    ) -> None:
        """Send zone query (loading screen exit)."""
        payload: dict[str, Any] = {"type": "zone_query"}
        if grace_entity_id is not None:
            payload["grace_entity_id"] = grace_entity_id
        if map_id is not None:
            payload["map_id"] = map_id
        if position is not None:
            payload["position"] = position
        if play_region_id is not None:
            payload["play_region_id"] = play_region_id
        self.ws.send_json(payload)

    def receive(self, timeout: float = 5) -> dict[str, Any]:
        """Receive next message. Raises TimeoutError after *timeout* seconds."""
        from concurrent.futures import Future, ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FuturesTimeout

        # Do NOT use ThreadPoolExecutor as a context manager here.
        # Its __exit__ calls shutdown(wait=True), which blocks forever
        # if the thread is stuck on ws.receive_json() after a timeout.
        executor = ThreadPoolExecutor(max_workers=1)
        future: Future[dict[str, Any]] = executor.submit(self.ws.receive_json)
        executor.shutdown(wait=False)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            raise TimeoutError(f"No WebSocket message received within {timeout}s") from None

    def receive_until_type(self, msg_type: str, max_messages: int = 10) -> dict[str, Any]:
        """Receive messages until getting one of the specified type."""
        for _ in range(max_messages):
            msg = self.receive()
            if msg.get("type") == msg_type:
                return msg
        raise TimeoutError(f"Did not receive message of type {msg_type}")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="function")
def integration_db():
    """Set up a fresh database for integration tests.

    This fixture patches the database module to use a file-based SQLite database,
    ensuring both the API routes and WebSocket handlers use the same database.
    """

    import speedfog_racing.api.races as races_module
    import speedfog_racing.database as db_module
    import speedfog_racing.main as main_module
    import speedfog_racing.services.stats_service as stats_service_module

    fd, test_db_path = tempfile.mkstemp(prefix="speedfog_integration_", suffix=".db")
    os.close(fd)
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    test_engine, test_session_maker = create_sqlite_async_shim(test_db_path)
    Base.metadata.create_all(bind=test_engine)

    # Patch the database module
    original_engine = db_module.engine
    original_session_maker = db_module.async_session_maker
    original_db_init = db_module.init_db
    original_main_init = main_module.init_db
    original_lifespan = app.router.lifespan_context
    original_races_session_maker = races_module.async_session_maker
    original_stats_session_maker = stats_service_module.async_session_maker

    async def _init_db_for_tests() -> None:
        return None

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    db_module.engine = test_engine
    db_module.async_session_maker = test_session_maker
    db_module.init_db = _init_db_for_tests

    # Also patch main module's import
    main_module.async_session_maker = test_session_maker
    main_module.init_db = _init_db_for_tests
    races_module.async_session_maker = test_session_maker
    stats_service_module.async_session_maker = test_session_maker
    app.router.lifespan_context = _noop_lifespan

    try:
        yield test_session_maker
    finally:
        # Restore originals
        db_module.engine = original_engine
        db_module.async_session_maker = original_session_maker
        db_module.init_db = original_db_init
        main_module.async_session_maker = original_session_maker
        main_module.init_db = original_main_init
        races_module.async_session_maker = original_races_session_maker
        stats_service_module.async_session_maker = original_stats_session_maker
        app.router.lifespan_context = original_lifespan

        # Clean up
        test_engine.dispose()
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


@pytest.fixture
def seed_folder():
    """Create a temporary seed zip with mock content."""
    graph_json = {
        "version": "4.0",
        "total_layers": 5,
        "nodes": {
            "start_node": {"type": "start", "zones": ["start"], "layer": 0, "tier": 1},
            "node_a": {"zones": ["zone_a"], "layer": 1, "tier": 1},
            "node_b": {"zones": ["zone_b"], "layer": 2, "tier": 2},
            "node_c": {"zones": ["zone_c"], "layer": 3, "tier": 3},
        },
        "area_tiers": {"zone_a": 1, "zone_b": 2, "zone_c": 3},
        "event_map": {
            "9000000": "node_a",
            "9000001": "node_b",
            "9000002": "node_c",
        },
        "finish_event": 9000003,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "seed_a1b2c3d4.zip"
        top = "speedfog_a1b2c3d4"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(f"{top}/lib/speedfog_racing.dll", "mock dll")
            zf.writestr(f"{top}/ModEngine/config.toml", "[config]")
            zf.writestr(f"{top}/graph.json", json.dumps(graph_json))
            zf.writestr(f"{top}/launch_speedfog.bat", "@echo off")
        yield zip_path


@pytest.fixture
def integration_client(integration_db):
    """Create test client with patched database."""
    # integration_db fixture patches the database module (used for side effects)
    _ = integration_db  # Mark as used to satisfy type checkers

    # Clear the global connection manager between tests
    manager.rooms.clear()

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    manager.rooms.clear()


@pytest.fixture
def race_with_participants(integration_db, integration_client, seed_folder):
    """Create a race with 3 participants.

    This is a sync fixture that sets up all the data needed for tests.
    """
    import asyncio

    async def setup():
        async with integration_db() as db:
            # Create organizer
            organizer = User(
                twitch_id="org_integration",
                twitch_username="organizer",
                twitch_display_name="The Organizer",
                api_token="organizer_token_integration",
                role=UserRole.ORGANIZER,
            )
            db.add(organizer)

            # Create players
            players = []
            for i in range(3):
                user = User(
                    twitch_id=f"player_integration_{i}",
                    twitch_username=f"player{i}",
                    twitch_display_name=f"Player {i}",
                    api_token=f"player_token_integration_{i}",
                    role=UserRole.USER,
                )
                db.add(user)
                players.append(user)

            # Create seed
            seed = Seed(
                seed_number="s999999",
                pool_name="standard",
                graph_json={
                    "version": "4.0",
                    "total_layers": 5,
                    "nodes": {
                        "start_node": {"type": "start", "zones": ["start"], "layer": 0, "tier": 1},
                        "node_a": {"zones": ["zone_a"], "layer": 1, "tier": 1},
                        "node_b": {"zones": ["zone_b"], "layer": 2, "tier": 2},
                        "node_c": {"zones": ["zone_c"], "layer": 3, "tier": 3},
                    },
                    "area_tiers": {"zone_a": 1, "zone_b": 2, "zone_c": 3},
                    "event_map": {
                        "9000000": "node_a",
                        "9000001": "node_b",
                        "9000002": "node_c",
                    },
                    "finish_event": 9000003,
                },
                total_layers=5,
                folder_path=str(seed_folder),
                status=SeedStatus.AVAILABLE,
            )
            db.add(seed)

            await db.commit()
            await db.refresh(organizer)
            for p in players:
                await db.refresh(p)

            return organizer, players

    organizer, players = asyncio.run(setup())

    # Create race
    response = integration_client.post(
        "/api/races",
        json={"name": "Integration Test Race", "pool_name": "standard"},
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 201, f"Failed to create race: {response.json()}"
    race_id = response.json()["id"]

    # Add participants
    for player in players:
        response = integration_client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": player.twitch_username},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200

    # Release seeds (required before start or download)
    response = integration_client.post(
        f"/api/races/{race_id}/release-seeds",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Get mod tokens and ensure seed has area_tiers for layer tests
    async def get_tokens():
        async with integration_db() as db:
            # Ensure the race's seed has area_tiers (real seeds from pool
            # scan may not have them)
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            if race.seed:
                graph = dict(race.seed.graph_json or {})
                graph["area_tiers"] = {"zone_a": 1, "zone_b": 2, "zone_c": 3}
                graph["nodes"] = {
                    "start_node": {
                        "type": "start",
                        "display_name": "Chapel of Anticipation",
                        "zones": ["start"],
                        "layer": 0,
                        "tier": 1,
                        "exits": [
                            {"text": "First door", "fog_id": 100, "to": "node_a"},
                            {"text": "Side exit", "fog_id": 101, "to": "node_b"},
                        ],
                    },
                    "node_a": {
                        "display_name": "Stormveil Castle",
                        "zones": ["zone_a"],
                        "layer": 1,
                        "tier": 1,
                        "exits": [
                            {"text": "Gate to B", "fog_id": 102, "to": "node_b"},
                        ],
                    },
                    "node_b": {
                        "display_name": "Raya Lucaria",
                        "zones": ["zone_b"],
                        "layer": 2,
                        "tier": 2,
                        "exits": [],
                    },
                    "node_c": {
                        "display_name": "Volcano Manor",
                        "zones": ["zone_c"],
                        "layer": 3,
                        "tier": 3,
                        "exits": [],
                    },
                }
                graph["event_map"] = {
                    "9000000": "node_a",
                    "9000001": "node_b",
                    "9000002": "node_c",
                }
                graph["finish_event"] = 9000003
                graph["total_layers"] = 5
                graph.pop("death_flags", None)
                race.seed.graph_json = graph
                race.seed.total_layers = 5
                await db.commit()

            result = await db.execute(
                select(Participant).where(Participant.race_id == uuid.UUID(race_id))
            )
            participants = result.scalars().all()

            # Refresh to get user relationship
            for p in participants:
                await db.refresh(p, ["user"])

            # Build (user, mod_token) mapping sorted by username
            player_data = []
            for p in sorted(participants, key=lambda x: x.user.twitch_username):
                player_data.append(
                    {
                        "user": p.user,
                        "mod_token": p.mod_token,
                        "participant_id": str(p.id),
                    }
                )
            return player_data

    player_data = asyncio.run(get_tokens())

    yield {
        "race_id": race_id,
        "organizer": organizer,
        "players": player_data,
    }


# =============================================================================
# Scenario 1: Complete Race Flow (3 Players)
# =============================================================================


def test_complete_race_flow(integration_client, race_with_participants):
    """Test complete race flow with event_flag messages."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Step 1: Connect first mod and verify auth_ok includes event_ids
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        auth_response = mod0.auth()
        assert auth_response["type"] == "auth_ok"
        assert auth_response["race"]["name"] == "Integration Test Race"
        assert "total_layers" in auth_response["seed"]
        # Verify event_ids includes event_map flags + finish_event
        event_ids = auth_response["seed"].get("event_ids")
        assert event_ids == [9000000, 9000001, 9000002, 9000003]

    # Step 2: Connect all 3 mods, send ready, start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_ready()
        mod1.receive()  # leaderboard_update

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
        mod2 = ModTestClient(ws2, players[2]["mod_token"])
        assert mod2.auth()["type"] == "auth_ok"
        mod2.send_ready()
        mod2.receive()  # leaderboard_update

    # Step 3: Organizer starts the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Step 4: Players send event_flag messages
    # Player 0: triggers flag 9000000 -> node_a (layer 1)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod0.send_event_flag(9000000, igt_ms=10000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 1

    # Player 1: triggers flag 9000001 -> node_b (layer 2)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_status_update(igt_ms=1000, death_count=0)
        mod1.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod1.send_event_flag(9000001, igt_ms=15000)
        lb = mod1.receive_until_type("leaderboard_update")
        p1 = next(p for p in lb["participants"] if p["twitch_username"] == "player1")
        assert p1["current_layer"] == 2

    # Player 2: triggers finish_event (9000003) -> race finish
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
        mod2 = ModTestClient(ws2, players[2]["mod_token"])
        assert mod2.auth()["type"] == "auth_ok"
        mod2.send_status_update(igt_ms=1000, death_count=0)
        mod2.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod2.send_event_flag(9000003, igt_ms=50000)
        lb = mod2.receive_until_type("leaderboard_update")
        p2 = next(p for p in lb["participants"] if p["twitch_username"] == "player2")
        assert p2["status"] == "finished"
        assert p2["current_layer"] == 5  # bumped to total_layers on finish

    # Player 0 finishes (already PLAYING from earlier)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_event_flag(9000003, igt_ms=70000)
        lb = mod0.receive_until_type("leaderboard_update")
        assert lb["participants"][0]["twitch_username"] == "player2"
        assert lb["participants"][1]["twitch_username"] == "player0"

    # Player 1 finishes last (triggers race completion; already PLAYING from earlier)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_event_flag(9000003, igt_ms=80000)

        st = mod1.receive_until_type("race_status_change")
        lb = mod1.receive_until_type("leaderboard_update")

        assert st["type"] == "race_status_change"
        assert st["status"] == "finished"

        assert lb["type"] == "leaderboard_update"
        assert lb["participants"][0]["twitch_username"] == "player2"
        assert lb["participants"][0]["igt_ms"] == 50000
        assert lb["participants"][1]["twitch_username"] == "player0"
        assert lb["participants"][1]["igt_ms"] == 70000
        assert lb["participants"][2]["twitch_username"] == "player1"
        assert lb["participants"][2]["igt_ms"] == 80000
        assert all(p["status"] == "finished" for p in lb["participants"])
        # All finished players should have current_layer == total_layers (5)
        assert all(p["current_layer"] == 5 for p in lb["participants"])


# =============================================================================
# Scenario 2: Error Handling
# =============================================================================


def test_auth_invalid_token(integration_client, race_with_participants):
    """Test that invalid auth token returns auth_error."""
    race_id = race_with_participants["race_id"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, "invalid_token_12345")
        response = mod.auth()
        assert response["type"] == "auth_error"
        assert "Invalid" in response["message"]

        # Connection should be closed after auth_error
        with pytest.raises(Exception):  # WebSocket closed
            ws.receive_json()


def test_auth_wrong_race(integration_client, race_with_participants):
    """Test that valid token for wrong race returns auth_error."""
    players = race_with_participants["players"]
    wrong_race_id = str(uuid.uuid4())

    with integration_client.websocket_connect(f"/ws/mod/{wrong_race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        response = mod.auth()
        assert response["type"] == "auth_error"


def test_malformed_json_ignored(integration_client, race_with_participants):
    """Test that malformed JSON is ignored but connection maintained."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        # Send malformed JSON
        ws.send_text("this is not json {{{")

        # Connection should still work - send ready
        mod.send_ready()
        response = mod.receive()
        assert response["type"] == "leaderboard_update"


def test_duplicate_connection_replaces_old(integration_client, race_with_participants):
    """A second connection for the same participant replaces the first.

    The server closes the old socket with code 4000 and accepts the new one.
    This avoids trapping a player behind a ghost connection after a network
    drop or crash.
    """
    from starlette.websockets import WebSocketDisconnect

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    mod_token = players[0]["mod_token"]

    # First connection
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, mod_token)
        assert mod1.auth()["type"] == "auth_ok"

        # Second connection with same token - accepted, first is closed
        with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
            mod2 = ModTestClient(ws2, mod_token)
            assert mod2.auth()["type"] == "auth_ok"

            # First connection should now be closed by the server
            with pytest.raises(WebSocketDisconnect) as exc_info:
                # Drain any buffered messages, then hit the close frame
                for _ in range(10):
                    mod1.receive(timeout=2)
            assert exc_info.value.code == 4000


def test_connect_broadcasts_leaderboard(integration_client, race_with_participants):
    """On connect, the server broadcasts a leaderboard_update with mod_connected=True."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        # Use drain=False so we can inspect the connect broadcast
        assert mod.auth(drain=False)["type"] == "auth_ok"

        lb = mod.receive_until_type("leaderboard_update")
        me = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert me["mod_connected"] is True

        # Other players not connected
        others = [p for p in lb["participants"] if p["twitch_username"] != "player0"]
        assert all(p["mod_connected"] is False for p in others)


def test_mod_receives_leaderboard_on_participant_added(
    integration_client, race_with_participants, integration_db
):
    """Mods connected during setup receive leaderboard_update when a participant joins."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Create a new user (not yet a participant)
    async def create_user():
        async with integration_db() as db:
            user = User(
                twitch_id="new_player_integration",
                twitch_username="newcomer",
                twitch_display_name="Newcomer",
                api_token="newcomer_token_integration",
                role=UserRole.USER,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    asyncio.run(create_user())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        # Organizer adds a new participant
        response = integration_client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "newcomer"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200

        # The mod should receive a leaderboard_update reflecting the new participant
        lb = mod.receive_until_type("leaderboard_update")
        assert len(lb["participants"]) == 4
        assert any(p["twitch_username"] == "newcomer" for p in lb["participants"])


def test_mod_receives_leaderboard_on_invite_accepted(
    integration_client, race_with_participants, integration_db
):
    """Mods connected during setup receive leaderboard_update when an invite is accepted."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Create a new user and an invite for them
    async def create_user_and_invite():
        async with integration_db() as db:
            user = User(
                twitch_id="invited_player_integration",
                twitch_username="invitee",
                twitch_display_name="Invitee",
                api_token="invitee_token_integration",
                role=UserRole.USER,
            )
            db.add(user)
            invite = Invite(
                race_id=uuid.UUID(race_id),
                twitch_username="invitee",
                token="integration_invite_token",
            )
            db.add(invite)
            await db.commit()
            await db.refresh(user)
            return user

    invitee = asyncio.run(create_user_and_invite())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        # Invitee accepts the invite
        response = integration_client.post(
            "/api/invite/integration_invite_token/accept",
            headers={"Authorization": f"Bearer {invitee.api_token}"},
        )
        assert response.status_code == 200

        # The mod should receive a leaderboard_update reflecting the new participant
        lb = mod.receive_until_type("leaderboard_update")
        assert len(lb["participants"]) == 4
        assert any(p["twitch_username"] == "invitee" for p in lb["participants"])


def test_mod_receives_leaderboard_on_participant_removed(
    integration_client, race_with_participants
):
    """Mods connected during setup receive leaderboard_update when a participant is removed."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        # Organizer removes player2
        response = integration_client.delete(
            f"/api/races/{race_id}/participants/{players[2]['participant_id']}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

        # The mod should receive a leaderboard_update reflecting the removal
        lb = mod.receive_until_type("leaderboard_update")
        assert len(lb["participants"]) == 2
        assert not any(p["twitch_username"] == "player2" for p in lb["participants"])


def test_unknown_message_type_ignored(integration_client, race_with_participants):
    """Test that unknown message types are ignored."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        # Send unknown message type
        ws.send_json({"type": "unknown_type", "data": "test"})

        # Connection should still work
        mod.send_ready()
        response = mod.receive()
        assert response["type"] == "leaderboard_update"


# =============================================================================
# Scenario 3: Seed Pack Generation Verification
# =============================================================================


def test_seed_pack_contains_player_specific_config(integration_client, race_with_participants):
    """Test that each player's seed pack contains their specific config with correct mod_token.

    This verifies the full API flow:
    1. Seed packs are generated via API
    2. Each player can download their own seed pack via /my-seed-pack
    3. The seed pack contains speedfog_racing.toml with their unique mod_token and race_id
    """
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Download and verify each player's seed pack
    for player_data in players:
        mod_token = player_data["mod_token"]
        username = player_data["user"].twitch_username

        # Download the seed pack via /my-seed-pack (authenticated as the player)
        download_response = integration_client.get(
            f"/api/races/{race_id}/my-seed-pack",
            headers={"Authorization": f"Bearer {player_data['user'].api_token}"},
        )
        assert download_response.status_code == 200, f"Failed to download seed pack for {username}"
        assert download_response.headers["content-type"] == "application/zip"

        # Extract and verify the config file
        zip_content = io.BytesIO(download_response.content)
        with zipfile.ZipFile(zip_content, "r") as zf:
            # Find the config file (speedfog_racing.toml)
            config_files = [n for n in zf.namelist() if n.endswith("speedfog_racing.toml")]
            assert len(config_files) == 1, f"Expected 1 config file, found {config_files}"

            config_content = zf.read(config_files[0]).decode("utf-8")

            # Verify the config contains this player's unique mod_token
            assert mod_token in config_content, (
                f"Config for {username} should contain their mod_token"
            )

            # Verify the config contains the race_id
            assert race_id in config_content, f"Config for {username} should contain the race_id"

            # Verify basic TOML structure
            assert "[server]" in config_content
            assert "[overlay]" in config_content
            assert "[keybindings]" in config_content


# =============================================================================
# Scenario 3b: Status Update Places Player in Start Zone
# =============================================================================


def test_status_update_transitions_to_playing_with_start_zone(
    integration_client, race_with_participants, integration_db
):
    """First status_update during running race sets PLAYING and places in start zone."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Connect, auth, send ready
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Send first status_update, should transition READY -> PLAYING + start zone
    # (player_update only goes to spectators, so verify via DB)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=1000, death_count=0)
        time.sleep(0.5)  # Let server process before disconnect

    # Verify DB state
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.status, p.current_zone, p.current_layer, p.zone_history

    status, zone, layer, history = asyncio.run(check_db())
    assert status == ParticipantStatus.PLAYING
    assert zone == "start_node"
    assert layer == 0
    assert history is not None
    assert len(history) == 1
    assert history[0]["node_id"] == "start_node"
    assert history[0]["igt_ms"] == 0


# =============================================================================
# Scenario 3c: Stale Save Rejected on Status Update
# =============================================================================


def test_stale_save_rejected_on_status_update(
    integration_client, race_with_participants, integration_db
):
    """status_update with high IGT (stale save) should be rejected, participant stays READY."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Connect, auth, send ready
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Send status_update with stale IGT (60 seconds)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=60_000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "error"
        assert "New Game" in resp["message"]

    # Verify participant is still READY (not transitioned to PLAYING)
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.status, p.zone_history

    status, history = asyncio.run(check_db())
    assert status == ParticipantStatus.READY
    assert history is None or len(history) == 0


def test_stale_save_self_heals_on_new_game(
    integration_client, race_with_participants, integration_db
):
    """After stale save rejection, a fresh save (low IGT) should succeed."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Connect, auth, send ready, start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # First: stale save rejected
        mod0.send_status_update(igt_ms=60_000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "error"

        # Second: player starts New Game, IGT resets
        mod0.send_status_update(igt_ms=500, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "leaderboard_update"  # READY->PLAYING broadcast

    # Verify PLAYING in DB
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.status

    status = asyncio.run(check_db())
    assert status == ParticipantStatus.PLAYING


def test_event_flag_ignored_when_participant_not_playing(
    integration_client, race_with_participants, integration_db
):
    """event_flag from a READY participant (not yet PLAYING) should be silently dropped."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready up and start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Connect but do NOT send status_update (stays READY), send event_flag
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        auth_ok = mod0.auth()
        assert auth_ok["type"] == "auth_ok"
        event_ids = auth_ok["seed"]["event_ids"]

        # Send event_flag while still READY
        mod0.send_event_flag(flag_id=event_ids[0], igt_ms=5000)
        # Then transition to PLAYING normally
        mod0.send_status_update(igt_ms=1000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "leaderboard_update"
        time.sleep(0.5)

    # Verify zone_history has only the spawn entry (no fog entry from the dropped event_flag)
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_db())
    assert history is not None
    assert len(history) == 1  # Only spawn entry, no fog entry
    assert history[0]["type"] == "spawn"


# =============================================================================
# Scenario 4: Zone History Accumulation
# =============================================================================


def test_zone_history_accumulates(integration_client, race_with_participants, integration_db):
    """Verify event_flag messages append to participant.zone_history."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Player 0: triggers flag 9000000 (node_a) then 9000001 (node_b)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")

        mod0.send_event_flag(9000001, igt_ms=20000)
        mod0.receive_until_type("leaderboard_update")

    # Check zone_history in DB
    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    # zone_history: spawn (from status_update) + node_a + node_b
    assert len(history) == 3
    assert history[1]["node_id"] == "node_a"
    assert history[1]["igt_ms"] == 10000
    assert history[2]["node_id"] == "node_b"
    assert history[2]["igt_ms"] == 20000


def test_per_zone_death_tracking(integration_client, race_with_participants, integration_db):
    """Deaths are attributed to the zone_history entry matching current_zone."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING (places in start_node)
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # Discover node_a (sets current_zone=node_a, adds to zone_history)
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")

        # Die twice in node_a (player_update goes to spectators only)
        mod0.send_status_update(igt_ms=15000, death_count=2)
        time.sleep(0.3)

        # Discover node_b (sets current_zone=node_b, adds to zone_history)
        mod0.send_event_flag(9000001, igt_ms=20000)
        mod0.receive_until_type("leaderboard_update")

        # Die three times in node_b
        mod0.send_status_update(igt_ms=25000, death_count=5)
        time.sleep(0.3)

    # Verify zone_history deaths in DB
    async def check_deaths():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history, p.death_count

    history, total_deaths = asyncio.run(check_deaths())
    assert total_deaths == 5
    # zone_history: spawn + node_a + node_b
    assert len(history) == 3

    # node_a got 2 deaths
    node_a_entry = next(e for e in history if e["node_id"] == "node_a")
    assert node_a_entry["deaths"] == 2

    # node_b got 3 deaths
    node_b_entry = next(e for e in history if e["node_id"] == "node_b")
    assert node_b_entry["deaths"] == 3


def test_per_zone_death_tracking_start_node(
    integration_client, race_with_participants, integration_db
):
    """Deaths on the very first status_update (reconnect) are attributed to start_node."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Send ready first so participant is READY
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[1]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Reconnect; first status_update carries death_count=2 (player died
    # before reconnecting). READY→PLAYING must fire before death attribution
    # so current_zone/zone_history exist when the delta is computed.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[1]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Single status_update: transitions READY→PLAYING AND carries deaths
        mod0.send_status_update(igt_ms=5000, death_count=2)
        time.sleep(0.5)

        # Die 2 more times in start zone
        mod0.send_status_update(igt_ms=10000, death_count=4)
        time.sleep(0.3)

    # Verify in DB
    async def check():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[1]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history, p.death_count

    history, total_deaths = asyncio.run(check())
    assert total_deaths == 4
    assert len(history) == 1

    start_entry = next(e for e in history if e["node_id"] == "start_node")
    assert start_entry["deaths"] == 4


def test_event_flag_unknown_ignored(integration_client, race_with_participants, integration_db):
    """Unknown event flag IDs are silently ignored."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Start the race
    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    # Player 0: sends unknown flag_id (not in event_map)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        mod0.send_event_flag(9999999, igt_ms=5000)
        # No leaderboard_update expected for unknown flag,
        # so send a ready to verify connection still works
        mod0.send_ready()
        mod0.receive_until_type("leaderboard_update")

    # Check zone_history is still None
    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is None


def test_event_flag_revisit_appends_to_zone_history(
    integration_client, race_with_participants, integration_db
):
    """Sending the same event flag twice appends both visits to zone_history."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # Send same flag twice (first visit + revisit)
        mod0.send_event_flag(9000000, igt_ms=10000, message_id=1)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 1
        mod0.receive_until_type("leaderboard_update")  # first visit: leaderboard_update

        mod0.send_event_flag(9000000, igt_ms=15000, message_id=2)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 2
        # Revisit: player_update (not leaderboard_update)
        msg = mod0.receive_until_type("player_update")
        assert msg["type"] == "player_update"

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    # zone_history: spawn + first visit node_a + revisit node_a
    assert len(history) == 3
    assert history[1]["node_id"] == "node_a"
    assert history[1]["igt_ms"] == 10000
    assert history[2]["node_id"] == "node_a"
    assert history[2]["igt_ms"] == 15000


def test_event_flag_replay_same_message_id_is_idempotent(
    integration_client, race_with_participants, integration_db
):
    """Replaying the same event_flag message_id must not append twice."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        mod0.send_event_flag(9000000, igt_ms=10000, message_id=77)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 77
        mod0.receive_until_type("leaderboard_update")
        mod0.receive_until_type("zone_update")

        # Replay of the same message after a hypothetical lost ack/reconnect.
        mod0.send_event_flag(9000000, igt_ms=10000, message_id=77)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 77

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    assert len(history) == 2
    assert history[1]["node_id"] == "node_a"
    assert history[1]["igt_ms"] == 10000
    assert history[1]["message_id"] == 77


def test_shared_entrance_multi_flag_dedup(
    integration_client, race_with_participants, integration_db
):
    """Two flags resolving to the same node with near-identical IGT are deduplicated.

    Shared entrances (DuplicateEntrance in FogMod) cause multiple SetEventFlag
    instructions for the same warp, producing multiple event_flag messages that
    resolve to the same node_id within the same EMEVD frame.
    """
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Add a second flag mapping to node_a (simulates shared entrance)
    async def add_shared_entrance_flag():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph["event_map"]["9000020"] = "node_a"  # second flag → same node
            race.seed.graph_json = graph
            await db.commit()

    asyncio.run(add_shared_entrance_flag())

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # Send two flags that resolve to the same node with near-identical IGT
        # (simulates shared entrance: both fire in same EMEVD frame)
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")  # first visit

        mod0.send_event_flag(9000020, igt_ms=10000)  # same node, same IGT
        time.sleep(0.5)  # give server time to process (should be silently dropped)

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    # zone_history: spawn + node_a (duplicate was deduped)
    assert len(history) == 2
    assert history[1]["node_id"] == "node_a"
    assert history[1]["igt_ms"] == 10000


def test_shared_entrance_dedup_allows_legitimate_revisit(
    integration_client, race_with_participants, integration_db
):
    """A revisit to the same node with IGT > tolerance window is NOT deduped."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # First visit to node_a
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")

        # Legitimate revisit 5 seconds later (well beyond 1s tolerance)
        mod0.send_event_flag(9000000, igt_ms=15000)
        mod0.receive_until_type("player_update")

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    # zone_history: spawn + first visit node_a + revisit node_a
    assert len(history) == 3
    assert history[1]["igt_ms"] == 10000
    assert history[2]["igt_ms"] == 15000


def test_event_flag_lower_layer_recorded_without_regressing(
    integration_client, race_with_participants, integration_db
):
    """Event flags for zones below current_layer are recorded but don't regress ranking."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition to PLAYING via status_update (places in start_node, layer 0).
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING

        # Progress to node_b (layer 2), skipping node_a (layer 1) is fine
        mod0.send_event_flag(9000001, igt_ms=20000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 2

        # Now send flag for node_a (layer 1), recorded but current_layer stays at 2
        mod0.send_event_flag(9000000, igt_ms=25000)
        lb2 = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb2["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 2  # high watermark, not regressed

    # Verify DB state
    async def check_state():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.current_layer, p.current_zone, p.zone_history

    current_layer, current_zone, history = asyncio.run(check_state())
    assert current_layer == 2  # high watermark preserved
    assert current_zone == "node_a"  # position updated to where player actually is
    assert history is not None
    node_ids = [e["node_id"] for e in history]
    assert "node_a" in node_ids  # recorded in history
    assert "node_b" in node_ids


def test_zone_history_entry_types(integration_client, race_with_participants, integration_db):
    """zone_history entries should have type field: spawn for start, fog for event_flag."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive_until_type("leaderboard_update")

    # Start the race after ready
    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # First status_update triggers spawn entry (READY→PLAYING)
        mod0.send_status_update(igt_ms=1000, death_count=0)

        # Fog gate traversal
        mod0.send_event_flag(9000000, igt_ms=10000)
        time.sleep(0.5)  # let server process both messages

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    assert len(history) == 2

    # First entry: spawn (from status_update READY→PLAYING)
    assert history[0]["type"] == "spawn"
    # Second entry: fog (from event_flag)
    assert history[1]["type"] == "fog"


def test_zone_history_backtrack_type(integration_db, integration_client, seed_folder):
    """zone_query that resolves to a different node produces a 'backtrack' type entry."""
    import asyncio

    # Graph: chapel_start → stormveil_godrick (event_flag 1040292800)
    # Grace 10012952 → chapel_start, grace 10002950 → stormveil_godrick
    graph_json = {
        "version": "4.0",
        "total_layers": 2,
        "nodes": {
            "chapel_start_4f96": {
                "type": "start",
                "display_name": "Chapel of Anticipation",
                "zones": ["chapel_start"],
                "layer": 0,
                "exits": [],
            },
            "stormveil_godrick_48fd": {
                "display_name": "Godrick the Grafted",
                "zones": ["stormveil_godrick"],
                "layer": 1,
                "tier": 5,
                "exits": [
                    {"text": "Before boss", "fog_id": 200, "to": "chapel_start_4f96"},
                ],
            },
        },
        "event_map": {"1040292800": "stormveil_godrick_48fd"},
        "finish_event": 1040292801,
    }

    async def setup():
        async with integration_db() as db:
            organizer = User(
                twitch_id="bt_organizer",
                twitch_username="bt_organizer",
                twitch_display_name="BT Org",
                api_token="bt_organizer_token",
                role=UserRole.ORGANIZER,
            )
            player = User(
                twitch_id="bt_player",
                twitch_username="bt_player",
                twitch_display_name="BT Player",
                api_token="bt_player_token",
                role=UserRole.USER,
            )
            player2 = User(
                twitch_id="bt_player2",
                twitch_username="bt_player2",
                twitch_display_name="BT Player2",
                api_token="bt_player2_token",
                role=UserRole.USER,
            )
            seed = Seed(
                seed_number="sbt_001",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path=str(seed_folder),
                status=SeedStatus.AVAILABLE,
            )
            db.add_all([organizer, player, player2, seed])
            await db.commit()
            await db.refresh(organizer)
            await db.refresh(player)
            await db.refresh(player2)
            return organizer, player, player2

    organizer, player, player2 = asyncio.run(setup())
    org_headers = {"Authorization": f"Bearer {organizer.api_token}"}

    # Create race
    resp = integration_client.post(
        "/api/races",
        json={"name": "Backtrack Type Test", "pool_name": "standard"},
        headers=org_headers,
    )
    assert resp.status_code == 201
    race_id = resp.json()["id"]

    # Override seed graph
    async def set_graph():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            if race.seed:
                race.seed.graph_json = graph_json
                race.seed.total_layers = 2
                await db.commit()

    asyncio.run(set_graph())

    # Add participants (need at least 2 to start)
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player2.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200

    # Get mod token
    async def get_token():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.mod_token

    mod_token = asyncio.run(get_token())

    # Ready + start
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"
        mod.send_ready()
        mod.receive_until_type("leaderboard_update")

    integration_client.post(f"/api/races/{race_id}/release-seeds", headers=org_headers)
    resp = integration_client.post(f"/api/races/{race_id}/start", headers=org_headers)
    assert resp.status_code == 200

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"

        # 1) status_update → spawn at start node (READY→PLAYING broadcasts leaderboard)
        mod.send_status_update(igt_ms=1000, death_count=0)
        mod.receive_until_type("leaderboard_update")

        # 2) event_flag → fog traversal to stormveil_godrick
        #    Server sends: leaderboard_update (broadcast) + zone_update (unicast)
        mod.send_event_flag(1040292800, igt_ms=5000, message_id=10)
        ack = mod.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 10
        mod.receive_until_type("leaderboard_update")
        fog_zone_update = mod.receive_until_type("zone_update")
        assert fog_zone_update["node_id"] == "stormveil_godrick_48fd"

        # 3) zone_query grace 10012952 → chapel_start (backtrack via fast-travel)
        #    Server sends: zone_update (unicast) + player_update (broadcast, revisit)
        mod.send_zone_query(10012952)
        backtrack_zone_update = mod.receive_until_type("zone_update")
        assert backtrack_zone_update["node_id"] == "chapel_start_4f96"

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    assert len(history) == 3

    assert history[0]["type"] == "spawn"
    assert history[0]["node_id"] == "chapel_start_4f96"
    assert history[1]["type"] == "fog"
    assert history[1]["node_id"] == "stormveil_godrick_48fd"
    assert history[2]["type"] == "backtrack"
    assert history[2]["node_id"] == "chapel_start_4f96"


def test_event_flag_same_layer_accepted(integration_client, race_with_participants, integration_db):
    """Event flags for zones at the same layer as current_layer are accepted."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Add a second node at layer 1 to the graph
    async def add_sibling_node():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            # Deep copy to ensure SQLAlchemy detects the mutation
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph["nodes"]["node_a2"] = {"zones": ["zone_a2"], "layer": 1, "tier": 1}
            graph["event_map"]["9000010"] = "node_a2"
            race.seed.graph_json = graph
            await db.commit()

    asyncio.run(add_sibling_node())

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition to PLAYING and drain the broadcast
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING

        # Progress to node_a (layer 1)
        mod0.send_event_flag(9000000, igt_ms=10000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 1

        # Send flag for node_a2 (also layer 1), same layer, should be accepted
        mod0.send_event_flag(9000010, igt_ms=15000)
        lb = mod0.receive_until_type("leaderboard_update")

    # Verify DB: both nodes in history
    async def check_state():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.current_layer, p.current_zone, p.zone_history

    current_layer, current_zone, history = asyncio.run(check_state())
    assert current_layer == 1
    assert current_zone == "node_a2"
    node_ids = [e["node_id"] for e in history]
    assert "node_a" in node_ids
    assert "node_a2" in node_ids


def test_zone_update_content(integration_client, race_with_participants):
    """Verify zone_update unicast contains correct node data and exit discovery."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(drain=False)["type"] == "auth_ok"

        # Reconnect to running race sends zone_update for start node, consume it
        zu_start = mod0.receive_until_type("zone_update")
        assert zu_start["node_id"] == "start_node"
        assert zu_start["display_name"] == "Chapel of Anticipation"

        # Transition READY->PLAYING (consumes the connect broadcast + PLAYING broadcast)
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING

        # Trigger flag 9000000 -> node_a ("Stormveil Castle")
        mod0.send_event_flag(9000000, igt_ms=10000)
        zu = mod0.receive_until_type("zone_update")

        assert zu["node_id"] == "node_a"
        assert zu["display_name"] == "Stormveil Castle"
        assert zu["tier"] == 1
        # node_a has one exit to node_b, which is not yet discovered
        assert len(zu["exits"]) == 1
        assert zu["exits"][0]["text"] == "Gate to B"
        assert zu["exits"][0]["to_name"] == "Raya Lucaria"
        assert zu["exits"][0]["discovered"] is False

        # Now trigger flag 9000001 -> node_b
        mod0.send_event_flag(9000001, igt_ms=20000)
        zu2 = mod0.receive_until_type("zone_update")

        assert zu2["node_id"] == "node_b"
        assert zu2["display_name"] == "Raya Lucaria"
        assert zu2["exits"] == []  # node_b has no exits


# =============================================================================
# Scenario 6: Race starts in SETUP
# =============================================================================


def test_race_starts_in_setup(integration_client, race_with_participants):
    """New race starts in SETUP status."""
    race_id = race_with_participants["race_id"]
    token = race_with_participants["organizer"].api_token

    resp = integration_client.get(
        f"/api/races/{race_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "setup"


# =============================================================================
# Scenario 7: Spawn Items in auth_ok
# =============================================================================


def test_auth_ok_spawn_items_empty_when_no_gems(
    integration_client, race_with_participants, integration_db
):
    """auth_ok.seed.spawn_items is an empty list when seed has no type-4 care_package items."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Strip care_package from the seed so there are no type-4 items
    async def strip_care_package():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph.pop("care_package", None)
            race.seed.graph_json = graph
            await db.commit()

    asyncio.run(strip_care_package())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth()
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["spawn_items"] == []


def test_auth_ok_spawn_items_includes_gem_items(
    integration_client, race_with_participants, integration_db
):
    """auth_ok.seed.spawn_items contains type-4 care_package items as SpawnItem objects."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Inject care_package with type-4 (gem) and non-type-4 items into the seed
    async def inject_care_package():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph["care_package"] = [
                {"id": 10100, "type": 4, "name": "Gem A"},
                {"id": 20200, "type": 2, "name": "Weapon B"},
                {"id": 10300, "type": 4, "name": "Gem C"},
            ]
            race.seed.graph_json = graph
            await db.commit()

    asyncio.run(inject_care_package())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth()
        assert auth["type"] == "auth_ok"
        spawn_items = auth["seed"]["spawn_items"]
        assert spawn_items is not None
        assert len(spawn_items) == 2
        # Only type-4 items should be present, in order
        assert spawn_items[0]["id"] == 10100
        assert spawn_items[0]["qty"] == 1
        assert spawn_items[1]["id"] == 10300


def test_auth_ok_finish_event_present(integration_client, race_with_participants):
    """auth_ok.seed.finish_event matches the seed's graph_json finish_event."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth()
        assert auth["type"] == "auth_ok"
        # The test fixture graph has finish_event: 9000003
        assert auth["seed"]["finish_event"] == 9000003
        # finish_event should also appear in event_ids
        assert 9000003 in auth["seed"]["event_ids"]


# =============================================================================
# Scenario 7: Race State Gating
# =============================================================================


def test_status_update_rejected_when_race_not_running(integration_client, race_with_participants):
    """status_update sent while race is not RUNNING should be rejected with error."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Race is DRAFT (not started). Connect and send status_update.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        mod.send_status_update(igt_ms=5000, death_count=1)
        resp = mod.receive()
        assert resp["type"] == "error"
        assert "not running" in resp["message"].lower()


def test_event_flag_rejected_when_race_not_running(integration_client, race_with_participants):
    """event_flag sent while race is not RUNNING should be rejected with error."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        mod.send_event_flag(flag_id=9000000, igt_ms=5000)
        resp = mod.receive()
        assert resp["type"] == "error"
        assert "not running" in resp["message"].lower()


def test_finished_rejected_when_race_not_running(integration_client, race_with_participants):
    """finished sent while race is not RUNNING should be rejected with error."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        assert mod.auth()["type"] == "auth_ok"

        mod.send_finished(igt_ms=50000)
        resp = mod.receive()
        assert resp["type"] == "error"
        assert "not running" in resp["message"].lower()


# =============================================================================
# Scenario: Zone Query (Fast Travel)
# =============================================================================


def test_zone_query_updates_overlay(integration_db, integration_client, seed_folder):
    """Fast travel zone_query resolves grace → graph node and sends zone_update."""
    import asyncio

    # Set up a race with a graph that includes stormveil_godrick zone
    # (grace entity 10002950 → zone_id "stormveil_godrick" in graces.json)
    graph_json = {
        "version": "4.0",
        "total_layers": 3,
        "nodes": {
            "chapel_start_4f96": {
                "type": "start",
                "display_name": "Chapel of Anticipation",
                "zones": ["chapel_start"],
                "layer": 0,
                "exits": [],
            },
            "stormveil_godrick_48fd": {
                "display_name": "Godrick the Grafted",
                "zones": ["stormveil_godrick"],
                "layer": 1,
                "tier": 5,
                "exits": [
                    {"text": "Before boss", "fog_id": 200, "to": "chapel_start_4f96"},
                ],
            },
        },
        "event_map": {
            "1040292800": "stormveil_godrick_48fd",
        },
        "finish_event": 1040292801,
    }

    async def setup():
        async with integration_db() as db:
            organizer = User(
                twitch_id="zq_organizer",
                twitch_username="zq_organizer",
                twitch_display_name="ZQ Organizer",
                api_token="zq_organizer_token",
                role=UserRole.ORGANIZER,
            )
            player = User(
                twitch_id="zq_player",
                twitch_username="zq_player",
                twitch_display_name="ZQ Player",
                api_token="zq_player_token",
                role=UserRole.USER,
            )
            player2 = User(
                twitch_id="zq_player2",
                twitch_username="zq_player2",
                twitch_display_name="ZQ Player2",
                api_token="zq_player2_token",
                role=UserRole.USER,
            )
            seed = Seed(
                seed_number="szq_001",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=3,
                folder_path=str(seed_folder),
                status=SeedStatus.AVAILABLE,
            )
            db.add_all([organizer, player, player2, seed])
            await db.commit()
            await db.refresh(organizer)
            await db.refresh(player)
            await db.refresh(player2)
            return organizer, player, player2

    organizer, player, player2 = asyncio.run(setup())
    org_headers = {"Authorization": f"Bearer {organizer.api_token}"}

    # Create race
    resp = integration_client.post(
        "/api/races",
        json={"name": "Zone Query Test", "pool_name": "standard"},
        headers=org_headers,
    )
    assert resp.status_code == 201
    race_id = resp.json()["id"]

    # Override seed graph to use our custom graph with stormveil_godrick
    async def set_graph():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            if race.seed:
                race.seed.graph_json = graph_json
                race.seed.total_layers = 3
                await db.commit()

    asyncio.run(set_graph())

    # Add participants (need at least 2 to start)
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player2.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200

    # Get mod token for player
    async def get_token():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.mod_token, str(p.id)

    mod_token, participant_id = asyncio.run(get_token())

    # Ready + start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"
        mod.send_ready()
        mod.receive_until_type("leaderboard_update")

    integration_client.post(f"/api/races/{race_id}/release-seeds", headers=org_headers)
    resp = integration_client.post(f"/api/races/{race_id}/start", headers=org_headers)
    assert resp.status_code == 200

    # Connect, become PLAYING, discover stormveil_godrick, then zone_query
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING before sending event flags
        mod.send_status_update(igt_ms=1000, death_count=0)
        mod.receive_until_type("leaderboard_update")  # READY->PLAYING

        # Discover stormveil_godrick via event_flag
        mod.send_event_flag(1040292800, 5000)
        # Server sends leaderboard_update (broadcast) + zone_update (unicast)
        lb = mod.receive_until_type("leaderboard_update")
        assert lb["type"] == "leaderboard_update"
        zone_update = mod.receive_until_type("zone_update")
        assert zone_update["node_id"] == "stormveil_godrick_48fd"

        # Now simulate fast travel back to Godrick grace
        # Grace entity ID 10002950 → zone_id "stormveil_godrick" → node "stormveil_godrick_48fd"
        mod.send_zone_query(10002950)
        zone_update2 = mod.receive_until_type("zone_update")
        assert zone_update2["node_id"] == "stormveil_godrick_48fd"
        assert zone_update2["display_name"] == "Godrick the Grafted"
        assert zone_update2["tier"] == 5

    # Verify current_zone updated in DB
    async def verify_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.current_zone

    current_zone = asyncio.run(verify_db())
    assert current_zone == "stormveil_godrick_48fd"


def test_zone_query_map_id_death_respawn(integration_db, integration_client, seed_folder):
    """zone_query with map_id only (death/respawn) resolves to correct node."""
    import asyncio

    # m12_04_00_00 → ainsel_boss (unique in graces.json)
    graph_json = {
        "version": "4.0",
        "total_layers": 2,
        "nodes": {
            "start_node": {
                "type": "start",
                "display_name": "Start",
                "zones": ["chapel_start"],
                "layer": 0,
                "exits": [],
            },
            "ainsel_boss_node": {
                "display_name": "Astel, Naturalborn of the Void",
                "zones": ["ainsel_boss"],
                "layer": 1,
                "tier": 8,
                "exits": [],
            },
        },
        "event_map": {"1040292800": "ainsel_boss_node"},
        "finish_event": 1040292801,
    }

    async def setup():
        async with integration_db() as db:
            organizer = User(
                twitch_id="zqmap_organizer",
                twitch_username="zqmap_organizer",
                twitch_display_name="ZQMap Org",
                api_token="zqmap_organizer_token",
                role=UserRole.ORGANIZER,
            )
            player = User(
                twitch_id="zqmap_player",
                twitch_username="zqmap_player",
                twitch_display_name="ZQMap Player",
                api_token="zqmap_player_token",
                role=UserRole.USER,
            )
            player2 = User(
                twitch_id="zqmap_player2",
                twitch_username="zqmap_player2",
                twitch_display_name="ZQMap Player2",
                api_token="zqmap_player2_token",
                role=UserRole.USER,
            )
            seed = Seed(
                seed_number="szqmap_001",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path=str(seed_folder),
                status=SeedStatus.AVAILABLE,
            )
            db.add_all([organizer, player, player2, seed])
            await db.commit()
            await db.refresh(organizer)
            await db.refresh(player)
            await db.refresh(player2)
            return organizer, player, player2

    organizer, player, player2 = asyncio.run(setup())
    org_headers = {"Authorization": f"Bearer {organizer.api_token}"}

    # Create race
    resp = integration_client.post(
        "/api/races",
        json={"name": "Map ID Zone Query Test", "pool_name": "standard"},
        headers=org_headers,
    )
    assert resp.status_code == 201
    race_id = resp.json()["id"]

    # Override seed graph
    async def set_graph():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            if race.seed:
                race.seed.graph_json = graph_json
                race.seed.total_layers = 2
                await db.commit()

    asyncio.run(set_graph())

    # Add participants (need at least 2 to start)
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player2.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200

    # Get mod token for player
    async def get_token():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.mod_token

    mod_token = asyncio.run(get_token())

    # Ready + start
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"
        mod.send_ready()
        mod.receive_until_type("leaderboard_update")

    integration_client.post(f"/api/races/{race_id}/release-seeds", headers=org_headers)
    resp = integration_client.post(f"/api/races/{race_id}/start", headers=org_headers)
    assert resp.status_code == 200

    # Connect, become PLAYING, explore ainsel_boss, then simulate death/respawn
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"

        # Transition READY->PLAYING and explore ainsel_boss via event_flag
        mod.send_status_update(igt_ms=1000, death_count=0)
        mod.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod.send_event_flag(1040292800, igt_ms=5000)
        mod.receive_until_type("leaderboard_update")

        # Send zone_query with map_id only (simulates death/respawn in ainsel_boss)
        # The player has already explored ainsel_boss_node so the history filter passes
        mod.send_zone_query(map_id="m12_04_00_00")
        zone_update = mod.receive_until_type("zone_update")
        assert zone_update["node_id"] == "ainsel_boss_node"
        assert zone_update["display_name"] == "Astel, Naturalborn of the Void"


def test_zone_query_no_data_ignored(integration_db, integration_client, seed_folder):
    """zone_query with no useful fields is silently ignored."""
    import asyncio

    graph_json = {
        "version": "4.0",
        "total_layers": 2,
        "nodes": {
            "start_node": {
                "type": "start",
                "display_name": "Start",
                "zones": ["chapel_start"],
                "layer": 0,
                "exits": [],
            },
        },
        "event_map": {},
        "finish_event": 1040292801,
    }

    async def setup():
        async with integration_db() as db:
            organizer = User(
                twitch_id="zqno_organizer",
                twitch_username="zqno_organizer",
                twitch_display_name="ZQNo Org",
                api_token="zqno_organizer_token",
                role=UserRole.ORGANIZER,
            )
            player = User(
                twitch_id="zqno_player",
                twitch_username="zqno_player",
                twitch_display_name="ZQNo Player",
                api_token="zqno_player_token",
                role=UserRole.USER,
            )
            player2 = User(
                twitch_id="zqno_player2",
                twitch_username="zqno_player2",
                twitch_display_name="ZQNo Player2",
                api_token="zqno_player2_token",
                role=UserRole.USER,
            )
            seed = Seed(
                seed_number="szqno_001",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path=str(seed_folder),
                status=SeedStatus.AVAILABLE,
            )
            db.add_all([organizer, player, player2, seed])
            await db.commit()
            await db.refresh(organizer)
            await db.refresh(player)
            await db.refresh(player2)
            return organizer, player, player2

    organizer, player, player2 = asyncio.run(setup())
    org_headers = {"Authorization": f"Bearer {organizer.api_token}"}

    # Create race
    resp = integration_client.post(
        "/api/races",
        json={"name": "No Data Zone Query Test", "pool_name": "standard"},
        headers=org_headers,
    )
    assert resp.status_code == 201
    race_id = resp.json()["id"]

    # Override seed graph
    async def set_graph():
        async with integration_db() as db:
            from sqlalchemy.orm import selectinload as _sinload

            race_result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(_sinload(Race.seed))
            )
            race = race_result.scalar_one()
            if race.seed:
                race.seed.graph_json = graph_json
                race.seed.total_layers = 2
                await db.commit()

    asyncio.run(set_graph())

    # Add participants (need at least 2 to start)
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200
    resp = integration_client.post(
        f"/api/races/{race_id}/participants",
        json={"twitch_username": player2.twitch_username},
        headers=org_headers,
    )
    assert resp.status_code == 200

    # Get mod token for player
    async def get_token():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == player.id,
                )
            )
            p = result.scalar_one()
            return p.mod_token

    mod_token = asyncio.run(get_token())

    # Ready + start
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"
        mod.send_ready()
        mod.receive_until_type("leaderboard_update")

    integration_client.post(f"/api/races/{race_id}/release-seeds", headers=org_headers)
    resp = integration_client.post(f"/api/races/{race_id}/start", headers=org_headers)
    assert resp.status_code == 200

    # Connect and send zone_query with no data, should be silently ignored
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, mod_token)
        assert mod.auth()["type"] == "auth_ok"

        mod.send_zone_query()  # No grace, no map_id
        # Should not receive zone_update; next message should time out
        with pytest.raises(TimeoutError):
            mod.receive(timeout=1)


# =============================================================================
# Scenario: Finished Participant Messages Rejected
# =============================================================================


def test_finished_participant_status_update_ignored(
    integration_client, race_with_participants, integration_db
):
    """status_update from a finished participant is silently dropped (IGT frozen)."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    # Player 0 finishes with igt=50000 (must be PLAYING first)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod0.send_event_flag(9000003, igt_ms=50000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["status"] == "finished"
        assert p0["igt_ms"] == 50000

    # Player 0 reconnects and sends status_update with higher IGT, should be dropped
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=99999, death_count=10)
        time.sleep(0.5)  # Let server process

    # Verify IGT is still frozen at 50000
    async def check_igt():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.igt_ms, p.death_count

    igt, deaths = asyncio.run(check_igt())
    assert igt == 50000, f"IGT should be frozen at 50000, got {igt}"
    assert deaths == 0, f"Death count should not have been updated, got {deaths}"


def test_finished_participant_event_flag_ignored(
    integration_client, race_with_participants, integration_db
):
    """event_flag from a finished participant is silently dropped (no layer/zone update)."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    # Player 0 finishes (must be PLAYING first)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod0.send_event_flag(9000003, igt_ms=50000)
        mod0.receive_until_type("leaderboard_update")

    # Player 0 sends an event_flag after finishing, should be dropped
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_event_flag(9000000, igt_ms=60000)
        time.sleep(0.5)

    # Verify zone_history was NOT updated with node_a
    async def check_state():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.igt_ms, p.current_layer, p.zone_history

    igt, layer, history = asyncio.run(check_state())
    assert igt == 50000, f"IGT should be frozen at 50000, got {igt}"
    assert layer == 5, f"Layer should stay at total_layers (5), got {layer}"
    # zone_history should NOT contain node_a
    if history:
        node_ids = [e.get("node_id") for e in history]
        assert "node_a" not in node_ids, "Finished player should not gain new zone history"


def test_finished_participant_event_flag_replay_acked(
    integration_client, race_with_participants, integration_db
):
    """event_flag with message_id from a finished participant gets ACKed (lost ACK recovery)."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    # Player 0 finishes via the finish_event
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING
        mod0.send_event_flag(9000003, igt_ms=50000, message_id=99)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 99
        mod0.receive_until_type("leaderboard_update")

    # Reconnect and replay the finish event (simulates lost ACK scenario).
    # The participant is already FINISHED, so the server should ACK without reprocessing.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_event_flag(9000003, igt_ms=50000, message_id=99)
        ack = mod0.receive_until_type("event_flag_ack")
        assert ack["message_id"] == 99


def test_death_counts_broadcast(integration_client, race_with_participants):
    """Deaths broadcast death_counts to all connected mods."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        assert mod1.auth()["type"] == "auth_ok"

        # Transition player 0 READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING (mod0)
        mod1.receive_until_type("leaderboard_update")  # broadcast to mod1 too

        # Player 0 discovers node_a
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")
        mod1.receive_until_type("leaderboard_update")

        # Player 0 dies twice in node_a
        mod0.send_status_update(igt_ms=15000, death_count=2)
        time.sleep(0.3)

        # Both mods should receive death_counts
        msg0 = mod0.receive_until_type("death_counts")
        assert msg0["counts"]["node_a"] == 2

        msg1 = mod1.receive_until_type("death_counts")
        assert msg1["counts"]["node_a"] == 2


def test_death_flags_default_empty_in_auth_ok(integration_client, race_with_participants):
    """auth_ok includes empty death_flags when graph_json has no death_flags."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["death_flags"] == {}


def test_death_counts_on_reconnect(integration_client, race_with_participants):
    """Reconnecting mod receives current death_counts after auth_ok."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 before starting
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Connect both mods
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        assert mod1.auth()["type"] == "auth_ok"

        # Transition player 0 READY->PLAYING before sending event flags
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")  # READY->PLAYING (mod0)
        mod1.receive_until_type("leaderboard_update")  # broadcast to mod1 too

        # Player 0 discovers node_a
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")
        mod1.receive_until_type("leaderboard_update")

        # Player 0 dies twice in node_a
        mod0.send_status_update(igt_ms=15000, death_count=2)
        # Drain player_update then death_counts from both mods
        mod0.receive_until_type("player_update")
        mod0.receive_until_type("death_counts")
        mod1.receive_until_type("death_counts")

    # mod1 is now disconnected; player 0 dies once more
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        mod0.send_status_update(igt_ms=20000, death_count=3)
        mod0.receive_until_type("player_update")
        mod0.receive_until_type("death_counts")

    # Reconnect mod1: should receive death_counts with node_a == 3
    # death_counts is sent during the auth phase (before leaderboard_update),
    # so we use drain=False to inspect it before it gets consumed.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        auth = mod1.auth(drain=False)
        assert auth["type"] == "auth_ok"

        msg = mod1.receive_until_type("death_counts")
        assert msg["counts"]["node_a"] == 3


def test_death_flags_populated_in_auth_ok(
    integration_client, race_with_participants, integration_db
):
    """auth_ok includes death_flags when the seed's graph_json contains them."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Patch the seed's graph_json to include death_flags
    async def add_death_flags():
        async with integration_db() as db:
            result = await db.execute(select(Race).where(Race.id == uuid.UUID(race_id)))
            race = result.scalar_one()
            result = await db.execute(select(Seed).where(Seed.id == race.seed_id))
            seed = result.scalar_one()
            graph = dict(seed.graph_json)
            graph["death_flags"] = {
                "node_a": [1040292500, 1040292501, 1040292502],
            }
            seed.graph_json = graph
            await db.commit()

    asyncio.run(add_death_flags())

    # Connect a mod and check auth_ok contains death_flags
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["death_flags"] == {
            "node_a": [1040292500, 1040292501, 1040292502],
        }


def test_items_spawned_flag_populated_in_auth_ok(
    integration_client, race_with_participants, integration_db
):
    """auth_ok includes items_spawned_flag when the seed's graph_json contains it."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Patch the seed's graph_json to include items_spawned_flag
    async def add_items_spawned_flag():
        async with integration_db() as db:
            result = await db.execute(select(Race).where(Race.id == uuid.UUID(race_id)))
            race = result.scalar_one()
            result = await db.execute(select(Seed).where(Seed.id == race.seed_id))
            seed = result.scalar_one()
            graph = dict(seed.graph_json)
            graph["items_spawned_flag"] = 1050290000
            seed.graph_json = graph
            await db.commit()

    asyncio.run(add_items_spawned_flag())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["items_spawned_flag"] == 1050290000


def test_items_spawned_flag_default_none_in_auth_ok(integration_client, race_with_participants):
    """auth_ok includes null items_spawned_flag when graph_json has no items_spawned_flag."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["items_spawned_flag"] is None


def test_spectator_receives_zone_history_snapshots(integration_client, race_with_participants):
    """Race spectator receives zone_history on spawn, event_flag, and death attribution."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready player 0 and start the race before opening the spectator WS.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws_prep:
        mod_prep = ModTestClient(ws_prep, players[0]["mod_token"])
        assert mod_prep.auth()["type"] == "auth_ok"
        mod_prep.send_ready()
        mod_prep.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    target_id = players[0]["participant_id"]

    def spec_receive_until(ws, msg_type: str, max_messages: int = 10) -> dict:
        """Drain spectator messages until the expected type is seen."""
        for _ in range(max_messages):
            m = ws.receive_json()
            if m.get("type") == msg_type:
                return m
        raise AssertionError(f"Did not receive {msg_type} from spectator")

    with integration_client.websocket_connect(f"/ws/race/{race_id}") as ws_spec:
        # Anonymous spectator: send no_auth to skip the grace period.
        ws_spec.send_json({"type": "no_auth"})
        race_state = ws_spec.receive_json()
        assert race_state["type"] == "race_state"

        with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws_mod:
            mod = ModTestClient(ws_mod, players[0]["mod_token"])
            assert mod.auth()["type"] == "auth_ok"
            # spectator observes the mod_connected leaderboard_update
            # (skipping any interleaved spectator_count)
            spec_receive_until(ws_spec, "leaderboard_update")

            # Spawn: first status_update transitions READY -> PLAYING and records
            # the spawn entry. Spectator sees leaderboard_update then
            # zone_history with the spawn entry.
            mod.send_status_update(igt_ms=1000, death_count=0)
            mod.receive_until_type("leaderboard_update")
            lb_spawn = spec_receive_until(ws_spec, "leaderboard_update")
            assert lb_spawn["participants"][0]["zone_history"] is None
            spawn_msg = spec_receive_until(ws_spec, "zone_history")
            assert spawn_msg["participant_id"] == target_id
            assert len(spawn_msg["history"]) == 1
            assert spawn_msg["history"][0]["type"] == "spawn"
            assert spawn_msg["history"][0]["igt_ms"] == 0
            spawn_node_id = spawn_msg["history"][0]["node_id"]

            # Fog gate: event_flag appends a fog entry. The snapshot now
            # carries both spawn and fog entries.
            mod.send_event_flag(9000000, igt_ms=10000)
            mod.receive_until_type("leaderboard_update")
            spec_receive_until(ws_spec, "leaderboard_update")
            fog_msg = spec_receive_until(ws_spec, "zone_history")
            assert len(fog_msg["history"]) == 2
            assert fog_msg["history"][0]["type"] == "spawn"
            assert fog_msg["history"][1]["type"] == "fog"
            assert fog_msg["history"][1]["igt_ms"] == 10000
            assert fog_msg["history"][1]["node_id"] == "node_a"
            assert spawn_node_id != "node_a"

            # Death attribution: status_update with death_count delta bumps
            # the current_zone entry's deaths count (node_a, igt_ms=10000).
            mod.send_status_update(igt_ms=15000, death_count=3)
            mod.receive_until_type("player_update")
            spec_receive_until(ws_spec, "player_update")
            death_msg = spec_receive_until(ws_spec, "zone_history")
            assert death_msg["participant_id"] == target_id
            assert len(death_msg["history"]) == 2
            # Same entry as before, deaths bumped to 3.
            assert death_msg["history"][1]["node_id"] == "node_a"
            assert death_msg["history"][1]["igt_ms"] == 10000
            assert death_msg["history"][1]["deaths"] == 3
            assert death_msg["history"][1]["type"] == "fog"
