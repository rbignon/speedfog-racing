"""Race items rules: tiers, draw, targets, effect payloads and banner copy."""

import json
import logging
import random
import uuid

import pytest
from pydantic import ValidationError

from speedfog_racing.config import DEFAULT_RACE_ITEMS_TIER_WEIGHTS, Settings, settings
from speedfog_racing.services.race_items import (
    ITEM_RULES,
    CatalogEntry,
    Runner,
    available_base_keys,
    base_key,
    draw_base_key,
    draw_camera_variant,
    effect_payload,
    extract_race_item_catalog,
    grant_banner,
    ink_can_land,
    item_order,
    reminder_for,
    resolve_targets,
    result_banner,
    rune_pouch_variant,
    shield_banner,
    target_banner,
    tier_of,
    tier_pool,
)


def _entry(
    name: str = "Item", duration_ms: int | None = 15000, speffect: int | None = 7
) -> CatalogEntry:
    return CatalogEntry(name, "icon", 60390, "race_item", speffect, duration_ms)


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


def test_rules_have_a_base_key_mapping():
    assert base_key("rune_pouch_2") == "rune_pouch"
    assert base_key("banana") == "banana"


def test_tier_pool_keeps_weighted_available_rules_only():
    weights = {"middle": {"red_shell": 2, "hammer": 0, "ghost": 5, "ink": 1}}
    assert tier_pool("middle", weights, {"red_shell", "hammer", "ink"}) == {
        "red_shell": 2,
        "ink": 1,
    }


def test_tier_pool_ignores_unknown_and_missing_items():
    assert tier_pool("front", {"middle": {"red_shell": 1}}, {"red_shell"}) == {}
    assert (
        draw_base_key("front", {"middle": {"red_shell": 1}}, {"red_shell"}, random.Random(1))
        is None
    )


def test_an_item_can_sit_in_two_tiers():
    w = {"front": {"mushroom": 1}, "middle": {"mushroom": 1}}
    assert draw_base_key("front", w, {"mushroom"}, random.Random(0)) == "mushroom"
    assert draw_base_key("middle", w, {"mushroom"}, random.Random(0)) == "mushroom"


def test_default_tier_table_names_known_items():
    for tier, weights in Settings().race_items_tier_weights.items():
        assert tier in ("front", "middle", "back")
        assert set(weights) <= set(ITEM_RULES)


def _settings_with_tier_weights(
    monkeypatch: pytest.MonkeyPatch, table: dict[str, dict[str, int]]
) -> Settings:
    monkeypatch.setenv("RACE_ITEMS_TIER_WEIGHTS", json.dumps(table))
    return Settings()


def test_a_partial_tier_table_keeps_the_default_of_the_other_tiers(monkeypatch):
    weights = _settings_with_tier_weights(
        monkeypatch, {"back": {"red_shell": 3}, "front": {}}
    ).race_items_tier_weights
    # A tier named replaces its default whole (an empty one draws nothing)...
    assert weights["back"] == {"red_shell": 3}
    assert weights["front"] == {}
    # ...and a tier left out keeps its default.
    assert weights["middle"] == DEFAULT_RACE_ITEMS_TIER_WEIGHTS["middle"]


def test_an_unknown_tier_refuses_the_settings(monkeypatch):
    with pytest.raises(ValidationError, match="unknown tier.*Front"):
        _settings_with_tier_weights(monkeypatch, {"Front": {"banana": 1}})


def test_a_negative_weight_refuses_the_settings(monkeypatch):
    with pytest.raises(ValidationError, match="negative weight.*middle.hammer"):
        _settings_with_tier_weights(monkeypatch, {"middle": {"hammer": -1, "ink": 1}})


