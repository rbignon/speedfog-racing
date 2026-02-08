// SpeedFog Racing Mod for Elden Ring

pub mod core;

#[cfg(target_os = "windows")]
mod eldenring;

#[cfg(target_os = "windows")]
mod dll;

#[cfg(target_os = "windows")]
use std::ffi::c_void;
#[cfg(target_os = "windows")]
use std::sync::OnceLock;

#[cfg(target_os = "windows")]
use hudhook::hooks::dx12::ImguiDx12Hooks;
#[cfg(target_os = "windows")]
use hudhook::{eject, Hudhook};
#[cfg(target_os = "windows")]
use tracing::{error, info};
#[cfg(target_os = "windows")]
use tracing_subscriber::layer::SubscriberExt;
#[cfg(target_os = "windows")]
use tracing_subscriber::{fmt, EnvFilter, Registry};
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::HINSTANCE;
#[cfg(target_os = "windows")]
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;

#[cfg(target_os = "windows")]
use crate::dll::config::RaceConfig;
#[cfg(target_os = "windows")]
use crate::dll::RaceTracker;

/// Keeps the log writer alive for the DLL's lifetime. Its Drop impl flushes
/// remaining buffered messages when DLL_PROCESS_DETACH triggers cleanup.
#[cfg(target_os = "windows")]
static LOG_GUARD: OnceLock<tracing_appender::non_blocking::WorkerGuard> = OnceLock::new();

#[cfg(target_os = "windows")]
fn init_logging(hmodule: HINSTANCE) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    if let Some(dll_dir) = RaceConfig::get_dll_directory(hmodule) {
        let file_appender = tracing_appender::rolling::never(&dll_dir, "speedfog_racing.log");
        let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);
        LOG_GUARD.set(guard).ok();

        let subscriber = Registry::default()
            .with(filter)
            .with(fmt::layer().with_writer(non_blocking).with_ansi(false));
        tracing::subscriber::set_global_default(subscriber).ok();
    } else {
        // Fallback: stderr only (original behavior)
        fmt().with_env_filter(filter).with_ansi(false).init();
    }
}

#[cfg(target_os = "windows")]
fn start_mod(hmodule: HINSTANCE) {
    init_logging(hmodule);
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
