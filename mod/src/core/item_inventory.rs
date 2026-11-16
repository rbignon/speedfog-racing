//! Race item inventory scan: how many of one item a block of the game's
//! inventory entries holds, and which entry a give added. The shell copies a
//! whole entry list out of game memory in one read, then hands the bytes
//! here. Also the Junk Weapon's choice of slot.
//!
//! Entry layout derived from fromsoftware-rs `cs/player_game_data.rs`
//! (`EquipInventoryDataListEntry`): `gaitem_handle` u32, `item_id` u32,
//! `quantity` u32, `sort_id` u32, `is_new` bool (padded), `pot_group` i32,
//! 0x18 bytes in all. The TGA Cheat Engine table v1.17.0 (inventory list
//! script) walks the entries with the same stride, id and quantity offsets.
//! Unverified by this mod in game until the Windows check.

use tracing::warn;

/// Size of one inventory entry.
pub const ENTRY_SIZE: usize = 0x18;
/// Gaitem handle, little-endian u32: each weapon instance gets its own.
const ENTRY_HANDLE_OFFSET: usize = 0x0;
/// Item id (category flag | param id), little-endian u32.
const ENTRY_ITEM_ID_OFFSET: usize = 0x4;
/// Quantity held, little-endian u32.
const ENTRY_QUANTITY_OFFSET: usize = 0x8;
/// Acquisition order, little-endian u32.
const ENTRY_SORT_ID_OFFSET: usize = 0xC;

/// Most entries a list may claim before its header reads as layout drift.
/// The game's held lists are far shorter (2688 normal items, 384 key items
/// in the TGA table's `getInvData`), so this only bounds a read through
/// misread offsets.
pub const MAX_LIST_ENTRIES: u32 = 0x2000;

/// How many entries of a list to read: its whole allocation (`capacity`).
/// A removed item leaves a gap, so the items need not sit below `len` (the
/// TGA script also walks the whole capacity), and an empty entry never
/// matches an item id. `None` when the header is implausible, a sign the
/// offsets no longer match the game: nothing allocated (the held lists
/// always are, so a zeroed header is misread memory, which must not pass
/// for an empty inventory and report every item lost), more in use than
/// allocated, or more allocated than any held list.
pub fn list_entry_count(capacity: u32, len: u32) -> Option<usize> {
    (capacity > 0 && len <= capacity && capacity <= MAX_LIST_ENTRIES).then_some(capacity as usize)
}

/// Whether the in-use counts of the normal and key lists can be a loaded
/// character's. A loaded character always holds items (its flasks), so two
/// empty lists are lists allocated but not filled yet, which must not pass
/// for an empty inventory either.
pub fn lists_hold_items(normal_len: u32, key_len: u32) -> bool {
    normal_len > 0 || key_len > 0
}

/// The little-endian u32 at `offset` of a whole entry.
fn field(entry: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        entry[offset],
        entry[offset + 1],
        entry[offset + 2],
        entry[offset + 3],
    ])
}

/// The whole entries of `entries` holding `item_id`, with their position
/// (a trailing partial entry is ignored).
fn entries_of(entries: &[u8], item_id: u32) -> impl Iterator<Item = (usize, &[u8])> {
    entries
        .chunks_exact(ENTRY_SIZE)
        .enumerate()
        .filter(move |(_, entry)| field(entry, ENTRY_ITEM_ID_OFFSET) == item_id)
}

/// Total quantity of `item_id` over the whole entries in `entries`
/// (a trailing partial entry is ignored).
pub fn quantity_in_entries(entries: &[u8], item_id: u32) -> u32 {
    entries_of(entries, item_id).fold(0u32, |total, (_, entry)| {
        total.saturating_add(field(entry, ENTRY_QUANTITY_OFFSET))
    })
}

/// The gaitem handles of the entries holding `item_id`, read before a give:
/// what `new_copy` tells the new entry from.
pub fn handles_of(entries: &[u8], item_id: u32) -> Vec<u32> {
    entries_of(entries, item_id)
        .map(|(_, entry)| field(entry, ENTRY_HANDLE_OFFSET))
        .collect()
}

