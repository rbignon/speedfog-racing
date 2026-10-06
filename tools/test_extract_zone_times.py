"""Tests for extract_zone_times.py (clear filtering, effective weights, proposals)."""

from __future__ import annotations

from extract_zone_times import (
    ParticipantData,
    compute_cluster_durations,
    format_overrides,
    get_current_weight,
)

NODES = {
    "start": {"type": "start", "layer": 0},
    "gaol": {"type": "boss_arena", "layer": 1, "randomized_bosses": ["Erdtree Avatar"]},
    "arena": {"type": "major_boss", "layer": 2, "randomized_bosses": ["Rykard"]},
    "cave": {"type": "mini_dungeon", "layer": 3},
    "keep": {"type": "final_boss", "layer": 4},
}
CLUSTER_TYPES = {
    "start": "start",
    "gaol": "boss_arena",
    "arena": "major_boss",
    "cave": "mini_dungeon",
    # Current type of the cluster this seed placed as its final boss.
    "keep": "major_boss",
}


def _entry(node_id: str, igt_s: float) -> dict:
    return {"node_id": node_id, "igt_ms": int(igt_s * 1000)}


def _finished_run() -> list[ParticipantData]:
    history = [
        _entry("start", 0),
        _entry("gaol", 10),  # 30 s
        _entry("arena", 40),  # 60 s
        _entry("cave", 100),  # 90 s
        _entry("keep", 190),  # 110 s, closed by the run's igt
    ]
    return [ParticipantData(history, "FINISHED", 300_000, "seed")]


def test_cluster_types_drop_other_roles_and_shuffled_major_bosses() -> None:
    durations = compute_cluster_durations(
        _finished_run(), {"seed": {"nodes": NODES}}, CLUSTER_TYPES
    )
    assert {nid: round(d[0] * 60) for nid, d in durations.items()} == {
        "start": 10,
        "gaol": 30,  # shuffled minor bosses are the usual traversal: kept
        "cave": 90,
    }


def test_without_cluster_types_every_clear_counts() -> None:
    durations = compute_cluster_durations(_finished_run(), {"seed": {"nodes": NODES}})
    assert set(durations) == {"start", "gaol", "arena", "cave", "keep"}


def test_clears_from_before_a_type_change_still_count() -> None:
    # The seed predates the cave's move from legacy to mini, and an older
    # graph carries no type at all on the start node.
    nodes = {
        **NODES,
        "start": {"layer": 0},
        "cave": {"type": "legacy_dungeon", "layer": 3},
    }
    durations = compute_cluster_durations(
        _finished_run(), {"seed": {"nodes": nodes}}, CLUSTER_TYPES
    )
    assert set(durations) == {"start", "gaol", "cave"}


def test_cluster_weight_override_wins_for_a_single_zone_cluster() -> None:
    info = {"n_zones": 1, "primary_zone": "town", "type": "legacy_dungeon", "weight": 2}
    metadata = {
        "defaults": {"legacy_dungeon": 3},
        "zones": {"town": {"weight": 1}},
        "clusters": {"town_d40f": {"weight": 2}},
    }
    assert get_current_weight("town_d40f", info, metadata) == (2, 2)


def _info(zones: list[str], weight: float) -> dict:
    return {
        "type": "mini_dungeon",
        "zones": zones,
        "n_zones": len(zones),
        "primary_zone": zones[0],
        "weight": weight,
        "display_name": "",
    }


def test_proposals_round_to_half_and_target_the_overriding_table() -> None:
    durations = {
        # Multi-zone, computed weight: a 1.4 median proposes 1.5, not 1.
        "pair_0001": [1.3, 1.4, 1.5],
        # Single zone already weighted at cluster level: the cluster table is
        # the one to edit, a zone override would be shadowed.
        "solo_0002": [1.6, 1.7, 1.8],
        # Single zone with a zone override.
        "cave_0003": [2.9, 3.0, 3.1],
    }
    info = {
        "pair_0001": _info(["pair", "pair_b"], 3.4),
        "solo_0002": _info(["solo"], 2),
        "cave_0003": _info(["cave"], 2),
    }
    metadata = {
        "defaults": {"mini_dungeon": 1},
        "zones": {"cave": {"weight": 2}},
        "clusters": {"solo_0002": {"weight": 2}},
    }
    report = "\n".join(format_overrides(durations, info, metadata, 0, 3))
    assert "ADD [clusters.pair_0001] weight = 1.5" in report
    assert "UPDATE [clusters] 2 -> 1.5" in report
    assert "UPDATE [zones] 2 -> 3" in report
