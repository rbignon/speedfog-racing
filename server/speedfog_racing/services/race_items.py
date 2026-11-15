"""Race items: the seed plugin contract, the item catalog a seed carries and the rules.

The wire schemas are imported inside the builders: ``websocket.schemas`` pulls in
the services package, which imports this module.
"""

import random
import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

from sqlalchemy import ColumnElement

from speedfog_racing.config import settings
from speedfog_racing.models import Seed

if TYPE_CHECKING:
    from speedfog_racing.websocket.schemas import ItemBanner, ItemEffectPayload, ItemReminder

RACE_ITEMS_PLUGIN = "race_items"


@dataclass(frozen=True)
class GoodsEntry:
    """One goods of a seed's catalog (``graph.json`` ``race_items.goods``): what
    the game holds. The Race Item carries every usable item; the Shield, never
    used, has its own and no use flag."""

    goods_id: int
    use_flag: int | None
    remove_flag: int
    icon: str
    icon_id: int


@dataclass(frozen=True)
class CatalogEntry:
    """One item of a seed's catalog (``graph.json`` ``race_items.items``),
    held as the goods its ``goods`` key names."""

    name: str
    icon: str
    icon_id: int
    goods: str
    effect_speffect: int | None
    duration_ms: int | None


@dataclass(frozen=True)
class RaceItemCatalog:
    """A seed's race item catalog; ``items`` only holds entries whose goods is in ``goods``."""

    goods: dict[str, GoodsEntry] = field(default_factory=dict)
    items: dict[str, CatalogEntry] = field(default_factory=dict)


def _plugin_enabled(graph_json: Mapping[str, Any]) -> bool:
    plugins = graph_json.get("plugins")
    if not isinstance(plugins, Mapping):
        return False
    plugin = plugins.get(RACE_ITEMS_PLUGIN)
    return isinstance(plugin, Mapping) and plugin.get("enabled") is True


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_optional_int(value: object) -> TypeGuard[int | None]:
    return value is None or _is_int(value)


def _parse_goods(raw: object) -> GoodsEntry | None:
    """A catalog goods, or None when a required field is missing or mistyped."""
    if not isinstance(raw, Mapping):
        return None
    goods_id, use_flag, remove_flag = (
        raw.get("goods_id"),
        raw.get("use_flag"),
        raw.get("remove_flag"),
    )
    icon, icon_id = raw.get("icon"), raw.get("icon_id")
    if (
        _is_int(goods_id)
        and _is_optional_int(use_flag)
        and _is_int(remove_flag)
        and isinstance(icon, str)
        and _is_int(icon_id)
    ):
        return GoodsEntry(goods_id, use_flag, remove_flag, icon, icon_id)
    return None


def _parse_item(raw: object) -> CatalogEntry | None:
    """A catalog item, or None when a required field is missing or mistyped."""
    if not isinstance(raw, Mapping):
        return None
    name, icon, icon_id, goods = (
        raw.get("name"),
        raw.get("icon"),
        raw.get("icon_id"),
        raw.get("goods"),
    )
    speffect, duration_ms = raw.get("effect_speffect"), raw.get("duration_ms")
    if (
        isinstance(name, str)
        and isinstance(icon, str)
        and _is_int(icon_id)
        and isinstance(goods, str)
        and _is_optional_int(speffect)
        and _is_optional_int(duration_ms)
    ):
        return CatalogEntry(name, icon, icon_id, goods, speffect, duration_ms)
    return None


def extract_race_item_catalog(graph_json: Mapping[str, Any]) -> RaceItemCatalog:
    """The valid goods and items of a seed (graph.json 4.12 ``{goods, items}``).

    Empty when the seed lacks the plugin or carries another shape, such as the
    flat ``{item_key: entry}`` dict of the seeds generated before 4.12: their
    per-item goods are gone from the protocol. An item on a goods the catalog
    lacks (or holds malformed) is dropped.
    """
    if not _plugin_enabled(graph_json):
        return RaceItemCatalog()
    raw = graph_json.get(RACE_ITEMS_PLUGIN)
    if not isinstance(raw, Mapping):
        return RaceItemCatalog()
    raw_goods, raw_items = raw.get("goods"), raw.get("items")
    if not isinstance(raw_goods, Mapping) or not isinstance(raw_items, Mapping):
        return RaceItemCatalog()
    goods: dict[str, GoodsEntry] = {}
    for key, value in raw_goods.items():
        entry = _parse_goods(value)
        if isinstance(key, str) and entry is not None:
            goods[key] = entry
    items: dict[str, CatalogEntry] = {}
    for key, value in raw_items.items():
        item = _parse_item(value)
        if isinstance(key, str) and item is not None and item.goods in goods:
            items[key] = item
    return RaceItemCatalog(goods, items)


