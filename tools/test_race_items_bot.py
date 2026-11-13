"""Tests for race_items_bot.py's graph walking (no database, no server).

Run from tools/: cd tools && uv run --project ../server pytest test_race_items_bot.py
"""

from __future__ import annotations

from race_items_bot import deepest_nodes, forward_path, node_flags

GRAPH = {
    "nodes": {
        "start": {"type": "start", "layer": 0, "exits": [{"to": "a"}, {"to": "b"}]},
        "a": {"type": "legacy_dungeon", "layer": 1, "exits": [{"to": "boss"}]},
        "b": {
            "type": "mini_dungeon",
            "layer": 1,
            "exits": [{"to": "c"}, {"to": "start"}],
        },
        "c": {"type": "mini_dungeon", "layer": 2, "exits": [{"to": "deep"}]},
        "boss": {"type": "boss_arena", "layer": 2, "exits": [{"to": "deep"}]},
        "deep": {"type": "mini_dungeon", "layer": 3, "exits": [{"to": "final"}]},
        "final": {"type": "final_boss", "layer": 4, "exits": []},
    },
    "event_map": {
        "30": "a",
        "20": "a",
        "21": "b",
        "22": "c",
        "23": "boss",
        "9": "deep",
        "10": "deep",
    },
}


def test_each_node_reports_its_lowest_flag():
    # Compared as numbers: as strings, "10" would sort before "9".
    assert node_flags(GRAPH) == {"a": 20, "b": 21, "c": 22, "boss": 23, "deep": 9}


def test_forward_path_is_the_shortest_deeper_walk():
    assert forward_path(GRAPH, "start", {"boss"}) == ["a", "boss"]
    assert forward_path(GRAPH, "start", {"deep"}) in (
        ["a", "boss", "deep"],
        ["b", "c", "deep"],
    )


def test_forward_path_never_walks_back_up_a_layer():
    # b's exit back to start is ignored: from b, a is unreachable.
    assert forward_path(GRAPH, "b", {"a"}) is None
    assert forward_path(GRAPH, "deep", {"boss"}) is None


def test_the_current_node_is_not_a_goal():
    assert forward_path(GRAPH, "boss", {"boss", "deep"}) == ["deep"]


def test_deepest_nodes_stop_before_the_final_boss():
    assert deepest_nodes(GRAPH) == {"deep"}
