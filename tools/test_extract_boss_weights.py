"""Tests for extract_boss_weights.py (clear times, attribution, fit, writing)."""

from __future__ import annotations

import json
import math

import pytest
from extract_boss_weights import (
    apply_weights,
    attribute,
    band_weights,
    boss_clears,
    fit_effects,
    rounded_weights,
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
    mu, eff = fit_effects(
        _rows(spec),
        factors=("arena", "boss", "tier", "user", "pool"),
        max_iter=100,
        tol=1e-12,
    )
    ratio = math.exp(eff["boss"]["b2"] - eff["boss"]["b1"])
    assert ratio == pytest.approx(3.0, rel=1e-6)


def test_fit_normalizes_the_tier_a_boss_was_met_at() -> None:
    """Identical bosses, one only seen at high tiers: equal weights."""
    tier = {1: 1.0, 2: 2.0, 3: 4.0}
    spec = [(a, "low", t, tier[t]) for a in ("a1", "a2") for t in (1, 2)]
    spec += [(a, "high", t, tier[t]) for a in ("a1", "a2") for t in (2, 3)]
    mu, eff = fit_effects(
        _rows(spec),
        factors=("arena", "boss", "tier", "user", "pool"),
        max_iter=100,
        tol=1e-12,
    )
    assert eff["boss"]["high"] == pytest.approx(eff["boss"]["low"], abs=1e-6)


NOISE = (-0.1, 0.0, 0.1)
SHIFT = {"early": 0.0, "mid": 0.3, "late": 0.6}  # common to the pool


def _band_rows(spec):
    """spec: {boss: {band: (effect, n)}} -> rows and the matching effects."""
    rows, effects = [], {"bossband": {}}
    for boss, bands in spec.items():
        for band, (effect, n) in bands.items():
            effects["bossband"][(boss, band)] = effect
            rows += [
                {"y": effect + NOISE[i % 3], "bossband": (boss, band)} for i in range(n)
            ]
    return rows, effects


def _follows(rel, n=40):
    """A boss whose relative effect is ``rel`` in every band."""
    return {band: (SHIFT[band] + rel, n) for band in SHIFT}


def test_band_weights_remove_the_common_band_shift() -> None:
    spec = {f"avg{i}": _follows(0.0) for i in range(4)}
    spec["flat"] = _follows(0.0)
    spec["light"] = _follows(-1.0)
    spec["steep"] = {"early": (0.0, 40), "mid": (0.3, 40), "late": (1.2, 40)}
    rows, effects = _band_rows(spec)
    weights = band_weights(rows, 0.0, effects, list(spec))
    flat, light, steep = weights["flat"][0], weights["light"][0], weights["steep"][0]
    assert flat["early"] == pytest.approx(flat["late"])
    assert light["early"] == pytest.approx(light["late"])
    assert light["early"] < flat["early"]
    assert steep["late"] > 1.5 * steep["mid"]
    assert steep["early"] == pytest.approx(steep["mid"])


def test_band_weights_ignore_thin_bands() -> None:
    spec = {f"avg{i}": _follows(0.0) for i in range(4)}
    spec["spiky"] = {"early": (0.0, 40), "mid": (0.3, 40), "late": (2.6, 5)}
    rows, effects = _band_rows(spec)
    spiky = band_weights(rows, 0.0, effects, list(spec), min_samples=20)["spiky"][0]
    assert spiky["late"] < 1.2 * spiky["mid"]


def test_rounded_weights_give_thin_bosses_each_band_median() -> None:
    weights = {
        "a": ({"early": 0.54, "mid": 0.6, "late": 0.7}, 100),
        "b": ({"early": 1.5, "mid": 1.6, "late": 1.7}, 100),
        "c": ({"early": 2.5, "mid": 2.6, "late": 0.01}, 100),
        "thin": ({"early": 9.0, "mid": 9.0, "late": 9.0}, 3),
    }
    out = rounded_weights(weights, min_samples=20)
    assert out["thin"] == ({"early": 1.5, "mid": 1.6, "late": 0.7}, True)
    assert out["a"] == ({"early": 0.5, "mid": 0.6, "late": 0.7}, False)
    assert out["c"][0]["late"] == 0.1  # boss.weight must stay > 0


TAGS_TEXT = (
    json.dumps(
        {
            "1000": {
                "name": "A",
                "boss": {"size": 1, "exclude_from_pool": False},
                "region": 1,
            },
            "2000": {"name": "B", "boss": {"size": 2, "weight": 1.0}, "region": 2},
        },
        indent=2,
    )
    + "\n"
)


def test_apply_weights_round_trips_untouched_text() -> None:
    assert apply_weights(TAGS_TEXT, {}) == TAGS_TEXT


def test_apply_weights_writes_band_objects_only() -> None:
    bands = {"early": 0.3, "mid": 0.2, "late": 0.2}
    out = json.loads(apply_weights(TAGS_TEXT, {1000: bands, 2000: bands}))
    before = json.loads(TAGS_TEXT)
    assert out["1000"]["boss"].pop("weight") == bands
    assert out["2000"]["boss"].pop("weight") == bands
    before["2000"]["boss"].pop("weight")
    assert out == before


def test_apply_weights_rejects_unknown_entities() -> None:
    with pytest.raises(KeyError):
        apply_weights(TAGS_TEXT, {3000: {"early": 1.0, "mid": 1.0, "late": 1.0}})
