//! Race item inventory scan: how many of one item a block of the game's
//! inventory entries holds. The shell copies a whole entry list out of game
//! memory in one read, then hands the bytes here.
//!
//! Entry layout derived from fromsoftware-rs `cs/player_game_data.rs`
//! (`EquipInventoryDataListEntry`): `gaitem_handle` u32, `item_id` u32,
//! `quantity` u32, `sort_id` u32, `is_new` bool (padded), `pot_group` i32,
//! 0x18 bytes in all. The TGA Cheat Engine table v1.17.0 (inventory list
//! script) walks the entries with the same stride, id and quantity offsets.
//! Unverified by this mod in game until the Windows check.

/// Size of one inventory entry.
pub const ENTRY_SIZE: usize = 0x18;
/// Item id (category flag | param id), little-endian u32.
const ENTRY_ITEM_ID_OFFSET: usize = 0x4;
/// Quantity held, little-endian u32.
const ENTRY_QUANTITY_OFFSET: usize = 0x8;

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

/// Total quantity of `item_id` over the whole entries in `entries`
/// (a trailing partial entry is ignored).
pub fn quantity_in_entries(entries: &[u8], item_id: u32) -> u32 {
    let field = |entry: &[u8], offset: usize| {
        u32::from_le_bytes([
            entry[offset],
            entry[offset + 1],
            entry[offset + 2],
            entry[offset + 3],
        ])
    };
    entries
        .chunks_exact(ENTRY_SIZE)
        .filter(|entry| field(entry, ENTRY_ITEM_ID_OFFSET) == item_id)
        .fold(0u32, |total, entry| {
            total.saturating_add(field(entry, ENTRY_QUANTITY_OFFSET))
        })
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