/// The entry a give of `item_id` added, from the entries read after it:
/// its position in `entries` and its gaitem handle. `before` holds the
/// handles of that item's entries before the give (`handles_of`): a weapon
/// never stacks, each instance has its own entry and handle, so the new one
/// is the entry whose handle is not there. Not the first entry of the id
/// (the game's own lookup): that may be the runner's own copy, with its Ash
/// of War, maybe equipped elsewhere; nor the last one, since a new item may
/// fill the gap a removed one left. Several new ones (logged) give the last
/// acquired (highest `sort_id`); none, `None` (nothing added: the
/// inventory was full).
pub fn new_copy(before: &[u32], entries: &[u8], item_id: u32) -> Option<(usize, u32)> {
    let new: Vec<(usize, u32, u32)> = entries_of(entries, item_id)
        .map(|(position, entry)| {
            (
                position,
                field(entry, ENTRY_HANDLE_OFFSET),
                field(entry, ENTRY_SORT_ID_OFFSET),
            )
        })
        .filter(|(_, handle, _)| !before.contains(handle))
        .collect();
    if new.len() > 1 {
        warn!(
            item_id,
            count = new.len(),
            "[ITEMS] Several new copies of a given item, the last acquired taken"
        );
    }
    new.into_iter()
        .max_by_key(|&(_, _, sort_id)| sort_id)
        .map(|(position, handle, _)| (position, handle))
}

/// Number of right weapon slots (ChrAsm keeps three per hand).
const WEAPON_SLOTS: u32 = 3;

/// The ChrAsm equipment slot of the right weapon in hand: the slots go left
/// then right for each of the three, so right `n` (0 to 2, PlayerGameData's
/// `right_weapon_slot`) is `1 + 2 * n`. Any other value is misread memory:
/// the first right slot.
pub fn junk_slot(right_weapon_slot: u32) -> usize {
    let slot = if right_weapon_slot < WEAPON_SLOTS {
        right_weapon_slot
    } else {
        0
    };
    1 + 2 * slot as usize
}

