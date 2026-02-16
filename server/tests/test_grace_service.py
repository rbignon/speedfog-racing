"""Unit tests for grace service."""

from speedfog_racing.services.grace_service import (
    load_graces_mapping,
    resolve_grace_to_node,
)

# --- load_graces_mapping ---


def test_load_graces_mapping():
    """Loads the real graces.json and returns a dict keyed by entity ID string."""
    mapping = load_graces_mapping()
    assert isinstance(mapping, dict)
    assert len(mapping) > 100  # Real file has 400+ entries
    # Check a known entry: Godrick the Grafted
    entry = mapping.get("10002950")
    assert entry is not None
    assert entry["zone_id"] == "stormveil_godrick"


# --- resolve_grace_to_node ---

SAMPLE_GRAPH = {
    "nodes": {
        "chapel_start_4f96": {
            "type": "start",
            "display_name": "Chapel of Anticipation",
            "zones": ["chapel_start", "roundtable"],
            "layer": 0,
        },
        "stormveil_godrick_48fd": {
            "display_name": "Godrick the Grafted",
            "zones": ["stormveil_godrick"],
            "layer": 3,
            "tier": 5,
        },
        "limgrave_cave_a1b2": {
            "display_name": "Coastal Cave",
            "zones": ["limgrave_coastalcave"],
            "layer": 1,
            "tier": 2,
        },
    }
}


def test_resolve_grace_to_node_found():
    """Grace entity ID for Godrick resolves to the graph node containing that zone."""
    # 10002950 → zone_id "stormveil_godrick" → node "stormveil_godrick_48fd"
    mapping = load_graces_mapping()
    node_id = resolve_grace_to_node(10002950, SAMPLE_GRAPH, mapping)
    assert node_id == "stormveil_godrick_48fd"


def test_resolve_grace_to_node_multi_zone():
    """Grace in a zone that's part of a multi-zone node resolves correctly."""
    # Roundtable Hold grace: entity ID 11102950 → zone_id "roundtable"
    # chapel_start_4f96 has zones=["chapel_start", "roundtable"]
    mapping = load_graces_mapping()
    node_id = resolve_grace_to_node(11102950, SAMPLE_GRAPH, mapping)
    assert node_id == "chapel_start_4f96"


def test_resolve_grace_to_node_not_in_graph():
    """Grace that maps to a zone_id not present in any graph node returns None."""
    mapping = load_graces_mapping()
    # 10002951 → zone_id "stormveil_margit" — not in SAMPLE_GRAPH
    node_id = resolve_grace_to_node(10002951, SAMPLE_GRAPH, mapping)
    assert node_id is None


def test_resolve_grace_to_node_unknown_grace():
    """Unknown grace_entity_id returns None."""
    mapping = load_graces_mapping()
    node_id = resolve_grace_to_node(99999999, SAMPLE_GRAPH, mapping)
    assert node_id is None


def test_resolve_grace_to_node_zero():
    """Grace entity ID 0 (no warp captured) returns None."""
    mapping = load_graces_mapping()
    node_id = resolve_grace_to_node(0, SAMPLE_GRAPH, mapping)
    assert node_id is None
