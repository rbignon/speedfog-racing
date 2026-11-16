//! The game's own equip function, `EquipGameData::ChangeEquipment`, and the
//! Junk Weapon's sequence on top of it: give the weapon, find the copy the
//! give added, equip that copy in the right hand in use, read the slot back.
//! Run once per effect, on the frame that executes it, never per frame.
//!
//! ### Why the game function, not a raw write
//!
//! An equipment slot is more than its param id: PlayerGameData keeps its
//! inventory index, an "index changed" byte, its gaitem handle, its param
//! id, the arm style, its bolt state and its equipment entry. The handle
//! holds a reference on the weapon's CSGaitem that only the game's
//! ref-counting assign keeps right: a raw write would leave the runner's own
//! weapon with a reference it no longer has. ChangeEquipment writes them
//! all, and the equipment menu equips through it. Nothing else equips here:
//! without the function the effect gives nothing, since a junk weapon given
//! but never equipped would be a free item.
//!
//! ### Pattern and signature source
//!
//! Static disassembly of eldenring.exe 1.16.2, 1.17.0, 1.17.1 and 1.17.2:
//! the function sits at RVA 0x249160 on all four, with the same body (the
//! TGA v1.17.0 table's `equipGear` calls it). The pattern is the body right
//! after the prologue, with no wildcard, and ends on `add rcx, 0x6C`, the
//! ChrAsm offset inside EquipGameData, so a layout move fails the scan
//! instead of running with stale offsets. The entry is `match - 0x17`, kept
//! only when the prologue there is the expected one.
//!
//! Seven arguments, MS x64: four in registers, then three bools on the
//! stack, which the function reads as bytes at entry `[rsp+0x28]`,
//! `[rsp+0x30]` and `[rsp+0x38]` (the game's own callers write them as
//! bytes). The type below declares all seven: a stack argument left out
//! reads whatever the caller left in that slot (the phantom skin regression,
//! see `sp_effect_apply`).
//!
//! ### PlayerGameData fields (1.17.x)
//!
//! Offsets from PlayerGameData, from fromsoftware-rs
//! `cs/player_game_data.rs` (`EquipGameData` inline at 0x2B0, its `ChrAsm`
//! at 0x6C in it), each checked against the instructions that access it in
//! the 1.17.0 executable:
//!
//! - per slot `s`: the inventory index at 0x2B8 + 4s, the gaitem handle at
//!   0x340 + 4s, the param id at 0x398 + 4s and the equipment entry (the
//!   full item id) at 0x5F8 + 4s;
//! - for both hands, the arm style at 0x324 (u32: 0 empty, 1 one-handed, 2
//!   left two-handed, 3 right two-handed).
//!
//! Unverified by this mod in game until the Windows check.

use std::ffi::c_void;
use std::fmt;
use std::sync::OnceLock;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use tracing::{info, warn};

use super::item_spawner::inject_one;
use super::race_items::{read_ptr, HeldInventory};
use super::scan::{module_base_and_size, scan_pattern_unique};
use super::sp_effect_apply::read_player_ins;
use crate::core::constants::{
    CHRASM_EQUIPMENT_PARAM_IDS_OFFSET, CHRASM_WEP_SLOT_RIGHT_OFFSET,
    GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET,
};
use crate::core::item_inventory::{handles_of, junk_is_free, junk_slot, new_copy, normal_index};
use crate::profile_span;

/// ChangeEquipment's body right after its prologue, one row per
/// instruction: `mov esi, r9d; mov rbx, r8; movsxd rbp, edx; mov rdi, rcx;`
/// `add rcx, 0x6C`. No wildcard (see the module docs).
const CHANGE_EQUIPMENT_PATTERN: &[Option<u8>] = &[
    Some(0x41),
    Some(0x8B),
    Some(0xF1),
    Some(0x49),
    Some(0x8B),
    Some(0xD8),
    Some(0x48),
    Some(0x63),
    Some(0xEA),
    Some(0x48),
    Some(0x8B),
    Some(0xF9),
    Some(0x48),
    Some(0x83),
    Some(0xC1),
    Some(0x6C),
];

