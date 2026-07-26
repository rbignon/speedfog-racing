//! Shared helpers for locating code inside the live `eldenring.exe` module
//! image. Windows-only (queries module info). The pure pattern-matching logic
//! lives in `crate::core::aob`.

use windows::Win32::Foundation::HMODULE;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
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

/// Address of the only match of `pattern` in `[base, base+size)`; `None` if
/// the pattern is absent or ambiguous (matches more than once).
pub(crate) fn scan_pattern_unique(
    base: usize,
    size: usize,
    pattern: &[Option<u8>],
) -> Option<usize> {
    if size == 0 {
        return None;
    }
    // SAFETY: the module was mapped by the OS; base..base+size is readable.
    let mem = unsafe { std::slice::from_raw_parts(base as *const u8, size) };
    crate::core::aob::find_unique(mem, pattern).map(|i| base + i)
}
