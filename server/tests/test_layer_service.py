"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import get_layer_for_node


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
