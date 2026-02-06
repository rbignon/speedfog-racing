"""Integration tests for complete race flow."""

import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from speedfog_racing.database import Base
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
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
        return self.ws.receive_json()

    def send_ready(self) -> None:
        """Send ready signal."""
        self.ws.send_json({"type": "ready"})

    def send_status_update(self, igt_ms: int, current_zone: str, death_count: int) -> None:
        """Send periodic status update (layer computed server-side from zone_entered)."""
        self.ws.send_json(
            {
                "type": "status_update",
                "igt_ms": igt_ms,
                "current_zone": current_zone,
                "death_count": death_count,
            }
        )

    def send_zone_entered(self, from_zone: str, to_zone: str, igt_ms: int) -> None:
        """Send zone change event."""
        self.ws.send_json(
            {
                "type": "zone_entered",
                "from_zone": from_zone,
                "to_zone": to_zone,
                "igt_ms": igt_ms,
            }
        )

    def send_finished(self, igt_ms: int) -> None:
        """Send finish event."""
        self.ws.send_json({"type": "finished", "igt_ms": igt_ms})

    def receive(self) -> dict[str, Any]:
        """Receive next message."""
        return self.ws.receive_json()

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
    """Create a temporary seed folder with mock content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        seed_dir = Path(tmpdir) / "seed_999999"
        seed_dir.mkdir()

        (seed_dir / "mod").mkdir()
        (seed_dir / "mod" / "speedfog.dll").write_text("mock dll")
        (seed_dir / "ModEngine").mkdir()
        (seed_dir / "ModEngine" / "config.toml").write_text("[config]")
        (seed_dir / "graph.json").write_text(
            json.dumps(
                {
                    "total_layers": 5,
                    "nodes": [],
                    "area_tiers": {"zone_a": 1, "zone_b": 2, "zone_c": 3},
                }
            )
        )
        (seed_dir / "launch_speedfog.bat").write_text("@echo off")

        yield seed_dir


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
    """Create a race with 3 participants and generate seed packs.

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
                role=UserRole.USER,
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
                seed_number=999999,
                pool_name="standard",
                graph_json={
                    "total_layers": 5,
                    "nodes": [],
                    "area_tiers": {"zone_a": 1, "zone_b": 2, "zone_c": 3},
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

    with tempfile.TemporaryDirectory() as output_dir:
        with patch("speedfog_racing.services.seed_pack_service.settings") as mock_settings:
            mock_settings.seed_packs_output_dir = output_dir
            mock_settings.websocket_url = "ws://test:8000"

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

            # Generate seed packs
            response = integration_client.post(
                f"/api/races/{race_id}/generate-seed-packs",
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
                        select(Race)
                        .where(Race.id == uuid.UUID(race_id))
                        .options(_sinload(Race.seed))
                    )
                    race = race_result.scalar_one()
                    if race.seed:
                        # Ensure area_tiers contains test zone names
                        graph = dict(race.seed.graph_json or {})
                        graph["area_tiers"] = {"zone_a": 1, "zone_b": 2, "zone_c": 3}
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
    """Test complete race flow with 3 players.

    This test runs the complete flow sequentially to avoid WebSocket threading issues.
    """
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Step 1: Connect first mod and verify auth
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        auth_response = mod0.auth()
        assert auth_response["type"] == "auth_ok"
        assert auth_response["race"]["name"] == "Integration Test Race"
        assert "total_layers" in auth_response["seed"]

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
        json={"scheduled_start": datetime.now(UTC).isoformat()},
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Step 4: Players send zone updates and finish (sequentially to avoid concurrency issues)
    # Player 0: enters zone — layer should be computed server-side from area_tiers
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_zone_entered("start", "zone_a", igt_ms=10000)
        lb = mod0.receive()
        assert lb["type"] == "leaderboard_update"
        # zone_a has layer 1 in area_tiers
        p0 = next(p for p in lb["participants"] if p["twitch_username"] == "player0")
        assert p0["current_layer"] == 1

    # Player 1: enters zone
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_zone_entered("start", "zone_b", igt_ms=15000)
        lb = mod1.receive()
        assert lb["type"] == "leaderboard_update"
        # zone_b has layer 2 in area_tiers
        p1 = next(p for p in lb["participants"] if p["twitch_username"] == "player1")
        assert p1["current_layer"] == 2

    # Player 2: enters zone and finishes first (fastest)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws2:
        mod2 = ModTestClient(ws2, players[2]["mod_token"])
        assert mod2.auth()["type"] == "auth_ok"
        mod2.send_finished(igt_ms=50000)
        lb = mod2.receive()
        assert lb["type"] == "leaderboard_update", f"Expected leaderboard_update, got: {lb}"
        # Player 2 should be first (finished)
        assert "participants" in lb, f"No participants in message: {lb}"
        assert lb["participants"][0]["twitch_username"] == "player2"
        assert lb["participants"][0]["status"] == "finished"

    # Player 0: finishes second (slower)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_finished(igt_ms=70000)
        lb = mod0.receive()
        # Player 2 first, player 0 second
        assert lb["participants"][0]["twitch_username"] == "player2"
        assert lb["participants"][1]["twitch_username"] == "player0"

    # Player 1: finishes last (triggers race completion)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth()["type"] == "auth_ok"
        mod1.send_finished(igt_ms=80000)

        # When all players finish, server sends race_status_change THEN leaderboard_update
        # So we may receive them in either order depending on timing
        msg1 = mod1.receive()
        msg2 = mod1.receive()

        # Identify which message is which
        if msg1["type"] == "race_status_change":
            status, lb = msg1, msg2
        else:
            lb, status = msg1, msg2

        # Verify race status change
        assert status["type"] == "race_status_change"
        assert status["status"] == "finished"

        # Verify final leaderboard: player2 (50k), player0 (70k), player1 (80k)
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

        # Download the seed pack using mod_token
        download_response = integration_client.get(f"/api/races/{race_id}/download/{mod_token}")
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
