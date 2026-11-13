"""Race items: the seed plugin contract, the item catalog a seed carries and the rules.

The wire schemas are imported inside the builders: ``websocket.schemas`` pulls in
the services package, which imports this module.
"""

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import ColumnElement

from speedfog_racing.config import settings
from speedfog_racing.models import Seed

if TYPE_CHECKING:
    from speedfog_racing.websocket.schemas import ItemBanner, ItemEffectPayload, ItemReminder

RACE_ITEMS_PLUGIN = "race_items"


@dataclass(frozen=True)
class CatalogEntry:
    """One item of a seed's catalog (``graph.json`` ``race_items``)."""

    name: str
    icon: str
    goods_id: int
    use_flag: int | None
    remove_flag: int
    effect_speffect: int | None
    duration_ms: int | None


def _plugin_enabled(graph_json: Mapping[str, Any]) -> bool:
    plugins = graph_json.get("plugins")
    if not isinstance(plugins, Mapping):
        return False
    plugin = plugins.get(RACE_ITEMS_PLUGIN)
    return isinstance(plugin, Mapping) and plugin.get("enabled") is True


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_entry(raw: object) -> CatalogEntry | None:
    """A catalog entry, or None when a required field is missing or mistyped."""
    if not isinstance(raw, Mapping):
        return None
    name, icon = raw.get("name"), raw.get("icon")
    goods_id, remove_flag = raw.get("goods_id"), raw.get("remove_flag")
    if not isinstance(name, str) or not isinstance(icon, str):
        return None
    if not _is_int(goods_id) or not _is_int(remove_flag):
        return None
    optional: list[int | None] = []
    for key in ("use_flag", "effect_speffect", "duration_ms"):
        value = raw.get(key)
        if value is not None and not _is_int(value):
            return None
        optional.append(value)
    return CatalogEntry(name, icon, goods_id, optional[0], remove_flag, optional[1], optional[2])  # type: ignore[arg-type]


def extract_race_item_catalog(graph_json: Mapping[str, Any]) -> dict[str, CatalogEntry]:
    """The valid catalog entries of a seed; empty when it lacks the plugin."""
    if not _plugin_enabled(graph_json):
        return {}
    raw = graph_json.get(RACE_ITEMS_PLUGIN)
    if not isinstance(raw, Mapping):
        return {}
    catalog: dict[str, CatalogEntry] = {}
    for key, value in raw.items():
        entry = _parse_entry(value)
        if isinstance(key, str) and entry is not None:
            catalog[key] = entry
    return catalog


def seed_has_race_items(graph_json: Mapping[str, Any]) -> bool:
    """Whether a seed supports items: plugin enabled and a non-empty catalog."""
    raw = graph_json.get(RACE_ITEMS_PLUGIN)
    return _plugin_enabled(graph_json) and isinstance(raw, Mapping) and len(raw) > 0


def use_flag_map(catalog: Mapping[str, CatalogEntry]) -> dict[int, str]:
    """Use event flag to item key; items without a use flag (the Shield) are left out."""
    return {e.use_flag: key for key, e in catalog.items() if e.use_flag is not None}


def race_items_seed_clause() -> ColumnElement[bool]:
    """SQL twin of ``seed_has_race_items``: the seeds that support items.

    It reads ``Seed.race_items``, which the pool scan sets from
    ``seed_has_race_items`` when it adds the seed, so no query parses a graph.
    """
    clause: ColumnElement[bool] = Seed.race_items.is_(True)
    return clause


# ---------------------------------------------------------------------------
# Rules: tiers, draw, targets, effect payloads and banner copy
# ---------------------------------------------------------------------------

Tier = Literal["front", "middle", "back"]
TargetRule = Literal["self", "passive", "behind", "ahead", "leader", "others"]
EffectKind = Literal["none", "speffect", "damage", "ink", "equip_load"]


@dataclass(frozen=True)
class ItemRule:
    """Rules of one base item key.

    ``grant_line`` and ``target_line`` may use ``{s}`` (seconds) and ``{pct}``
    (damage percent); ``reminder`` is the label of the countdown line, if any.
    """

    tier: Tier
    target: TargetRule
    effect: EffectKind
    grant_line: str
    target_line: str = ""
    reminder: str | None = None