/// Distance from the pattern's match back to the function's entry.
const ENTRY_OFFSET: usize = 0x17;

/// The prologue expected at the entry: `push rbx; push rbp; push rsi;`
/// `push rdi; push r14; sub rsp, 0x90`.
const PROLOGUE: [u8; 14] = [
    0x40, 0x53, 0x55, 0x56, 0x57, 0x41, 0x56, 0x48, 0x81, 0xEC, 0x90, 0x00, 0x00, 0x00,
];

/// PlayerGameData + 0x2B0: `EquipGameData`, held inline, ChangeEquipment's
/// first argument.
const EQUIP_GAME_DATA_OFFSET: usize = 0x2B0;
/// PlayerGameData + 0x2B8: the inventory index of each slot's item (u32).
const EQUIP_INDEX_LIST_OFFSET: usize = 0x2B8;
/// PlayerGameData + 0x324: the arm style (u32), shared by both hands.
const ARM_STYLE_OFFSET: usize = 0x324;
/// PlayerGameData + 0x340: the gaitem handle of each slot's item (u32).
const GAITEM_HANDLES_OFFSET: usize = 0x340;
/// PlayerGameData + 0x5F8: the full item id of each slot's item (u32).
const EQUIPMENT_ENTRIES_OFFSET: usize = 0x5F8;
/// PlayerGameData + 0x6AC: the outcome of the last item added (fromsoftware-rs
/// `last_add_item_result`; 4 when the inventory was full). Only logged.
const LAST_ADD_ITEM_RESULT_OFFSET: usize = 0x6AC;

/// The arm style the game leaves when it changes a weapon in hand.
const ARM_STYLE_ONE_HANDED: u32 = 1;

/// MS x64, see the module docs:
/// - RCX = EquipGameData* (PlayerGameData + 0x2B0)
/// - EDX = the ChrAsm slot (1 = first right weapon), sign-extended
/// - R8 = pointer to the gaitem handle, read once at the start
/// - R9D = the inventory index of the item
/// - `[rsp+0x28]` = force: skip the "already equipped" early return
/// - `[rsp+0x30]` = update_entries: also write the slot's equipment entry
/// - `[rsp+0x38]` = refresh_if_same: only read on the early return
///
/// No return value.
type ChangeEquipmentFn = unsafe extern "system" fn(
    equip_game_data: *mut c_void,
    slot: i32,
    gaitem_handle: *const u32,
    inventory_index: u32,
    force: bool,
    update_entries: bool,
    refresh_if_same: bool,
);

/// Resolved once per process. None means the scan or the prologue check
/// failed.
static CHANGE_FN_ADDR: OnceLock<Option<usize>> = OnceLock::new();

/// Resolve ChangeEquipment's entry (idempotent, cached).
fn resolve_change_fn() -> Option<usize> {
    *CHANGE_FN_ADDR.get_or_init(|| {
        let Some((base, size)) = module_base_and_size() else {
            warn!("[ITEMS] Failed to query eldenring.exe module info, ChangeEquipment unresolved");
            return None;
        };
        // Unique match: the address found is executed.
        let Some(found) = scan_pattern_unique(base, size, CHANGE_EQUIPMENT_PATTERN) else {
            warn!("[ITEMS] ChangeEquipment pattern absent or ambiguous in eldenring.exe, junk weapons disabled");
            return None;
        };
        // SAFETY: an entry at or past `base` lies in the module image
        // scanned above, its 14 bytes ending before the match.
        let Some(entry) = found.checked_sub(ENTRY_OFFSET).filter(|&entry| {
            entry >= base
                && unsafe { std::slice::from_raw_parts(entry as *const u8, PROLOGUE.len()) }
                    == PROLOGUE
        }) else {
            warn!(
                found = format_args!("0x{found:X}"),
                "[ITEMS] ChangeEquipment prologue not the expected one, junk weapons disabled"
            );
            return None;
        };
        info!(
            addr = format_args!("0x{entry:X}"),
            rva = format_args!("0x{:X}", entry - base),
            "[ITEMS] Resolved ChangeEquipment"
        );
        Some(entry)
    })
}

