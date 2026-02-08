"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import (
    get_layer_for_node,
    get_layer_for_zone,
    get_node_for_zone,
)


def test_get_layer_for_known_zone():
    graph = {"area_tiers": {"Limgrave": 1, "Liurnia": 2, "Caelid": 3}}
    assert get_layer_for_zone("Limgrave", graph) == 1
    assert get_layer_for_zone("Liurnia", graph) == 2
    assert get_layer_for_zone("Caelid", graph) == 3


def test_get_layer_for_unknown_zone():
    graph = {"area_tiers": {"Limgrave": 1}}
    assert get_layer_for_zone("UnknownArea", graph) == 0


def test_get_layer_with_no_area_tiers():
    graph = {"total_layers": 5, "nodes": []}
    assert get_layer_for_zone("Limgrave", graph) == 0


def test_get_layer_with_empty_area_tiers():
    graph = {"area_tiers": {}}
    assert get_layer_for_zone("Limgrave", graph) == 0


# =============================================================================
# get_node_for_zone tests
# =============================================================================


def test_get_node_for_zone_found():
    graph = {
        "nodes": {
            "node_1": {"zones": ["Limgrave", "Stormveil"]},
            "node_2": {"zones": ["Liurnia", "Academy"]},
        }
    }
    assert get_node_for_zone("Limgrave", graph) == "node_1"
    assert get_node_for_zone("Academy", graph) == "node_2"


def test_get_node_for_zone_not_found():
    graph = {
        "nodes": {
            "node_1": {"zones": ["Limgrave"]},
        }
    }
    assert get_node_for_zone("UnknownArea", graph) is None


def test_get_node_for_zone_no_nodes():
    assert get_node_for_zone("Limgrave", {}) is None
    assert get_node_for_zone("Limgrave", {"nodes": {}}) is None


def test_get_node_for_zone_handles_non_dict_nodes():
    """Gracefully handles node values that aren't dicts."""
    graph = {
        "nodes": {
            "node_1": "invalid",
            "node_2": {"zones": ["Limgrave"]},
        }
    }
    assert get_node_for_zone("Limgrave", graph) == "node_2"


# =============================================================================
# Tests against real v3 graph.json fixture
# =============================================================================


def test_get_layer_real_graph(sample_graph_json: dict):
    """get_layer_for_zone works on real v3 seed data."""
    area_tiers = sample_graph_json["area_tiers"]
    # Pick the first zone from area_tiers
    zone, expected_tier = next(iter(area_tiers.items()))
    assert get_layer_for_zone(zone, sample_graph_json) == expected_tier


def test_get_node_for_zone_real_graph(sample_graph_json: dict):
    """get_node_for_zone finds nodes in real v3 seed data."""
    nodes = sample_graph_json["nodes"]
    # Pick the first node and its first zone
    node_id, node_data = next(iter(nodes.items()))
    zone = node_data["zones"][0]
    assert get_node_for_zone(zone, sample_graph_json) == node_id


# =============================================================================
# get_layer_for_node tests
# =============================================================================


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