ITEM_RULES: dict[str, ItemRule] = {
    "shield": ItemRule("front", "passive", "none", "Blocks the next item aimed at you"),
    "rune_pouch": ItemRule("front", "self", "none", "Use it for runes"),
    "banana": ItemRule("front", "behind", "damage", "Hits the runner behind", "Hit for {pct}% HP"),
    "red_shell": ItemRule(
        "middle", "ahead", "damage", "Hits the runner ahead", "Hit for {pct}% HP"
    ),
    "mushroom": ItemRule(
        "middle", "self", "none", "Infinite stamina for {s} s", "", "Infinite stamina"
    ),
    "hammer": ItemRule(
        "middle",
        "others",
        "equip_load",
        "Everyone else fat-rolls for {s} s",
        "Fat-roll for {s} s",
        "Fat-roll",
    ),
    "ink": ItemRule(
        "middle",
        "others",
        "ink",
        "Hides everyone else's exits for {s} s",
        "Exits hidden for {s} s",
        "Ink",
    ),
    "blue_shell": ItemRule(
        "back",
        "leader",
        "speffect",
        "Halves the leader's max HP for {s} s",
        "Max HP halved for {s} s",
        "Max HP halved",
    ),
    "lightning": ItemRule(
        "back",
        "others",
        "speffect",
        "Slows everyone else for {s} s",
        "Slowed for {s} s",
        "Slowed",
    ),
    "flask_stopper": ItemRule(
        "back",
        "others",
        "speffect",
        "Blocks everyone else's flasks for {s} s",
        "Flasks blocked for {s} s",
        "Flasks blocked",
    ),
    "toxic_blossom": ItemRule("back", "others", "speffect", "Poisons everyone else", "Poisoned"),
}

_MISSED_LINE = {
    "ahead": "Missed: nobody ahead",
    "behind": "Missed: nobody behind",
}


def base_key(item_key: str) -> str:
    """The rules key of a catalog key: the three Rune Pouch variants share one."""
    return "rune_pouch" if item_key.startswith("rune_pouch_") else item_key


def tier_of(index: int, count: int) -> Tier:
    """Tier of the runner at ``index`` among ``count`` playing runners (leader first)."""
    if count <= 2:
        return "front" if index == 0 else "back"
    if 3 * index < count:
        return "front"
    if 3 * index < 2 * count:
        return "middle"
    return "back"


def draw_base_key(tier: Tier, weights: Mapping[str, int], rng: random.Random) -> str:
    """Weighted draw in a tier's pool; a missing weight is 1, 0 excludes the item.

    When every weight of the pool is 0 the draw falls back to uniform, so a
    runner is never left without an item.
    """
    pool = [key for key, rule in ITEM_RULES.items() if rule.tier == tier]
    pool_weights = [max(0, weights.get(key, 1)) for key in pool]
    if not any(pool_weights):
        return rng.choice(pool)
    return rng.choices(pool, weights=pool_weights)[0]


def rune_pouch_variant(current_layer: int, total_layers: int) -> str:
    """Pouch variant by progress through the seed's layers (thirds)."""
    if total_layers <= 0:
        return "rune_pouch_1"
    if 3 * current_layer < total_layers:
        return "rune_pouch_1"
    if 3 * current_layer < 2 * total_layers:
        return "rune_pouch_2"
    return "rune_pouch_3"


@dataclass(frozen=True)
class Runner:
    participant_id: uuid.UUID
    name: str


def resolve_targets(
    target: TargetRule, sender_id: uuid.UUID, playing: Sequence[Runner]
) -> list[Runner]:
    """Runners an item hits; ``playing`` is in leaderboard order, leader first."""
    index = next((i for i, r in enumerate(playing) if r.participant_id == sender_id), None)
    others = [r for r in playing if r.participant_id != sender_id]
    if target == "self":
        return [] if index is None else [playing[index]]
    if target == "passive":
        return []
    if target == "others":
        return others
    if target == "leader":
        return others[:1]
    if index is None:
        return []
    neighbor = index - 1 if target == "ahead" else index + 1
    return [playing[neighbor]] if 0 <= neighbor < len(playing) else []


def _percent(value: int) -> int:
    """A percent setting clamped to 0..100: the mod reads each as a byte."""
    return max(0, min(100, value))


