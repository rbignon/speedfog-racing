"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import (
    compute_zone_update,
    get_layer_for_node,
    get_start_node,
    get_tier_for_node,
)


def test_get_layer_for_node_found():
    graph = {
        "nodes": {
            "academy_d5a9": {"layer": 3, "zones": ["academy"]},
            "caelid_cave_aa21": {"layer": 5, "zones": ["caelid_cave"]},
        }
    }
    assert get_layer_for_node("academy_d5a9", graph) == 3
    assert get_layer_for_node("caelid_cave_aa21", graph) == 5


def test_get_layer_for_node_not_found():
    graph = {"nodes": {"academy_d5a9": {"layer": 3}}}
    assert get_layer_for_node("unknown_node", graph) == 0


def test_get_layer_for_node_no_nodes():
    assert get_layer_for_node("any", {}) == 0


def test_get_layer_for_node_missing_layer_key():
    graph = {"nodes": {"node_a": {"zones": ["zone_a"]}}}
    assert get_layer_for_node("node_a", graph) == 0


def test_get_tier_for_node_found():
    graph = {
        "nodes": {
            "academy_d5a9": {"layer": 3, "tier": 2, "zones": ["academy"]},
            "caelid_cave_aa21": {"layer": 5, "tier": 4, "zones": ["caelid_cave"]},
        }
    }
    assert get_tier_for_node("academy_d5a9", graph) == 2
    assert get_tier_for_node("caelid_cave_aa21", graph) == 4


def test_get_tier_for_node_not_found():
    graph = {"nodes": {"academy_d5a9": {"tier": 3}}}
    assert get_tier_for_node("unknown_node", graph) is None


def test_get_tier_for_node_no_tier_key():
    graph = {"nodes": {"node_a": {"layer": 1, "zones": ["zone_a"]}}}
    assert get_tier_for_node("node_a", graph) is None


def test_get_tier_for_node_no_nodes():
    assert get_tier_for_node("any", {}) is None


def test_get_start_node_found():
    graph = {
        "nodes": {
            "chapel_start_4f96": {"type": "start", "layer": 0, "zones": ["chapel"]},
            "volcano_ac44": {"type": "legacy_dungeon", "layer": 1},
        }
    }
    assert get_start_node(graph) == "chapel_start_4f96"


def test_get_start_node_not_found():
    graph = {
        "nodes": {
            "node_a": {"type": "legacy_dungeon", "layer": 1},
            "node_b": {"type": "boss_arena", "layer": 2},
        }
    }
    assert get_start_node(graph) is None


def test_get_start_node_no_nodes():
    assert get_start_node({}) is None


def test_get_start_node_empty_nodes():
    assert get_start_node({"nodes": {}}) is None


# =============================================================================
# compute_zone_update
# =============================================================================

GRAPH_WITH_EXITS = {
    "nodes": {
        "cave_e235": {
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "layer": 2,
            "exits": [
                {"text": "Soldier of Godrick front", "fog_id": 42, "to": "catacombs_a123"},
                {"text": "Graveyard first door", "fog_id": 43, "to": "precipice_b456"},
            ],
        },
        "catacombs_a123": {
            "display_name": "Road's End Catacombs",
            "tier": 3,
            "layer": 3,
            "exits": [],
        },
        "precipice_b456": {
            "display_name": "Ruin-Strewn Precipice",
            "tier": 4,
            "layer": 4,
            "exits": [],
        },
    }
}


def test_compute_zone_update_basic():
    """All exits undiscovered."""
    result = compute_zone_update("cave_e235", GRAPH_WITH_EXITS, zone_history=None)
    assert result is not None
    assert result["type"] == "zone_update"
    assert result["node_id"] == "cave_e235"
    assert result["display_name"] == "Cave of Knowledge"
    assert result["tier"] == 5
    assert len(result["exits"]) == 2
    assert result["exits"][0]["text"] == "Soldier of Godrick front"
    assert result["exits"][0]["to_name"] == "Road's End Catacombs"
    assert result["exits"][0]["discovered"] is False
    assert result["exits"][1]["to_name"] == "Ruin-Strewn Precipice"
    assert result["exits"][1]["discovered"] is False


def test_compute_zone_update_discovered():
    """Some exits discovered via zone_history."""
    history = [
        {"node_id": "cave_e235", "igt_ms": 1000},
        {"node_id": "catacombs_a123", "igt_ms": 5000},
    ]
    result = compute_zone_update("cave_e235", GRAPH_WITH_EXITS, zone_history=history)
    assert result is not None
    assert result["exits"][0]["discovered"] is True  # catacombs_a123 in history
    assert result["exits"][1]["discovered"] is False  # precipice_b456 not in history


def test_compute_zone_update_node_not_found():
    """Returns None for unknown node."""
    result = compute_zone_update("nonexistent", GRAPH_WITH_EXITS, zone_history=None)
    assert result is None


def test_compute_zone_update_no_exits():
    """Node with no exits returns empty exits list."""
    result = compute_zone_update("catacombs_a123", GRAPH_WITH_EXITS, zone_history=None)
    assert result is not None
    assert result["exits"] == []


def test_compute_zone_update_no_tier():
    """Node without tier returns None for tier."""
    graph = {
        "nodes": {
            "start_node": {
                "display_name": "Chapel of Anticipation",
                "layer": 0,
                "type": "start",
                "exits": [],
            }
        }
    }
    result = compute_zone_update("start_node", graph, zone_history=None)
    assert result is not None
    assert result["tier"] is None