/// Resolve ChangeEquipment now: its scan walks the whole game image, a cost
/// the first junk weapon would otherwise pay on the render thread.
/// Idempotent; call it from a background thread.
pub fn prewarm() {
    profile_span!("equip_change.prewarm");
    let _ = resolve_change_fn();
}

/// One equipment slot as PlayerGameData holds it, with the arm style both
/// hands share.
struct SlotState {
    index: u32,
    handle: u32,
    param_id: i32,
    entry_id: u32,
    arm_style: u32,
}

impl SlotState {
    /// Slot `slot` of the PlayerGameData at `player_game_data`, every field
    /// read fault-safe. `None` when one is unreadable.
    fn read(player_game_data: usize, slot: usize) -> Option<Self> {
        Some(Self {
            index: read(player_game_data + EQUIP_INDEX_LIST_OFFSET + 4 * slot)?,
            handle: read(player_game_data + GAITEM_HANDLES_OFFSET + 4 * slot)?,
            param_id: read(player_game_data + CHRASM_EQUIPMENT_PARAM_IDS_OFFSET + 4 * slot)?,
            entry_id: read(player_game_data + EQUIPMENT_ENTRIES_OFFSET + 4 * slot)?,
            arm_style: read(player_game_data + ARM_STYLE_OFFSET)?,
        })
    }
}

impl fmt::Display for SlotState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "index={} handle=0x{:08X} param_id={} entry_id={} arm_style={}",
            self.index, self.handle, self.param_id, self.entry_id, self.arm_style
        )
    }
}

/// The value at `addr`, read with `ReadProcessMemory` (`None` instead of a
/// fault on an unmapped address).
fn read<T>(addr: usize) -> Option<T> {
    PointerChain::<T>::new(&[addr]).read()
}

