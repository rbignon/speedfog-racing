//! Return-to-title bit reader, debug-overlay telemetry only.
//!
//! Reads the `return_title_requested` flag: bit 11 of
//! `CSLuaEventProxy.control_flags`, set by `RegistReturnTitle`. Live testing
//! showed it only fires on scripted returns to title (endings, arena), never
//! on the pause menu "Quit game", so quit-out detection instead relies on
//! the IGT regression a menu save-load produces (see `RaceMachine::tick`).
//!
//! ### Pattern source
//!
//! AOB lifted from the TGA Cheat Engine table v1.17.0 (`CSLuaEventManager`):
//! a `cmp qword ptr [rip+disp32], 0` on the CSLuaEventMan static. Struct
//! offsets derived from fromsoftware-rs `cs/lua_event_man.rs`
//! (proxy pointer at +0x8, `LuaEventControlFlags` u32 at +0x88).

use std::sync::OnceLock;

use tracing::{info, warn};

use super::scan::{module_base_and_size, scan_pattern};
use crate::core::aob::rip_relative_target;
use crate::profile_span;

/// `48 83 3D ?? ?? ?? ?? 00 48 8B F9 0F 84 ?? ?? ?? ?? 48`
const CS_LUA_EVENT_MAN_PATTERN: &[Option<u8>] = &[
    Some(0x48),
    Some(0x83),
    Some(0x3D),
    None,
    None,
    None,
    None,
    Some(0x00),
    Some(0x48),
    Some(0x8B),
    Some(0xF9),
    Some(0x0F),
    Some(0x84),
    None,
    None,
    None,
    None,
    Some(0x48),
];

/// `cmp qword ptr [rip+disp32], imm8` is 8 bytes: 3 opcode, 4 disp, 1 imm.
const CMP_RIP_IMM8_LEN: usize = 8;
const DISP32_OFFSET: usize = 3;

const LUA_EVENT_PROXY_OFFSET: usize = 0x8;
const CONTROL_FLAGS_OFFSET: usize = 0x88;
const RETURN_TITLE_BIT: u32 = 11;

/// Address of the CSLuaEventMan static pointer. Resolved once per process;
/// `None` means the AOB scan failed (fallback detection takes over).
static STATIC_ADDR: OnceLock<Option<usize>> = OnceLock::new();

fn resolve_static() -> Option<usize> {
    *STATIC_ADDR.get_or_init(|| {
        profile_span!("quitout_aob_scan");
        let (base, size) = match module_base_and_size() {
            Some(v) => v,
            None => {
                warn!("[QUITOUT] Failed to query eldenring.exe module info");
                return None;
            }
        };
        match scan_pattern(base, size, CS_LUA_EVENT_MAN_PATTERN) {
            Some(match_addr) => {
                // SAFETY: match_addr..match_addr+pattern_len is inside the scanned
                // module image (scan_pattern's Some contract); disp32 at +3 is not
                // 4-aligned, hence read_unaligned.
                let disp = unsafe { ((match_addr + DISP32_OFFSET) as *const i32).read_unaligned() };
                let addr = rip_relative_target(match_addr, disp, CMP_RIP_IMM8_LEN);
                info!(
                    addr = format!("0x{addr:X}"),
                    "[QUITOUT] Resolved CSLuaEventMan static"
                );
                Some(addr)
            }
            None => {
                warn!(
                    "[QUITOUT] CSLuaEventMan AOB not found; \
                     falling back to title-screen detection"
                );
                None
            }
        }
    })
}

/// Whether the primary signal resolved (drives the machine's fallback mode).
pub fn is_available() -> bool {
    resolve_static().is_some()
}

/// Current value of `return_title_requested`. `None` when the AOB scan
/// failed or a pointer link is null (e.g. before the menu system exists).
pub fn read_return_title_requested() -> Option<bool> {
    profile_span!("read_return_title_requested");
    let static_addr = resolve_static()?;
    // SAFETY: static_addr points into eldenring.exe's mapped image; the
    // instance and proxy pointers are null-checked before each deref.
    unsafe {
        let instance = (static_addr as *const usize).read();
        if instance == 0 {
            return None;
        }
        let proxy = ((instance + LUA_EVENT_PROXY_OFFSET) as *const usize).read();
        if proxy == 0 {
            return None;
        }
        let flags = ((proxy + CONTROL_FLAGS_OFFSET) as *const u32).read();
        Some(flags & (1 << RETURN_TITLE_BIT) != 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pattern_matches_cmp_rip_prefix() {
        // 18 bytes (cmp 8 + mov rdi,rcx 3 + jz rel32 6 + 1); starts with the
        // cmp qword [rip+disp32], 0 opcode.
        assert_eq!(CS_LUA_EVENT_MAN_PATTERN.len(), 18);
        assert_eq!(CS_LUA_EVENT_MAN_PATTERN[0], Some(0x48));
        assert_eq!(CS_LUA_EVENT_MAN_PATTERN[1], Some(0x83));
        assert_eq!(CS_LUA_EVENT_MAN_PATTERN[2], Some(0x3D));
        assert_eq!(CS_LUA_EVENT_MAN_PATTERN[7], Some(0x00));
    }
}
