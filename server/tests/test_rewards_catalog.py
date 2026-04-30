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


def test_badge_dataclass_is_frozen():
    badge = BADGES["early_adopter"]
    assert dataclasses.is_dataclass(badge)
    try:
        badge.name = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Badge should be frozen")
