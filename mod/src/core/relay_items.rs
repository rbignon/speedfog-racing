//! Item union rules of a relay handoff: from the giver's raw item ids, which
//! are transferable, which the receiver lacks, and how a built state is
//! fitted to the wire. Pure: the one game parameter needed
//! (`EquipParamGoods.goods_type`) is an input, never read here.
//!
//! A weapon id is only checked for its shape (not ammunition, not bare
//! hands, upgrade level at most 25): this module cannot tell a somber weapon
//! (at most +10) from a standard one (+25), nor whether the id has a row in
//! the weapon param table. The shell validates that an id exists in its
//! param table before injecting it.
//!
//! The receiver filters the giver's list again with the same rules, so a
//! state from a tampered or newer teammate cannot make it inject anything
//! not recognisably transferable.

use std::collections::{HashMap, HashSet};

use super::item_inventory::category_nibble;
use super::protocol::CharacterState;

/// Most items a `relay_state` may carry (server cap, beyond which it drops
/// the whole message).
pub const MAX_STATE_ITEMS: usize = 4000;
/// Most grace flags a `relay_state` may carry.
pub const MAX_STATE_GRACES: usize = 1000;
/// Largest integer of a `relay_state` attribute, level, runes or grace flag.
pub const MAX_STATE_INT: u32 = 2_147_483_647;

const MAX_ATTRIBUTE: u32 = 99;
const MAX_LEVEL: u32 = 713;
const MAX_RUNES: u32 = 999_999_999;
/// A character's level is the sum of its attributes minus this.
const LEVEL_OFFSET: u64 = 79;

/// Mask of the param id under the category nibble.
const PARAM_MASK: u32 = 0x0FFF_FFFF;
/// Weapon id layout (base, affinity, upgrade level): see `same_weapon` in
/// `item_inventory`.
const WEAPON_BASE_DIV: u32 = 10_000;
const WEAPON_LEVEL_DIV: u32 = 100;
/// Highest upgrade level of any weapon (standard ones; somber stop at 10).
const MAX_WEAPON_LEVEL: u32 = 25;
/// Ammunition and other stackable weapons: ids in this range.
const AMMO_RANGE: std::ops::Range<u32> = 50_000_000..54_000_000;
/// Bare hands, the weapon base `110000` at every affinity and level.
const BARE_HANDS_BASE: u32 = 11;
/// The naked protectors the game wears when nothing is equipped.
const NAKED_ARMOR: [u32; 4] = [10_000, 10_100, 10_200, 10_300];
/// `EquipParamGoods.goods_type` values that transfer: 5 and 17 sorceries,
/// 16 and 18 incantations, 7 and 8 spirit ashes, 10 crystal tears.
const GOODS_TYPES: [u8; 7] = [5, 7, 8, 10, 16, 17, 18];

fn is_weapon(item_id: u32) -> bool {
    category_nibble(item_id) == 0x0
}

fn weapon_base(item_id: u32) -> u32 {
    item_id / WEAPON_BASE_DIV
}

/// Whether `item_id` may be handed over. `goods_type` is the goods param's
/// type for a goods id (`None` when the row is missing: not transferable);
/// it is ignored for every other category.
pub fn is_transferable(item_id: u32, goods_type: Option<u8>) -> bool {
    match category_nibble(item_id) {
        0x0 => {
            item_id != 0
                && !AMMO_RANGE.contains(&item_id)
                && weapon_base(item_id) != BARE_HANDS_BASE
                && item_id % WEAPON_LEVEL_DIV <= MAX_WEAPON_LEVEL
        }
        0x1 => !NAKED_ARMOR.contains(&(item_id & PARAM_MASK)),
        0x2 | 0x8 => true,
        0x4 => goods_type.is_some_and(|ty| GOODS_TYPES.contains(&ty)),
        _ => false,
    }
}

/// Whether `item_id` passes `is_transferable`, asking `goods_type` (the goods
/// param id, without the nibble) only for a goods id.
fn passes(item_id: u32, goods_type: &impl Fn(u32) -> Option<u8>) -> bool {
    let ty = (category_nibble(item_id) == 0x4)
        .then(|| goods_type(item_id & PARAM_MASK))
        .flatten();
    is_transferable(item_id, ty)
}

/// The transferable ids among `held`, sorted, each once.
pub fn transferable_items(
    held: impl Iterator<Item = u32>,
    goods_type: impl Fn(u32) -> Option<u8>,
) -> Vec<u32> {
    let mut items: Vec<u32> = held.filter(|&id| passes(id, &goods_type)).collect();
    items.sort_unstable();
    items.dedup();
    items
}

