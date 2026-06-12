//! Runtime SpEffect application for the local player.
//!
//! Used by the phantom skins feature to apply a cosmetic aura (a SpEffect
//! baked by speedfog into regulation.bin, e.g. id 1450700 for `gold-aura`)
//! to the player at game-world load time.
//!
//! ### How it works
//!
//! The mod runs *inside* eldenring.exe (DLL injection), so we can call game
//! functions directly. ER doesn't expose a stable export for SpEffect
//! application, so we locate the function via an AOB pattern scan over the
//! main module's executable section, cache the resolved address, then call
//! it with the documented Microsoft x64 calling convention.
//!
//! ### Pattern source
//!
//! AOB taken from the publicly distributed Cheat Engine table
//! `eldenring_all-in-one_Hexinton-v5.0_ce7.5.ct` (script `ApplyEffectAOBFecth`).
//! Confirmed to apply phantom-skin SpEffect IDs (1450700-1450705) by manual
//! validation in CE prior to integration.

use std::ffi::c_void;
use std::sync::OnceLock;

use super::scan::{module_base_and_size, scan_pattern};
use libeldenring::pointers::Pointers;
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use tracing::{debug, error, info, warn};

const PLAYER_INS_OFFSET_NEW: usize = 0x1E508; // V1_07_0+
const PLAYER_INS_OFFSET_OLD: usize = 0x18468; // V1_02 .. V1_06
const SP_EFFECT_CTRL_OFFSET: usize = 0x178;

/// AOB pattern for the SpEffect-application function.
///
/// `Some(byte)` = exact match; `None` = wildcard (0x?? in the CE script).
/// 70 bytes total. Matches the prologue of `ChrIns_ApplySpEffect`.
const APPLY_SP_EFFECT_PATTERN: &[Option<u8>] = &[
    Some(0x48),
    Some(0x89),
    Some(0x6C),
    Some(0x24),
    Some(0x10),
    Some(0x48),
    Some(0x89),
    Some(0x74),
    Some(0x24),
    Some(0x18),
    Some(0x57),
    Some(0x41),
    Some(0x56),
    Some(0x41),
    Some(0x57),
    Some(0x48),
    Some(0x83),
    Some(0xEC),
    Some(0x60),
    Some(0x0F),
    Some(0xB6),
    Some(0x84),
    Some(0x24),
    Some(0xB0),
    Some(0x00),
    Some(0x00),
    Some(0x00),
    Some(0x49),
    Some(0x8B),
    Some(0xF1),
    Some(0x88),
    Some(0x44),
    Some(0x24),
    Some(0x20),
    Some(0x4D),
    Some(0x8B),
    Some(0xF0),
    Some(0x8B),
    Some(0xEA),
    Some(0x4C),
    Some(0x8B),
    Some(0xF9),
    Some(0xE8),
    None,
    None,
    None,
    None,
    Some(0x84),
    Some(0xC0),
    Some(0x0F),
    Some(0x84),
    None,
    None,
    None,
    None,
    Some(0x48),
    Some(0x83),
    Some(0xCF),
    Some(0xFF),
    Some(0x48),
    Some(0x89),
    Some(0x9C),
    Some(0x24),
    Some(0x80),
    Some(0x00),
    Some(0x00),
    Some(0x00),
    Some(0x48),
    Some(0x8B),
    Some(0xDF),
];

/// MS x64 calling convention:
/// - RCX = SpEffectCtrl (PlayerIns + 0x178)
/// - EDX = effect_id
/// - R8  = PlayerIns (emitter)
/// - R9  = PlayerIns
/// - [rsp+0x20] = 1.0f (multiplier)
type ApplySpEffectFn = unsafe extern "system" fn(
    sp_effect_ctrl: *mut c_void,
    effect_id: u32,
    chr_ins_a: *mut c_void,
    chr_ins_b: *mut c_void,
    multiplier: f32,
);

