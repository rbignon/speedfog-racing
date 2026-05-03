"""Tests for the static rewards catalog (badges and name templates)."""

import dataclasses

from speedfog_racing.rewards.catalog import (
    BADGES,
    DEFAULT_PHANTOM_SKIN_ID,
    NAME_TEMPLATES,
    PHANTOM_SKINS,
)
from speedfog_racing.rewards.models_data import PhantomSkin


def test_v1_badges_present():
    assert "early_adopter" in BADGES
    assert "contributor" in BADGES
    assert "top1_elo" in BADGES
    assert "weekly_daily_champion" in BADGES


def test_badge_lifecycle_values():
    assert BADGES["early_adopter"].lifecycle == "permanent"
    assert BADGES["contributor"].lifecycle == "permanent"
    assert BADGES["top1_elo"].lifecycle == "transient"
    assert BADGES["weekly_daily_champion"].lifecycle == "transient"


def test_v1_templates_present():
    assert "default" in NAME_TEMPLATES
    assert "elo_crown" in NAME_TEMPLATES
    assert "runebearer" in NAME_TEMPLATES
    assert "pioneer" in NAME_TEMPLATES
    assert "archon" in NAME_TEMPLATES
    assert "weathered" in NAME_TEMPLATES


def test_default_template_is_solid_white():
    default = NAME_TEMPLATES["default"]
    assert default.color == "#FFFFFF"
    assert default.gradient is None
    assert default.name_css is None
    assert default.background_css is None


def test_elo_crown_belongs_to_inter_italic_elo_family():
    """elo_crown shares Inter italic with runebearer (same data axis: ELO rank)."""
    crown = NAME_TEMPLATES["elo_crown"]
    assert crown.gradient == ("#FFE9A8", "#C8A44E")
    assert crown.name_css is not None
    assert "italic" in crown.name_css
    # No font-family override: keeps the charter Inter, like runebearer.
    assert "font-family" not in crown.name_css


def test_runebearer_belongs_to_inter_italic_elo_family():
    rune = NAME_TEMPLATES["runebearer"]
    assert rune.gradient is not None
    assert len(rune.gradient) == 2
    assert rune.name_css is not None
    assert "italic" in rune.name_css
    assert "font-family" not in rune.name_css


def test_pioneer_has_no_gradient_and_uses_georgia():
    """pioneer is web-only by design: no gradient means the mod overlay
    keeps the player's status color, while the web renders the parchment
    look via name_css and background_css.
    """
    pioneer = NAME_TEMPLATES["pioneer"]
    assert pioneer.gradient is None
    assert pioneer.color is None
    assert pioneer.name_css is not None
    assert "Georgia" in pioneer.name_css
    assert "italic" in pioneer.name_css


def test_archon_uses_mono_font_in_violet():
    archon = NAME_TEMPLATES["archon"]
    assert archon.gradient == ("#C4B5FD", "#7C3AED")
    assert archon.name_css is not None
    assert "ui-monospace" in archon.name_css
    assert "font-weight: 600" in archon.name_css


def test_weathered_uses_steel_gradient_and_semibold():
    weathered = NAME_TEMPLATES["weathered"]
    assert weathered.gradient == ("#D6DCE0", "#7A8590")
    assert weathered.name_css is not None
    assert "font-weight: 600" in weathered.name_css
    # weathered keeps Inter (no font-family override) and is not italic;
    # those signals are reserved for other tiers (serif=lore, italic=ELO).
    assert "font-family" not in weathered.name_css
    assert "italic" not in weathered.name_css


def test_badge_dataclass_is_frozen():
    badge = BADGES["early_adopter"]
    assert dataclasses.is_dataclass(badge)
    try:
        badge.name = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Badge should be frozen")


def test_v1_phantom_skins_present():
    assert "none" in PHANTOM_SKINS
    assert "gold-aura" in PHANTOM_SKINS
    assert "silver-aura" in PHANTOM_SKINS
    assert "cyan-aura" in PHANTOM_SKINS
    assert "emerald-aura" in PHANTOM_SKINS
    assert "crimson-aura" in PHANTOM_SKINS
    assert "violet-aura" in PHANTOM_SKINS


def test_default_phantom_skin_id_is_none():
    assert DEFAULT_PHANTOM_SKIN_ID == "none"
    assert PHANTOM_SKINS[DEFAULT_PHANTOM_SKIN_ID].sort_order == 0


def test_phantom_skins_have_screenshot_filenames():
    for skin in PHANTOM_SKINS.values():
        assert skin.screenshot_filename.endswith(".jpg")
        assert skin.screenshot_filename == f"{skin.id}.jpg"


def test_phantom_skin_dataclass_fields():
    skin = PHANTOM_SKINS["gold-aura"]
    assert isinstance(skin, PhantomSkin)
    assert skin.id == "gold-aura"
    assert skin.name == "Gold Aura"
    assert skin.sort_order == 10


def test_phantom_skin_sort_order_unique_and_monotonic():
    orders = sorted(s.sort_order for s in PHANTOM_SKINS.values())
    assert orders == sorted(set(orders)), "sort_order values must be unique"


def test_emerald_aura_is_not_obtainable():
    assert PHANTOM_SKINS["emerald-aura"].obtainable is False


def test_other_phantom_skins_are_obtainable():
    for skin_id, skin in PHANTOM_SKINS.items():
        if skin_id == "emerald-aura":
            continue
        assert skin.obtainable is True, f"{skin_id} should be obtainable by default"
