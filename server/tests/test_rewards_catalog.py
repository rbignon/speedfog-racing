"""Tests for invariants of the static rewards catalog.

Tests that just re-assert the literal values defined in `catalog.py` were
removed: they only catch "the constant changed", which is exactly what we
want when we update the catalog. This file keeps invariants that go beyond
single values (uniqueness, derivation rules, structural constraints).
"""

import dataclasses

from speedfog_racing.rewards.catalog import BADGES, DEFAULT_PHANTOM_SKIN_ID, PHANTOM_SKINS


def test_default_phantom_skin_id_points_to_a_real_skin():
    """Invariant: the sentinel id is always present in the catalog.

    Several call sites in services/rewards do `PHANTOM_SKINS[DEFAULT_PHANTOM_SKIN_ID]`
    so a typo in the constant would only blow up at runtime on the first hit.
    """
    assert DEFAULT_PHANTOM_SKIN_ID in PHANTOM_SKINS


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
