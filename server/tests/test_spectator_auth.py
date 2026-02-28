"""Tests for spectator seed info construction."""

import uuid
from unittest.mock import MagicMock

from speedfog_racing.models import (
    Race,
    RaceStatus,
    Seed,
)
from speedfog_racing.websocket.spectator import build_seed_info


def _make_race(
    status: RaceStatus,
    organizer_id: uuid.UUID,
    seed: Seed | None = None,
) -> Race:
    r = MagicMock(spec=Race)
    r.id = uuid.uuid4()
    r.name = "Test Race"
    r.status = status
    r.organizer_id = organizer_id
    r.participants = []
    r.casters = []
    r.seed = seed
    return r


def _make_seed(graph_json: dict, total_layers: int) -> Seed:
    s = MagicMock(spec=Seed)
    s.total_layers = total_layers
    s.graph_json = graph_json
    return s


# =============================================================================
# build_seed_info Tests
# =============================================================================


class TestBuildSeedInfo:
    """Test SeedInfo construction — graph_json always included."""

    def test_no_seed(self):
        """No seed returns minimal SeedInfo."""
        race = _make_race(RaceStatus.SETUP, uuid.uuid4())
        race.seed = None
        info = build_seed_info(race)
        assert info.total_layers == 0
        assert info.graph_json is None

    def test_running_includes_graph(self, sample_graph_json: dict):
        """RUNNING race includes graph_json."""
        graph = sample_graph_json
        seed = _make_seed(graph, total_layers=graph["total_layers"])
        race = _make_race(RaceStatus.RUNNING, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is not None
        assert info.total_layers == graph["total_layers"]
        assert info.total_nodes == graph["total_nodes"]
        assert info.total_paths == graph["total_paths"]

    def test_finished_includes_graph(self, sample_graph_json: dict):
        """FINISHED race includes graph_json."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        race = _make_race(RaceStatus.FINISHED, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is not None

    def test_setup_includes_graph_for_anonymous(self, sample_graph_json: dict):
        """SETUP race includes graph_json for all spectators (no role restriction)."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        race = _make_race(RaceStatus.SETUP, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is not None
        assert info.total_nodes is not None
        assert info.total_paths is not None

    def test_metadata_computed_from_nodes(self):
        """total_nodes/total_paths computed from graph when not explicit."""
        graph = {"nodes": {"a": {}, "b": {}, "c": {}}, "edges": []}
        seed = _make_seed(graph, total_layers=2)
        race = _make_race(RaceStatus.RUNNING, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.total_nodes == 3
        assert info.total_paths == 0
