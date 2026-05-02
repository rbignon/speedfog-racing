//! Background runner that re-applies phantom-skin SpEffects on every
//! game-world load.
//!
//! Spawned once per session when `auth_ok` carries a non-null
//! `phantom_skin` and the per-seed map resolves it to one or more SpEffect
//! IDs. The thread polls the player ChrIns availability through
//! `WorldChrMan + offset` and reapplies whenever the player transitions from
//! "not loaded" to "loaded" (covers initial load, save+quit+reload, and
//! grace warps that round-trip through a loading screen).
//!
//! Application is idempotent at the game level (a SpEffect that's already
//! active is a no-op), so missed transitions are safe; the cost is at most
//! a couple of extra calls per second.

use std::ffi::c_void;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use libeldenring::pointers::Pointers;
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use tracing::{info, warn};

use crate::eldenring::sp_effect_apply::apply_speffect;

const POLL_INTERVAL_MS: u64 = 500;

/// Spawn the loop. Returns the join handle. The thread runs until `stop` is
/// flipped to true, after which it exits at the next poll tick. Currently no
/// caller stops it (the thread dies with the process), but the flag is in
/// place for future mid-session skin changes.
pub fn spawn(
    skin_name: String,
    speffect_ids: Vec<i32>,
    stop: Arc<AtomicBool>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        info!(
            skin = %skin_name,
            count = speffect_ids.len(),
            ids = ?speffect_ids,
            "[PHANTOM_SKIN] Runner started"
        );
        let pointers = Pointers::new();
        let mut player_was_loaded = false;
        loop {
            if stop.load(Ordering::Relaxed) {
                info!(skin = %skin_name, "[PHANTOM_SKIN] Runner stopping");
                return;
            }

            let player_loaded = !read_player_ins(&pointers).is_null();
            if player_loaded && !player_was_loaded {
                // Transition: not loaded -> loaded. Apply each SpEffect.
                for id in &speffect_ids {
                    if *id < 0 {
                        warn!(id, "[PHANTOM_SKIN] Negative SpEffect id, skipping");
                        continue;
                    }
                    let applied = apply_speffect(*id as u32);
                    if applied {
                        info!(skin = %skin_name, id = *id, "[PHANTOM_SKIN] Applied");
                    }
                }
            }
            player_was_loaded = player_loaded;
            std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
        }
    })
}

fn player_ins_offset() -> usize {
    use Version::*;
    match get_version() {
        V1_02_0 | V1_02_1 | V1_02_2 | V1_02_3 | V1_03_0 | V1_03_1 | V1_03_2 | V1_04_0 | V1_04_1
        | V1_05_0 | V1_06_0 => 0x18468,
        _ => 0x1E508,
    }
}

fn read_player_ins(pointers: &Pointers) -> *mut c_void {
    let world_chr_man_loc = pointers.base_addresses.world_chr_man;
    if world_chr_man_loc == 0 {
        return std::ptr::null_mut();
    }
    let pp = world_chr_man_loc as *const *const c_void;
    let wcm = unsafe { pp.read() };
    if wcm.is_null() {
        return std::ptr::null_mut();
    }
    let player_ins_field = (wcm as usize) + player_ins_offset();
    unsafe { (player_ins_field as *const *const c_void).read() as *mut c_void }
}
