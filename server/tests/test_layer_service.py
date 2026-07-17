"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import (
    _format_zone_name,
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


def test_get_start_node_fallback_to_top_level_key():
    """Falls back to top-level start_node when no node has type 'start'."""
    graph = {
        "start_node": "limgrave_start",
        "nodes": {
            "limgrave_start": {"layer": 0, "tier": 1},
            "stormveil_01": {"layer": 1, "tier": 2},
        },
    }
    assert get_start_node(graph) == "limgrave_start"


def test_get_start_node_fallback_invalid_reference():
    """Fallback start_node is ignored if it doesn't exist in nodes."""
    graph = {
        "start_node": "nonexistent_node",
        "nodes": {
            "stormveil_01": {"layer": 1, "tier": 2},
        },
    }
    assert get_start_node(graph) is None


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
    """All exits undiscovered, is_first_visit defaults to False."""
    result = compute_zone_update("cave_e235", GRAPH_WITH_EXITS, zone_history=None)
    assert result is not None
    assert result["type"] == "zone_update"
    assert result["node_id"] == "cave_e235"
    assert result["display_name"] == "Cave of Knowledge"
    assert result["tier"] == 5
    assert result["layer"] == 2
    assert result["is_first_visit"] is False
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
    assert result["layer"] == 0


def test_compute_zone_update_no_layer():
    """Node without layer returns None for layer."""
    graph = {
        "nodes": {
            "mystery": {
                "display_name": "Mystery Node",
                "tier": 1,
                "exits": [],
            }
        }
    }
    result = compute_zone_update("mystery", graph, zone_history=None)
    assert result is not None
    assert result["layer"] is None


# =============================================================================
# _format_zone_name
# =============================================================================


def test_format_zone_name():
    assert _format_zone_name("roundtable") == "Roundtable"
    assert _format_zone_name("volcano_drawingroom") == "Volcano Drawingroom"
    assert _format_zone_name("caelid_gaeltunnel_rear") == "Caelid Gaeltunnel Rear"


# =============================================================================
# compute_zone_update: from zone annotation
# =============================================================================

GRAPH_MULTI_ZONE = {
    "nodes": {
        "volcano_ac44": {
            "display_name": "Volcano Manor Entrance",
            "tier": 7,
            "layer": 4,
            "zones": ["volcano", "volcano_drawingroom", "volcano_predoor"],
            "exits": [
                {
                    "text": "Before Prison Town Church grace",
                    "fog_id": "AEG099_232_9005",
                    "from": "volcano_drawingroom",
                    "from_text": "Mt. Gelmir - Volcano Manor - Drawing Room",
                    "to": "siofra_boss_c9b0",
                },
            ],
        },
        "chapel_start_4f96": {
            "display_name": "Roundtable Hold",
            "tier": 1,
            "layer": 0,
            "zones": ["chapel_start", "roundtable"],
            "exits": [
                {
                    "text": "Grafted Scion front",
                    "fog_id": "AEG099_001_9000",
                    "from": "chapel_start",
                    "to": "siofra_boss_c9b0",
                },
                {
                    "text": "Roundtable Hold gate",
                    "fog_id": "AEG099_231_9000",
                    "from": "roundtable",
                    "from_text": "Roundtable Hold",
                    "to": "siofra_boss_c9b0",
                },
            ],
        },
        "single_zone_node": {
            "display_name": "Simple Cave",
            "tier": 3,
            "layer": 1,
            "zones": ["simple_cave"],
            "exits": [
                {
                    "text": "Boss front",
                    "fog_id": "AEG099_001_9000",
                    "from": "simple_cave",
                    "to": "siofra_boss_c9b0",
                },
            ],
        },
        "siofra_boss_c9b0": {
            "display_name": "Ancestor Spirit",
            "tier": 8,
            "layer": 5,
            "zones": ["siofra_boss"],
            "exits": [],
        },
    }
}


def test_compute_zone_update_from_subzone_annotated():
    """Exit from a sub-zone passes from_zone last segment (for i18n assembly)."""
    result = compute_zone_update("volcano_ac44", GRAPH_MULTI_ZONE, zone_history=None)
    assert result is not None
    assert len(result["exits"]) == 1
    assert result["exits"][0]["text"] == "Before Prison Town Church grace"
    # Composite "Mt. Gelmir - Volcano Manor - Drawing Room" → last segment
    assert result["exits"][0]["from_zone"] == "Drawing Room"


def test_compute_zone_update_from_primary_zone_not_annotated():
    """Exit from the primary zone (zones[0]) has no from_zone."""
    result = compute_zone_update("chapel_start_4f96", GRAPH_MULTI_ZONE, zone_history=None)
    assert result is not None
    assert len(result["exits"]) == 2
    # First exit from "chapel_start" (= zones[0]), no annotation
    assert result["exits"][0]["text"] == "Grafted Scion front"
    assert "from_zone" not in result["exits"][0]
    # Second exit from "roundtable" (≠ zones[0]), from_zone uses from_text
    assert result["exits"][1]["text"] == "Roundtable Hold gate"
    assert result["exits"][1]["from_zone"] == "Roundtable Hold"


def test_compute_zone_update_single_zone_not_annotated():
    """Exit from a single-zone node has no from_zone."""
    result = compute_zone_update("single_zone_node", GRAPH_MULTI_ZONE, zone_history=None)
    assert result is not None
    assert len(result["exits"]) == 1
    assert result["exits"][0]["text"] == "Boss front"
    assert "from_zone" not in result["exits"][0]


# =============================================================================
# original_tier
# =============================================================================


