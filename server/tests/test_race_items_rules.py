"""Race items rules: tiers, draw, targets, effect payloads and banner copy."""

import random
import uuid

import pytest

from speedfog_racing.config import settings
from speedfog_racing.services.race_items import (
    ITEM_RULES,
    CatalogEntry,
    Runner,
    base_key,
    draw_base_key,
    effect_payload,
    grant_banner,
    reminder_for,
    resolve_targets,
    result_banner,
    rune_pouch_variant,
    shield_banner,
    target_banner,
    tier_of,
)


def _entry(
    name: str = "Item", duration_ms: int | None = 15000, speffect: int | None = 7
) -> CatalogEntry:
    return CatalogEntry(name, "icon", 1, 2, 3, speffect, duration_ms)


def _runners(n: int) -> list[Runner]:
    return [Runner(uuid.uuid4(), f"R{i}") for i in range(n)]


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, ["front"]),
        (2, ["front", "back"]),
        (3, ["front", "middle", "back"]),
        (4, ["front", "front", "middle", "back"]),
        (6, ["front", "front", "middle", "middle", "back", "back"]),
    ],
)
def test_tier_of(count, expected):
    assert [tier_of(i, count) for i in range(count)] == expected


def test_rules_cover_every_base_key_with_a_tier_pool():
    for tier in ("front", "middle", "back"):
        assert [k for k, r in ITEM_RULES.items() if r.tier == tier]
    assert base_key("rune_pouch_2") == "rune_pouch"
    assert base_key("banana") == "banana"


def test_draw_respects_zero_weight():
    rng = random.Random(1)
    draws = {draw_base_key("front", {"shield": 0}, rng) for _ in range(200)}
    assert "shield" not in draws
    assert draws == {"rune_pouch", "banana"}


def test_draw_weight_biases_and_all_zero_falls_back():
    rng = random.Random(2)
    draws = [draw_base_key("back", {"lightning": 50}, rng) for _ in range(300)]
    assert draws.count("lightning") > 200
    zero = {k: 0 for k in ITEM_RULES}
    assert draw_base_key("middle", zero, rng) in {
        k for k, r in ITEM_RULES.items() if r.tier == "middle"
    }


@pytest.mark.parametrize(
    "layer,total,expected",
    [
        (0, 12, "rune_pouch_1"),
        (3, 12, "rune_pouch_1"),
        (4, 12, "rune_pouch_2"),
        (7, 12, "rune_pouch_2"),
        (8, 12, "rune_pouch_3"),
        (12, 12, "rune_pouch_3"),
        (5, 0, "rune_pouch_1"),
    ],
)
def test_rune_pouch_variant_thresholds(layer, total, expected):
    assert rune_pouch_variant(layer, total) == expected


def test_red_shell_targets_the_runner_just_ahead():
    p = _runners(4)
    assert resolve_targets("ahead", p[2].participant_id, p) == [p[1]]
    assert resolve_targets("ahead", p[0].participant_id, p) == []


def test_banana_targets_the_runner_just_behind():
    p = _runners(4)
    assert resolve_targets("behind", p[1].participant_id, p) == [p[2]]
    assert resolve_targets("behind", p[3].participant_id, p) == []


def test_blue_shell_skips_the_sender_when_leading():
    p = _runners(3)
    assert resolve_targets("leader", p[0].participant_id, p) == [p[1]]
    assert resolve_targets("leader", p[2].participant_id, p) == [p[0]]
    assert resolve_targets("leader", p[0].participant_id, p[:1]) == []


def test_group_items_hit_everyone_else():
    p = _runners(4)
    assert resolve_targets("others", p[1].participant_id, p) == [p[0], p[2], p[3]]


def test_self_and_passive_targets():
    p = _runners(2)
    assert resolve_targets("self", p[1].participant_id, p) == [p[1]]
    assert resolve_targets("passive", p[1].participant_id, p) == []