/// Give the junk weapon `weapon_id` and equip that copy in the right hand in
/// use (`core::item_inventory::junk_slot`) through ChangeEquipment, then
/// read the slot back. Every step logs an `[ITEMS] Junk weapon` line. True
/// when the read-back shows the weapon in that slot, or when the hand
/// already held it (`junk_is_free`, nothing given). False otherwise: nothing
/// is given when the failure comes before the give (ChangeEquipment
/// unresolved, player or inventory unreadable); a weapon given whose copy is
/// not found (the inventory was full) stays where the game put it.
pub fn equip_junk_weapon(weapon_id: u32) -> bool {
    profile_span!("equip_change.equip_junk_weapon");
    // The function before the give: a junk weapon given but never equipped
    // would be a free item.
    let Some(change_fn) = resolve_change_fn() else {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon skipped, nothing given: ChangeEquipment unresolved"
        );
        return false;
    };
    let pointers = Pointers::new();
    if read_player_ins(&pointers).is_null() {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon skipped, nothing given: player not loaded"
        );
        return false;
    }
    let Some(player_game_data) = read_ptr(pointers.base_addresses.game_data_man)
        .and_then(|game_data_man| read_ptr(game_data_man + GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET))
    else {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon skipped, nothing given: PlayerGameData unreadable"
        );
        return false;
    };
    let Some(right_weapon_slot) = read::<u32>(player_game_data + CHRASM_WEP_SLOT_RIGHT_OFFSET)
    else {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon skipped, nothing given: right weapon slot unreadable"
        );
        return false;
    };
    let slot = junk_slot(right_weapon_slot);
    let Some(before) = SlotState::read(player_game_data, slot) else {
        warn!(
            weapon_id,
            slot, "[ITEMS] Junk weapon skipped, nothing given: slot unreadable"
        );
        return false;
    };
    info!(
        weapon_id,
        right_weapon_slot,
        slot,
        state = %before,
        "[ITEMS] Junk weapon slot before"
    );
    if junk_is_free(before.param_id, weapon_id) {
        info!(
            weapon_id,
            slot, "[ITEMS] Junk weapon already in hand, nothing given"
        );
        return true;
    }
    let Some(inventory) = HeldInventory::read() else {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon skipped, nothing given: inventory unreadable"
        );
        return false;
    };
    let had = handles_of(inventory.normal_entries(), weapon_id);
    // A weapon's item id has category 0: its encoded id is its param id.
    if !inject_one(weapon_id) {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon not given: the give function or MapItemMan is unavailable"
        );
        return false;
    }
    let Some(inventory) = HeldInventory::read() else {
        warn!(
            weapon_id,
            "[ITEMS] Junk weapon given, not equipped: inventory unreadable after the give"
        );
        return false;
    };
    let Some((position, handle)) = new_copy(&had, inventory.normal_entries(), weapon_id) else {
        warn!(
            weapon_id,
            had = format_args!("{had:08X?}"),
            last_add_item_result = ?read::<u32>(player_game_data + LAST_ADD_ITEM_RESULT_OFFSET),
            "[ITEMS] Junk weapon given, not equipped: no new copy in the held inventory (full?)"
        );
        return false;
    };
    let key_capacity = inventory.key_capacity();
    let Some(index) = normal_index(key_capacity, position) else {
        warn!(
            weapon_id,
            position,
            key_capacity,
            "[ITEMS] Junk weapon given, not equipped: inventory index out of range"
        );
        return false;
    };
    info!(
        weapon_id,
        handle = format_args!("0x{handle:08X}"),
        had = format_args!("{had:08X?}"),
        position,
        key_capacity,
        index,
        "[ITEMS] Junk weapon copy found"
    );
    {
        profile_span!("equip_change.change_equipment");
        // SAFETY: `change_fn` is ChangeEquipment's entry, found by a unique
        // pattern and its prologue; the type declares its seven arguments.
        // It gets the live EquipGameData of the PlayerGameData read above,
        // a right weapon slot (1, 3 or 5), a pointer to a handle that
        // outlives the call, the copy's inventory index, and the arguments
        // the equipment menu passes: force, update the entry, no refresh.
        let change: ChangeEquipmentFn = unsafe { std::mem::transmute(change_fn) };
        unsafe {
            change(
                (player_game_data + EQUIP_GAME_DATA_OFFSET) as *mut c_void,
                slot as i32,
                &handle,
                index,
                true,
                true,
                false,
            );
        }
    }
    info!(
        weapon_id,
        slot,
        handle = format_args!("0x{handle:08X}"),
        index,
        "[ITEMS] Junk weapon ChangeEquipment called"
    );
    let Some(after) = SlotState::read(player_game_data, slot) else {
        warn!(
            weapon_id,
            slot, "[ITEMS] Junk weapon read-back failed: slot unreadable"
        );
        return false;
    };
    // The game equips by handle and index; the param id and the entry
    // follow from them (a weapon's full item id is its param id).
    let in_hand = after.index == index
        && after.handle == handle
        && u32::try_from(after.param_id) == Ok(weapon_id)
        && after.entry_id == weapon_id;
    // The slot is the one in hand, so the game goes one-handed.
    if in_hand && after.arm_style == ARM_STYLE_ONE_HANDED {
        info!(
            weapon_id,
            slot,
            state = %after,
            "[ITEMS] Junk weapon read back, as expected"
        );
    } else {
        warn!(
            weapon_id,
            slot,
            expected_index = index,
            expected_handle = format_args!("0x{handle:08X}"),
            expected_arm_style = ARM_STYLE_ONE_HANDED,
            state = %after,
            "[ITEMS] Junk weapon read back differs from the equip"
        );
    }
    in_hand
}
