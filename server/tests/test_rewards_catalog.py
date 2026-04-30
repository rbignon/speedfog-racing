"""Tests for the static rewards catalog (badges and name templates)."""

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


def test_default_template_is_solid_white():
    default = NAME_TEMPLATES["default"]
    assert default.color == "#FFFFFF"
    assert default.gradient is None
    assert default.background_css is None


def test_elo_crown_has_gradient():
    crown = NAME_TEMPLATES["elo_crown"]
    assert crown.gradient is not None
    assert len(crown.gradient) == 2


def test_badge_dataclass_is_frozen():
    badge = BADGES["early_adopter"]
    import dataclasses

    assert dataclasses.is_dataclass(badge)
    try:
        badge.name = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Badge should be frozen")