/// The ids to inject, sorted, with their nibble: what `giver` carries that
/// passes `is_transferable` and `own` lacks. A weapon is lacking when `own`
/// holds no weapon of the same base (`id / 10000`) at any affinity or level;
/// it is given bare (no affinity) at the highest level among the giver's
/// copies of that base. Any other item is lacking when its exact id is
/// absent.
pub fn missing_items(
    giver: &[u32],
    own: &[u32],
    goods_type: impl Fn(u32) -> Option<u8>,
) -> Vec<u32> {
    let own_ids: HashSet<u32> = own.iter().copied().collect();
    let own_bases: HashSet<u32> = own
        .iter()
        .copied()
        .filter(|&id| is_weapon(id))
        .map(weapon_base)
        .collect();
    let mut best_level: HashMap<u32, u32> = HashMap::new();
    let mut missing = Vec::new();
    for &id in giver {
        if !passes(id, &goods_type) {
            continue;
        }
        if is_weapon(id) {
            let base = weapon_base(id);
            if !own_bases.contains(&base) {
                let level = id % WEAPON_LEVEL_DIV;
                let best = best_level.entry(base).or_insert(level);
                *best = (*best).max(level);
            }
        } else if !own_ids.contains(&id) {
            missing.push(id);
        }
    }
    missing.extend(
        best_level
            .into_iter()
            .map(|(base, level)| base * WEAPON_BASE_DIV + level),
    );
    missing.sort_unstable();
    missing.dedup();
    missing
}

/// Whether the stats of a state are within what a character can have: every
/// attribute in 1 to 99, level in 1 to 713 and equal to the sum of the eight
/// attributes minus 79 (the game's rule: 713 = 8 * 99 - 79), runes at most
/// 999999999. A state outside it is not written (the take still completes).
pub fn stats_plausible(state: &CharacterState) -> bool {
    state
        .attributes
        .iter()
        .all(|a| (1..=MAX_ATTRIBUTE).contains(a))
        && (1..=MAX_LEVEL).contains(&state.level)
        && state.attributes.iter().map(|&a| u64::from(a)).sum::<u64>()
            == u64::from(state.level) + LEVEL_OFFSET
        && state.runes <= MAX_RUNES
}

