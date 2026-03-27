//! Runtime item spawner for SpeedFog Racing
//!
//! Spawns gem (Ash of War) items received via WebSocket auth_ok. EMEVD's
//! DirectlyGivePlayerItem doesn't support the Gem item type, so we use
//! func_item_inject (same function as the ER practice tool) at runtime.
//!
//! Re-spawn prevention has three layers:
//! 1. In-process `items_spawned` AtomicBool in RaceTracker (primary; covers
//!    reconnects). Set by this thread AFTER items are actually spawned.
//! 2. IGT freshness check: if IGT > 15s when the game loads, the save is stale
//!    (not a fresh New Game). Skip spawning so the player can retry with a new save.
//! 3. Event flag from `items_spawned_flag` in graph.json (covers game restarts).
//!    The flag ID is provided by the server in the auth_ok seed message and lives
//!    in the saved flag range (persists in the save file).

use std::ffi::c_void;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use libeldenring::pointers::Pointers;
use tracing::{error, info, warn};

use crate::core::protocol::SpawnItem;
use crate::eldenring::EventFlagReader;

/// Maximum IGT (in milliseconds) for a save to be considered fresh.
/// Matches the server-side `MAX_FRESH_IGT_MS` constant.
/// A fresh New Game reaches the first load screen at ~3-5s IGT.
const MAX_FRESH_IGT_MS: u32 = 15_000;

/// Gem type flag in item ID encoding (high nibble 0x8 = EquipParamGem)
const GEM_TYPE_FLAG: u32 = 0x8000_0000;

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
/// Call this from a dedicated thread. It polls MapItemMan every 500ms until
/// the player has loaded into the game world, then calls func_item_inject
/// for each item.
///
/// Before spawning, checks the in-game time (IGT). If the save is stale
/// (IGT > 15s), skips the spawn so the player can create a fresh save.
/// The `items_spawned` AtomicBool is only set to `true` after items are
/// actually given, allowing a retry on the next auth_ok.
///
/// When `items_spawned_flag` is `Some(flag_id)`, checks the flag before
/// spawning and sets it after to prevent re-giving items on game restart.
pub fn spawn_items_blocking(
    items: Vec<SpawnItem>,
    flag_reader: &EventFlagReader,
    items_spawned_flag: Option<u32>,
    items_spawned: &AtomicBool,
) {
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
    // No timeout: the player may stay on the title screen or character creation
    // for an arbitrarily long time before loading in (e.g. race lobby).
    // The thread is lightweight (sleeps 500ms) and bounded by the game process.
    let pp = base.map_item_man as *const *const c_void;
    let wait_start = std::time::Instant::now();
    let mut last_log = std::time::Instant::now();
    loop {
        let p = unsafe { pp.read() };
        if !p.is_null() {
            break;
        }
        if last_log.elapsed() > Duration::from_secs(60) {
            info!(
                elapsed_s = wait_start.elapsed().as_secs(),
                "Still waiting for MapItemMan (player not in game yet)"
            );
            last_log = std::time::Instant::now();
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    // Brief delay for the game to finish initialization after MapItemMan is set
    std::thread::sleep(Duration::from_secs(2));

    // Stale save guard: if IGT is already high, the player loaded an existing
    // save instead of starting a New Game. Skip spawning so the server's
    // "Please start a New Game" rejection doesn't permanently block items.
    // The player can then create a fresh save and items will spawn on the
    // next auth_ok (since items_spawned AtomicBool was never set to true).
    let igt_ms = pointers.igt.read().map(|v| v as u32).unwrap_or(0);
    if igt_ms > MAX_FRESH_IGT_MS {
        warn!(
            igt_ms,
            max = MAX_FRESH_IGT_MS,
            "Stale save detected (IGT too high), skipping item spawn"
        );
        return;
    }

    // Check re-spawn prevention flag (only when server provides one)
    if let Some(flag_id) = items_spawned_flag {
        match flag_reader.is_flag_set(flag_id) {
            Some(true) => {
                info!(flag = flag_id, "Items already spawned (flag set), skipping");
                return;
            }
            Some(false) => {
                // Flag not set, proceed with spawning
            }
            None => {
                warn!("Cannot read items-spawned flag, proceeding anyway");
            }
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

    // Mark as spawned in-process (primary guard against reconnect double-spawn)
    items_spawned.store(true, Ordering::Relaxed);

    // Set re-spawn prevention flag (only when server provides one)
    if let Some(flag_id) = items_spawned_flag {
        if flag_reader.set_flag(flag_id, true) {
            info!(flag = flag_id, "Items-spawned flag set");
        } else {
            warn!(flag = flag_id, "Failed to set items-spawned flag");
        }
    }

    info!(count = items.len(), "All items spawned");
}