def test_startup_warns_about_unknown_tier_items(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from speedfog_racing.main import app

    # The settings cannot check item keys (the rules import them): the server
    # start does, and a typo is never drawn.
    monkeypatch.setattr(
        settings, "race_items_tier_weights", {"front": {"banana": 1, "bananna": 1}, "back": {}}
    )
    with caplog.at_level(logging.WARNING, logger="speedfog_racing.main"), TestClient(app):
        pass
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert "RACE_ITEMS_TIER_WEIGHTS names unknown race items, never drawn: bananna" in warnings


def test_available_base_keys_folds_the_pouches():
    assert available_base_keys(["rune_pouch_2", "banana"]) == {"rune_pouch", "banana"}


def test_draw_respects_zero_weight():
    w = {"front": {"shield": 0, "rune_pouch": 1, "banana": 1}}
    avail = {"shield", "rune_pouch", "banana"}
    rng = random.Random(1)
    assert {draw_base_key("front", w, avail, rng) for _ in range(200)} == {"rune_pouch", "banana"}


def test_draw_weight_biases():
    w = {"back": {"lightning": 50, "blue_shell": 1}}
    rng = random.Random(2)
    draws = [draw_base_key("back", w, {"lightning", "blue_shell"}, rng) for _ in range(300)]
    assert draws.count("lightning") > 200


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


def test_item_order_keeps_the_leaderboard_order_under_the_lead():
    a, b, c = (uuid.uuid4() for _ in range(3))
    # c is 59 s ahead of b in IGT, b 30 s ahead of a: not enough to move.
    assert item_order([a, b, c], {a: 0, b: -30_000, c: -89_000}, 60_000) == [a, b, c]


def test_item_order_moves_a_runner_up_past_each_runner_it_leads_by_the_lead():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    # d (listed last on a shallower layer) leads c and b by 60 s or more, but
    # a by less: it stops under a.
    gaps = {a: 0, b: 20_000, c: 45_000, d: -40_000}
    assert item_order([a, b, c, d], gaps, 60_000) == [a, d, b, c]
    # Leading the leader by the lead too: d takes the lead.
    gaps[d] = -60_000
    assert item_order([a, b, c, d], gaps, 60_000) == [d, a, b, c]


def test_item_order_stops_at_the_first_runner_it_does_not_lead_enough():
    a, b, c = (uuid.uuid4() for _ in range(3))
    # c leads a by 70 s, but b (30 s ahead of a, so still under it) only by
    # 40 s: c stays where the leaderboard has it.
    assert item_order([a, b, c], {a: 0, b: -30_000, c: -70_000}, 60_000) == [a, b, c]


def test_item_order_without_a_gap_neither_moves_nor_is_passed():
    a, b, c = (uuid.uuid4() for _ in range(3))
    assert item_order([a, b, c], {a: 0, b: None, c: -500_000}, 60_000) == [a, b, c]
    assert item_order([a, b, c], {a: 0, b: 10_000, c: None}, 60_000) == [a, b, c]
    # A lead of 0 still keeps equal gaps in leaderboard order.
    assert item_order([a, b], {a: 0, b: 0}, 0) == [a, b]


def test_red_shell_targets_the_runner_just_ahead():
    p = _runners(4)
    assert resolve_targets("ahead", p[2].participant_id, p) == [p[1]]
    assert resolve_targets("ahead", p[0].participant_id, p) == []


def test_banana_targets_the_runner_just_behind():
    p = _runners(4)
    assert resolve_targets("behind", p[1].participant_id, p) == [p[2]]
    assert resolve_targets("behind", p[3].participant_id, p) == []


def test_blue_shell_hits_the_leader_even_its_sender():
    p = _runners(3)
    assert resolve_targets("leader", p[2].participant_id, p) == [p[0]]
    # Drawn at the back, used once leading: it comes back for the sender.
    assert resolve_targets("leader", p[0].participant_id, p) == [p[0]]
    assert resolve_targets("leader", p[0].participant_id, p[:1]) == [p[0]]
    # A sender no longer playing (finished) still hits the leader.
    assert resolve_targets("leader", p[0].participant_id, p[1:]) == [p[1]]
    assert resolve_targets("leader", p[0].participant_id, []) == []


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
        ("hammer", [], ["C", "D"], 0, "Blocked by 2 runners"),
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
    assert result_banner("hammer", _entry("Hammer", 30000), ["A"], [], 0).detail == "30s"
    mushroom = result_banner("mushroom", _entry("Mushroom", 20000), [], [], 0)
    assert (mushroom.line, mushroom.detail) == ("Infinite stamina for 20s", "20s")
    assert result_banner("rune_pouch_2", _entry("Pouch"), [], [], 0).line == "Runes added"


def test_result_banner_without_a_hit_quotes_no_strength():
    # Nothing landed: the item's strength would read as if it had.
    assert result_banner("red_shell", _entry("Red Shell"), [], ["C"], 0).detail == ""
    assert result_banner("hammer", _entry("Hammer", 15000), [], [], 2).detail == ""
    assert result_banner("hammer", _entry("Hammer", 15000), ["A"], ["C"], 0).detail == "15s"


def test_grant_and_target_banners_format_values(monkeypatch):
    monkeypatch.setattr(settings, "race_items_banana_pct", 12)
    e = _entry("Hammer", 45000)
    assert grant_banner("hammer", e).line == "Everyone else fat-rolls for 45s"
    b = target_banner("hammer", e, "Bob")
    assert (b.title, b.line, b.detail) == ("Hammer", "Fat-roll for 45s", "from Bob")
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


def test_hammer_payload_targets_a_share_of_the_max_load(monkeypatch):
    monkeypatch.setattr(settings, "race_items_hammer_load_pct", 97)
    assert effect_payload("hammer", _entry(speffect=99)).model_dump() == {
        "kind": "equip_load",
        "speffect_id": 99,
        "duration_ms": 15000,
        "load_pct": 97,
    }
    # A full 100 could round past the max and overload the target.
    monkeypatch.setattr(settings, "race_items_hammer_load_pct", 150)
    payload = effect_payload("hammer", _entry(speffect=99))
    assert payload and payload.load_pct == 99


def test_other_effect_payloads():
    assert effect_payload("lightning", _entry(speffect=99)).model_dump() == {
        "kind": "speffect",
        "speffect_id": 99,
        "duration_ms": 15000,
    }
    assert effect_payload("ink", _entry(duration_ms=20000)).model_dump() == {
        "kind": "ink",
        "duration_ms": 20000,
    }
    assert effect_payload("shield", _entry()) is None


def test_timed_effects_carry_their_duration():
    mushroom = effect_payload("mushroom", _entry(speffect=5, duration_ms=30000))
    assert mushroom and mushroom.model_dump() == {
        "kind": "speffect",
        "speffect_id": 5,
        "duration_ms": 30000,
    }
    hammer = effect_payload("hammer", _entry(speffect=99, duration_ms=15000))
    assert hammer and hammer.duration_ms == 15000
    # An instant effect has no duration to send.
    pouch = effect_payload("rune_pouch", _entry(speffect=7, duration_ms=None))
    assert pouch and "duration_ms" not in pouch.model_dump()


def test_self_items_send_their_effect_row():
    # The sender's own mod applies a self item's effect row (stamina, runes).
    assert effect_payload("mushroom", _entry(speffect=1450826)).model_dump() == {
        "kind": "speffect",
        "speffect_id": 1450826,
        "duration_ms": 15000,
    }
    pouch = effect_payload("rune_pouch_3", _entry(speffect=1450823, duration_ms=None))
    assert pouch and pouch.model_dump() == {"kind": "speffect", "speffect_id": 1450823}


def test_memory_effect_payloads(monkeypatch):
    vanish = effect_payload("vanish", _entry("Vanish", 15000, None))
    assert vanish and vanish.model_dump() == {"kind": "vanish", "duration_ms": 15000}
    foes = effect_payload("unseen_foes", _entry("Unseen Foes", 15000, None))
    assert foes and foes.model_dump() == {"kind": "unseen_foes", "duration_ms": 15000}
    slow = effect_payload("slow_mo", _entry("Slow-mo", 15000, None))
    assert slow and (slow.kind, slow.speed_pct) == ("slow_mo", 50)
    mini = effect_payload("mini", _entry("Mini", 15000, None))
    giant = effect_payload("giant", _entry("Giant", 15000, None))
    assert mini and mini.model_dump() == {"kind": "scale", "duration_ms": 15000, "scale_pct": 50}
    assert giant and giant.scale_pct == 150

    monkeypatch.setattr(settings, "race_items_slow_mo_speed_pct", 5)
    monkeypatch.setattr(settings, "race_items_mini_scale_pct", 10)
    monkeypatch.setattr(settings, "race_items_giant_scale_pct", 400)
    assert effect_payload("slow_mo", _entry("Slow-mo", 15000, None)).speed_pct == 10
    assert effect_payload("mini", _entry("Mini", 15000, None)).scale_pct == 25
    assert effect_payload("giant", _entry("Giant", 15000, None)).scale_pct == 300
    monkeypatch.setattr(settings, "race_items_slow_mo_speed_pct", 500)
    monkeypatch.setattr(settings, "race_items_mini_scale_pct", 5)
    monkeypatch.setattr(settings, "race_items_giant_scale_pct", 400)
    assert effect_payload("slow_mo", _entry("Slow-mo", 15000, None)).speed_pct == 100
    assert effect_payload("mini", _entry("Mini", 15000, None)).scale_pct == 25


@pytest.mark.parametrize("key", ["vanish", "unseen_foes", "slow_mo", "mini", "giant", "camera"])
def test_a_memory_effect_without_duration_is_not_sent(key, caplog):
    # The mod requires duration_ms on these kinds and would drop the whole
    # message: nothing goes, and the server says why.
    with caplog.at_level(logging.WARNING, logger="speedfog_racing.services.race_items"):
        assert effect_payload(key, _entry(key, None, None), "wide") is None
    assert any(key in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_camera_draws_a_variant_and_names_it():
    entry = _entry("Camera", 15000, None)
    lines = {
        "first_person": ("First-person camera for 15s", "First person"),
        "inverted": ("Upside-down camera for 15s", "Upside down"),
        "wide": ("Wide camera for 15s", "Wide camera"),
    }
    rng = random.Random(7)
    seen = set()
    for _ in range(40):
        variant = draw_camera_variant(rng)
        payload = effect_payload("camera", entry, variant)
        assert payload and payload.model_dump() == {
            "kind": "camera",
            "duration_ms": 15000,
            "variant": variant,
        }
        line, reminder = lines[variant]
        assert target_banner("camera", entry, "Bob", variant).line == line
        rem = reminder_for("camera", entry, variant)
        assert rem and (rem.text, rem.duration_ms) == (reminder, 15000)
        assert result_banner("camera", entry, ["Ann"], [], 0, variant=variant).detail == (
            f"{reminder}, 15s"
        )
        seen.add(variant)
    assert seen == set(lines)


def test_a_star_blocked_result_names_the_blocker():
    entry = _entry("Red Shell")
    assert result_banner("red_shell", entry, [], [], 0, ["Ann"]).line == "Blocked by Ann's Star"
    assert result_banner("hammer", entry, [], ["C"], 0, ["Ann"]).line == "Blocked by 2 runners"
    assert result_banner("hammer", entry, ["B"], [], 0, ["Ann"]).line == "Hit B, 1 blocked"


def _hub_graph(**counts: object) -> dict:
    """s -> a -> b -> end and s -> c -> end, each node's unused_exits as given
    (a node left out has no count)."""
    names = ("s", "a", "b", "c", "end")
    nodes = {n: ({"unused_exits": counts[n]} if n in counts else {}) for n in names}
    pairs = [("s", "a"), ("a", "b"), ("b", "end"), ("s", "c"), ("c", "end")]
    return {"nodes": nodes, "edges": [{"from": f, "to": t} for f, t in pairs]}


def test_ink_can_land_while_a_runner_can_reach_unused_exits():
    graph = _hub_graph(s=0, a=0, b=2, c=0, end=0)
    assert ink_can_land(graph, ["s"])
    assert ink_can_land(graph, ["b"])
    # Past the last zone with unused exits: nothing left to hide.
    assert not ink_can_land(graph, ["c"])
    assert not ink_can_land(graph, ["end"])
    # One runner who can still meet one is enough.
    assert ink_can_land(graph, ["c", "a"])
    # Nobody to hit.
    assert not ink_can_land(graph, [])
    # A cycle (a malformed graph) ends the walk all the same.
    graph["edges"].append({"from": "end", "to": "c"})
    assert not ink_can_land(graph, ["c"])


def test_ink_can_land_when_a_count_or_a_runner_is_unknown():
    # A seed older than graph.json 4.13 carries no count.
    assert ink_can_land(_hub_graph(), ["c"])
    assert ink_can_land(_hub_graph(s=0, a=0, b=0, c=0), ["c"])
    for bad in (True, "2", None):
        assert ink_can_land(_hub_graph(s=0, a=0, b=0, c=bad, end=0), ["c"])
    # A negative count is no 0, as the mod reads it; edges that are no list.
    assert ink_can_land(_hub_graph(s=0, a=0, b=0, c=-1, end=0), ["c"])
    assert ink_can_land({"nodes": {"c": {"unused_exits": 0}}, "edges": None}, ["c"])
    # A runner not placed yet, or on a node the graph lacks.
    assert ink_can_land(_hub_graph(s=0, a=0, b=0, c=0, end=0), [None])
    assert ink_can_land(_hub_graph(s=0, a=0, b=0, c=0, end=0), ["gone"])


def _seed_graph(**blocks: object) -> dict:
    goods = {
        "race_item": {
            "goods_id": 1450801,
            "use_flag": 1050290101,
            "remove_flag": 1050290201,
            "icon": "item_box",
            "icon_id": 60396,
        }
    }
    items = {
        key: {
            "name": key,
            "icon": key,
            "icon_id": 1,
            "goods": "race_item",
            "effect_speffect": None,
            "duration_ms": 60000 if key == "hunter" else None,
        }
        for key in ("talisman_thief", "junk_weapon", "hunter", "red_shell")
    }
    return {
        "plugins": {"race_items": {"enabled": True}},
        "race_items": {"goods": goods, "items": items, **blocks},
    }


FULL_BLOCKS = {
    "talismans": [{"id": 1000, "name": "Crimson Amber Medallion", "flag": 1050290300}],
    "junk_weapons": [{"id": 11010000, "name": "Club"}],
    "hunter": {"chr_id": 2130, "think_param": 1450850, "npc_params": [1450850, 1450851]},
}


def test_an_item_without_its_seed_data_is_not_drawn(caplog):
    full = extract_race_item_catalog(_seed_graph(**FULL_BLOCKS))
    assert {"talisman_thief", "junk_weapon", "hunter"} <= set(full.items)
    assert full.hunter is not None and full.hunter.npc_params == (1450850, 1450851)

    for missing, dropped in [
        ("talismans", "talisman_thief"),
        ("junk_weapons", "junk_weapon"),
        ("hunter", "hunter"),
    ]:
        blocks = {k: v for k, v in FULL_BLOCKS.items() if k != missing}
        with caplog.at_level(logging.DEBUG):
            catalog = extract_race_item_catalog(_seed_graph(**blocks))
        assert dropped not in catalog.items
        assert "red_shell" in catalog.items
        assert len(catalog.items) == 3
        # Every catalog parse of a pre-4.14 seed says it: debug only.
        levels = {r.levelno for r in caplog.records if dropped in r.getMessage()}
        assert levels == {logging.DEBUG}
        caplog.clear()

    # An empty or malformed block counts as missing.
    empty = extract_race_item_catalog(
        _seed_graph(talismans=[], junk_weapons=[{"id": "x"}], hunter={"chr_id": 1})
    )
    assert set(empty.items) == {"red_shell"}


def test_the_new_items_are_in_their_default_tiers():
    weights = DEFAULT_RACE_ITEMS_TIER_WEIGHTS
    assert {t for t, w in weights.items() if "talisman_thief" in w} == {"middle", "back"}
    assert {t for t, w in weights.items() if "junk_weapon" in w} == {"back"}
    assert {t for t, w in weights.items() if "hunter" in w} == {"back"}
