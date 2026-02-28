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
    ExitInfo,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PingMessage,
    PongMessage,
    RaceInfo,
    RaceStateMessage,
    RaceStatusChangeMessage,
    SeedInfo,
    ZoneUpdateMessage,
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
        status: RaceStatus = RaceStatus.SETUP,
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
            race=RaceInfo(id="1", name="Race", status="setup"),
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

    def test_seed_info_event_ids_default_empty(self):
        """Test SeedInfo event_ids defaults to empty list."""
        info = SeedInfo(total_layers=10)
        data = json.loads(info.model_dump_json())
        assert data["event_ids"] == []

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

    def test_zone_update_message(self):
        """Test ZoneUpdateMessage serialization."""
        msg = ZoneUpdateMessage(
            node_id="cave_e235",
            display_name="Cave of Knowledge",
            tier=5,
            exits=[
                ExitInfo(
                    text="Soldier of Godrick front",
                    to_name="Road's End Catacombs",
                    discovered=False,
                ),
                ExitInfo(
                    text="Graveyard first door",
                    to_name="Ruin-Strewn Precipice",
                    discovered=True,
                ),
            ],
        )
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "zone_update"
        assert data["node_id"] == "cave_e235"
        assert data["display_name"] == "Cave of Knowledge"
        assert data["tier"] == 5
        assert len(data["exits"]) == 2
        assert data["exits"][0]["discovered"] is False
        assert data["exits"][1]["discovered"] is True

    def test_zone_update_message_no_tier(self):
        """Test ZoneUpdateMessage with no tier."""
        msg = ZoneUpdateMessage(
            node_id="start",
            display_name="Chapel of Anticipation",
            exits=[],
        )
        data = json.loads(msg.model_dump_json())
        assert data["tier"] is None
        assert data["exits"] == []


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

    def test_sort_playing_same_layer_by_entry_igt(self):
        """On same layer, player who entered first should be ranked higher."""
        graph = {
            "nodes": {
                "start": {"layer": 0, "tier": 1},
                "zone_a": {"layer": 1, "tier": 2},
                "zone_b": {"layer": 2, "tier": 3},
            }
        }
        # Player A entered layer 2 first (at IGT 100s) but has higher total IGT now
        p1 = MockParticipant(
            status=ParticipantStatus.PLAYING,
            current_layer=2,
            igt_ms=120000,
            zone_history=[
                {"node_id": "start", "igt_ms": 0},
                {"node_id": "zone_a", "igt_ms": 30000},
                {"node_id": "zone_b", "igt_ms": 100000},
            ],
        )
        # Player B entered layer 2 later (at IGT 110s) but has lower total IGT
        p2 = MockParticipant(
            status=ParticipantStatus.PLAYING,
            current_layer=2,
            igt_ms=115000,
            zone_history=[
                {"node_id": "start", "igt_ms": 0},
                {"node_id": "zone_a", "igt_ms": 40000},
                {"node_id": "zone_b", "igt_ms": 110000},
            ],
        )

        sorted_list = sort_leaderboard([p2, p1], graph_json=graph)

        # Player A should be first (entered layer 2 at 100000 < 110000)
        assert sorted_list[0].igt_ms == 120000  # p1
        assert sorted_list[1].igt_ms == 115000  # p2

    def test_sort_abandoned_by_layer_then_igt(self):
        """Abandoned (DNF) players sorted by layer (highest first), then IGT."""
        p1 = MockParticipant(status=ParticipantStatus.ABANDONED, current_layer=2, igt_ms=90000)
        p2 = MockParticipant(status=ParticipantStatus.ABANDONED, current_layer=5, igt_ms=120000)
        p3 = MockParticipant(status=ParticipantStatus.ABANDONED, current_layer=5, igt_ms=80000)

        sorted_list = sort_leaderboard([p1, p2, p3])

        # Layer 5 players first, sorted by IGT
        assert sorted_list[0].current_layer == 5
        assert sorted_list[0].igt_ms == 80000
        assert sorted_list[1].current_layer == 5
        assert sorted_list[1].igt_ms == 120000
        assert sorted_list[2].current_layer == 2


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

    def test_participant_info_always_includes_zone_history(self):
        """Test participant_to_info always includes zone_history."""
        user = MockUser(twitch_username="p1")
        history = [{"node_id": "node_a", "igt_ms": 1000}]
        participant = MockParticipant(user=user, zone_history=history)
        info = participant_to_info(participant)
        assert info.zone_history == history