def seed_has_race_items(graph_json: Mapping[str, Any]) -> bool:
    """Whether a seed supports items: plugin enabled and at least one valid item."""
    return bool(extract_race_item_catalog(graph_json).items)


def use_flag_map(catalog: RaceItemCatalog) -> dict[int, str]:
    """Use event flag to goods key; goods without a use flag (the Shield) are left out."""
    return {g.use_flag: key for key, g in catalog.goods.items() if g.use_flag is not None}


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
EffectKind = Literal[
    "none",
    "speffect",
    "damage",
    "ink",
    "equip_load",
    "vanish",
    "unseen_foes",
    "slow_mo",
    "scale",
    "camera",
]
CameraVariant = Literal["first_person", "inverted", "wide"]
CAMERA_VARIANTS: tuple[CameraVariant, ...] = ("first_person", "inverted", "wide")

# The Camera's target line and reminder per variant, drawn at each use.
_CAMERA_TARGET_LINES: dict[str, str] = {
    "first_person": "First-person camera for {s} s",
    "inverted": "Upside-down camera for {s} s",
    "wide": "Wide camera for {s} s",
}
_CAMERA_REMINDERS: dict[str, str] = {
    "first_person": "First person",
    "inverted": "Upside down",
    "wide": "Wide camera",
}


@dataclass(frozen=True)
class ItemRule:
    """Rules of one base item key.

    ``grant_line`` and ``target_line`` may use ``{s}`` (seconds) and ``{pct}``
    (damage percent); ``reminder`` is the label of the countdown line, if any.
    """

    target: TargetRule
    effect: EffectKind
    grant_line: str
    target_line: str = ""
    reminder: str | None = None


ITEM_RULES: dict[str, ItemRule] = {
    "shield": ItemRule("passive", "none", "Blocks the next item aimed at you"),
    "rune_pouch": ItemRule("self", "speffect", "Use it for runes"),
    "banana": ItemRule("behind", "damage", "Hits the runner behind", "Hit for {pct}% HP"),
    "red_shell": ItemRule("ahead", "damage", "Hits the runner ahead", "Hit for {pct}% HP"),
    "mushroom": ItemRule("self", "speffect", "Infinite stamina for {s} s", "", "Infinite stamina"),
    "hammer": ItemRule(
        "others",
        "equip_load",
        "Everyone else fat-rolls for {s} s",
        "Fat-roll for {s} s",
        "Fat-roll",
    ),
    "ink": ItemRule(
        "others",
        "ink",
        "Hides everyone else's exits for {s} s",
        "Exits hidden for {s} s in a hub zone",
        "Ink",
    ),
    "blue_shell": ItemRule(
        "leader",
        "speffect",
        "Halves the leader's max HP for {s} s",
        "Max HP halved for {s} s",
        "Max HP halved",
    ),
    "lightning": ItemRule(
        "others",
        "speffect",
        "Slows everyone else for {s} s",
        "Slowed for {s} s",
        "Slowed",
    ),
    "flask_stopper": ItemRule(
        "others",
        "speffect",
        "Blocks everyone else's flasks for {s} s",
        "Flasks blocked for {s} s",
        "Flasks blocked",
    ),
    "toxic_blossom": ItemRule("others", "speffect", "Poisons everyone else", "Poisoned"),
    "star": ItemRule("self", "speffect", "Invincible for {s} s", "", "Invincible"),
    "vanish": ItemRule(
        "others",
        "vanish",
        "Everyone else turns invisible for {s} s",
        "You are invisible for {s} s",
        "Invisible",
    ),
    "unseen_foes": ItemRule(
        "others",
        "unseen_foes",
        "Hides everyone else's enemies for {s} s",
        "Enemies unseen for {s} s",
        "Unseen foes",
    ),
    "slow_mo": ItemRule(
        "ahead",
        "slow_mo",
        "Slows the runner ahead for {s} s",
        "Half speed for {s} s",
        "Slow-mo",
    ),
    "mini": ItemRule(
        "others", "scale", "Shrinks everyone else for {s} s", "Shrunk for {s} s", "Mini"
    ),
    "giant": ItemRule(
        "others", "scale", "Everyone else grows huge for {s} s", "Giant for {s} s", "Giant"
    ),
    # The target line and the reminder depend on the variant drawn at each use.
    "camera": ItemRule("ahead", "camera", "Messes with the camera of the runner ahead for {s} s"),
}

