"""Unit tests for grace service."""

from speedfog_racing.services.grace_service import (
    load_graces_mapping,
    resolve_grace_to_node,
    resolve_zone_query,
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


# --- resolve_zone_query ---


def test_resolve_zone_query_grace_primary():
    """grace_entity_id present → uses grace lookup (highest priority)."""
    mapping = load_graces_mapping()
    node_id = resolve_zone_query(SAMPLE_GRAPH, mapping, grace_entity_id=10002950)
    assert node_id == "stormveil_godrick_48fd"


def test_resolve_zone_query_grace_priority_over_map():
    """grace_entity_id takes priority even when map_id is also provided."""
    mapping = load_graces_mapping()
    node_id = resolve_zone_query(
        SAMPLE_GRAPH, mapping, grace_entity_id=10002950, map_id="m60_44_36_00"
    )
    assert node_id == "stormveil_godrick_48fd"


def test_resolve_zone_query_map_id_unambiguous():
    """map_id resolves when exactly one graph node matches fog.txt zones."""
    # m12_04_00_00 maps to ainsel_preboss, ainsel_boss, ainsel_postboss in fog.txt
    # But graph only has ainsel_boss → unique match
    graph = {
        "nodes": {
            "ainsel_boss_node": {
                "display_name": "Astel, Naturalborn of the Void",
                "zones": ["ainsel_boss"],
                "layer": 1,
            },
        }
    }
    mapping = load_graces_mapping()
    node_id = resolve_zone_query(graph, mapping, map_id="m12_04_00_00")
    assert node_id == "ainsel_boss_node"


def test_resolve_zone_query_map_id_ambiguous():
    """map_id maps to multiple graph nodes → returns None."""
    # m10_00_00_00 has stormveil_godrick, stormhill, etc. in fog.txt
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00")
    assert node_id is None


def test_resolve_zone_query_no_data():
    """No grace, no map → returns None."""
    mapping = load_graces_mapping()
    assert resolve_zone_query(SAMPLE_GRAPH, mapping) is None


def test_resolve_zone_query_unknown_map():
    """map_id not in fog.txt → returns None."""
    mapping = load_graces_mapping()
    assert resolve_zone_query(SAMPLE_GRAPH, mapping, map_id="m99_99_99_99") is None


# --- resolve_zone_query: zone_history disambiguation ---


def test_resolve_zone_query_ambiguous_narrowed_by_history():
    """Ambiguous map_id resolved when zone_history narrows to one candidate."""
    # m10_00_00_00 matches both node_a and node_b
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    history = [{"node_id": "node_a", "igt_ms": 0}]
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00", zone_history=history)
    assert node_id == "node_a"


def test_resolve_zone_query_ambiguous_both_explored():
    """Ambiguous map_id stays ambiguous when both candidates are in history."""
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    history = [
        {"node_id": "node_a", "igt_ms": 0},
        {"node_id": "node_b", "igt_ms": 5000},
    ]
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00", zone_history=history)
    assert node_id is None


def test_resolve_zone_query_ambiguous_empty_history():
    """Ambiguous map_id with empty zone_history still returns None (no filter)."""
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00", zone_history=[])
    assert node_id is None


def test_resolve_zone_query_ambiguous_no_history_match():
    """Ambiguous map_id where no candidate is in history → None."""
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    history = [{"node_id": "some_other_node", "igt_ms": 0}]
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00", zone_history=history)
    assert node_id is None


# --- resolve_zone_query: Leyndell bug regression ---


def test_resolve_zone_query_leyndell_bug():
    """Regression: Leyndell map_id should NOT resolve to leyndell_sanctuary when
    player has only visited leyndell.

    Previously, graces.json had no map_id for regular Leyndell graces, so
    m11_00_00_00 only matched leyndell_sanctuary → false resolution.
    With fog.txt, both zones are candidates and zone_history disambiguates.
    """
    graph = {
        "nodes": {
            "leyndell_1259": {
                "display_name": "Leyndell",
                "zones": ["leyndell"],
                "layer": 5,
            },
            "leyndell_sanctuary_d3e5": {
                "display_name": "Erdtree Sanctuary",
                "zones": ["leyndell_sanctuary"],
                "layer": 8,
            },
        }
    }
    mapping = load_graces_mapping()
    history = [{"node_id": "leyndell_1259", "igt_ms": 120000}]
    node_id = resolve_zone_query(
        graph,
        mapping,
        map_id="m11_00_00_00",
        zone_history=history,
    )
    assert node_id == "leyndell_1259"


def test_resolve_zone_query_leyndell_with_position():
    """Position disambiguates Leyndell even when both nodes are visited."""
    graph = {
        "nodes": {
            "leyndell_1259": {
                "display_name": "Leyndell",
                "zones": ["leyndell"],
                "layer": 5,
            },
            "leyndell_sanctuary_d3e5": {
                "display_name": "Erdtree Sanctuary",
                "zones": ["leyndell_sanctuary"],
                "layer": 8,
            },
        }
    }
    mapping = load_graces_mapping()
    history = [
        {"node_id": "leyndell_1259", "igt_ms": 120000},
        {"node_id": "leyndell_sanctuary_d3e5", "igt_ms": 300000},
    ]

    # Main city position (low Y) → resolves to leyndell
    node_id = resolve_zone_query(
        graph,
        mapping,
        map_id="m11_00_00_00",
        position=(0.0, -50.0, 0.0),
        zone_history=history,
    )
    assert node_id == "leyndell_1259"

    # Sanctuary position (high Y, low Z) → resolves to leyndell_sanctuary
    node_id = resolve_zone_query(
        graph,
        mapping,
        map_id="m11_00_00_00",
        position=(0.0, 30.0, -400.0),
        zone_history=history,
    )
    assert node_id == "leyndell_sanctuary_d3e5"


def test_resolve_zone_query_single_match_unexplored():
    """Single graph node match should NOT resolve if player hasn't explored it.

    zone_query is only sent on death/respawn/fast-travel (never on fog gate
    traversal), so the target zone must already be in zone_history.
    """
    graph = {
        "nodes": {
            "ainsel_boss_node": {
                "zones": ["ainsel_boss"],
                "layer": 3,
            }
        }
    }
    mapping = load_graces_mapping()
    # Player has explored a different node — ainsel_boss_node is not in history
    history = [{"node_id": "some_other_node", "igt_ms": 60000}]
    node_id = resolve_zone_query(graph, mapping, map_id="m12_04_00_00", zone_history=history)
    assert node_id is None