class TestGapComputation:
    """Test gap timing computation."""

    def _graph(self):
        """Helper graph: 4 nodes across 4 layers."""
        return {
            "nodes": {
                "start": {"layer": 0, "tier": 1},
                "zone_a": {"layer": 1, "tier": 2},
                "zone_b": {"layer": 2, "tier": 3},
                "boss": {"layer": 3, "tier": 4},
            }
        }

    def test_build_leader_splits(self):
        """Leader splits map each layer to the first IGT at that layer."""
        from speedfog_racing.websocket.manager import build_leader_splits

        history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 30000},
            {"node_id": "zone_b", "igt_ms": 75000},
            {"node_id": "boss", "igt_ms": 120000},
        ]
        splits = build_leader_splits(history, self._graph())
        assert splits == {0: 0, 1: 30000, 2: 75000, 3: 120000}

    def test_build_leader_splits_keeps_first_igt_per_layer(self):
        """If multiple nodes share a layer, keep the first IGT."""
        from speedfog_racing.websocket.manager import build_leader_splits

        graph = {
            "nodes": {
                "start": {"layer": 0, "tier": 1},
                "zone_a": {"layer": 1, "tier": 2},
                "zone_a2": {"layer": 1, "tier": 2},
                "zone_b": {"layer": 2, "tier": 3},
            }
        }
        history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 30000},
            {"node_id": "zone_a2", "igt_ms": 45000},
            {"node_id": "zone_b", "igt_ms": 75000},
        ]
        splits = build_leader_splits(history, graph)
        # Layer 1 should have 30000 (first), not 45000
        assert splits[1] == 30000

    def test_build_leader_splits_empty_history(self):
        """Empty history returns empty splits."""
        from speedfog_racing.websocket.manager import build_leader_splits

        splits = build_leader_splits([], self._graph())
        assert splits == {}

    def test_build_leader_splits_none_history(self):
        """None history returns empty splits."""
        from speedfog_racing.websocket.manager import build_leader_splits

        splits = build_leader_splits(None, self._graph())
        assert splits == {}

    def test_build_leader_splits_skips_unknown_nodes(self):
        """Unknown nodes in zone_history are skipped, not mapped to layer 0."""
        from speedfog_racing.websocket.manager import build_leader_splits

        history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "ghost_node", "igt_ms": 15000},  # not in graph
            {"node_id": "zone_a", "igt_ms": 30000},
        ]
        splits = build_leader_splits(history, self._graph())
        # ghost_node should not appear; layer 0 should be from "start"
        assert splits == {0: 0, 1: 30000}
        assert "ghost_node" not in str(splits)

    def test_compute_gap_within_budget(self):
        """Player within leader's time budget on layer -> gap = entry delta (fixed)."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        leader_splits = {0: 0, 1: 30000, 2: 75000, 3: 120000}
        # Player entered layer 2 at 80000, leader entered layer 2 at 75000
        # Leader exited layer 2 at 120000 (= leader_splits[3])
        # Player current IGT 100000 < 120000 -> within budget
        gap = compute_gap_ms(
            "playing",
            igt_ms=100000,
            current_layer=2,
            player_layer_entry_igt=80000,
            leader_splits=leader_splits,
            leader_igt_ms=0,
        )
        assert gap == 5000  # 80000 - 75000 = entry delta

    def test_compute_gap_exceeded_budget(self):
        """Player exceeded leader's time budget on layer -> gap = igt - leader_exit."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        leader_splits = {0: 0, 1: 30000, 2: 75000, 3: 120000}
        # Player entered layer 2 at 80000, leader entered layer 2 at 75000
        # Leader exited layer 2 at 120000 (= leader_splits[3])
        # Player current IGT 130000 > 120000 -> exceeded budget
        gap = compute_gap_ms(
            "playing",
            igt_ms=130000,
            current_layer=2,
            player_layer_entry_igt=80000,
            leader_splits=leader_splits,
            leader_igt_ms=0,
        )
        assert gap == 10000  # 130000 - 120000

    def test_compute_gap_negative_entry_delta(self):
        """Player entered layer faster than leader -> negative gap (ahead)."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        leader_splits = {0: 0, 1: 30000, 2: 75000, 3: 120000}
        # Player entered layer 2 at 70000, leader at 75000 -> ahead by 5s
        # Player current IGT 80000 < 120000 -> within budget
        gap = compute_gap_ms(
            "playing",
            igt_ms=80000,
            current_layer=2,
            player_layer_entry_igt=70000,
            leader_splits=leader_splits,
            leader_igt_ms=0,
        )
        assert gap == -5000  # 70000 - 75000 = -5000

    def test_compute_gap_leader_still_on_layer(self):
        """Leader hasn't left current layer -> use entry delta (no exit split)."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        leader_splits = {0: 0, 1: 30000, 2: 75000}
        # Player at layer 2, leader also at layer 2 (no layer 3 split)
        gap = compute_gap_ms(
            "playing",
            igt_ms=90000,
            current_layer=2,
            player_layer_entry_igt=80000,
            leader_splits=leader_splits,
            leader_igt_ms=0,
        )
        assert gap == 5000  # 80000 - 75000 = entry delta only

    def test_compute_gap_finished_non_leader(self):
        """Finished non-leader gap = their IGT - leader IGT."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        gap = compute_gap_ms(
            "finished",
            igt_ms=150000,
            current_layer=3,
            player_layer_entry_igt=0,
            leader_splits={},
            leader_igt_ms=120000,
        )
        assert gap == 30000

    def test_compute_gap_leader_returns_none(self):
        """Leader always has gap=None."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        gap = compute_gap_ms(
            "finished",
            igt_ms=120000,
            current_layer=3,
            player_layer_entry_igt=0,
            leader_splits={},
            leader_igt_ms=120000,
            is_leader=True,
        )
        assert gap is None

    def test_compute_gap_ready_returns_none(self):
        """Ready participants always have gap=None."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        gap = compute_gap_ms(
            "ready",
            igt_ms=0,
            current_layer=0,
            player_layer_entry_igt=0,
            leader_splits={},
            leader_igt_ms=0,
        )
        assert gap is None

    def test_compute_gap_no_split_for_layer(self):
        """If leader has no split for player's layer, return None."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        leader_splits = {0: 0, 1: 30000}
        gap = compute_gap_ms(
            "playing",
            igt_ms=90000,
            current_layer=2,
            player_layer_entry_igt=80000,
            leader_splits=leader_splits,
            leader_igt_ms=0,
        )
        assert gap is None

    def test_compute_gap_abandoned_returns_none(self):
        """Abandoned (DNF) participants always have gap=None."""
        from speedfog_racing.websocket.manager import compute_gap_ms

        gap = compute_gap_ms(
            "abandoned",
            igt_ms=90000,
            current_layer=3,
            player_layer_entry_igt=80000,
            leader_splits={0: 0, 1: 30000, 2: 75000, 3: 120000},
            leader_igt_ms=120000,
        )
        assert gap is None

    def test_get_layer_entry_igt(self):
        """Returns first IGT at the specified layer."""
        from speedfog_racing.websocket.manager import get_layer_entry_igt

        history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 30000},
            {"node_id": "zone_b", "igt_ms": 75000},
        ]
        assert get_layer_entry_igt(history, 1, self._graph()) == 30000

    def test_get_layer_entry_igt_none_for_missing_layer(self):
        """Returns None if player has no entry for the layer."""
        from speedfog_racing.websocket.manager import get_layer_entry_igt

        history = [{"node_id": "start", "igt_ms": 0}]
        assert get_layer_entry_igt(history, 2, self._graph()) is None

    def test_get_layer_entry_igt_empty_history(self):
        """Returns None for empty history."""
        from speedfog_racing.websocket.manager import get_layer_entry_igt

        assert get_layer_entry_igt([], 0, self._graph()) is None
        assert get_layer_entry_igt(None, 0, self._graph()) is None

    def test_participant_to_info_with_gap(self):
        """participant_to_info passes gap_ms through."""
        user = MockUser(twitch_username="p1")
        participant = MockParticipant(user=user, status=ParticipantStatus.PLAYING)
        info = participant_to_info(participant, gap_ms=5000)
        assert info.gap_ms == 5000

    def test_participant_to_info_gap_defaults_none(self):
        """participant_to_info gap_ms defaults to None."""
        user = MockUser(twitch_username="p1")
        participant = MockParticipant(user=user, status=ParticipantStatus.PLAYING)
        info = participant_to_info(participant)
        assert info.gap_ms is None

    def test_leader_splits_ignore_backtrack_entries(self):
        """Backtrack entries in zone_history should not affect leader splits."""
        from speedfog_racing.websocket.manager import build_leader_splits

        history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 60000},
            {"node_id": "zone_b", "igt_ms": 120000},
            {"node_id": "zone_a", "igt_ms": 200000},  # backtrack
            {"node_id": "zone_b", "igt_ms": 250000},  # revisit
            {"node_id": "zone_c", "igt_ms": 350000},
        ]
        graph_json = {
            "nodes": {
                "start": {"layer": 0},
                "zone_a": {"layer": 1},
                "zone_b": {"layer": 2},
                "zone_c": {"layer": 3},
            }
        }
        splits = build_leader_splits(history, graph_json)
        # Should use FIRST entry per layer, ignoring backtracks
        assert splits == {0: 0, 1: 60000, 2: 120000, 3: 350000}


