"""Tests for extract_boss_weights.py (clear times, attribution, fit, writing)."""

from __future__ import annotations

import json
import math

import pytest
from extract_boss_weights import (
    apply_weights,
    attribute,
    boss_clears,
    fit_effects,
    rounded_weights,
    shrunk_weights,
)

NODES = {
    "start": {"type": "start", "layer": 0},
    "gaol": {"type": "boss_arena", "layer": 1, "defeat_flag": 1000},
    "cave": {"type": "mini_dungeon", "layer": 2},
    "keep": {"type": "major_boss", "layer": 3, "defeat_flag": 2000},
}


def _entry(node_id: str, igt_s: float) -> dict:
    return {"node_id": node_id, "igt_ms": int(igt_s * 1000)}


def test_boss_clears_accumulates_visits_and_keeps_cleared_bosses() -> None:
    history = [
        _entry("start", 0),
        _entry("gaol", 10),  # 30 s, dies
        _entry("start", 40),
        _entry("gaol", 50),  # 60 s more, then clears
        _entry("cave", 110),
        _entry("keep", 200),  # last entry of a finished run
    ]
    clears = boss_clears(history, 290_000, "FINISHED", NODES)
    assert {c.node_id: round(c.minutes, 3) for c in clears} == {
        "gaol": 1.5,
        "keep": 1.5,
    }


def test_boss_clears_drops_backed_out_and_abandoned_bosses() -> None:
    history = [_entry("start", 0), _entry("gaol", 10), _entry("start", 70)]
    assert boss_clears(history, 100_000, "FINISHED", NODES) == []
    history = [_entry("start", 0), _entry("gaol", 10)]
    assert boss_clears(history, 100_000, "ABANDONED", NODES) == []


NAMES = {"Solo Boss": {5000}, "Twin Name": {6000, 6001}}


def test_attribute_prefers_exact_assignments() -> None:
    node = {"defeat_flag": 1000, "randomized_bosses": ["Twin Name"]}
    assert attribute(node, {"1000": "6001"}, NAMES, {}) == 6001
    assert attribute(node, {"9999": "6001"}, NAMES, {}) is None


def test_attribute_falls_back_to_unique_names_only() -> None:
    assert (
        attribute(
            {"defeat_flag": 1000, "randomized_bosses": ["Solo Boss"]}, None, NAMES, {}
        )
        == 5000
    )
    assert (
        attribute(
            {"defeat_flag": 1000, "randomized_bosses": ["Twin Name"]}, None, NAMES, {}
        )
        is None
    )
    assert attribute({"defeat_flag": 1000}, None, NAMES, {}) is None


def test_attribute_skips_multi_slot_nodes() -> None:
    node = {"defeat_flag": 1000, "randomized_bosses": ["Solo Boss", "Solo Boss"]}
    assert (
        attribute(node, {"1000": "5000", "1001": "5000"}, NAMES, {1000: 1001}) is None
    )


def _rows(spec):
    """spec: iterable of (arena, boss, tier, minutes)."""
    return [
        {"y": math.log(m), "arena": a, "boss": b, "tier": t, "user": "u", "pool": "p"}
        for a, b, t, m in spec
    ]


def test_fit_recovers_planted_boss_ratio() -> None:
    arena = {"a1": 1.0, "a2": 2.0}
    boss = {"b1": 1.0, "b2": 3.0}
    tier = {1: 1.0, 2: 1.5}
    spec = [
        (a, b, t, 0.5 * arena[a] * boss[b] * tier[t])
        for a in arena
        for b in boss
        for t in tier
    ]
    mu, eff = fit_effects(_rows(spec), max_iter=100, tol=1e-12)
    ratio = math.exp(eff["boss"]["b2"] - eff["boss"]["b1"])
    assert ratio == pytest.approx(3.0, rel=1e-6)


def test_fit_normalizes_the_tier_a_boss_was_met_at() -> None:
    """Identical bosses, one only seen at high tiers: equal weights."""
    tier = {1: 1.0, 2: 2.0, 3: 4.0}
    spec = [(a, "low", t, tier[t]) for a in ("a1", "a2") for t in (1, 2)]
    spec += [(a, "high", t, tier[t]) for a in ("a1", "a2") for t in (2, 3)]
    mu, eff = fit_effects(_rows(spec), max_iter=100, tol=1e-12)
    assert eff["boss"]["high"] == pytest.approx(eff["boss"]["low"], abs=1e-6)


def test_shrunk_weights_pull_thin_samples_toward_the_pool() -> None:
    rows = []
    for boss, effect, n in (
        ("m1", 0.0, 50),
        ("m2", 0.0, 50),
        ("m3", 0.0, 50),
        ("thin", 1.0, 1),
        ("thick", 1.0, 200),
    ):
        for i in range(n):
            rows.append({"y": effect + (-0.3, 0.0, 0.3)[i % 3], "boss": boss})
    effects = {"boss": {"m1": 0.0, "m2": 0.0, "m3": 0.0, "thin": 1.0, "thick": 1.0}}
    weights = shrunk_weights(rows, 0.0, effects, ["m1", "m2", "m3", "thin", "thick"])
    assert weights["thin"][0] < weights["thick"][0]
    assert weights["thick"][0] == pytest.approx(math.e, rel=0.02)
    assert weights["thin"][1] == 1


TAGS_TEXT = (
    json.dumps(
        {
            "1000": {
                "name": "A",
                "boss": {"size": 1, "exclude_from_pool": False},
                "region": 1,
            },
            "2000": {
                "name": "B",
                "boss": {"size": 2, "exclude_from_pool": True},
                "region": 2,
            },
        },
        indent=2,
    )
    + "\n"
)


def test_apply_weights_round_trips_untouched_text() -> None:
    assert apply_weights(TAGS_TEXT, {}) == TAGS_TEXT


def test_apply_weights_only_sets_the_weight_field() -> None:
    out = json.loads(apply_weights(TAGS_TEXT, {1000: 1.3}))
    before = json.loads(TAGS_TEXT)
    assert out["1000"]["boss"].pop("weight") == 1.3
    assert out == before


def test_apply_weights_rejects_unknown_entities() -> None:
    with pytest.raises(KeyError):
        apply_weights(TAGS_TEXT, {3000: 1.0})


def test_rounded_weights_give_thin_bosses_the_job_median() -> None:
    """A handful of clears must neither block nor be blocked by the spread."""
    weights = {
        "a": (0.64, 120),
        "b": (1.36, 80),
        "c": (2.0, 40),
        "thin": (0.4, 3),
        "tiny": (0.01, 50),
    }
    out = rounded_weights(weights, min_samples=20)
    assert out["thin"] == (1.0, True)  # median of 0.01, 0.64, 1.36, 2.0
    assert out["a"] == (0.6, False)
    assert out["b"] == (1.4, False)
    assert out["tiny"] == (0.1, False)  # boss.weight must stay > 0
