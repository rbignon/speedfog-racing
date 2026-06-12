//! Shared helpers for locating and patching code inside the live
//! `eldenring.exe` module image. Windows-only (queries module info and writes
//! to the executable's pages). The pure pattern-matching logic lives in
//! `crate::core::aob`.

use std::ffi::c_void;

use windows::Win32::Foundation::HMODULE;
use windows::Win32::System::Diagnostics::Debug::FlushInstructionCache;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Memory::{
    VirtualProtect, PAGE_EXECUTE_READWRITE, PAGE_PROTECTION_FLAGS,
};
use windows::Win32::System::ProcessStatus::{GetModuleInformation, MODULEINFO};
use windows::Win32::System::Threading::GetCurrentProcess;

/// Base address and image size of the main module (`eldenring.exe`), or `None`
/// if querying the module info fails.
pub(crate) fn module_base_and_size() -> Option<(usize, usize)> {
    unsafe {
        // Passing None to GetModuleHandleW returns a handle to the executable
        // that loaded this DLL, i.e. eldenring.exe.
        let module: HMODULE = GetModuleHandleW(None).ok()?;
        let mut info = MODULEINFO::default();
        if GetModuleInformation(
            GetCurrentProcess(),
            module,
            &mut info,
            std::mem::size_of::<MODULEINFO>() as u32,
        )
        .is_err()
        {
            return None;
        }
        Some((info.lpBaseOfDll as usize, info.SizeOfImage as usize))
    }
}

/// Address of the first match of `pattern` in `[base, base+size)`, or `None`.
pub(crate) fn scan_pattern(base: usize, size: usize, pattern: &[Option<u8>]) -> Option<usize> {
    if size == 0 {
        return None;
    }
    // SAFETY: the module was mapped by the OS; base..base+size is readable.
    let mem = unsafe { std::slice::from_raw_parts(base as *const u8, size) };
    crate::core::aob::find_first(mem, pattern).map(|i| base + i)
}

/// Address of the unique match of `pattern` in `[base, base+size)`.
/// `Err(0)` = not found; `Err(2)` = found two or more times (ambiguous).
pub(crate) fn scan_unique(
    base: usize,
    size: usize,
    pattern: &[Option<u8>],
) -> Result<usize, usize> {
    if size == 0 {
        return Err(0);
    }
    // SAFETY: the module was mapped by the OS; base..base+size is readable.
    let mem = unsafe { std::slice::from_raw_parts(base as *const u8, size) };
    crate::core::aob::find_unique(mem, pattern).map(|i| base + i)
}

/// Overwrite `bytes.len()` bytes at `addr` inside an executable page.
/// Temporarily flips the page to RWX, writes, restores the original
/// protection, then flushes the instruction cache.
///
/// # Safety
/// `addr` must point at `bytes.len()` writable-after-`VirtualProtect` bytes
/// inside a mapped module image, and overwriting them must produce valid code.
pub(crate) unsafe fn patch_bytes(addr: usize, bytes: &[u8]) -> windows::core::Result<()> {
    let mut old = PAGE_PROTECTION_FLAGS(0);
    VirtualProtect(
        addr as *const c_void,
        bytes.len(),
        PAGE_EXECUTE_READWRITE,
        &mut old,
    )?;
    std::ptr::copy_nonoverlapping(bytes.as_ptr(), addr as *mut u8, bytes.len());
    let mut restored = PAGE_PROTECTION_FLAGS(0);
    VirtualProtect(addr as *const c_void, bytes.len(), old, &mut restored)?;
    FlushInstructionCache(
        GetCurrentProcess(),
        Some(addr as *const c_void),
        bytes.len(),
    )?;
    Ok(())
}
