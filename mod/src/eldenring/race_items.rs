//! Race item game access for the shell: goods spawn, inventory quantity,
//! the player's HP and equip load, and the equip load effect's rate. Called
//! on rare events (a grant, a game load, an effect), never per frame.
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
use libeldenring::params::{
    EquipParamAccessory, EquipParamProtector, EquipParamWeapon, Params, SpEffect, PARAMS,
};
use libeldenring::pointers::Pointers;
use once_cell::sync::Lazy;
use tracing::{info, warn};
use windows::Win32::System::Diagnostics::Debug::ReadProcessMemory;
use windows::Win32::System::Threading::GetCurrentProcess;

use super::item_spawner::inject_one;
use crate::core::constants::{
    CHRASM_EQUIPMENT_PARAM_IDS_OFFSET, GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET,
    PLAYER_GAME_DATA_MAX_EQUIP_LOAD_OFFSET,
};
use crate::core::equip_load::{weight_row, EquipParam, EQUIP_SLOTS};
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

/// The player's current and max equip load: the summed weights of the
/// equipped items, read from their equipment params, and the max the
/// equipment screen shows. A slot whose row is missing counts as 0 and is
/// logged. `None` while the player is unreadable or the params are not
/// indexed yet (`prewarm_params`).
pub fn read_equip_load() -> Option<(f32, f32)> {
    profile_span!("race_items.read_equip_load");
    let game_data_man = read_ptr(Pointers::new().base_addresses.game_data_man)?;
    let player_game_data = read_ptr(game_data_man + GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET)?;
    let ids = read_bytes(
        player_game_data + CHRASM_EQUIPMENT_PARAM_IDS_OFFSET,
        EQUIP_SLOTS * 4,
    )?;
    let max = read_bytes(player_game_data + PLAYER_GAME_DATA_MAX_EQUIP_LOAD_OFFSET, 4)?;
    let max = f32::from_le_bytes(max.try_into().ok()?);
    let params = Lazy::get(&PARAMS)?.read();
    let mut current = 0.0;
    for (slot, bytes) in ids.chunks_exact(4).enumerate() {
        let id = i32::from_le_bytes(bytes.try_into().ok()?);
        let Some((param, row)) = weight_row(slot, id) else {
            continue;
        };
        let weight = match param {
            EquipParam::Weapon => {
                param_row::<EquipParamWeapon>(&params, "EquipParamWeapon", row).map(|r| r.weight)
            }
            EquipParam::Protector => {
                param_row::<EquipParamProtector>(&params, "EquipParamProtector", row)
                    .map(|r| r.weight)
            }
            EquipParam::Accessory => {
                param_row::<EquipParamAccessory>(&params, "EquipParamAccessory", row)
                    .map(|r| r.weight)
            }
        };
        match weight {
            Some(weight) => current += weight,
            None => warn!(slot, id, row, "[ITEMS] No weight row for an equipped item"),
        }
    }
    Some((current, max))
}

/// Write `rate` as the max equip load rate of SpEffect row `speffect_id`.
/// False when the row is missing or the params are not indexed yet.
pub fn set_equip_load_rate(speffect_id: u32, rate: f32) -> bool {
    profile_span!("race_items.set_equip_load_rate");
    let Some(params) = Lazy::get(&PARAMS).map(|lock| lock.read()) else {
        return false;
    };
    // The in-memory param table goes by the regulation's name, SpEffectParam;
    // "SpEffect" is only the name of the paramdef and the generated struct.
    let Some(row) = param_row::<SpEffect>(&params, "SpEffectParam", speffect_id) else {
        return false;
    };
    // SAFETY: the field is an aligned f32 of a live param row; the game reads
    // it from its own thread, so the store is volatile and never read back.
    unsafe { std::ptr::write_volatile(&mut row.equip_weight_change_rate, rate) };
    true
}

/// Index the game's param table (libeldenring waits until the params are in
/// memory). Run off the render thread: the readers above only use an index
/// already built, and keep the row's rate until then.
pub fn prewarm_params() {
    let count = PARAMS.read().keys().count();
    info!(count, "[ITEMS] Params indexed");
}

/// Row `id` of the param `name`, as its generated struct.
fn param_row<T: 'static>(params: &Params, name: &str, id: u32) -> Option<&'static mut T> {
    // SAFETY: the params live for the whole game session and libeldenring
    // casts each row to its generated struct. The game uses the rows from
    // its own threads: callers only read fields or store one with a
    // volatile write, and keep no reference past their call.
    unsafe { params.iter_param::<T>(name) }?
        .find(|row| row.id == u64::from(id))?
        .param
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
