"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import (
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