/// Resolved once per process. None means scanning failed.
static APPLY_FN_ADDR: OnceLock<Option<usize>> = OnceLock::new();

fn player_ins_offset() -> usize {
    use Version::*;
    match get_version() {
        V1_02_0 | V1_02_1 | V1_02_2 | V1_02_3 | V1_03_0 | V1_03_1 | V1_03_2 | V1_04_0 | V1_04_1
        | V1_05_0 | V1_06_0 => PLAYER_INS_OFFSET_OLD,
        _ => PLAYER_INS_OFFSET_NEW,
    }
}

/// Resolve the apply-function address (idempotent, cached after first success).
fn resolve_apply_fn() -> Option<usize> {
    *APPLY_FN_ADDR.get_or_init(|| {
        let (base, size) = match module_base_and_size() {
            Some(v) => v,
            None => {
                error!("Failed to query eldenring.exe module info");
                return None;
            }
        };
        match scan_pattern(base, size, APPLY_SP_EFFECT_PATTERN) {
            Some(addr) => {
                info!(
                    addr = format!("0x{addr:X}"),
                    "Resolved ApplySpEffect function"
                );
                Some(addr)
            }
            None => {
                warn!("ApplySpEffect AOB pattern not found in eldenring.exe");
                None
            }
        }
    })
}

/// Read PlayerIns from WorldChrMan. Returns null until the player is loaded
/// into the game world.
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
    let player_ins = unsafe { (player_ins_field as *const *const c_void).read() } as *mut c_void;
    player_ins
}

/// Apply a single SpEffect to the local player. Returns true on success.
///
/// Returns false (with a log line) if:
/// - The apply function couldn't be located (AOB scan failed).
/// - The player ChrIns is not yet loaded (call again later).
/// - The SpEffectCtrl chain is null (very unusual; means the player struct
///   is mid-initialization).
pub fn apply_speffect(effect_id: u32) -> bool {
    let func_addr = match resolve_apply_fn() {
        Some(a) => a,
        None => return false,
    };

    let pointers = Pointers::new();
    let player_ins = read_player_ins(&pointers);
    if player_ins.is_null() {
        debug!("Cannot apply SpEffect: player not loaded yet");
        return false;
    }

    let sp_effect_ctrl_field = (player_ins as usize) + SP_EFFECT_CTRL_OFFSET;
    let sp_effect_ctrl = unsafe { (sp_effect_ctrl_field as *const *mut c_void).read() };
    if sp_effect_ctrl.is_null() {
        warn!(effect_id, "SpEffectCtrl is null on player; skipping apply");
        return false;
    }

    // SAFETY: we've located the function via AOB and verified its prologue
    // matches CE's known-good signature. We pass a non-null SpEffectCtrl and
    // a non-null PlayerIns; the multiplier 1.0 is what every CE script uses.
    // The function may mutate the player's SpEffect linked list. If the
    // pattern ever shifts (game patch breaks the AOB), `resolve_apply_fn`
    // returns None and we never reach this call.
    let apply: ApplySpEffectFn = unsafe { std::mem::transmute(func_addr) };
    unsafe {
        apply(sp_effect_ctrl, effect_id, player_ins, player_ins, 1.0);
    }
    debug!(effect_id, "Applied SpEffect");
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pattern_has_expected_length() {
        // Sanity check: 70 bytes, matching the CE script's AOB.
        assert_eq!(APPLY_SP_EFFECT_PATTERN.len(), 70);
    }

    #[test]
    fn pattern_first_byte_is_function_prologue() {
        // The function prologue starts with `48 89 6C 24 10`
        // (mov [rsp+0x10], rbp). Sanity-check we kept the byte order.
        assert_eq!(APPLY_SP_EFFECT_PATTERN[0], Some(0x48));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[1], Some(0x89));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[2], Some(0x6C));
    }

    // No test for player_ins_offset(): it calls libeldenring::version::get_version()
    // which panics outside a running ER process. The function is exercised
    // indirectly when apply_speffect runs in-game.
}
