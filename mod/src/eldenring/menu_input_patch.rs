//! Removes the 1.12+ "prevent accidental skips" menu input delay by reverting
//! the per-dialog threshold setter to its inert 1.11 form.
//!
//! ### Mechanism
//!
//! 1.12 introduced a per-dialog confirm delay: a threshold (~0.32 s) is stored
//! into each dialog template by a tiny setter, then a per-frame accumulator
//! must reach it before confirm is accepted. In 1.11 that setter was an empty
//! stub (`mov rax,rcx; ret`), so the threshold stayed 0 and confirm was
//! instant. We restore that stub at runtime: locate the setter by AOB and
//! overwrite its 4-byte prologue. Because the setter runs at dialog-template
//! creation, patching it once affects every dialog opened afterward (yes/no
//! boxes and conversation menus alike). No per-frame cost.
//!
//! On builds without the delay (e.g. 1.11) the AOB does not match and this is
//! a no-op. See `docs/MENU_INPUT_SKIP.md`.

use std::sync::OnceLock;

use tracing::{error, info, warn};

use super::scan::{module_base_and_size, patch_bytes, scan_unique};

/// AOB of the threshold setter. `None` wildcards the call rel32 (bytes 10-13)
/// and the destination field disp8 (byte 18), so the pattern survives those
/// varying across builds. Matches exactly one function on builds with the
/// delay (validated 1.12, 1.13).
const SETTER_PATTERN: &[Option<u8>] = &[
    Some(0x40),
    Some(0x53),
    Some(0x48),
    Some(0x83),
    Some(0xEC),
    Some(0x20),
    Some(0x48),
    Some(0x8B),
    Some(0xD9),
    Some(0xE8),
    None,
    None,
    None,
    None,
    Some(0xF3),
    Some(0x0F),
    Some(0x11),
    Some(0x43),
    None,
    Some(0x48),
    Some(0x8B),
    Some(0xC3),
    Some(0x48),
    Some(0x83),
    Some(0xC4),
    Some(0x20),
    Some(0x5B),
    Some(0xC3),
];

/// `mov rax, rcx ; ret` -- the inert 1.11 stub. Overwrites the first 4 bytes
/// of the setter prologue.
const STUB: [u8; 4] = [0x48, 0x8B, 0xC1, 0xC3];

/// Latched once so the patch is applied at most once per process.
static INSTALLED: OnceLock<bool> = OnceLock::new();

/// Apply the menu-input delay removal. Idempotent; logs and continues on any
/// failure (missing module info, pattern not found, ambiguous match, or write
/// failure) without aborting mod init.
pub fn install() {
    INSTALLED.get_or_init(|| {
        let Some((base, size)) = module_base_and_size() else {
            error!("menu-input patch: failed to query eldenring.exe module info");
            return false;
        };
        match scan_unique(base, size, SETTER_PATTERN) {
            Ok(addr) => {
                // SAFETY: `addr` is the unique match of the setter prologue inside
                // the module's executable image; STUB is valid code (`mov rax,rcx;
                // ret`) of the same length we overwrite.
                match unsafe { patch_bytes(addr, &STUB) } {
                    Ok(()) => {
                        info!(
                            addr = format!("0x{addr:X}"),
                            "menu-input delay patch applied"
                        );
                        true
                    }
                    Err(e) => {
                        error!(error = %e, "menu-input patch: memory write failed");
                        false
                    }
                }
            }
            Err(0) => {
                info!("menu-input patch: setter not found (build has no delay); skipping");
                false
            }
            Err(_) => {
                warn!("menu-input patch: pattern not unique; skipping for safety");
                false
            }
        }
    });
}
