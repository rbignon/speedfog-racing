//! Runtime item spawner for SpeedFog Racing
//!
//! Spawns gem (Ash of War) items received via WebSocket auth_ok. EMEVD's
//! DirectlyGivePlayerItem doesn't support the Gem item type, so we use
//! func_item_inject (same function as the ER practice tool) at runtime.
//!
//! Re-spawn prevention uses event flag 1040292900 in the VirtualMemoryFlag tree.
//! This flag persists in the save file, so restarting the game or reconnecting
//! won't re-give items.

use std::ffi::c_void;
use std::time::Duration;

use libeldenring::pointers::Pointers;
use tracing::{error, info, warn};

use crate::core::protocol::SpawnItem;
use crate::eldenring::EventFlagReader;

/// Gem type flag in item ID encoding (high nibble 0x8 = EquipParamGem)
const GEM_TYPE_FLAG: u32 = 0x8000_0000;

/// Event flag used to prevent re-spawning items (persists in save file).
/// Category 1040292, offset 900 — in the FogRando-created category.
const ITEMS_SPAWNED_FLAG: u32 = 1040292900;

/// Spawn request struct matching Elden Ring's internal MapItemMan format.
#[repr(C)]
struct SpawnRequest {
    one: u32,
    item_id: u32,
    qty: u32,
    dur: i32,
    gem: i32,
}

/// func_item_inject signature: (MapItemMan*, SpawnRequest*, output*, flags)
type SpawnItemFn = unsafe extern "system" fn(*const c_void, *mut SpawnRequest, *mut u32, u32);

/// Spawn items received from auth_ok. **Blocks** until the game is fully loaded.
///
/// Call this from a dedicated thread — it polls MapItemMan every 500ms until
/// the player has loaded into the game world, then calls func_item_inject
/// for each item.
///
/// Uses event flag `ITEMS_SPAWNED_FLAG` to prevent re-giving items on
/// reconnect or game restart (flag persists in save file).
pub fn spawn_items_blocking(items: Vec<SpawnItem>, flag_reader: &EventFlagReader) {
    if items.is_empty() {
        return;
    }

    info!(count = items.len(), "Waiting to spawn items...");

    let pointers = Pointers::new();
    let base = &pointers.base_addresses;

    let func_addr = base.func_item_inject;
    if func_addr == 0 {
        error!("func_item_inject not available for this game version");
        return;
    }

    // Wait for MapItemMan to be initialized (player loaded into game world).
    let pp = base.map_item_man as *const *const c_void;
    let wait_start = std::time::Instant::now();
    loop {
        let p = unsafe { pp.read() };
        if !p.is_null() {
            break;
        }
        if wait_start.elapsed() > Duration::from_secs(120) {
            error!("MapItemMan not available after 120s, aborting spawn");
            return;
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    // Brief delay for the game to finish initialization after MapItemMan is set
    std::thread::sleep(Duration::from_secs(2));

    // Check re-spawn prevention flag
    match flag_reader.is_flag_set(ITEMS_SPAWNED_FLAG) {
        Some(true) => {
            info!(
                flag = ITEMS_SPAWNED_FLAG,
                "Items already spawned (flag set), skipping"
            );
            return;
        }
        Some(false) => {
            // Flag not set, proceed with spawning
        }
        None => {
            warn!("Cannot read items-spawned flag, proceeding anyway");
        }
    }

    let p_map_item_man = unsafe { pp.read() };
    if p_map_item_man.is_null() {
        error!("MapItemMan became null after delay");
        return;
    }

    let spawn_fn: SpawnItemFn = unsafe { std::mem::transmute(func_addr) };

    for item in &items {
        let encoded_id = GEM_TYPE_FLAG | item.id;

        for _ in 0..item.qty {
            let mut request = SpawnRequest {
                one: 1,
                item_id: encoded_id,
                qty: 1,
                dur: -1,
                gem: -1,
            };
            let mut output = 0u32;

            unsafe {
                spawn_fn(
                    p_map_item_man,
                    &mut request as *mut _,
                    &mut output as *mut _,
                    0,
                );
            }
        }

        info!(
            id = item.id,
            qty = item.qty,
            encoded = format_args!("0x{:08X}", encoded_id),
            "Spawned item"
        );
    }

    // Set re-spawn prevention flag
    if flag_reader.set_flag(ITEMS_SPAWNED_FLAG, true) {
        info!("Items-spawned flag set");
    } else {
        warn!("Failed to set items-spawned flag");
    }

    info!(count = items.len(), "All items spawned");
}
