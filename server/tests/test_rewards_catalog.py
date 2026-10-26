"""Tests for invariants of the static rewards catalog.

Tests that just re-assert the literal values defined in `catalog.py` were
removed: they only catch "the constant changed", which is exactly what we
want when we update the catalog. This file keeps invariants that go beyond
single values (uniqueness, derivation rules, structural constraints).
"""

import dataclasses
from pathlib import Path

from speedfog_racing.rewards.catalog import (
    BADGES,
    DEFAULT_PHANTOM_SKIN_ID,
    NAME_TEMPLATES,
    PHANTOM_SKINS,
    PSEUDO_PHANTOM_SKIN_IDS,
    RANDOM_PHANTOM_SKIN_ID,
)

BADGE_DIR = Path(__file__).resolve().parents[2] / "web" / "static" / "badges"


def test_every_badge_icon_ships_with_the_web_app():
    """A catalog badge whose SVG is missing renders a broken image everywhere."""
    missing = [
        b.icon_filename for b in BADGES.values() if not (BADGE_DIR / b.icon_filename).is_file()
    ]
    assert missing == []


def test_badge_sort_order_unique():
    orders = [b.sort_order for b in BADGES.values()]
    assert len(orders) == len(set(orders))


def test_name_template_sort_order_unique():
    orders = [t.sort_order for t in NAME_TEMPLATES.values()]
    assert len(orders) == len(set(orders))


def test_pseudo_skins_are_exactly_the_two_choice_entries():
    """Invariant tying the `pseudo` flags to the ids the code hardcodes.

    Call sites do `PHANTOM_SKINS[DEFAULT_PHANTOM_SKIN_ID]` or compare against
    `RANDOM_PHANTOM_SKIN_ID`, so a typo in either constant would only blow up
    at runtime on the first hit. The other direction matters too: flagging a
    real aura `pseudo` would make it un-grantable and hide it from the picker
    and from profile avatars.
    """
    assert PSEUDO_PHANTOM_SKIN_IDS == {DEFAULT_PHANTOM_SKIN_ID, RANDOM_PHANTOM_SKIN_ID}


def test_badge_dataclass_is_frozen():
    badge = BADGES["early_adopter"]
    assert dataclasses.is_dataclass(badge)
    try:
        badge.name = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Badge should be frozen")


def test_phantom_skins_have_screenshot_filenames():
    """Screenshot filename is derived from the skin id."""
    for skin in PHANTOM_SKINS.values():
        assert skin.screenshot_filename.endswith(".jpg")
        assert skin.screenshot_filename == f"{skin.id}.jpg"


def test_phantom_skin_sort_order_unique_and_monotonic():
    orders = sorted(s.sort_order for s in PHANTOM_SKINS.values())
    assert orders == sorted(set(orders)), "sort_order values must be unique"


def test_only_emerald_aura_is_not_obtainable():
    """The catalog has exactly one non-obtainable skin (emerald-aura, dev-only).

    If a future skin is added as non-obtainable by mistake, this test catches it.
    """
    non_obtainable = {sid for sid, s in PHANTOM_SKINS.items() if not s.obtainable}
    assert non_obtainable == {"emerald-aura"}
