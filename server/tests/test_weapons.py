"""Unit tests for the equipped-weapons filter."""

from speedfog_racing.services.weapons import (
    BASE_ROW_MODULUS,
    EXCLUDED_WEP_TYPES,
    WEAPONS,
    bump_combo,
    filter_equipped,
)


def test_catalogue_loaded() -> None:
    """weapons.json is reachable from the package and parses to a non-trivial mapping."""
    # If this assert ever needs updating because we refreshed weapons.json, that is
    # fine: the point is to catch an empty / broken load, not pin the exact count.
    assert len(WEAPONS) > 400
    longsword = WEAPONS.get(2000000)
    assert longsword is not None
    assert longsword.name == "Longsword"
    assert longsword.wep_type == 3


def test_catalogue_keys_are_base_rows() -> None:
    # filter_equipped strips raw_id % BASE_ROW_MODULUS, so every catalogue key
    # must be a multiple of it or that weapon could never be resolved.
    assert all(base_id % BASE_ROW_MODULUS == 0 for base_id in WEAPONS)


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
    # actually present in the JSON. We resolve IDs at test time so the test does not
    # break if the catalogue's first row of a given type changes.
    seen_types: set[int] = set()
    for raw_id, info in WEAPONS.items():
        if info.wep_type in EXCLUDED_WEP_TYPES and info.wep_type not in seen_types:
            assert filter_equipped(raw_id) is None, f"{info.name} ({raw_id}) leaked"
            seen_types.add(info.wep_type)
    assert seen_types == EXCLUDED_WEP_TYPES


def test_filter_unknown_id_returns_none() -> None:
    assert filter_equipped(99_999_900) is None


def test_filter_unarmed_returns_none() -> None:
    # 110000 = Unarmed per libeldenring param_names.json. Not in weapons.json.
    assert filter_equipped(110000) is None


def test_filter_handles_none_zero_negative() -> None:
    assert filter_equipped(None) is None
    assert filter_equipped(0) is None
    assert filter_equipped(-1) is None


def test_bump_combo_appends_single_weapon_when_list_empty() -> None:
    out = bump_combo([], None, 2000025)
    assert out == [{"ids": [2000025], "ticks": 1}]


def test_bump_combo_increments_existing_single_weapon() -> None:
    initial = [{"ids": [2000025], "ticks": 3}]
    out = bump_combo(initial, None, 2000025)
    assert out == [{"ids": [2000025], "ticks": 4}]


def test_bump_combo_single_weapon_canonicalisation_left_then_right() -> None:
    # (None, X) and (X, None) increment the same {ids: [X]} entry.
    state = bump_combo([], None, 2000025)
    state = bump_combo(state, 2000025, None)
    state = bump_combo(state, None, 2000025)
    assert state == [{"ids": [2000025], "ticks": 3}]


def test_bump_combo_dual_preserves_mod_order() -> None:
    out = bump_combo([], 3070000, 2000025)
    assert out == [{"ids": [3070000, 2000025], "ticks": 1}]


def test_bump_combo_dual_swapped_hands_is_a_distinct_combo() -> None:
    # [X, Y] and [Y, X] must NOT merge: this anti-test catches accidental sorting.
    state = bump_combo([], 3070000, 2000025)
    state = bump_combo(state, 2000025, 3070000)
    assert state == [
        {"ids": [3070000, 2000025], "ticks": 1},
        {"ids": [2000025, 3070000], "ticks": 1},
    ]


def test_bump_combo_appends_new_combo_alongside_existing() -> None:
    initial = [{"ids": [2000025], "ticks": 5}]
    out = bump_combo(initial, 3070000, 2000025)
    assert out == [
        {"ids": [2000025], "ticks": 5},
        {"ids": [3070000, 2000025], "ticks": 1},
    ]


def test_bump_combo_returns_unchanged_when_both_none() -> None:
    # Caller is expected to skip before calling, but the helper should be safe.
    initial = [{"ids": [2000025], "ticks": 3}]
    out = bump_combo(initial, None, None)
    assert out == initial


def test_filter_preserves_affinity_and_upgrade_for_known_weapon() -> None:
    # 23150925 = Rotten Greataxe (base 23150000) + Cold affinity (9 * 100) + +25.
    # Must resolve via modulo 10000 to the base row and be kept (wep_type=41).
    assert filter_equipped(23150925) == 23150925


def test_filter_keeps_affinities_above_cold() -> None:
    # Poison, Blood and Occult are affinity indexes 10..12, so they occupy the
    # thousands digit: 1001205 = Dagger (1000000) + Occult (12 * 100) + 5.
    assert filter_equipped(1001000) == 1001000  # Poison Dagger
    assert filter_equipped(1001125) == 1001125  # Blood Dagger +25
    assert filter_equipped(1001205) == 1001205  # Occult Dagger +5


def test_filter_keeps_affinity_only_no_upgrade() -> None:
    # 23150900 = Rotten Greataxe + Cold + 0.
    assert filter_equipped(23150900) == 23150900
