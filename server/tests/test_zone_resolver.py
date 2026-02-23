"""Unit tests for zone_resolver module."""

from speedfog_racing.services.zone_resolver import (
    get_zones_for_map,
    resolve_zone_by_position,
)

# --- get_zones_for_map ---


def test_get_zones_for_map_leyndell():
    """m11_00_00_00 returns leyndell + leyndell_sanctuary + other Leyndell zones."""
    zones = get_zones_for_map("m11_00_00_00")
    assert "leyndell" in zones
    assert "leyndell_sanctuary" in zones
    assert "leyndell_divinebridge" in zones
    assert len(zones) >= 5  # leyndell has many sub-zones


def test_get_zones_for_map_stormveil():
    """m10_00_00_00 returns stormveil zones."""
    zones = get_zones_for_map("m10_00_00_00")
    assert "stormveil_godrick" in zones
    assert "stormhill" in zones


def test_get_zones_for_map_unknown():
    """Unknown map_id returns empty set."""
    zones = get_zones_for_map("m99_99_99_99")
    assert zones == set()


def test_get_zones_for_map_ainsel_boss():
    """m12_04_00_00 returns ainsel boss area zones."""
    zones = get_zones_for_map("m12_04_00_00")
    assert "ainsel_boss" in zones


# --- resolve_zone_by_position ---


def test_resolve_zone_by_position_leyndell_main_city():
    """Low Y position in m11_00_00_00 resolves to leyndell (main city, default)."""
    # Main city is the default (lowest level) — Y below all conditional thresholds
    zone = resolve_zone_by_position("m11_00_00_00", 0.0, -50.0, 0.0)
    assert zone == "leyndell"


def test_resolve_zone_by_position_leyndell_sanctuary():
    """High Y + low Z in m11_00_00_00 resolves to leyndell_sanctuary (Godfrey arena)."""
    # YAbove: 25, ZBelow: -380 → inside the arena
    zone = resolve_zone_by_position("m11_00_00_00", 0.0, 30.0, -400.0)
    assert zone == "leyndell_sanctuary"


def test_resolve_zone_by_position_leyndell_bedchamber():
    """Very high Y in m11_00_00_00 resolves to leyndell_bedchamber."""
    # YAbove: 45
    zone = resolve_zone_by_position("m11_00_00_00", 0.0, 50.0, 0.0)
    assert zone == "leyndell_bedchamber"


def test_resolve_zone_by_position_no_rules():
    """Map without submaps rules returns None."""
    zone = resolve_zone_by_position("m10_01_00_00", 0.0, 0.0, 0.0)
    assert zone is None


def test_resolve_zone_by_position_default_fallback():
    """Position not matching any conditional rule falls back to default area."""
    # Academy m14_00_00_00: default is academy_entrance (lowest)
    # Very low Y doesn't match any rule
    zone = resolve_zone_by_position("m14_00_00_00", 0.0, -100.0, 0.0)
    assert zone == "academy_entrance"


def test_resolve_zone_by_position_academy_library():
    """High Y in academy resolves to academy_library (Rennala)."""
    # YAbove: 140
    zone = resolve_zone_by_position("m14_00_00_00", 0.0, 150.0, 0.0)
    assert zone == "academy_library"


def test_resolve_zone_by_position_unknown_map():
    """Unknown map returns None."""
    zone = resolve_zone_by_position("m99_99_99_99", 0.0, 0.0, 0.0)
    assert zone is None