/// Fits `state` to the server's wire caps: drops grace flags above
/// `MAX_STATE_INT`, sorts and dedups both lists, keeps the first
/// `MAX_STATE_ITEMS` items and `MAX_STATE_GRACES` grace flags. Returns how
/// many values it dropped or cut (duplicates excluded), for the caller to
/// warn about. Sorted order makes what is kept independent of memory order
/// and keeps weapons, armor and talismans ahead of goods and gems.
/// Precondition: attributes, level and runes are not checked against the
/// wire maximum; the caller builds them from non-negative `i32` reads.
pub fn fit_to_wire(state: &mut CharacterState) -> usize {
    let mut dropped = 0;
    let graces_before = state.grace_flags.len();
    state.grace_flags.retain(|&flag| flag <= MAX_STATE_INT);
    dropped += graces_before - state.grace_flags.len();
    for (list, cap) in [
        (&mut state.items, MAX_STATE_ITEMS),
        (&mut state.grace_flags, MAX_STATE_GRACES),
    ] {
        list.sort_unstable();
        list.dedup();
        if list.len() > cap {
            dropped += list.len() - cap;
            list.truncate(cap);
        }
    }
    dropped
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::protocol::CharacterState;

    const ARMOR: u32 = 0x1000_0000;
    const TALISMAN: u32 = 0x2000_0000;
    const GOODS: u32 = 0x4000_0000;
    const GEM: u32 = 0x8000_0000;

    fn no_goods(_: u32) -> Option<u8> {
        None
    }

    fn state() -> CharacterState {
        CharacterState {
            attributes: [40, 20, 30, 18, 16, 9, 7, 12],
            level: 73,
            runes: 12_345,
            items: vec![2_000_005, TALISMAN | 1000],
            grace_flags: vec![76_100, 76_101],
        }
    }

    #[test]
    fn weapons_are_compared_without_level_or_affinity_and_given_bare() {
        // Longsword: Heavy +7 and a plain +3 on the giver.
        let giver = [2_000_107, 2_000_003];
        assert_eq!(missing_items(&giver, &[], no_goods), vec![2_000_007]);
        // Owned Keen +0: nothing given, the lower level is not replaced.
        assert_eq!(
            missing_items(&giver, &[2_000_200], no_goods),
            Vec::<u32>::new()
        );
        // Another base is another weapon.
        assert_eq!(
            missing_items(&giver, &[2_010_000], no_goods),
            vec![2_000_007]
        );
        // An owned id of another category with the same low digits is not it.
        assert_eq!(
            missing_items(&giver, &[TALISMAN | 2_000_000], no_goods),
            vec![2_000_007]
        );
    }

    #[test]
    fn ammunition_bare_hands_and_naked_armor_do_not_transfer() {
        for id in [
            50_000_000,
            53_990_000,
            110_000,
            110_105,
            ARMOR | 10_000,
            ARMOR | 10_300,
            0,
        ] {
            assert!(!is_transferable(id, None), "{id:#x}");
        }
        for id in [
            2_000_000,
            49_990_000,
            54_000_000,
            60_500_000,
            ARMOR | 40_000,
        ] {
            assert!(is_transferable(id, None), "{id:#x}");
        }
    }

    #[test]
    fn goods_transfer_by_type() {
        for (ty, want) in [
            (5, true),
            (16, true),
            (17, true),
            (18, true),
            (7, true),
            (8, true),
            (10, true),
            (0, false),
            (1, false),
            (2, false),
            (9, false),
            (11, false),
            (14, false),
            (15, false),
            (255, false),
        ] {
            assert_eq!(is_transferable(GOODS | 4000, Some(ty)), want, "type {ty}");
        }
        assert!(!is_transferable(GOODS | 4000, None));
    }

    #[test]
    fn other_categories_never_transfer() {
        // 0x3 (accessory-like unknowns), 0x5, 0xF and the empty marker.
        for id in [0x3000_0001, 0x5000_0001, 0xC000_0001, u32::MAX] {
            assert!(!is_transferable(id, Some(5)), "{id:#x}");
        }
    }

    #[test]
    fn a_foreign_state_is_filtered_on_the_receiver() {
        let goods = |id: u32| match id {
            130 => Some(1),
            4000 => Some(5),
            _ => None,
        };
        let giver = [
            GOODS | 130,
            GOODS | 4000,
            0x3000_0001,
            50_000_000,
            TALISMAN | 1000,
            GEM | 10_000,
        ];
        assert_eq!(
            missing_items(&giver, &[TALISMAN | 1000], goods),
            vec![GOODS | 4000, GEM | 10_000]
        );
    }

    #[test]
    fn the_goods_lookup_takes_the_param_id_without_the_nibble() {
        let seen = std::cell::RefCell::new(Vec::new());
        let lookup = |id: u32| {
            seen.borrow_mut().push(id);
            Some(5)
        };
        assert_eq!(
            missing_items(&[GOODS | 4000, TALISMAN | 7], &[], lookup),
            vec![TALISMAN | 7, GOODS | 4000]
        );
        assert_eq!(*seen.borrow(), vec![4000]);
    }

    #[test]
    fn the_receiver_holding_everything_lacks_nothing() {
        let giver = [ARMOR | 40_000, TALISMAN | 1, GEM | 9, 2_000_105];
        let own = [2_000_000, GEM | 9, TALISMAN | 1, ARMOR | 40_000];
        assert!(missing_items(&giver, &own, no_goods).is_empty());
        assert!(missing_items(&[], &own, no_goods).is_empty());
        assert!(missing_items(&[], &[], no_goods).is_empty());
    }

    #[test]
    fn transferable_items_lists_each_once() {
        let goods = |id: u32| (id == 100).then_some(0);
        let held = [2_000_005, 2_000_005, GOODS | 100, GEM | 10_000];
        assert_eq!(
            transferable_items(held.into_iter(), goods),
            vec![2_000_005, GEM | 10_000]
        );
        assert!(transferable_items(std::iter::empty(), no_goods).is_empty());
    }

    /// `state()` with these attributes and the level they imply.
    fn with_attributes(attributes: [u32; 8]) -> CharacterState {
        let level = attributes.iter().sum::<u32>().saturating_sub(79);
        CharacterState {
            attributes,
            level,
            ..state()
        }
    }

    #[test]
    fn stats_plausible_bounds() {
        assert!(stats_plausible(&state()));
        for idx in 0..8 {
            for (value, want) in [(0, false), (1, true), (99, true), (100, false)] {
                let mut attributes = state().attributes;
                attributes[idx] = value;
                assert_eq!(
                    stats_plausible(&with_attributes(attributes)),
                    want,
                    "attribute {idx} = {value}"
                );
            }
        }
        // Level bounds, each level consistent with its attributes.
        assert!(stats_plausible(&with_attributes([99; 8])), "level 713");
        assert!(
            stats_plausible(&with_attributes([10, 10, 10, 10, 10, 10, 10, 10])),
            "level 1"
        );
        assert!(
            !stats_plausible(&with_attributes([10, 10, 10, 10, 10, 10, 10, 9])),
            "level 0"
        );
        for (value, want) in [
            (0, true),
            (999_999_999, true),
            (1_000_000_000, false),
            (u32::MAX, false),
        ] {
            let mut s = state();
            s.runes = value;
            assert_eq!(stats_plausible(&s), want, "runes {value}");
        }
    }

    #[test]
    fn the_level_must_match_the_attributes() {
        let mut s = state();
        assert_eq!(s.attributes.iter().sum::<u32>() - 79, s.level);
        assert!(stats_plausible(&s));
        s.level += 1;
        assert!(!stats_plausible(&s));
        s.level -= 2;
        assert!(!stats_plausible(&s));
        // Past the maximum level.
        s.level = 714;
        assert!(!stats_plausible(&s));
    }

    #[test]
    fn a_tampered_weapon_level_is_not_given() {
        // +99 beside +7 of the same base: the +7 wins, the +99 never counts.
        assert_eq!(
            missing_items(&[2_000_099, 2_000_007], &[], no_goods),
            vec![2_000_007]
        );
        assert!(missing_items(&[2_000_026], &[], no_goods).is_empty());
        assert_eq!(missing_items(&[2_000_025], &[], no_goods), vec![2_000_025]);
        assert!(!is_transferable(2_000_126, None));
        assert!(is_transferable(2_000_125, None));
    }

    #[test]
    fn a_weapon_held_at_another_affinity_or_level_only_is_not_given() {
        // Same base, other affinity, same level.
        assert!(missing_items(&[2_000_005], &[2_000_105], no_goods).is_empty());
        // Same base, same affinity, other level.
        assert!(missing_items(&[2_000_105], &[2_000_103], no_goods).is_empty());
        assert!(missing_items(&[2_000_105], &[2_000_110], no_goods).is_empty());
    }

    #[test]
    fn duplicates_are_removed_before_the_cap_is_applied() {
        // 4001 values of which 2 repeat: 3999 distinct, nothing cut.
        let mut s = state();
        s.items = (1..=3999).collect();
        s.items.extend([1, 2]);
        assert_eq!(s.items.len(), MAX_STATE_ITEMS + 1);
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.items.len(), 3999);
    }

    #[test]
    fn a_state_is_fitted_to_the_wire_caps() {
        // Unchanged when already within bounds.
        let mut s = state();
        let before = s.clone();
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s, before);

        // Exactly the cap: nothing cut. One over: the highest id goes.
        let mut s = state();
        s.items = (0..MAX_STATE_ITEMS as u32).rev().map(|i| i + 1).collect();
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.items.len(), MAX_STATE_ITEMS);
        let mut s = state();
        s.items = (1..=MAX_STATE_ITEMS as u32 + 1).rev().collect();
        assert_eq!(fit_to_wire(&mut s), 1);
        assert_eq!(s.items, (1..=MAX_STATE_ITEMS as u32).collect::<Vec<_>>());

        let mut s = state();
        s.grace_flags = (1..=MAX_STATE_GRACES as u32).collect();
        assert_eq!(fit_to_wire(&mut s), 0);
        s.grace_flags.push(MAX_STATE_GRACES as u32 + 1);
        assert_eq!(fit_to_wire(&mut s), 1);
        assert_eq!(s.grace_flags.len(), MAX_STATE_GRACES);
        assert_eq!(s.grace_flags.last(), Some(&(MAX_STATE_GRACES as u32)));

        // A grace flag past the wire integer is dropped, the bound kept.
        let mut s = state();
        s.grace_flags = vec![2_147_483_648, 2_147_483_647, u32::MAX];
        assert_eq!(fit_to_wire(&mut s), 2);
        assert_eq!(s.grace_flags, vec![2_147_483_647]);

        // Duplicates collapse without counting.
        let mut s = state();
        s.items = vec![5, 3, 5, 3, 4];
        s.grace_flags = vec![9, 9, 8];
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.items, vec![3, 4, 5]);
        assert_eq!(s.grace_flags, vec![8, 9]);
    }

    #[test]
    fn the_items_kept_do_not_depend_on_the_input_order() {
        let ids: Vec<u32> = (0..MAX_STATE_ITEMS as u32 + 50)
            .map(|i| i.wrapping_mul(2_654_435_761))
            .collect();
        let ids_sorted = ids.clone();
        let mut a = state();
        a.items = ids.clone();
        let mut b = state();
        b.items = ids.into_iter().rev().collect();
        assert_eq!(fit_to_wire(&mut a), 50);
        assert_eq!(fit_to_wire(&mut b), 50);
        assert_eq!(a.items, b.items);
        // What is dropped is the 50 highest ids.
        let mut sorted = ids_sorted;
        sorted.sort_unstable();
        assert_eq!(a.items, sorted[..MAX_STATE_ITEMS]);
    }
}