/// Whether the right hand already holds `weapon_id`, that exact weapon
/// (same upgrade and affinity): forcing it in would change nothing.
pub fn junk_is_free(held_param_id: i32, weapon_id: u32) -> bool {
    u32::try_from(held_param_id) == Ok(weapon_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOODS: u32 = 0x4000_0000 | 2900;

    /// Entries with the given `(item_id, quantity)`, other fields filled
    /// with a marker so a misaligned read cannot pass for a match.
    fn entries(items: &[(u32, u32)]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for &(item_id, quantity) in items {
            let mut entry = [0xA5u8; ENTRY_SIZE];
            entry[ENTRY_ITEM_ID_OFFSET..ENTRY_ITEM_ID_OFFSET + 4]
                .copy_from_slice(&item_id.to_le_bytes());
            entry[ENTRY_QUANTITY_OFFSET..ENTRY_QUANTITY_OFFSET + 4]
                .copy_from_slice(&quantity.to_le_bytes());
            bytes.extend_from_slice(&entry);
        }
        bytes
    }

    #[test]
    fn finds_the_item_past_other_entries() {
        let list = entries(&[(u32::MAX, 0), (0x4000_0000 | 100, 7), (GOODS, 2)]);
        assert_eq!(quantity_in_entries(&list, GOODS), 2);
    }

    #[test]
    fn absent_item_holds_zero() {
        let list = entries(&[(0x4000_0000 | 100, 7), (u32::MAX, 0)]);
        assert_eq!(quantity_in_entries(&list, GOODS), 0);
        assert_eq!(quantity_in_entries(&[], GOODS), 0);
    }

    #[test]
    fn same_param_in_another_category_does_not_count() {
        // 0x8000_0000 | 2900 is a gem with the same param id.
        let list = entries(&[(0x8000_0000 | 2900, 1)]);
        assert_eq!(quantity_in_entries(&list, GOODS), 0);
    }

    #[test]
    fn stacks_add_up() {
        let list = entries(&[(GOODS, 1), (0x4000_0000 | 100, 7), (GOODS, 2)]);
        assert_eq!(quantity_in_entries(&list, GOODS), 3);
    }

    #[test]
    fn trailing_partial_entry_is_ignored() {
        let mut list = entries(&[(GOODS, 1)]);
        let partial = entries(&[(GOODS, 5)]);
        list.extend_from_slice(&partial[..ENTRY_SIZE - 1]);
        assert_eq!(quantity_in_entries(&list, GOODS), 1);
    }

    const CLUB: u32 = 11_010_000;

    /// Weapon entries with the given `(handle, item_id, sort_id)`, quantity
    /// 1, the other bytes a marker.
    fn weapons(items: &[(u32, u32, u32)]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for &(handle, item_id, sort_id) in items {
            let mut entry = [0xA5u8; ENTRY_SIZE];
            entry[ENTRY_HANDLE_OFFSET..ENTRY_HANDLE_OFFSET + 4]
                .copy_from_slice(&handle.to_le_bytes());
            entry[ENTRY_ITEM_ID_OFFSET..ENTRY_ITEM_ID_OFFSET + 4]
                .copy_from_slice(&item_id.to_le_bytes());
            entry[ENTRY_QUANTITY_OFFSET..ENTRY_QUANTITY_OFFSET + 4]
                .copy_from_slice(&1u32.to_le_bytes());
            entry[ENTRY_SORT_ID_OFFSET..ENTRY_SORT_ID_OFFSET + 4]
                .copy_from_slice(&sort_id.to_le_bytes());
            bytes.extend_from_slice(&entry);
        }
        bytes
    }

    #[test]
    fn the_new_copy_is_not_one_the_runner_had() {
        // The runner's own Club (with its Ash of War) sits first: the game's
        // first match would pick it.
        let before = weapons(&[(0x8080_0001, CLUB, 10), (0x8080_0002, 0x0010_0000, 11)]);
        let handles = handles_of(&before, CLUB);
        assert_eq!(handles, [0x8080_0001]);
        // The give filled a gap the game left after a removed item.
        let after = weapons(&[
            (0x8080_0001, CLUB, 10),
            (0x8080_0003, CLUB, 12),
            (0x8080_0002, 0x0010_0000, 11),
        ]);
        assert_eq!(new_copy(&handles, &after, CLUB), Some((1, 0x8080_0003)));
    }

    #[test]
    fn two_new_copies_give_the_last_acquired() {
        let after = weapons(&[
            (0x8080_0005, CLUB, 21),
            (0x8080_0004, CLUB, 20),
            (0x8080_0001, CLUB, 10),
        ]);
        assert_eq!(
            new_copy(&[0x8080_0001], &after, CLUB),
            Some((0, 0x8080_0005))
        );
    }

    #[test]
    fn nothing_added_gives_no_copy() {
        // Inventory full: the give put nothing in the held list.
        let list = weapons(&[(0x8080_0001, CLUB, 10), (u32::MAX, u32::MAX, 0)]);
        assert_eq!(new_copy(&handles_of(&list, CLUB), &list, CLUB), None);
        assert_eq!(new_copy(&[], &[], CLUB), None);
    }

    #[test]
    fn the_junk_goes_to_the_right_slot_in_hand() {
        // ChrAsm slots: left then right, three of each.
        assert_eq!(junk_slot(0), 1);
        assert_eq!(junk_slot(1), 3);
        assert_eq!(junk_slot(2), 5);
        // A value the game never holds there is misread memory: slot 1.
        assert_eq!(junk_slot(3), 1);
        assert_eq!(junk_slot(u32::MAX), 1);
    }

    #[test]
    fn a_hand_holding_that_junk_already_is_free() {
        assert!(junk_is_free(11_010_000, CLUB));
        // Another upgrade or affinity of it is another weapon.
        assert!(!junk_is_free(11_010_003, CLUB));
        assert!(!junk_is_free(11_010_100, CLUB));
        // A slot read as -1 holds no weapon.
        assert!(!junk_is_free(-1, CLUB));
    }

    #[test]
    fn two_empty_lists_are_no_loaded_inventory() {
        // Allocated but not filled yet: a loaded character holds its flasks.
        assert!(!lists_hold_items(0, 0));
        assert!(lists_hold_items(12, 0));
        assert!(lists_hold_items(0, 3));
    }

    #[test]
    fn implausible_list_headers_are_rejected() {
        assert_eq!(list_entry_count(0xA80, 12), Some(0xA80));
        assert_eq!(list_entry_count(0xA80, 0), Some(0xA80));
        // Zeroed memory: no allocated list, not an empty inventory.
        assert_eq!(list_entry_count(0, 0), None);
        assert_eq!(list_entry_count(4, 5), None);
        assert_eq!(list_entry_count(MAX_LIST_ENTRIES + 1, 0), None);
    }
}
