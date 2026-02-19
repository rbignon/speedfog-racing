"""Server-side translation of game data (zone names, fog gate text).

Translations are loaded once at startup from TOML files in ``data/i18n/``.
Graph JSON and zone-update messages are translated on the fly based on the
user's locale.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TranslationData:
    """Parsed translation data for a single locale."""

    locale: str
    language: str
    types: dict[str, str] = field(default_factory=dict)
    bosses: dict[str, str] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)
    locations: dict[str, str] = field(default_factory=dict)
    patterns_text: dict[str, str] = field(default_factory=dict)
    patterns_side_text: dict[str, str] = field(default_factory=dict)
    overrides_text: dict[str, str] = field(default_factory=dict)
    overrides_side_text: dict[str, str] = field(default_factory=dict)


# Module-level state – populated by ``load_translations()``.
_translations: dict[str, TranslationData] = {}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_translations(i18n_dir: Path) -> dict[str, TranslationData]:
    """Load all ``*.toml`` translation files from *i18n_dir*.

    Stores result in module-level ``_translations`` and returns it.
    """
    global _translations  # noqa: PLW0603

    loaded: dict[str, TranslationData] = {}
    if not i18n_dir.is_dir():
        logger.warning("i18n directory not found: %s", i18n_dir)
        _translations = loaded
        return loaded

    for path in sorted(i18n_dir.glob("*.toml")):
        try:
            raw = path.read_bytes()
            data = tomllib.loads(raw.decode())
        except Exception:
            logger.exception("Failed to parse translation file: %s", path)
            continue

        meta = data.get("meta", {})
        locale = meta.get("locale", path.stem)
        td = TranslationData(
            locale=locale,
            language=meta.get("language", locale),
            types=data.get("types", {}),
            bosses=data.get("names", {}).get("bosses", {}),
            regions=data.get("names", {}).get("regions", {}),
            locations=data.get("names", {}).get("locations", {}),
            patterns_text=data.get("patterns", {}).get("text", {}),
            patterns_side_text=data.get("patterns", {}).get("side_text", {}),
            overrides_text=data.get("overrides", {}).get("text", {}),
            overrides_side_text=data.get("overrides", {}).get("side_text", {}),
        )
        loaded[locale] = td
        logger.info("Loaded i18n: %s (%s) from %s", locale, td.language, path.name)

    _translations = loaded
    return loaded


def get_available_locales() -> list[dict[str, str]]:
    """Return list of available locales including English (always present)."""
    locales = [{"code": "en", "name": "English"}]
    for td in _translations.values():
        locales.append({"code": td.locale, "name": td.language})
    return locales


# ---------------------------------------------------------------------------
# Name translation
# ---------------------------------------------------------------------------


def _lookup_name(name: str, data: TranslationData) -> str | None:
    """Look up a single name in bosses → regions → locations."""
    return data.bosses.get(name) or data.regions.get(name) or data.locations.get(name) or None


def _translate_name(name: str, data: TranslationData) -> str:
    """Translate a proper name via bosses → regions → locations lookups.

    Handles composite names like ``"Region - Location - Boss"`` by splitting
    on ``" - "`` and translating each segment individually.
    """
    # Try full name first
    result = _lookup_name(name, data)
    if result is not None:
        return result

    # Composite: "Capital Outskirts - Sealed Tunnel - Onyx Lord"
    parts = name.split(" - ")
    if len(parts) > 1:
        translated_parts = [_lookup_name(p, data) or p for p in parts]
        if translated_parts != parts:
            return " - ".join(translated_parts)

    return name


# ---------------------------------------------------------------------------
# Display name formatting (article stripping + capitalization)
# ---------------------------------------------------------------------------

# Leading articles stripped from display names to produce label-style text.
# Matches: "le ", "la ", "les ", "l'" (case-insensitive).
_LEADING_ARTICLE_RE = re.compile(r"^(?:les |le |la |l')", re.IGNORECASE)


def _format_display_name(name: str) -> str:
    """Strip leading French article and capitalize for standalone display.

    Handles composite names (``"Region - Location - Boss"``) by processing
    each segment independently.
    """
    if " - " in name:
        return " - ".join(_format_display_name(p) for p in name.split(" - "))
    stripped = _LEADING_ARTICLE_RE.sub("", name)
    if stripped:
        return stripped[0].upper() + stripped[1:]
    return name


# ---------------------------------------------------------------------------
# French grammar contractions
# ---------------------------------------------------------------------------

# Contraction rules applied after pattern substitution.
_CONTRACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bde le\b"), "du"),
    (re.compile(r"\bde les\b"), "des"),
    (re.compile(r"\bDe le\b"), "Du"),
    (re.compile(r"\bDe les\b"), "Des"),
    (re.compile(r"\bà le\b"), "au"),
    (re.compile(r"\bà les\b"), "aux"),
    (re.compile(r"\bÀ le\b"), "Au"),
    (re.compile(r"\bÀ les\b"), "Aux"),
]


def _apply_french_contractions(text: str) -> str:
    """Apply mandatory French contractions (de le → du, etc.)."""
    for pattern, replacement in _CONTRACTIONS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Text translation (overrides → patterns → fallback)
# ---------------------------------------------------------------------------

# Cache compiled regexes keyed by English pattern template.
# Bounded by the number of patterns in the TOML files (currently ~30).
_pattern_regex_cache: dict[str, re.Pattern[str]] = {}

# Placeholder names used in the TOML pattern templates.
_PLACEHOLDER_NAMES = {"boss", "zone", "zone1", "zone2", "location", "direction"}


def _build_pattern_regex(en_template: str) -> re.Pattern[str]:
    """Convert a pattern template like ``"{boss} front"`` into a regex.

    Named capture groups match the entity names to extract.
    """
    if en_template in _pattern_regex_cache:
        return _pattern_regex_cache[en_template]

    # Escape regex-special characters except our placeholders.
    # We temporarily replace placeholders, escape, then put groups back.
    placeholder_map: dict[str, str] = {}
    temp = en_template
    for ph in _PLACEHOLDER_NAMES:
        token = "{" + ph + "}"
        if token in temp:
            marker = f"__PH_{ph}__"
            placeholder_map[marker] = ph
            temp = temp.replace(token, marker)

    escaped = re.escape(temp)

    for marker, ph in placeholder_map.items():
        escaped_marker = re.escape(marker)
        escaped = escaped.replace(escaped_marker, f"(?P<{ph}>.+?)")

    # Handle possessive forms: {boss}'s and {boss}' in English.
    # re.escape() in Python 3.7+ does NOT escape apostrophes, so the literal
    # pattern contains "'s" (not "\'s") after escaping.
    escaped = escaped.replace("'s", "(?:'s|')")

    regex = re.compile(f"^{escaped}$", re.IGNORECASE)
    _pattern_regex_cache[en_template] = regex
    return regex


def _translate_text(
    text: str,
    field_name: str,
    data: TranslationData,
) -> str:
    """Translate a fog gate text string.

    Strategy: overrides → pattern match with entity substitution → fallback.
    *field_name* is ``"text"`` or ``"side_text"``.
    """
    if not text:
        return text

    # 1. Override (exact match)
    overrides = data.overrides_text if field_name == "text" else data.overrides_side_text
    if text in overrides:
        return overrides[text]

    # 2. Pattern matching
    patterns = data.patterns_text if field_name == "text" else data.patterns_side_text
    for en_template, fr_template in patterns.items():
        regex = _build_pattern_regex(en_template)
        m = regex.match(text)
        if m:
            # Extract captured entity names and translate them
            translated_parts: dict[str, str] = {}
            for ph in _PLACEHOLDER_NAMES:
                try:
                    value = m.group(ph)
                except IndexError:
                    continue
                if value is not None:
                    translated_parts[ph] = _translate_name(value, data)

            # Substitute into French template
            result = fr_template
            for ph, translated_value in translated_parts.items():
                result = result.replace("{" + ph + "}", translated_value)

            # Apply French grammar contractions
            result = _apply_french_contractions(result)
            return result

    # 3. Fallback: return original English text
    return text


def _translate_exit_text(text: str, data: TranslationData) -> str:
    """Translate exit text, falling back to side_text patterns.

    ``output.py`` puts side_text content into the ``"text"`` field of
    graph.json exits (there is no separate side_text field), so we try
    text overrides/patterns first, then side_text ones.
    """
    result = _translate_text(text, "text", data)
    if result == text:
        result = _translate_text(text, "side_text", data)
    return result


# ---------------------------------------------------------------------------
# Graph JSON translation (cached)
# ---------------------------------------------------------------------------


def _graph_json_hash(graph_json: dict[str, Any]) -> str:
    """Stable hash for a graph_json dict (used as cache key)."""
    raw = json.dumps(graph_json, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()


@lru_cache(maxsize=64)
def _translate_graph_json_cached(graph_hash: str, locale: str) -> dict[str, Any] | None:
    """Translate a graph_json. Cached by (hash, locale).

    Returns None when locale is unknown so caller can fall back to original.
    This is an internal helper – the real entry point is ``translate_graph_json``.
    """
    # _translate_graph_json_impl stores the original in _graph_json_store[hash]
    original = _graph_json_store.get(graph_hash)
    if original is None:
        return None  # Should not happen
    return _translate_graph_json_impl(original, locale)


# Temporary store for the original graph_json (keyed by hash) so the cached
# function can access it without passing the full dict through lru_cache.
# Bounded in practice by the number of distinct seeds used across all active
# races (typically < 100).  The lru_cache(64) on the translation layer further
# limits useful entries.
_graph_json_store: dict[str, dict[str, Any]] = {}


def translate_graph_json(graph_json: dict[str, Any], locale: str) -> dict[str, Any]:
    """Translate all translatable fields in *graph_json* for *locale*.

    Returns the original dict unchanged for ``"en"`` or unknown locales.
    Translated results are cached by ``(graph_json_hash, locale)``.
    """
    if locale == "en" or locale not in _translations:
        return graph_json

    h = _graph_json_hash(graph_json)
    _graph_json_store[h] = graph_json
    result = _translate_graph_json_cached(h, locale)
    return result if result is not None else graph_json


def _translate_graph_json_impl(graph_json: dict[str, Any], locale: str) -> dict[str, Any]:
    """Deep-copy graph_json and translate node display_name, type, and exits."""
    data = _translations.get(locale)
    if data is None:
        return graph_json

    translated = copy.deepcopy(graph_json)
    nodes: dict[str, Any] = translated.get("nodes", {})

    for node_data in nodes.values():
        if not isinstance(node_data, dict):
            continue

        # Translate display_name (strip article + capitalize for label context)
        display_name = node_data.get("display_name")
        if isinstance(display_name, str):
            node_data["display_name"] = _format_display_name(_translate_name(display_name, data))

        # Add translated display_type (e.g. "legacy_dungeon" → "donjon majeur").
        # Keep original "type" intact — the frontend uses it for rendering logic.
        node_type = node_data.get("type")
        if isinstance(node_type, str) and node_type in data.types:
            node_data["display_type"] = data.types[node_type]

        # Translate exits (text field may contain side_text content)
        exits = node_data.get("exits", [])
        for exit_data in exits:
            if not isinstance(exit_data, dict):
                continue
            text = exit_data.get("text")
            if isinstance(text, str):
                exit_data["text"] = _translate_exit_text(text, data)

    return translated


# ---------------------------------------------------------------------------
# Zone update translation (not cached – small payloads)
# ---------------------------------------------------------------------------


def translate_zone_update(zone_update: dict[str, Any], locale: str) -> dict[str, Any]:
    """Translate a zone_update message for *locale*.

    Returns the original dict unchanged for ``"en"`` or unknown locales.
    """
    if locale == "en" or locale not in _translations:
        return zone_update

    data = _translations[locale]
    translated = copy.copy(zone_update)

    # Translate display_name (strip article + capitalize for label context)
    display_name = translated.get("display_name")
    if isinstance(display_name, str):
        translated["display_name"] = _format_display_name(_translate_name(display_name, data))

    # Translate exits
    exits = translated.get("exits")
    if isinstance(exits, list):
        new_exits = []
        for exit_data in exits:
            if not isinstance(exit_data, dict):
                new_exits.append(exit_data)
                continue
            ex = dict(exit_data)
            text = ex.get("text")
            if isinstance(text, str):
                ex["text"] = _translate_exit_text(text, data)
            to_name = ex.get("to_name")
            if isinstance(to_name, str):
                ex["to_name"] = _translate_name(to_name, data)
            new_exits.append(ex)
        translated["exits"] = new_exits

    return translated
