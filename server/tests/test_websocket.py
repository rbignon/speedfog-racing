"""Tests for WebSocket handlers."""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from speedfog_racing.models import ParticipantStatus, RaceStatus
from speedfog_racing.websocket.manager import (
    ConnectionManager,
    RaceRoom,
    SpectatorConnection,
    participant_to_info,
    sort_leaderboard,
)
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    AuthOkMessage,
    EventFlagMessage,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PingMessage,
    PongMessage,
    RaceInfo,
    RaceStateMessage,
    RaceStatusChangeMessage,
    SeedInfo,
)

# --- Mock Models ---


class MockUser:
    def __init__(
        self,
        id: uuid.UUID | None = None,
        twitch_username: str = "testuser",
        twitch_display_name: str | None = "TestUser",
    ):
        self.id = id or uuid.uuid4()
        self.twitch_username = twitch_username
        self.twitch_display_name = twitch_display_name


class MockSeed:
    def __init__(
        self,
        id: uuid.UUID | None = None,
        total_layers: int = 10,
        graph_json: dict | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.total_layers = total_layers
        self.graph_json = graph_json or {"layers": []}


class MockParticipant:
    def __init__(
        self,
        id: uuid.UUID | None = None,
        race_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        user: MockUser | None = None,
        mod_token: str = "test_token",
        status: ParticipantStatus = ParticipantStatus.REGISTERED,
        current_zone: str | None = None,
        current_layer: int = 0,
        igt_ms: int = 0,
        death_count: int = 0,
        finished_at: datetime | None = None,
        color_index: int = 0,
        zone_history: list[dict] | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.race_id = race_id or uuid.uuid4()
        self.user_id = user_id or uuid.uuid4()
        self.user = user or MockUser(id=self.user_id)
        self.mod_token = mod_token
        self.status = status
        self.current_zone = current_zone
        self.current_layer = current_layer
        self.igt_ms = igt_ms
        self.death_count = death_count
        self.finished_at = finished_at
        self.color_index = color_index
        self.zone_history = zone_history


class MockRace:
    def __init__(
        self,
        id: uuid.UUID | None = None,
        name: str = "Test Race",
        status: RaceStatus = RaceStatus.DRAFT,
        seed: MockSeed | None = None,
        participants: list | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.name = name
        self.status = status
        self.seed = seed or MockSeed()
        self.participants = participants or []


# --- Schema Tests ---


class TestSchemas:
    """Test WebSocket message schemas."""

    def test_participant_info(self):
        """Test ParticipantInfo schema."""
        info = ParticipantInfo(
            id="123",
            twitch_username="player1",
            twitch_display_name="Player One",
            status="playing",
            current_zone="zone_a",
            current_layer=3,
            current_layer_tier=2,
            igt_ms=60000,
            death_count=2,
        )
        assert info.twitch_username == "player1"
        assert info.current_layer == 3
        assert info.current_layer_tier == 2

    def test_participant_info_tier_defaults_none(self):
        """Test ParticipantInfo current_layer_tier defaults to None."""
        info = ParticipantInfo(
            id="123",
            twitch_username="player1",
            twitch_display_name=None,
            status="registered",
            current_zone=None,
            current_layer=0,
            igt_ms=0,
            death_count=0,
        )
        assert info.current_layer_tier is None

    def test_participant_info_tier_computed_from_graph(self):
        """Test participant_to_info computes current_layer_tier from graph_json."""
        graph = {
            "nodes": {
                "node_a": {"layer": 1, "tier": 3, "zones": ["zone_a"]},
            }
        }
        user = MockUser(twitch_username="p1")
        participant = MockParticipant(user=user, current_zone="node_a", current_layer=1)
        info = participant_to_info(participant, graph_json=graph)
        assert info.current_layer_tier == 3

    def test_participant_info_tier_none_without_graph(self):
        """Test participant_to_info returns None tier when no graph_json."""
        user = MockUser(twitch_username="p1")
        participant = MockParticipant(user=user, current_zone="node_a", current_layer=1)
        info = participant_to_info(participant)
        assert info.current_layer_tier is None

    def test_race_info(self):
        """Test RaceInfo schema."""
        info = RaceInfo(
            id="race-123",
            name="Test Race",
            status="running",
        )
        assert info.name == "Test Race"
        assert info.status == "running"

    def test_auth_ok_message(self):
        """Test AuthOkMessage serialization."""
        msg = AuthOkMessage(
            participant_id="abc-123",
            race=RaceInfo(id="1", name="Race", status="draft"),
            seed=SeedInfo(total_layers=10),
            participants=[],
        )
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "auth_ok"
        assert data["participant_id"] == "abc-123"
        assert data["race"]["name"] == "Race"

    def test_auth_error_message(self):
        """Test AuthErrorMessage serialization."""
        msg = AuthErrorMessage(message="Invalid token")
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "auth_error"
        assert data["message"] == "Invalid token"

    def test_leaderboard_update_message(self):
        """Test LeaderboardUpdateMessage serialization."""
        msg = LeaderboardUpdateMessage(
            participants=[
                ParticipantInfo(
                    id="1",
                    twitch_username="player1",
                    twitch_display_name="P1",
                    status="playing",
                    current_zone=None,
                    current_layer=5,
                    igt_ms=30000,
                    death_count=1,
                )
            ]
        )
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "leaderboard_update"
        assert len(data["participants"]) == 1

    def test_race_state_message(self):
        """Test RaceStateMessage for spectators."""
        msg = RaceStateMessage(
            race=RaceInfo(id="1", name="Race", status="running"),
            seed=SeedInfo(total_layers=10, graph_json={"layers": []}),
            participants=[],
        )
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "race_state"
        assert data["seed"]["graph_json"] is not None

    def test_race_status_change_message(self):
        """Test RaceStatusChangeMessage."""
        msg = RaceStatusChangeMessage(status="running")
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "race_status_change"
        assert data["status"] == "running"

    def test_event_flag_message(self):
        """Test EventFlagMessage schema."""
        msg = EventFlagMessage(flag_id=9000003, igt_ms=4532100)
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "event_flag"
        assert data["flag_id"] == 9000003
        assert data["igt_ms"] == 4532100

    def test_seed_info_with_event_ids(self):
        """Test SeedInfo includes event_ids."""
        info = SeedInfo(
            total_layers=12,
            event_ids=[9000001, 9000002, 9000003],
        )
        data = json.loads(info.model_dump_json())
        assert data["event_ids"] == [9000001, 9000002, 9000003]

    def test_seed_info_event_ids_default_none(self):
        """Test SeedInfo event_ids defaults to None."""
        info = SeedInfo(total_layers=10)
        data = json.loads(info.model_dump_json())
        assert data.get("event_ids") is None

    def test_ping_message(self):
        """Test PingMessage schema."""
        msg = PingMessage()
        data = json.loads(msg.model_dump_json())
        assert data == {"type": "ping"}

    def test_pong_message(self):
        """Test PongMessage schema."""
        msg = PongMessage()
        data = json.loads(msg.model_dump_json())
        assert data == {"type": "pong"}


# --- Manager Tests ---


class TestConnectionManager:
    """Test ConnectionManager."""

    def test_get_or_create_room(self):
        """Test room creation."""
        manager = ConnectionManager()
        race_id = uuid.uuid4()

        room = manager.get_or_create_room(race_id)
        assert room.race_id == race_id
        assert race_id in manager.rooms

        # Same room returned
        room2 = manager.get_or_create_room(race_id)
        assert room is room2

    def test_get_room_not_exists(self):
        """Test getting non-existent room."""
        manager = ConnectionManager()
        assert manager.get_room(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_connect_disconnect_mod(self):
        """Test mod connection lifecycle."""
        manager = ConnectionManager()
        race_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        websocket = MagicMock()

        await manager.connect_mod(race_id, participant_id, user_id, websocket)
        assert manager.is_mod_connected(race_id, participant_id)

        await manager.disconnect_mod(race_id, participant_id)
        assert not manager.is_mod_connected(race_id, participant_id)

    @pytest.mark.asyncio
    async def test_connect_disconnect_spectator(self):
        """Test spectator connection lifecycle."""
        manager = ConnectionManager()
        race_id = uuid.uuid4()
        websocket = AsyncMock()
        conn = SpectatorConnection(websocket=websocket)

        await manager.connect_spectator(race_id, conn)
        room = manager.get_room(race_id)
        assert conn in room.spectators

        await manager.disconnect_spectator(race_id, conn)
        # Room should be cleaned up when empty
        assert manager.get_room(race_id) is None

    @pytest.mark.asyncio
    async def test_broadcast_to_mods(self):
        """Test broadcasting to mod connections."""
        room = RaceRoom(race_id=uuid.uuid4())
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        room.mods[uuid.uuid4()] = MagicMock(websocket=ws1)
        room.mods[uuid.uuid4()] = MagicMock(websocket=ws2)

        await room.broadcast_to_mods('{"type": "test"}')

        ws1.send_text.assert_called_once_with('{"type": "test"}')
        ws2.send_text.assert_called_once_with('{"type": "test"}')

    @pytest.mark.asyncio
    async def test_broadcast_to_spectators(self):
        """Test broadcasting to spectator connections."""
        room = RaceRoom(race_id=uuid.uuid4())
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        room.spectators = [
            SpectatorConnection(websocket=ws1),
            SpectatorConnection(websocket=ws2),
        ]

        await room.broadcast_to_spectators('{"type": "test"}')

        ws1.send_text.assert_called_once_with('{"type": "test"}')
        ws2.send_text.assert_called_once_with('{"type": "test"}')

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected(self):
        """Test that disconnected clients are removed during broadcast."""
        room = RaceRoom(race_id=uuid.uuid4())
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = Exception("Connection closed")

        conn_bad = SpectatorConnection(websocket=ws_bad)
        conn_good = SpectatorConnection(websocket=ws_good)
        room.spectators = [conn_bad, conn_good]

        await room.broadcast_to_spectators('{"type": "test"}')

        # Bad connection should be removed
        assert conn_bad not in room.spectators
        assert conn_good in room.spectators


# --- Leaderboard Tests ---


class TestLeaderboard:
    """Test leaderboard sorting."""

    def test_sort_finished_first(self):
        """Finished players should come first."""
        p1 = MockParticipant(status=ParticipantStatus.PLAYING, current_layer=5, igt_ms=60000)
        p2 = MockParticipant(status=ParticipantStatus.FINISHED, igt_ms=50000)
        p3 = MockParticipant(status=ParticipantStatus.REGISTERED)

        sorted_list = sort_leaderboard([p1, p2, p3])

        assert sorted_list[0].status == ParticipantStatus.FINISHED
        assert sorted_list[1].status == ParticipantStatus.PLAYING
        assert sorted_list[2].status == ParticipantStatus.REGISTERED

    def test_sort_finished_by_igt(self):
        """Finished players sorted by IGT (lowest first)."""
        p1 = MockParticipant(status=ParticipantStatus.FINISHED, igt_ms=60000)
        p2 = MockParticipant(status=ParticipantStatus.FINISHED, igt_ms=50000)
        p3 = MockParticipant(status=ParticipantStatus.FINISHED, igt_ms=70000)

        sorted_list = sort_leaderboard([p1, p2, p3])

        assert sorted_list[0].igt_ms == 50000
        assert sorted_list[1].igt_ms == 60000
        assert sorted_list[2].igt_ms == 70000

    def test_sort_playing_by_layer_then_igt(self):
        """Playing players sorted by layer (highest first), then IGT."""
        p1 = MockParticipant(status=ParticipantStatus.PLAYING, current_layer=3, igt_ms=60000)
        p2 = MockParticipant(status=ParticipantStatus.PLAYING, current_layer=5, igt_ms=50000)
        p3 = MockParticipant(status=ParticipantStatus.PLAYING, current_layer=5, igt_ms=40000)

        sorted_list = sort_leaderboard([p1, p2, p3])

        # Layer 5 players first, sorted by IGT
        assert sorted_list[0].current_layer == 5
        assert sorted_list[0].igt_ms == 40000
        assert sorted_list[1].current_layer == 5
        assert sorted_list[1].igt_ms == 50000
        assert sorted_list[2].current_layer == 3

    def test_sort_abandoned_last(self):
        """Abandoned players should come last."""
        p1 = MockParticipant(status=ParticipantStatus.ABANDONED)
        p2 = MockParticipant(status=ParticipantStatus.REGISTERED)
        p3 = MockParticipant(status=ParticipantStatus.READY)

        sorted_list = sort_leaderboard([p1, p2, p3])

        assert sorted_list[0].status == ParticipantStatus.READY
        assert sorted_list[1].status == ParticipantStatus.REGISTERED
        assert sorted_list[2].status == ParticipantStatus.ABANDONED


class TestParticipantToInfo:
    """Test participant to info conversion."""

    def test_convert_participant(self):
        """Test converting a participant model to info schema."""
        user = MockUser(twitch_username="player1", twitch_display_name="Player One")
        participant = MockParticipant(
            user=user,
            status=ParticipantStatus.PLAYING,
            current_zone="zone_a",
            current_layer=3,
            igt_ms=60000,
            death_count=2,
        )

        info = participant_to_info(participant)

        assert info.twitch_username == "player1"
        assert info.twitch_display_name == "Player One"
        assert info.status == "playing"
        assert info.current_zone == "zone_a"
        assert info.current_layer == 3
        assert info.igt_ms == 60000
        assert info.death_count == 2

    def test_convert_participant_null_display_name(self):
        """Test converting participant with null display name."""
        user = MockUser(twitch_username="player1", twitch_display_name=None)
        participant = MockParticipant(user=user)

        info = participant_to_info(participant)

        assert info.twitch_display_name is None