@pytest.mark.parametrize(
    "key,hits,blocked,offline,line",
    [
        ("hammer", ["A"], [], 0, "Hit A"),
        ("hammer", ["A", "B", "C"], [], 0, "Hit 3 runners"),
        ("hammer", ["A", "B"], ["C"], 0, "Hit 2 runners, 1 blocked"),
        ("hammer", ["A"], ["C"], 0, "Hit A, 1 blocked"),
        ("hammer", [], ["C"], 0, "Blocked by C's shield"),
        ("hammer", [], ["C", "D"], 0, "Blocked by 2 shields"),
        ("red_shell", [], [], 0, "Missed: nobody ahead"),
        ("banana", [], [], 0, "Missed: nobody behind"),
        ("lightning", [], [], 0, "Missed: no other runner"),
        ("hammer", [], [], 2, "Missed"),
    ],
)
def test_result_banner_lines(key, hits, blocked, offline, line):
    assert result_banner(key, _entry("Hammer"), hits, blocked, offline).line == line


def test_result_banner_details_and_self_results(monkeypatch):
    monkeypatch.setattr(settings, "race_items_red_shell_pct", 25)
    assert result_banner("red_shell", _entry("Red Shell"), ["A"], [], 0).detail == "25% HP"
    assert result_banner("hammer", _entry("Hammer", 30000), ["A"], [], 0).detail == "30 s"
    mushroom = result_banner("mushroom", _entry("Mushroom", 20000), [], [], 0)
    assert (mushroom.line, mushroom.detail) == ("Infinite stamina for 20 s", "20 s")
    assert result_banner("rune_pouch_2", _entry("Pouch"), [], [], 0).line == "Runes added"


def test_grant_and_target_banners_format_values(monkeypatch):
    monkeypatch.setattr(settings, "race_items_banana_pct", 12)
    e = _entry("Hammer", 45000)
    assert grant_banner("hammer", e).line == "Everyone else fat-rolls for 45 s"
    b = target_banner("hammer", e, "Bob")
    assert (b.title, b.line, b.detail) == ("Hammer", "Fat-roll for 45 s", "from Bob")
    assert target_banner("banana", _entry("Banana"), "Bob").line == "Hit for 12% HP"


def test_shield_banner():
    b = shield_banner("Hammer", "Bob")
    assert (b.title, b.line, b.detail) == ("Shield", "Blocked Hammer", "from Bob")


def test_reminder_for_uses_catalog_duration():
    assert reminder_for("hammer", _entry(duration_ms=30000)).model_dump() == {
        "text": "Fat-roll",
        "duration_ms": 30000,
    }
    assert reminder_for("banana", _entry()) is None
    assert reminder_for("hammer", _entry(duration_ms=None)) is None


def test_damage_payload_uses_settings(monkeypatch):
    monkeypatch.setattr(settings, "race_items_banana_pct", 10)
    monkeypatch.setattr(settings, "race_items_red_shell_pct", 20)
    monkeypatch.setattr(settings, "race_items_damage_floor_pct", 20)
    monkeypatch.setattr(settings, "race_items_damage_tail_pct", 5)
    red = effect_payload("red_shell", _entry())
    banana = effect_payload("banana", _entry())
    assert red and red.model_dump() == {
        "kind": "damage",
        "base_pct": 20,
        "floor_pct": 20,
        "tail_pct": 5,
    }
    assert banana and banana.base_pct == 10


def test_damage_settings_are_clamped_to_a_percent(monkeypatch):
    monkeypatch.setattr(settings, "race_items_red_shell_pct", 150)
    monkeypatch.setattr(settings, "race_items_damage_floor_pct", -10)
    monkeypatch.setattr(settings, "race_items_damage_tail_pct", 300)
    red = effect_payload("red_shell", _entry("Red Shell"))
    assert red and (red.base_pct, red.floor_pct, red.tail_pct) == (100, 0, 100)
    # The banners quote the damage actually applied.
    assert target_banner("red_shell", _entry("Red Shell"), "Bob").line == "Hit for 100% HP"
    assert result_banner("red_shell", _entry("Red Shell"), ["A"], [], 0).detail == "100% HP"


def test_other_effect_payloads():
    assert effect_payload("lightning", _entry(speffect=99)).model_dump() == {
        "kind": "speffect",
        "speffect_id": 99,
    }
    assert effect_payload("ink", _entry(duration_ms=20000)).model_dump() == {
        "kind": "ink",
        "duration_ms": 20000,
    }
    assert effect_payload("shield", _entry()) is None
    assert effect_payload("mushroom", _entry()) is None