def test_compute_zone_update_with_original_tier():
    """Node with original_tier passes it through."""
    graph = {
        "nodes": {
            "cave_e235": {
                "display_name": "Cave of Knowledge",
                "tier": 2,
                "original_tier": 8,
                "layer": 2,
                "exits": [],
            }
        }
    }
    result = compute_zone_update("cave_e235", graph, zone_history=None)
    assert result is not None
    assert result["tier"] == 2
    assert result["original_tier"] == 8


def test_compute_zone_update_without_original_tier():
    """Node without original_tier returns None for it."""
    graph = {
        "nodes": {
            "cave_e235": {
                "display_name": "Cave of Knowledge",
                "tier": 5,
                "layer": 2,
                "exits": [],
            }
        }
    }
    result = compute_zone_update("cave_e235", graph, zone_history=None)
    assert result is not None
    assert result["original_tier"] is None


def test_compute_zone_update_original_tier_in_full_graph():
    """original_tier works with the full GRAPH_WITH_EXITS fixture."""
    result = compute_zone_update("cave_e235", GRAPH_WITH_EXITS, zone_history=None)
    assert result is not None
    # GRAPH_WITH_EXITS doesn't have original_tier
    assert result["original_tier"] is None


def test_compute_zone_update_first_visit():
    """is_first_visit=True is passed through to the output."""
    result = compute_zone_update(
        "cave_e235", GRAPH_WITH_EXITS, zone_history=None, is_first_visit=True
    )
    assert result is not None
    assert result["is_first_visit"] is True


# =============================================================================
# compute_zone_update: to_bosses (boss names for discovered destinations)
# =============================================================================

GRAPH_WITH_BOSSES = {
    "nodes": {
        "hub_1234": {
            "display_name": "Hub Zone",
            "tier": 2,
            "layer": 1,
            "exits": [
                {"text": "Gideon front", "fog_id": 1, "to": "gideon_5678"},
                {"text": "Maliketh front", "fog_id": 2, "to": "maliketh_9abc"},
                {"text": "Catacombs entrance", "fog_id": 3, "to": "catacombs_def0"},
                {"text": "Vanilla boss front", "fog_id": 4, "to": "vanilla_1111"},
                {"text": "Empty boss front", "fog_id": 5, "to": "empty_2222"},
                {"text": "Empty list front", "fog_id": 6, "to": "emptylist_3333"},
            ],
        },
        "gideon_5678": {
            "display_name": "Ashen Leyndell - Gideon",
            "boss_name": "Mimic Tear",
            "randomized_bosses": ["Mimic Tear"],
            "exits": [],
        },
        "maliketh_9abc": {
            "display_name": "Maliketh the Black Blade",
            "boss_name": "Metyr, Mother of Fingers",
            "randomized_bosses": ["Red Wolf of Radagon", "Metyr, Mother of Fingers"],
            "exits": [],
        },
        "catacombs_def0": {
            "display_name": "Road's End Catacombs",
            "exits": [],
        },
        "vanilla_1111": {
            "display_name": "Leyndell - Godfrey",
            "boss_name": "Godfrey, First Elden Lord",
            "randomized_bosses": None,
            "exits": [],
        },
        "empty_2222": {
            "display_name": "Empty Arena",
            "boss_name": "",
            "exits": [],
        },
        "emptylist_3333": {
            "display_name": "Siofra - Ancestor Spirit",
            "boss_name": "Ancestor Spirit",
            "randomized_bosses": [],
            "exits": [],
        },
    }
}

FULL_BOSS_HISTORY = [
    {"node_id": "hub_1234", "igt_ms": 0},
    {"node_id": "gideon_5678", "igt_ms": 1000},
    {"node_id": "maliketh_9abc", "igt_ms": 2000},
    {"node_id": "catacombs_def0", "igt_ms": 3000},
    {"node_id": "vanilla_1111", "igt_ms": 4000},
    {"node_id": "empty_2222", "igt_ms": 5000},
    {"node_id": "emptylist_3333", "igt_ms": 6000},
]


def test_to_bosses_discovered_randomized():
    """Discovered exit to a randomized boss node carries randomized_bosses."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert result["exits"][0]["to_bosses"] == ["Mimic Tear"]
    # to_name keeps the zone name; translate_zone_update() does the swap
    assert result["exits"][0]["to_name"] == "Ashen Leyndell - Gideon"


def test_to_bosses_multi_phase():
    """Multi-phase arenas keep one entry per phase."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert result["exits"][1]["to_bosses"] == [
        "Red Wolf of Radagon",
        "Metyr, Mother of Fingers",
    ]


def test_to_bosses_falls_back_to_boss_name():
    """Null randomized_bosses (non-randomized seed) falls back to boss_name."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert result["exits"][3]["to_bosses"] == ["Godfrey, First Elden Lord"]


def test_to_bosses_empty_randomized_list_falls_back_to_boss_name():
    """Empty randomized_bosses list (distinct from null) falls back to boss_name."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert result["exits"][5]["to_bosses"] == ["Ancestor Spirit"]


def test_to_bosses_absent_for_non_boss_node():
    """Nodes without boss data get no to_bosses key."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert "to_bosses" not in result["exits"][2]


def test_to_bosses_empty_boss_name_treated_as_absent():
    """Empty-string boss_name does not produce a to_bosses key."""
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=FULL_BOSS_HISTORY)
    assert result is not None
    assert "to_bosses" not in result["exits"][4]


def test_to_bosses_absent_when_undiscovered():
    """Undiscovered boss destinations keep the plain zone name (no to_bosses)."""
    history = [{"node_id": "hub_1234", "igt_ms": 0}]
    result = compute_zone_update("hub_1234", GRAPH_WITH_BOSSES, zone_history=history)
    assert result is not None
    for ex in result["exits"]:
        assert "to_bosses" not in ex