_MISSED_LINE = {
    "ahead": "Missed: nobody ahead",
    "behind": "Missed: nobody behind",
}


def base_key(item_key: str) -> str:
    """The rules key of a catalog key: the three Rune Pouch variants share one."""
    return "rune_pouch" if item_key.startswith("rune_pouch_") else item_key


def item_order(
    ids: Sequence[uuid.UUID], gaps: Mapping[uuid.UUID, int | None], lead_ms: int
) -> list[uuid.UUID]:
    """Playing runners in race item order, the leader first.

    ``ids`` is the leaderboard order (deepest layer, then layer entry IGT) and
    ``gaps`` each runner's gap_ms (IGT behind the leaderboard leader at the same
    point, ``leaderboard_gaps``). A runner whose time lost outside IGT (slow
    loads, a crash) left it on a shallower layer can be ahead in IGT, which
    ranks the race: each runner moves up past every runner directly above it
    that it leads by ``lead_ms`` or more, and stops at the first it does not.
    Smaller leads keep the leaderboard order, so items mostly follow the order
    the runners see. A runner without a gap neither moves nor is passed.
    """
    lead = max(lead_ms, 1)
    result: list[uuid.UUID] = []
    for pid in ids:
        own = gaps.get(pid)
        pos = len(result)
        while own is not None and pos > 0:
            above = gaps.get(result[pos - 1])
            if above is None or above - own < lead:
                break
            pos -= 1
        result.insert(pos, pid)
    return result


def tier_of(index: int, count: int) -> Tier:
    """Tier of the runner at ``index`` among ``count`` playing runners (leader first)."""
    if count <= 2:
        return "front" if index == 0 else "back"
    if 3 * index < count:
        return "front"
    if 3 * index < 2 * count:
        return "middle"
    return "back"


def available_base_keys(catalog_keys: Iterable[str]) -> set[str]:
    """The rules keys a seed's catalog can serve (the Rune Pouch variants fold into one)."""
    return {base_key(key) for key in catalog_keys}


def tier_pool(
    tier: Tier, tier_weights: Mapping[str, Mapping[str, int]], available: Collection[str]
) -> dict[str, int]:
    """The tier's drawable items: known rules the seed has, with a weight above 0."""
    weights = tier_weights.get(tier, {})
    return {
        key: weight
        for key, weight in weights.items()
        if key in ITEM_RULES and key in available and weight > 0
    }


def unknown_tier_items(tier_weights: Mapping[str, Mapping[str, int]]) -> list[str]:
    """The item keys of a tier table that no rule knows (a typo): never drawn."""
    return sorted({key for weights in tier_weights.values() for key in weights} - set(ITEM_RULES))


def draw_base_key(
    tier: Tier,
    tier_weights: Mapping[str, Mapping[str, int]],
    available: Collection[str],
    rng: random.Random,
) -> str | None:
    """Weighted draw in a tier's pool, None when nothing is left to draw."""
    pool = tier_pool(tier, tier_weights, available)
    if not pool:
        return None
    return rng.choices(list(pool), weights=list(pool.values()))[0]


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
    """Runners an item hits; ``playing`` is in leaderboard order, leader first.

    The leader rule counts the sender too: as in Mario Kart, a Blue Shell
    drawn at the back and used once leading comes back for its sender.
    """
    index = next((i for i, r in enumerate(playing) if r.participant_id == sender_id), None)
    others = [r for r in playing if r.participant_id != sender_id]
    if target == "self":
        return [] if index is None else [playing[index]]
    if target == "passive":
        return []
    if target == "others":
        return others
    if target == "leader":
        return list(playing[:1])
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


def _scale_pct(key: str) -> int:
    """Mini and Giant sizes, clamped to what the mod can apply."""
    value = (
        settings.race_items_mini_scale_pct if key == "mini" else settings.race_items_giant_scale_pct
    )
    return max(25, min(300, value))


def draw_camera_variant(rng: random.Random | None = None) -> CameraVariant:
    """The Camera's variant, uniform at each use."""
    return (rng or random).choice(CAMERA_VARIANTS)


def _seconds(entry: CatalogEntry) -> int:
    return (entry.duration_ms or 0) // 1000


def _format(template: str, key: str, entry: CatalogEntry) -> str:
    return template.format(s=_seconds(entry), pct=_damage_pct(key))


