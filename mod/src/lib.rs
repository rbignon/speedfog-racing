// SpeedFog Racing Mod for Elden Ring

pub mod core;

#[cfg(target_os = "windows")]
mod eldenring;

#[cfg(target_os = "windows")]
mod dll;

#[cfg(target_os = "windows")]
use std::ffi::c_void;

#[cfg(target_os = "windows")]
use hudhook::hooks::dx12::ImguiDx12Hooks;
#[cfg(target_os = "windows")]
use hudhook::{eject, Hudhook};
#[cfg(target_os = "windows")]
use tracing::{error, info};
#[cfg(target_os = "windows")]
use tracing_subscriber::{fmt, EnvFilter};
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::HINSTANCE;
#[cfg(target_os = "windows")]
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;

#[cfg(target_os = "windows")]
use crate::dll::RaceTracker;

#[cfg(target_os = "windows")]
fn init_logging() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    fmt().with_env_filter(filter).with_ansi(false).init();
}

#[cfg(target_os = "windows")]
fn start_mod(hmodule: HINSTANCE) {
    init_logging();
    info!("SpeedFog Racing mod starting...");

    let tracker = match RaceTracker::new(hmodule) {
        Some(t) => t,
        None => {
            error!("Failed to initialize RaceTracker");
            eject();
            return;
        }
    };

    if let Err(e) = Hudhook::builder()
        .with::<ImguiDx12Hooks>(tracker)
        .with_hmodule(hmodule)
        .build()
        .apply()
    {
        error!("Couldn't apply hooks: {e:?}");
        eject();
    }
}

#[cfg(target_os = "windows")]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "system" fn DllMain(hmodule: HINSTANCE, reason: u32, _: *mut c_void) -> bool {
    if reason == DLL_PROCESS_ATTACH {
        if libeldenring::version::check_version().is_err() {
            return false;
        }
        std::thread::spawn(move || {
            start_mod(hmodule);
        });
    }
    true
}
