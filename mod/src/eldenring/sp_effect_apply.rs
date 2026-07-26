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
//! application, so we locate the ChrIns-level apply wrapper via an AOB
//! pattern scan over the main module's executable section, cache the
//! resolved address, then call it with the documented Microsoft x64 calling
//! convention.
//!
//! ### Why the ChrIns wrapper and not the lower-level function
//!
//! The lower-level `ChrIns_ApplySpEffect` (SpEffectCtrl-based, the AOB the
//! Hexinton CE table hooks) takes SEVEN arguments: its prologue reads a byte
//! at caller-`[rsp+0x30]` (7th argument) and forwards it to an inner call
//! whose boolean result gates the whole application. A 5-argument foreign
//! signature leaves that slot uninitialized, so the game reads whatever
//! local variable the compiler happened to place there; a stack-layout
//! change between rustc 1.96 and 1.97 silently flipped that byte and broke
//! phantom skins while still logging success. The wrapper takes all its
//! arguments in registers, so no stack slot can leak.
//!
//! ### Pattern source
//!
//! AOB taken from The Grand Archives CE table (`ER_TGA_v1.17.0.CT`, script
//! `SpEffect_code`, function `SpEffect.addForSelf`), which calls the wrapper
//! as `(ChrIns*, effect_id, 1)`. The pattern matches inside the wrapper;
//! the entry point is `match - 0x1D`, mirroring the TGA script's
//! `AOBScanModuleUnique(...) - 0x1D`.

use std::ffi::c_void;
use std::sync::OnceLock;

use super::scan::{module_base_and_size, scan_pattern_unique};
use libeldenring::pointers::Pointers;
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use tracing::{debug, error, info, warn};

const PLAYER_INS_OFFSET_NEW: usize = 0x1E508; // V1_07_0+
const PLAYER_INS_OFFSET_OLD: usize = 0x18468; // V1_02 .. V1_06
const SP_EFFECT_CTRL_OFFSET: usize = 0x178;

/// AOB pattern for the ChrIns-level SpEffect apply wrapper.
///
/// `Some(byte)` = exact match; `None` = wildcard (0x?? in the TGA script).
/// 19 bytes total, matching a movaps/lea/movaps/movzx sequence inside the
/// wrapper body (`0F 28 0D .. | .. 8D .. | 0F 29 .. | 0F B6 D8`).
const APPLY_SP_EFFECT_PATTERN: &[Option<u8>] = &[
    Some(0x0F),
    Some(0x28),
    Some(0x0D),
    None,
    None,
    None,
    None,
    None,
    Some(0x8D),
    None,
    None,
    Some(0x0F),
    Some(0x29),
    None,
    None,
    None,
    Some(0x0F),
    Some(0xB6),
    Some(0xD8),
];

/// Distance from the AOB match back to the wrapper's entry point.
const WRAPPER_ENTRY_OFFSET: usize = 0x1D;

/// MS x64 calling convention, registers only:
/// - RCX = ChrIns* (the character receiving the effect; here PlayerIns)
/// - EDX = effect_id
/// - R8D = flag; the TGA `addForSelf` script always passes 1
///
/// No stack arguments: see the module docs for why that matters.
type ApplySpEffectFn = unsafe extern "system" fn(chr_ins: *mut c_void, effect_id: u32, flag: u32);

/// Resolved once per process. None means scanning failed.
static APPLY_FN_ADDR: OnceLock<Option<usize>> = OnceLock::new();

/// WorldChrMan -> PlayerIns offset, version-dependent. Single source of
/// truth shared with sp_effect_runner; a silent drift between two copies
/// would break phantom skins on one path only.
pub(crate) fn player_ins_offset() -> usize {
    use Version::*;
    match get_version() {
        V1_02_0 | V1_02_1 | V1_02_2 | V1_02_3 | V1_03_0 | V1_03_1 | V1_03_2 | V1_04_0 | V1_04_1
        | V1_05_0 | V1_06_0 => PLAYER_INS_OFFSET_OLD,
        _ => PLAYER_INS_OFFSET_NEW,
    }
}

/// Resolve the wrapper's entry address (idempotent, cached after first success).
fn resolve_apply_fn() -> Option<usize> {
    *APPLY_FN_ADDR.get_or_init(|| {
        let (base, size) = match module_base_and_size() {
            Some(v) => v,
            None => {
                error!("Failed to query eldenring.exe module info");
                return None;
            }
        };
        // Unique-match scan: the pattern anchors mid-body, so a false match
        // would resolve to an arbitrary address that we then execute. The
        // TGA script asserts uniqueness the same way (AOBScanModuleUnique).
        match scan_pattern_unique(base, size, APPLY_SP_EFFECT_PATTERN) {
            Some(addr) => {
                let entry = addr - WRAPPER_ENTRY_OFFSET;
                info!(
                    addr = format!("0x{entry:X}"),
                    "Resolved ApplySpEffect function"
                );
                Some(entry)
            }
            None => {
                warn!("ApplySpEffect AOB pattern not found (or ambiguous) in eldenring.exe");
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

    // The wrapper resolves SpEffectCtrl itself; this read is only a
    // readiness guard so we don't call into a half-initialized player.
    let sp_effect_ctrl_field = (player_ins as usize) + SP_EFFECT_CTRL_OFFSET;
    let sp_effect_ctrl = unsafe { (sp_effect_ctrl_field as *const *mut c_void).read() };
    if sp_effect_ctrl.is_null() {
        warn!(effect_id, "SpEffectCtrl is null on player; skipping apply");
        return false;
    }

    // SAFETY: we've located the wrapper via AOB and call it with the same
    // register-only arguments as the TGA script (ChrIns, effect_id, 1). The
    // function may mutate the player's SpEffect linked list. If the pattern
    // ever shifts (game patch breaks the AOB), `resolve_apply_fn` returns
    // None and we never reach this call.
    let apply: ApplySpEffectFn = unsafe { std::mem::transmute(func_addr) };
    unsafe {
        apply(player_ins, effect_id, 1);
    }
    debug!(effect_id, "Applied SpEffect");
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pattern_has_expected_length() {
        // Sanity check: 19 bytes, matching the TGA script's AOB.
        assert_eq!(APPLY_SP_EFFECT_PATTERN.len(), 19);
    }

    #[test]
    fn pattern_anchors_are_exact_bytes() {
        // The pattern starts with `0F 28 0D` (movaps xmm1, [rip+..]) and
        // ends with the tail of `41 0F B6 D8` (movzx ebx, r8b on current
        // builds; the REX prefix is wildcarded). Sanity-check we kept the
        // byte order when transcribing from the CE script.
        assert_eq!(APPLY_SP_EFFECT_PATTERN[0], Some(0x0F));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[1], Some(0x28));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[2], Some(0x0D));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[16], Some(0x0F));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[17], Some(0xB6));
        assert_eq!(APPLY_SP_EFFECT_PATTERN[18], Some(0xD8));
    }

    // No test for player_ins_offset(): it calls libeldenring::version::get_version()
    // which panics outside a running ER process. The function is exercised
    // indirectly when apply_speffect runs in-game.
}
