"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import get_layer_for_zone, get_node_for_zone


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
