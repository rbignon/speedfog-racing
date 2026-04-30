"""Tests for the static rewards catalog (badges and name templates)."""

import dataclasses

from speedfog_racing.rewards.catalog import BADGES, NAME_TEMPLATES


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


def test_default_template_is_solid_white():
    default = NAME_TEMPLATES["default"]
    assert default.color == "#FFFFFF"
    assert default.gradient is None
    assert default.name_css is None
    assert default.background_css is None


def test_elo_crown_has_gradient_and_serif_name_css():
    crown = NAME_TEMPLATES["elo_crown"]
    assert crown.gradient is not None
    assert len(crown.gradient) == 2
    assert crown.name_css is not None
    assert "Georgia" in crown.name_css
    assert "italic" in crown.name_css


def test_runebearer_has_silver_gradient_and_italic_name_css():
    rune = NAME_TEMPLATES["runebearer"]
    assert rune.gradient is not None
    assert len(rune.gradient) == 2
    assert rune.name_css is not None
    assert "italic" in rune.name_css
    # runebearer keeps the default Inter font (no font-family override)
    assert "font-family" not in rune.name_css


def test_pioneer_has_bronze_gradient_and_italic_inter():
    pioneer = NAME_TEMPLATES["pioneer"]
    assert pioneer.gradient == ("#E8DCC4", "#A88B5C")
    assert pioneer.name_css is not None
    assert "italic" in pioneer.name_css
    assert "font-family" not in pioneer.name_css


def test_archon_uses_mono_font_in_violet():
    archon = NAME_TEMPLATES["archon"]
    assert archon.gradient == ("#C4B5FD", "#7C3AED")
    assert archon.name_css is not None
    assert "ui-monospace" in archon.name_css
    assert "font-weight: 600" in archon.name_css


def test_badge_dataclass_is_frozen():
    badge = BADGES["early_adopter"]
    assert dataclasses.is_dataclass(badge)
    try:
        badge.name = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Badge should be frozen")
