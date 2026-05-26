"""Unit tests for the equipped-weapons filter."""

from speedfog_racing.services.weapons import (
    EXCLUDED_WEP_TYPES,
    WEAPONS,
    filter_equipped,
)


def test_csv_loaded() -> None:
    """The CSV is reachable from the package and parses to a non-trivial mapping."""
    # If this assert ever needs updating because we refreshed weapons.csv, that is
    # fine: the point is to catch an empty / broken load, not pin the exact count.
    assert len(WEAPONS) > 400
    longsword = WEAPONS.get(2000000)
    assert longsword is not None
    assert longsword.name == "Longsword"
    assert longsword.wep_type == 3


def test_filter_keeps_known_weapon_at_zero_upgrade() -> None:
    assert filter_equipped(2000000) == 2000000


def test_filter_preserves_upgrade_level_in_returned_id() -> None:
    # Longsword +25 is the runtime ID; the base row is 2000000, but we return raw.
    assert filter_equipped(2000025) == 2000025


def test_filter_rejects_staff() -> None:
    # Academy Glintstone Staff: wep_type=57 (Staff)
    assert filter_equipped(33200000) is None


def test_filter_rejects_shield_and_torch() -> None:
    # Verify the filter rejects representative entries for each excluded category
    # actually present in the CSV. We resolve IDs at test time so the test does not
    # break if the CSV snapshot's first row of a given type changes.
    seen_types: set[int] = set()
    for raw_id, info in WEAPONS.items():
        if info.wep_type in EXCLUDED_WEP_TYPES and info.wep_type not in seen_types:
            assert filter_equipped(raw_id) is None, f"{info.name} ({raw_id}) leaked"
            seen_types.add(info.wep_type)
    assert seen_types == EXCLUDED_WEP_TYPES


def test_filter_unknown_id_returns_none() -> None:
    assert filter_equipped(99_999_900) is None


def test_filter_unarmed_returns_none() -> None:
    # 110000 = Unarmed per libeldenring param_names.json. Not in weapons.csv.
    assert filter_equipped(110000) is None


def test_filter_handles_none_zero_negative() -> None:
    assert filter_equipped(None) is None
    assert filter_equipped(0) is None
    assert filter_equipped(-1) is None
