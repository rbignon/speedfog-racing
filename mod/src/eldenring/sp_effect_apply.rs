//! Runtime SpEffect application for the local player.
//!
//! Used by the phantom skins feature to apply a cosmetic aura (a SpEffect
//! baked by speedfog into regulation.bin, e.g. id 1450700 for `gold-aura`)
//! to the player at game-world load time, and by race items to apply their
//! effects and set the time left of a timed one (`set_speffect_timer`).
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
//! `AOBScanModuleUnique(...) - 0x1D`, and is kept only when the wrapper's
//! prologue sits there (`WRAPPER_PROLOGUE`).

use std::ffi::c_void;
use std::sync::OnceLock;

use super::race_items::layout_known;
use super::scan::{module_base_and_size, scan_pattern_unique};
use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use tracing::{debug, error, info, warn};

use crate::profile_span;

const PLAYER_INS_OFFSET_NEW: usize = 0x1E508; // V1_07_0+
const PLAYER_INS_OFFSET_OLD: usize = 0x18468; // V1_02 .. V1_06
const SP_EFFECT_CTRL_OFFSET: usize = 0x178;

// The player's active SpEffect list (fromsoftware-rs `cs/sp_effect.rs`,
// `SpecialEffect` and `SpecialEffectEntry`; the TGA v1.17.0 table's
// "Active Effects" reads the same fields): the `SpecialEffect` at
// `SP_EFFECT_CTRL_OFFSET` holds the head entry, each entry its param id, the
// next entry and its removal timer.
const SP_EFFECT_HEAD_OFFSET: usize = 0x8;
const SP_EFFECT_ENTRY_PARAM_ID_OFFSET: usize = 0x8;
const SP_EFFECT_ENTRY_NEXT_OFFSET: usize = 0x30;
/// Seconds left before the game removes the entry (TGA "Duration"; the
/// row's full duration, TGA "Total Duration", follows at +0x48).
const SP_EFFECT_ENTRY_REMOVAL_TIMER_OFFSET: usize = 0x40;
/// Entries walked at most: a bound against a corrupt or cyclic list.
const SP_EFFECT_LIST_MAX_ENTRIES: usize = 256;

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

/// The prologue expected at the entry: `mov rax, rsp; mov [rax+8], rbx;`
/// `mov [rax+0x10], rsi; push rdi; sub rsp, 0xC0`. The same bytes in every
/// executable from 1.10 to 1.17.2. The pattern matches inside the body, so
/// a build that keeps the body but changes what precedes it would put the
/// entry mid-instruction: the address is executed only behind this check.
const WRAPPER_PROLOGUE: [u8; 19] = [
    0x48, 0x8B, 0xC4, 0x48, 0x89, 0x58, 0x08, 0x48, 0x89, 0x70, 0x10, 0x57, 0x48, 0x81, 0xEC, 0xC0,
    0x00, 0x00, 0x00,
];

/// MS x64 calling convention, registers only:
/// - RCX = ChrIns* (the character receiving the effect; here PlayerIns)
/// - EDX = effect_id
/// - R8D = flag; the TGA `addForSelf` script always passes 1
///
/// No stack arguments: see the module docs for why that matters.
type ApplySpEffectFn = unsafe extern "system" fn(chr_ins: *mut c_void, effect_id: u32, flag: u32);

/// Resolved once per process. None means the scan or the prologue check
/// failed.
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
        let Some(found) = scan_pattern_unique(base, size, APPLY_SP_EFFECT_PATTERN) else {
            warn!("ApplySpEffect AOB pattern not found (or ambiguous) in eldenring.exe");
            return None;
        };
        // SAFETY: an entry at or past `base` lies in the module image
        // scanned above, its 19 bytes ending before the match.
        let Some(entry) = found.checked_sub(WRAPPER_ENTRY_OFFSET).filter(|&entry| {
            entry >= base
                && unsafe { std::slice::from_raw_parts(entry as *const u8, WRAPPER_PROLOGUE.len()) }
                    == WRAPPER_PROLOGUE
        }) else {
            warn!(
                found = format_args!("0x{found:X}"),
                "ApplySpEffect prologue not the expected one, SpEffects disabled"
            );
            return None;
        };
        info!(
            addr = format!("0x{entry:X}"),
            "Resolved ApplySpEffect function"
        );
        Some(entry)
    })
}

/// Resolve the apply function now: its pattern scan walks the whole game
/// image, a cost the first `apply_speffect` would otherwise pay on the
/// thread that calls it (a frame stall on the render thread). Idempotent;
/// call it from a background thread.
pub fn prewarm() {
    profile_span!("sp_effect_apply.prewarm");
    let _ = resolve_apply_fn();
}

/// Read PlayerIns from WorldChrMan. Returns null until the player is loaded
/// into the game world.
pub(super) fn read_player_ins(pointers: &Pointers) -> *mut c_void {
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

/// Write `seconds` as the time left of the player's active SpEffect
/// `effect_id` (its entry's removal timer). False when the player, its
/// SpEffect list or an entry with that id is not found, or the write fails.
/// Every read after PlayerIns (which `read_player_ins` reads raw, as
/// `apply_speffect` does) and the write go through `PointerChain`
/// (ReadProcessMemory / WriteProcessMemory), so an entry freed under the
/// walk fails instead of faulting. The list's offsets are 1.17.x's: false
/// on another game version (`layout_known`), where the row then runs its
/// own duration.
pub fn set_speffect_timer(effect_id: u32, seconds: f32) -> bool {
    profile_span!("sp_effect_apply.set_speffect_timer");
    let player_ins = read_player_ins(&Pointers::new());
    if player_ins.is_null() || !layout_known() {
        return false;
    }
    let read_ptr = |addr: usize| {
        PointerChain::<usize>::new(&[addr])
            .read()
            .filter(|&ptr| ptr != 0)
    };
    let Some(sp_effect) = read_ptr(player_ins as usize + SP_EFFECT_CTRL_OFFSET) else {
        return false;
    };
    let mut entry = read_ptr(sp_effect + SP_EFFECT_HEAD_OFFSET);
    for _ in 0..SP_EFFECT_LIST_MAX_ENTRIES {
        let Some(addr) = entry else {
            return false;
        };
        let Some(param_id) =
            PointerChain::<i32>::new(&[addr + SP_EFFECT_ENTRY_PARAM_ID_OFFSET]).read()
        else {
            return false;
        };
        if u32::try_from(param_id) == Ok(effect_id) {
            return PointerChain::<f32>::new(&[addr + SP_EFFECT_ENTRY_REMOVAL_TIMER_OFFSET])
                .write(seconds)
                .is_some();
        }
        entry = read_ptr(addr + SP_EFFECT_ENTRY_NEXT_OFFSET);
    }
    // A list of exactly the bound ends here; only a further entry is one
    // the walk never read.
    if entry.is_some() {
        warn!(
            effect_id,
            max = SP_EFFECT_LIST_MAX_ENTRIES,
            "[ITEMS] SpEffect list longer than the walk bound, timer not set"
        );
    }
    false
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
