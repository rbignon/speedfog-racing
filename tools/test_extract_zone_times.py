"""Tests for extract_zone_times.py (clear filtering, effective weights, proposals)."""

from __future__ import annotations

import pytest
from extract_zone_times import (
    Clear,
    ParticipantData,
    compute_cluster_durations,
    current_band_weights,
    estimate_band_weights,
    format_band_report,
    format_overrides,
    get_current_weight,
    iter_cluster_clears,
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


# --- per-band weights of major boss arenas ---------------------------------


def test_clears_carry_the_node_tier_and_the_player() -> None:
    nodes = {**NODES, "cave": {"type": "mini_dungeon", "layer": 3, "tier": 12}}
    run = _finished_run()
    run[0].user_id = "u1"

    clears = {
        c.node_id: c for c in iter_cluster_clears(run, {"seed": {"nodes": nodes}})
    }

    assert (clears["cave"].tier, clears["cave"].user_id) == (12, "u1")
    assert clears["gaol"].tier is None  # older graphs: no tier on the node


def _clears(node: str, tier: int | None, minutes: list[float], user: str = "u") -> list:
    return [Clear(node, m, tier, f"{user}{i}") for i, m in enumerate(minutes)]


def test_bands_are_medians_of_the_clears_at_that_band() -> None:
    clears = (
        _clears("mohg", 5, [1.0, 1.2, 1.4])
        + _clears("mohg", 12, [1.8, 2.0, 2.2])
        + _clears("mohg", 20, [2.3, 2.5, 9.0])
        + _clears("cave", 5, [7.0, 7.0, 7.0])  # not a banded type
        + _clears("mohg", None, [50.0, 50.0, 50.0])  # no tier: ignored
    )
    types = {"mohg": "major_boss", "cave": "mini_dungeon"}

    estimates = estimate_band_weights(clears, types, min_samples=3, adjust=False)

    assert set(estimates) == {"mohg"}
    assert estimates["mohg"].weights == {"early": 1.2, "mid": 2.0, "late": 2.5}
    assert estimates["mohg"].counts == {"early": 3, "mid": 3, "late": 3}


@pytest.mark.parametrize(
    ("measured_tiers", "expected"),
    [
        # final bosses: never seen early, early takes mid
        ((12, 20), {"early": 2.0, "mid": 2.0, "late": 3.0}),
        # one band only: everywhere
        ((20,), {"early": 3.0, "mid": 3.0, "late": 3.0}),
        # mid missing between two measured bands: the later one
        ((5, 20), {"early": 1.0, "mid": 3.0, "late": 3.0}),
    ],
)
def test_thin_band_takes_the_nearest_measured_band(measured_tiers, expected) -> None:
    minutes = {5: 1.0, 12: 2.0, 20: 3.0}
    clears = []
    for tier in (5, 12, 20):
        n = 3 if tier in measured_tiers else 2  # 2 clears: below min_samples
        clears += _clears("pcr", tier, [minutes[tier]] * n, user=f"t{tier}_")

    estimates = estimate_band_weights(
        clears, {"pcr": "final_boss"}, min_samples=3, adjust=False
    )

    assert estimates["pcr"].weights == expected


def test_cluster_without_a_measured_band_gets_no_proposal() -> None:
    estimates = estimate_band_weights(
        _clears("mohg", 5, [1.0, 1.0]), {"mohg": "major_boss"}, min_samples=3
    )
    assert estimates["mohg"].weights is None


def test_adjustment_removes_the_speed_of_who_played_the_band() -> None:
    """Both arenas take everyone the same time relative to their own pace,
    but only fast players reach "hard" late: the plain late median reads it
    as shorter than "easy", the adjusted one does not."""
    fast = [f"fast{i}" for i in range(6)]
    slow = [f"slow{i}" for i in range(6)]
    clears = []
    for user, pace in [(u, 1.0) for u in fast] + [(u, 2.0) for u in slow]:
        # enough clears per player to estimate their pace
        for node in ("easy", "hard"):
            for tier in (5, 12):
                clears.append(Clear(node, 2.0 * pace, tier, user))
        clears.append(Clear("easy", 2.0 * pace, 20, user))
        if pace == 1.0:
            clears.append(Clear("hard", 2.0 * pace, 20, user))
    types = {"easy": "major_boss", "hard": "major_boss"}

    plain = estimate_band_weights(clears, types, min_samples=6, adjust=False)
    adjusted = estimate_band_weights(clears, types, min_samples=6, adjust=True)

    assert plain["hard"].weights["late"] < plain["easy"].weights["late"]
    assert adjusted["hard"].weights["late"] == adjusted["easy"].weights["late"]


def test_current_weight_reads_band_tables() -> None:
    info = {
        "type": "major_boss",
        "n_zones": 1,
        "primary_zone": "mohg",
        "weight": 1.88,
        "weights": {"early": 1.13, "mid": 1.88, "late": 2.32},
    }
    metadata = {
        "zones": {"mohg": {"weight": {"early": 1.13, "mid": 1.88, "late": 2.32}}}
    }

    assert get_current_weight("mohg_1", info, metadata) == (1.88, 1.88)
    assert current_band_weights(info, metadata, "mohg_1") == {
        "early": 1.13,
        "mid": 1.88,
        "late": 2.32,
    }
    flat = {**info, "weights": None}
    assert current_band_weights(flat, {"zones": {"mohg": {"weight": 2}}}, "mohg_1") == {
        "early": 2.0,
        "mid": 2.0,
        "late": 2.0,
    }


def test_band_proposals_target_the_table_the_generator_reads() -> None:
    """Single-zone cluster: [zones.<zone>]; multi-zone, or a cluster that
    already has a [clusters.<id>] weight: [clusters.<id>]."""
    clears = []
    for node in ("mohg_1", "library_2", "temple_3"):
        for tier, m in ((5, 1.0), (12, 2.0), (20, 3.0)):
            clears += _clears(node, tier, [m] * 3, user=f"{node}{tier}_")
    info = {
        "mohg_1": {"type": "major_boss", "n_zones": 1, "primary_zone": "mohg"},
        "library_2": {"type": "major_boss", "n_zones": 2, "primary_zone": "library"},
        "temple_3": {"type": "major_boss", "n_zones": 1, "primary_zone": "temple"},
    }
    for value in info.values():
        value.update(weight=2, weights=None, display_name="Name", zones=[])
    metadata = {"zones": {}, "clusters": {"temple_3": {"weight": 1.5}}, "defaults": {}}
    estimates = estimate_band_weights(
        clears, {n: "major_boss" for n in info}, min_samples=3, adjust=False
    )

    lines = format_band_report(estimates, info, metadata)

    table = "weight = { early = 1, mid = 2, late = 3 }"
    for header in ("[zones.mohg]", "[clusters.library_2]", "[clusters.temple_3]"):
        i = next(i for i, line in enumerate(lines) if line.startswith(header))
        assert lines[i + 1] == table


def test_final_clears_only_measure_a_boss_never_placed_mid_run() -> None:
    """keep (current type major_boss) is this seed's final boss: its clear is
    dropped by default, yielded as_final on request; the estimate uses such
    clears only when the cluster has no mid-run measurement."""
    nodes = {k: {**v, "tier": 20} for k, v in NODES.items()}
    graphs = {"seed": {"nodes": nodes}}
    default = list(iter_cluster_clears(_finished_run(), graphs, CLUSTER_TYPES))
    with_final = list(
        iter_cluster_clears(_finished_run(), graphs, CLUSTER_TYPES, include_final=True)
    )
    assert "keep" not in {c.node_id for c in default}
    assert [c.as_final for c in with_final if c.node_id == "keep"] == [True]

    types = {"only_final": "major_boss", "both": "major_boss"}
    clears = (
        [Clear("only_final", 4.0, 20, f"a{i}", as_final=True) for i in range(3)]
        + [Clear("both", 4.0, 20, f"b{i}", as_final=True) for i in range(3)]
        + _clears("both", 12, [2.0] * 3)
    )
    estimates = estimate_band_weights(clears, types, min_samples=3, adjust=False)

    assert estimates["only_final"].weights == {"early": 4.0, "mid": 4.0, "late": 4.0}
    assert estimates["both"].weights == {"early": 2.0, "mid": 2.0, "late": 2.0}


def test_shuffled_arena_clears_never_reach_the_band_estimate() -> None:
    """A final arena whose boss was shuffled (boss shuffle pools) measures
    the drawn boss: flagged by the iterator, ignored by the estimate, for a
    final_boss cluster and for a major one placed as the final boss."""
    nodes = {
        k: {**v, "tier": 20, "randomized_bosses": ["Someone Else"]}
        for k, v in NODES.items()
    }
    graphs = {"seed": {"nodes": nodes}}
    for keep_type in ("final_boss", "major_boss"):
        types = {**CLUSTER_TYPES, "keep": keep_type}
        clears = [
            c
            for c in iter_cluster_clears(
                _finished_run(), graphs, types, include_final=True
            )
            if c.node_id == "keep"
        ]
        assert [c.shuffled for c in clears] == [True], keep_type

        estimates = estimate_band_weights(clears * 3, types, min_samples=3)
        assert "keep" not in estimates, keep_type


def test_proposal_from_final_clears_is_marked() -> None:
    clears = [Clear("placi", 4.0, 20, f"a{i}", as_final=True) for i in range(3)]
    info = {
        "placi": {
            "type": "major_boss",
            "n_zones": 1,
            "primary_zone": "placi",
            "weight": 5.5,
            "weights": None,
            "display_name": "Placidusax",
        }
    }
    estimates = estimate_band_weights(
        clears, {"placi": "major_boss"}, min_samples=3, adjust=False
    )

    lines = format_band_report(estimates, info, {"zones": {}, "defaults": {}})

    assert any("measured as a final boss" in line for line in lines)
