"""Race items: the seed plugin contract and the item catalog a seed carries."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement

from speedfog_racing.models import Seed

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
    """SQL twin of the plugin check on ``Seed.graph_json``.

    The catalog's non-emptiness is not checked here: the generator never emits
    the plugin without one. A tuple path, since chained indexing nests
    ``JSON_QUOTE`` on SQLite.
    """
    clause: ColumnElement[bool] = (
        Seed.graph_json[("plugins", RACE_ITEMS_PLUGIN, "enabled")].as_boolean().is_(True)
    )
    return clause
