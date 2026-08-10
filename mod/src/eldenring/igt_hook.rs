//! In-game IGT truncation-fix hook, ported from SoulSplitter's soulmods
//! (https://github.com/FrankvdStam/SoulSplitter, GPLv3; compatible with
//! this crate's AGPL-3.0). See `core::igt_fix` for the arithmetic and the
//! rationale.
//!
//! The hooked site sits inside the game's IGT-increment function, right
//! after the `mulss` that scales the raw frame delta: xmm0 still holds the
//! delta in seconds, xmm1 the scaled value the game is about to truncate.
//! The callback recomputes the increment through the fractional
//! accumulator and overwrites xmm1 with a whole-millisecond value, so the
//! game's own cast loses nothing.
//!
//! Failure policy: warn + continue. If the pattern is missing (game patch,
//! or another IGT tool such as SoulSplitter already patched these bytes),
//! the fix is disabled and racing proceeds on vanilla IGT; a game patch
//! affects every participant of a seed identically.

use ilhook::x64::{CallbackOption, HookFlags, HookType, Hooker, Registers};
use parking_lot::Mutex;
use tracing::{info, warn};

use super::scan::{module_base_and_size, scan_pattern_unique};
use crate::core::igt_fix::IgtFix;
use crate::profile_span;

/// SoulSplitter's `increment igt` pattern (soulmods `eldenring.rs`), one
/// row per instruction:
/// `mov qword [rsp+0x20], -2; movaps [rsp+0x40], xmm6; movaps xmm6, xmm0;`
/// `mov rcx, [rip+?]; movaps xmm1, xmm0; mulss xmm1, [rip+?]`.
const INCREMENT_IGT_PATTERN: &[Option<u8>] = &[
    Some(0x48),
    Some(0xC7),
    Some(0x44),
    Some(0x24),
    Some(0x20),
    Some(0xFE),
    Some(0xFF),
    Some(0xFF),
    Some(0xFF),
    Some(0x0F),
    Some(0x29),
    Some(0x74),
    Some(0x24),
    Some(0x40),
    Some(0x0F),
    Some(0x28),
    Some(0xF0),
    Some(0x48),
    Some(0x8B),
    Some(0x0D),
    None,
    None,
    None,
    None,
    Some(0x0F),
    Some(0x28),
    Some(0xC8),
    Some(0xF3),
    Some(0x0F),
    Some(0x59),
    Some(0x0D),
    None,
    None,
    None,
    None,
];

/// Shared with nothing but the hook callback; uncontended lock, once per
/// game frame.
static IGT_FIX: Mutex<IgtFix> = Mutex::new(IgtFix::new());

/// JmpBack callback: runs on the game's frame thread at the hook site.
/// Keep it allocation-free and branch-light (per-frame path).
unsafe extern "win64" fn increment_igt(registers: *mut Registers, _: usize) {
    let frame_delta_secs = f32::from_bits((*registers).xmm0 as u32);
    let corrected = IGT_FIX.lock().corrected_delta_ms(frame_delta_secs);
    (*registers).xmm1 = f32::to_bits(corrected) as u128;
}

/// Scan and install the hook. Called once from `RaceTracker::new` on a
/// background thread (the scan walks the whole module image). The hook
/// stays installed for the process lifetime: the `HookPoint` is
/// deliberately leaked, mirroring the never-uninstalled warp detour.
pub fn install() {
    profile_span!("igt_hook_install");
    let Some((base, size)) = module_base_and_size() else {
        warn!("[IGT] Failed to query eldenring.exe module info; truncation fix disabled");
        return;
    };
    let Some(match_addr) = scan_pattern_unique(base, size, INCREMENT_IGT_PATTERN) else {
        warn!(
            "[IGT] increment-IGT pattern absent or ambiguous (game patch, or another \
             IGT tool already hooked it); truncation fix disabled"
        );
        return;
    };
    let hook_addr = match_addr + INCREMENT_IGT_PATTERN.len();
    // SAFETY: hook_addr points at an instruction boundary inside the
    // scanned image (pattern ends exactly on the mulss); ilhook writes the
    // detour with the same mechanics upstream has used for years.
    let result = unsafe {
        Hooker::new(
            hook_addr,
            HookType::JmpBack(increment_igt),
            CallbackOption::None,
            0,
            HookFlags::empty(),
        )
        .hook()
    };
    match result {
        Ok(hook) => {
            // Never unhooked: dropping the HookPoint would unpatch the
            // site while the game may be executing it.
            std::mem::forget(hook);
            info!(
                addr = format!("0x{hook_addr:X}"),
                "[IGT] Truncation-fix hook installed"
            );
        }
        Err(e) => warn!(error = ?e, "[IGT] Failed to install truncation-fix hook"),
    }
}
