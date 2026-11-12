//! Race item game access for the shell: goods spawn, inventory quantity,
//! and the player's HP. Called on rare events (a grant, a game load, an
//! effect), never per frame.
//!
//! ### Inventory layout source
//!
//! Struct offsets derived from fromsoftware-rs `cs/player_game_data.rs`:
//! `PlayerGameData.equipment` (`EquipGameData`) sits at +0x2B0 and holds
//! its `EquipInventoryData` inline at +0x158 (after the 0xE8-byte `ChrAsm`
//! at +0x6C, padded to 8), so at PlayerGameData + 0x408; its
//! `InventoryItemsData` follows the vftable, at PlayerGameData + 0x410.
//! The same derivation lands the ChrAsm fields where `core::constants`
//! has them (verified in game), and lands `EquipItemData.inventory` and
//! `PlayerGameData.storage` on +0x5D0 and +0x8D0, the two inventory
//! pointers the TGA Cheat Engine table v1.17.0 reads. The list header
//! below and the entry layout (`core::item_inventory`) match that table's
//! inventory script. Unverified by this mod in game until the Windows
//! check.

use std::ffi::c_void;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use tracing::info;
use windows::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows::Win32::System::Threading::GetCurrentProcess;

use super::item_spawner::inject_one;
use crate::core::constants::GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET;
use crate::core::item_inventory::{
    list_entry_count, lists_hold_items, quantity_in_entries, ENTRY_SIZE,
};
use crate::profile_span;

/// Goods type flag in item ID encoding (high nibble 0x4 = EquipParamGoods).
const GOODS_TYPE_FLAG: u32 = 0x4000_0000;

/// PlayerGameData + 0x410: `InventoryItemsData` of the held inventory.
const PLAYER_GAME_DATA_INVENTORY_ITEMS_OFFSET: usize = 0x410;

/// Head of `InventoryItemsData`: the normal and key item lists (the
/// multiplayer key list and the id hash table that follow are not read).
#[repr(C)]
struct InventoryLists {
    _global_capacity: u32,
    normal_capacity: u32,
    normal_head: usize,
    normal_len: u32,
    key_capacity: u32,
    key_head: usize,
    key_len: u32,
}

/// Give one unit of a goods item. False when nothing was injected
/// (func_item_inject unknown for this game version, or MapItemMan null).
/// No fresh-save gate and no wait: race items arrive mid-race, on a loaded
/// player.
pub fn spawn_goods(goods_id: u32) -> bool {
    profile_span!("race_items.spawn_goods");
    inject_one(GOODS_TYPE_FLAG | goods_id)
}

/// The held inventory's normal and key item lists, copied out of game
/// memory once, for as many goods lookups as needed.
pub struct HeldInventory {
    normal: Vec<u8>,
    key: Vec<u8>,
}

impl HeldInventory {
    /// `None` when the inventory is unreadable: a null or unreadable
    /// pointer on the way, a list header that no longer looks like the
    /// layout above (zeroed memory included), or both lists empty
    /// (allocated, not filled yet). Logs the list headers it read.
    pub fn read() -> Option<Self> {
        profile_span!("race_items.read_inventory");
        let game_data_man = read_ptr(Pointers::new().base_addresses.game_data_man)?;
        let player_game_data = read_ptr(game_data_man + GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET)?;
        let lists = PointerChain::<InventoryLists>::new(&[
            player_game_data + PLAYER_GAME_DATA_INVENTORY_ITEMS_OFFSET
        ])
        .read()?;
        // Info, the default filter's level: a rare read (a game load, a
        // spawn) whose headers confirm the layout from the mod log.
        info!(
            normal_capacity = lists.normal_capacity,
            normal_len = lists.normal_len,
            key_capacity = lists.key_capacity,
            key_len = lists.key_len,
            "[ITEMS] Inventory list headers"
        );
        if !lists_hold_items(lists.normal_len, lists.key_len) {
            return None;
        }
        Some(Self {
            normal: read_list(lists.normal_head, lists.normal_capacity, lists.normal_len)?,
            key: read_list(lists.key_head, lists.key_capacity, lists.key_len)?,
        })
    }

    /// How many of a goods item the lists hold (0 when absent).
    pub fn goods_quantity(&self, goods_id: u32) -> u32 {
        let item_id = GOODS_TYPE_FLAG | goods_id;
        quantity_in_entries(&self.normal, item_id)
            .saturating_add(quantity_in_entries(&self.key, item_id))
    }
}

/// How many of a goods item the player holds: `Some(0)` when absent,
/// `None` when the inventory is unreadable (see `HeldInventory::read`).
pub fn goods_quantity(goods_id: u32) -> Option<u32> {
    Some(HeldInventory::read()?.goods_quantity(goods_id))
}

/// The player's current HP and effective max HP (`max_hp_ro[0]`, which a
/// max-HP SpEffect such as the Blue Shell's lowers). `None` while the player
/// is not loaded.
pub fn read_hp() -> Option<(i32, i32)> {
    profile_span!("race_items.read_hp");
    let points = Pointers::new().character_points.read()?;
    Some((points.hp, points.max_hp_ro[0]))
}

/// Write the player's current HP. The `character_points` chain resolves to
/// the struct's first field, `hp`, so the cast writes that i32 alone, never
/// the max HP fields after it.
pub fn write_hp(hp: i32) -> bool {
    profile_span!("race_items.write_hp");
    Pointers::new()
        .character_points
        .cast::<i32>()
        .write(hp)
        .is_some()
}

/// Pointer stored at `addr`, `None` when unreadable or null.
fn read_ptr(addr: usize) -> Option<usize> {
    PointerChain::<usize>::new(&[addr])
        .read()
        .filter(|&ptr| ptr != 0)
}

/// One inventory list's entries, copied out in one read.
fn read_list(head: usize, capacity: u32, len: u32) -> Option<Vec<u8>> {
    let count = list_entry_count(capacity, len)?;
    if head == 0 {
        return None;
    }
    read_bytes(head, count * ENTRY_SIZE)
}

/// Copy `len` bytes of game memory. `PointerChain` reads a fixed-size type;
/// a list's length is only known at runtime, so this calls the same
/// `ReadProcessMemory` on the current process, which fails instead of
/// faulting on an unmapped address.
fn read_bytes(addr: usize, len: usize) -> Option<Vec<u8>> {
    let mut buf = vec![0u8; len];
    // SAFETY: the destination is `buf`, exactly `len` writable bytes; the
    // source is only read by the kernel, which reports an unmapped range as
    // an error.
    unsafe {
        ReadProcessMemory(
            GetCurrentProcess(),
            addr as *const c_void,
            buf.as_mut_ptr() as *mut c_void,
            len,
            None,
        )
    }
    .ok()?;
    Some(buf)
}