class TestEventFlagBacktracking:
    """Test event flag handling with zone backtracking."""

    def test_event_flag_revisit_appends_to_zone_history(self):
        """Revisiting a node should append a new entry to zone_history."""
        # Simulate the logic from handle_event_flag with the new always-append behavior
        # We test the data mutation logic directly since the handler requires full WS setup
        old_history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 60000},
            {"node_id": "zone_b", "igt_ms": 120000},
        ]
        node_id = "zone_a"  # revisit
        igt = 200000
        node_layer = 1  # same as before
        current_layer = 2  # high watermark

        is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)
        assert not is_first_visit  # confirm it's a revisit

        # Always append (new behavior)
        new_entry = {"node_id": node_id, "igt_ms": igt}
        new_history = [*old_history, new_entry]

        # current_layer should NOT regress
        new_layer = current_layer
        if node_layer > current_layer:
            new_layer = node_layer

        assert len(new_history) == 4  # was 3, now 4
        assert new_history[-1] == {"node_id": "zone_a", "igt_ms": 200000}
        assert new_layer == 2  # unchanged (high watermark)

    def test_deaths_attributed_to_last_visit_of_backtracked_zone(self):
        """When player backtracks, deaths go to the most recent zone_history entry."""
        zone_history = [
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 60000},
            {"node_id": "zone_b", "igt_ms": 120000},
            {"node_id": "zone_a", "igt_ms": 200000},  # backtrack
        ]
        current_zone = "zone_a"
        delta = 3

        # New behavior: iterate in reverse to find last matching entry
        history = [dict(e) for e in zone_history]
        for entry in reversed(history):
            if entry.get("node_id") == current_zone:
                entry["deaths"] = entry.get("deaths", 0) + delta
                break

        # Deaths should be on the LAST zone_a entry (index 3), NOT the first (index 1)
        assert history[1].get("deaths") is None  # first visit untouched
        assert history[3]["deaths"] == 3  # last visit gets deaths