def _damage_pct(key: str) -> int:
    if key == "banana":
        return _percent(settings.race_items_banana_pct)
    return _percent(settings.race_items_red_shell_pct)


def _seconds(entry: CatalogEntry) -> int:
    return (entry.duration_ms or 0) // 1000


def _format(template: str, key: str, entry: CatalogEntry) -> str:
    return template.format(s=_seconds(entry), pct=_damage_pct(key))


def effect_payload(item_key: str, entry: CatalogEntry) -> "ItemEffectPayload | None":
    """The wire effect an item applies to a target; None for self and passive items."""
    from speedfog_racing.websocket.schemas import ItemEffectPayload

    key = base_key(item_key)
    kind = ITEM_RULES[key].effect
    if kind == "speffect":
        return ItemEffectPayload(kind="speffect", speffect_id=entry.effect_speffect)
    if kind == "damage":
        return ItemEffectPayload(
            kind="damage",
            base_pct=_damage_pct(key),
            floor_pct=_percent(settings.race_items_damage_floor_pct),
            tail_pct=_percent(settings.race_items_damage_tail_pct),
        )
    if kind == "ink":
        return ItemEffectPayload(kind="ink", duration_ms=entry.duration_ms)
    if kind == "equip_load":
        return ItemEffectPayload(
            kind="equip_load",
            speffect_id=entry.effect_speffect,
            # 100 could round past the max and overload the target.
            load_pct=min(_percent(settings.race_items_hammer_load_pct), 99),
        )
    return None


def grant_banner(item_key: str, entry: CatalogEntry) -> "ItemBanner":
    """Banner shown when the item lands in the holder's pouch."""
    from speedfog_racing.websocket.schemas import ItemBanner

    rule = ITEM_RULES[base_key(item_key)]
    return ItemBanner(
        icon=entry.icon,
        title=entry.name,
        line=_format(rule.grant_line, base_key(item_key), entry),
        detail="",
    )


def target_banner(item_key: str, entry: CatalogEntry, sender: str) -> "ItemBanner":
    """Banner shown to a runner the item hits."""
    from speedfog_racing.websocket.schemas import ItemBanner

    key = base_key(item_key)
    return ItemBanner(
        icon=entry.icon,
        title=entry.name,
        line=_format(ITEM_RULES[key].target_line, key, entry),
        detail=f"from {sender}",
    )


def result_banner(
    item_key: str,
    entry: CatalogEntry,
    hits: Sequence[str],
    blocked: Sequence[str],
    offline: int,
) -> "ItemBanner":
    """Banner shown to the sender once the item resolved."""
    from speedfog_racing.websocket.schemas import ItemBanner

    key = base_key(item_key)
    rule = ITEM_RULES[key]
    detail = ""
    if rule.effect == "damage":
        detail = f"{_damage_pct(key)}% HP"
    elif entry.duration_ms is not None and rule.reminder is not None:
        detail = f"{_seconds(entry)} s"

    if rule.target == "self":
        line = "Runes added" if key == "rune_pouch" else _format(rule.grant_line, key, entry)
    elif hits:
        line = f"Hit {hits[0]}" if len(hits) == 1 else f"Hit {len(hits)} runners"
        if blocked:
            line += f", {len(blocked)} blocked"
    elif blocked:
        line = (
            f"Blocked by {blocked[0]}'s shield"
            if len(blocked) == 1
            else f"Blocked by {len(blocked)} shields"
        )
    elif offline:
        line = "Missed"
    else:
        line = _MISSED_LINE.get(rule.target, "Missed: no other runner")
    return ItemBanner(icon=entry.icon, title=entry.name, line=line, detail=detail)


def shield_banner(item_name: str, sender: str) -> "ItemBanner":
    """Banner shown to a shield holder whose shield blocked an item."""
    from speedfog_racing.websocket.schemas import ItemBanner

    return ItemBanner(
        icon="shield", title="Shield", line=f"Blocked {item_name}", detail=f"from {sender}"
    )


def reminder_for(item_key: str, entry: CatalogEntry) -> "ItemReminder | None":
    """Countdown line for a timed effect; None for items without one."""
    from speedfog_racing.websocket.schemas import ItemReminder

    text = ITEM_RULES[base_key(item_key)].reminder
    if text is None or entry.duration_ms is None:
        return None
    return ItemReminder(text=text, duration_ms=entry.duration_ms)
