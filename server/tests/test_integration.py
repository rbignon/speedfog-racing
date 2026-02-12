"""Integration tests for complete race flow."""

import io
import json
import os
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from speedfog_racing.database import Base
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.manager import manager

# Use a unique test database file for integration tests (cross-platform)
INTEGRATION_TEST_DB = os.path.join(tempfile.gettempdir(), "speedfog_integration_test.db")


# =============================================================================
# Helper Classes
# =============================================================================


class ModTestClient:
    """Simulates a mod connecting to the race WebSocket."""

    def __init__(self, websocket, mod_token: str):
        self.ws = websocket
        self.mod_token = mod_token

    def auth(self) -> dict[str, Any]:
        """Send auth and return response."""
        self.ws.send_json({"type": "auth", "mod_token": self.mod_token})
        return self.receive()

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

    def send_event_flag(self, flag_id: int, igt_ms: int) -> None:
        """Send event flag trigger."""
        self.ws.send_json(
            {
                "type": "event_flag",
                "flag_id": flag_id,
                "igt_ms": igt_ms,
            }
        )

    def send_finished(self, igt_ms: int) -> None:
        """Send finish event."""
        self.ws.send_json({"type": "finished", "igt_ms": igt_ms})

    def receive(self, timeout: float = 5) -> dict[str, Any]:
        """Receive next message. Raises TimeoutError after *timeout* seconds."""
        from concurrent.futures import Future, ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FuturesTimeout

        with ThreadPoolExecutor(max_workers=1) as executor:
            future: Future[dict[str, Any]] = executor.submit(self.ws.receive_json)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeout:
                future.cancel()
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
    import asyncio

    import speedfog_racing.database as db_module
    import speedfog_racing.main as main_module

    # Clean up any existing test db
    if os.path.exists(INTEGRATION_TEST_DB):
        os.remove(INTEGRATION_TEST_DB)

    # Create new engine and session maker for tests
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{INTEGRATION_TEST_DB}",
        echo=False,
    )
    test_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    async def init():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init())

    # Patch the database module
    original_engine = db_module.engine
    original_session_maker = db_module.async_session_maker

    db_module.engine = test_engine
    db_module.async_session_maker = test_session_maker

    # Also patch main module's import
    main_module.async_session_maker = test_session_maker

    try:
        yield test_session_maker
    finally:
        # Restore originals
        db_module.engine = original_engine
        db_module.async_session_maker = original_session_maker
        main_module.async_session_maker = original_session_maker

        # Clean up
        asyncio.run(test_engine.dispose())
        if os.path.exists(INTEGRATION_TEST_DB):
            os.remove(INTEGRATION_TEST_DB)


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
            zf.writestr(f"{top}/lib/speedfog_race_mod.dll", "mock dll")
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
                race.seed.graph_json = graph
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
        mod0.send_event_flag(9000000, igt_ms=10000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 1

    # Player 1: triggers flag 9000001 -> node_b (layer 2)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_event_flag(9000001, igt_ms=15000)
        lb = mod1.receive_until_type("leaderboard_update")
        p1 = next(p for p in lb["participants"] if p["twitch_username"] == "player1")
        assert p1["current_layer"] == 2

    # Player 2: triggers finish_event (9000003) -> race finish
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
        mod2 = ModTestClient(ws2, players[2]["mod_token"])
        assert mod2.auth()["type"] == "auth_ok"
        mod2.send_event_flag(9000003, igt_ms=50000)
        lb = mod2.receive_until_type("leaderboard_update")
        p2 = next(p for p in lb["participants"] if p["twitch_username"] == "player2")
        assert p2["status"] == "finished"

    # Player 0 finishes
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_event_flag(9000003, igt_ms=70000)
        lb = mod0.receive_until_type("leaderboard_update")
        assert lb["participants"][0]["twitch_username"] == "player2"
        assert lb["participants"][1]["twitch_username"] == "player0"

    # Player 1 finishes last (triggers race completion)
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


def test_duplicate_connection_rejected(integration_client, race_with_participants):
    """Test that duplicate connection for same participant is rejected."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    mod_token = players[0]["mod_token"]

    # First connection
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, mod_token)
        assert mod1.auth()["type"] == "auth_ok"

        # Second connection with same token
        with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
            mod2 = ModTestClient(ws2, mod_token)
            response = mod2.auth()
            assert response["type"] == "auth_error"
            assert "Already connected" in response["message"]


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
    2. Each player can download their seed pack
    3. The seed pack contains speedfog_race.toml with their unique mod_token and race_id
    """
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Seed packs were already generated in the fixture, get download URLs
    race_response = integration_client.get(f"/api/races/{race_id}")
    assert race_response.status_code == 200

    # Download and verify each player's seed pack
    for player_data in players:
        mod_token = player_data["mod_token"]
        username = player_data["user"].twitch_username

        # Download the seed pack using mod_token (authenticated as the player)
        download_response = integration_client.get(
            f"/api/races/{race_id}/download/{mod_token}",
            headers={"Authorization": f"Bearer {player_data['user'].api_token}"},
        )
        assert download_response.status_code == 200, f"Failed to download seed pack for {username}"
        assert download_response.headers["content-type"] == "application/zip"

        # Extract and verify the config file
        zip_content = io.BytesIO(download_response.content)
        with zipfile.ZipFile(zip_content, "r") as zf:
            # Find the config file (speedfog_race.toml)
            config_files = [n for n in zf.namelist() if n.endswith("speedfog_race.toml")]
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

    # Send first status_update — should transition READY → PLAYING + start zone
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
# Scenario 4: Zone History Accumulation
# =============================================================================


def test_zone_history_accumulates(integration_client, race_with_participants, integration_db):
    """Verify event_flag messages append to participant.zone_history."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

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
    assert len(history) == 2
    assert history[0]["node_id"] == "node_a"
    assert history[0]["igt_ms"] == 10000
    assert history[1]["node_id"] == "node_b"
    assert history[1]["igt_ms"] == 20000


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


def test_event_flag_duplicate_ignored(integration_client, race_with_participants, integration_db):
    """Sending the same event flag twice doesn't duplicate zone_history entries."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Send same flag twice
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive()  # leaderboard_update

        mod0.send_event_flag(9000000, igt_ms=11000)
        # No leaderboard_update for duplicate -- verify with a ready
        mod0.send_ready()
        msg = mod0.receive()
        assert msg["type"] == "leaderboard_update"

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
    assert len(history) == 1  # Not duplicated
    assert history[0]["node_id"] == "node_a"


def test_event_flag_lower_layer_recorded_without_regressing(
    integration_client, race_with_participants, integration_db
):
    """Event flags for zones below current_layer are recorded but don't regress ranking."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition to PLAYING via status_update (places in start_node, layer 0).
        mod0.send_status_update(igt_ms=1000, death_count=0)

        # Progress to node_b (layer 2) — skipping node_a (layer 1) is fine
        mod0.send_event_flag(9000001, igt_ms=20000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 2

        # Now send flag for node_a (layer 1) — recorded but current_layer stays at 2
        mod0.send_event_flag(9000000, igt_ms=25000)
        lb2 = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb2["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 2  # high watermark — not regressed

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

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition to PLAYING (no response to mod — sequential processing)
        mod0.send_status_update(igt_ms=1000, death_count=0)

        # Progress to node_a (layer 1)
        mod0.send_event_flag(9000000, igt_ms=10000)
        lb = mod0.receive_until_type("leaderboard_update")
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 1

        # Send flag for node_a2 (also layer 1) — same layer, should be accepted
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

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Reconnect to running race sends zone_update for start node — consume it
        zu_start = mod0.receive_until_type("zone_update")
        assert zu_start["node_id"] == "start_node"
        assert zu_start["display_name"] == "Chapel of Anticipation"

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
# Scenario 6: Open Race (DRAFT → OPEN)
# =============================================================================


def test_open_race(integration_client, race_with_participants):
    """Test DRAFT → OPEN status transition."""
    race_id = race_with_participants["race_id"]
    token = race_with_participants["organizer"].api_token

    # Race starts in DRAFT
    resp = integration_client.get(
        f"/api/races/{race_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"

    # Open the race
    resp = integration_client.post(
        f"/api/races/{race_id}/open",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"

    # Verify it persisted
    resp = integration_client.get(
        f"/api/races/{race_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["status"] == "open"


def test_open_race_not_organizer(integration_client, race_with_participants):
    """Non-organizer cannot open a race."""
    race_id = race_with_participants["race_id"]
    other_token = race_with_participants["players"][0]["user"].api_token

    resp = integration_client.post(
        f"/api/races/{race_id}/open",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


def test_open_race_already_open(integration_client, race_with_participants):
    """Cannot open a race that's not in DRAFT."""
    race_id = race_with_participants["race_id"]
    token = race_with_participants["organizer"].api_token

    # Open it first
    resp = integration_client.post(
        f"/api/races/{race_id}/open",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Try opening again — should fail
    resp = integration_client.post(
        f"/api/races/{race_id}/open",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