def effect_payload(
    item_key: str, entry: CatalogEntry, variant: CameraVariant | None = None
) -> "ItemEffectPayload | None":
    """The wire effect an item applies to a target (a self item's target is its
    sender's own mod); None for the passive Shield. ``variant`` is the Camera's
    (drawn when absent)."""
    from speedfog_racing.websocket.schemas import ItemEffectPayload

    key = base_key(item_key)
    kind = ITEM_RULES[key].effect
    if kind == "speffect":
        return ItemEffectPayload(
            kind="speffect",
            speffect_id=entry.effect_speffect,
            duration_ms=entry.duration_ms,
        )
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
            duration_ms=entry.duration_ms,
            # 100 could round past the max and overload the target.
            load_pct=min(_percent(settings.race_items_hammer_load_pct), 99),
        )
    if kind == "vanish":
        return ItemEffectPayload(kind="vanish", duration_ms=entry.duration_ms)
    if kind == "unseen_foes":
        return ItemEffectPayload(kind="unseen_foes", duration_ms=entry.duration_ms)
    if kind == "slow_mo":
        return ItemEffectPayload(
            kind="slow_mo",
            duration_ms=entry.duration_ms,
            speed_pct=max(10, min(100, settings.race_items_slow_mo_speed_pct)),
        )
    if kind == "scale":
        return ItemEffectPayload(
            kind="scale", duration_ms=entry.duration_ms, scale_pct=_scale_pct(key)
        )
    if kind == "camera":
        return ItemEffectPayload(
            kind="camera", duration_ms=entry.duration_ms, variant=variant or draw_camera_variant()
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


def target_banner(
    item_key: str, entry: CatalogEntry, sender: str, variant: CameraVariant | None = None
) -> "ItemBanner":
    """Banner shown to a runner the item hits."""
    from speedfog_racing.websocket.schemas import ItemBanner

    key = base_key(item_key)
    template = ITEM_RULES[key].target_line
    if ITEM_RULES[key].effect == "camera":
        template = _CAMERA_TARGET_LINES[variant or "first_person"]
    return ItemBanner(
        icon=entry.icon,
        title=entry.name,
        line=_format(template, key, entry),
        detail=f"from {sender}",
    )


def result_banner(
    item_key: str,
    entry: CatalogEntry,
    hits: Sequence[str],
    blocked: Sequence[str],
    offline: int,
    stars: Sequence[str] = (),
    variant: CameraVariant | None = None,
) -> "ItemBanner":
    """Banner shown to the sender once the item resolved. ``blocked`` names the
    runners whose shield blocked it, ``stars`` those whose Star did."""
    from speedfog_racing.websocket.schemas import ItemBanner

    key = base_key(item_key)
    rule = ITEM_RULES[key]
    detail = ""
    # The strength only when something landed, or it reads as dealt.
    landed = bool(hits) or rule.target == "self"
    if landed and rule.effect == "damage":
        detail = f"{_damage_pct(key)}% HP"
    elif landed and rule.effect == "camera" and entry.duration_ms is not None:
        detail = f"{_CAMERA_REMINDERS[variant or 'first_person']}, {_seconds(entry)} s"
    elif landed and entry.duration_ms is not None and rule.reminder is not None:
        detail = f"{_seconds(entry)} s"

    if rule.target == "self":
        line = "Runes added" if key == "rune_pouch" else _format(rule.grant_line, key, entry)
    elif hits:
        line = f"Hit {hits[0]}" if len(hits) == 1 else f"Hit {len(hits)} runners"
        if blocked or stars:
            line += f", {len(blocked) + len(stars)} blocked"
    elif blocked or stars:
        if len(blocked) + len(stars) > 1:
            line = f"Blocked by {len(blocked) + len(stars)} runners"
        elif blocked:
            line = f"Blocked by {blocked[0]}'s shield"
        else:
            line = f"Blocked by {stars[0]}'s Star"
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


def star_banner(item_name: str, sender: str) -> "ItemBanner":
    """Banner shown to a Star holder whose Star blocked an item."""
    from speedfog_racing.websocket.schemas import ItemBanner

    return ItemBanner(
        icon="star", title="Star", line=f"Blocked {item_name}", detail=f"from {sender}"
    )


def reminder_for(
    item_key: str, entry: CatalogEntry, variant: CameraVariant | None = None
) -> "ItemReminder | None":
    """Countdown line for a timed effect; None for items without one."""
    from speedfog_racing.websocket.schemas import ItemReminder

    rule = ITEM_RULES[base_key(item_key)]
    text = rule.reminder
    if rule.effect == "camera":
        text = _CAMERA_REMINDERS[variant or "first_person"]
    if text is None or entry.duration_ms is None:
        return None
    return ItemReminder(text=text, duration_ms=entry.duration_ms)
