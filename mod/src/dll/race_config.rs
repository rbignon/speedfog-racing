//! Configuration for SpeedFog Racing mod
//!
//! Loads settings from speedfog_race.toml next to the DLL.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tracing::{error, info};
use windows::Win32::Foundation::HINSTANCE;
use windows::Win32::System::LibraryLoader::GetModuleFileNameW;

/// Server connection settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerSettings {
    /// WebSocket server URL (e.g., "wss://speedfog-racing.example.com")
    pub url: String,
    /// Participant's mod token (unique per player per race)
    pub mod_token: String,
    /// Race ID (UUID)
    pub race_id: String,
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            url: String::new(),
            mod_token: String::new(),
            race_id: String::new(),
        }
    }
}

/// Overlay display settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OverlaySettings {
    /// Enable overlay
    #[serde(default = "default_enabled")]
    pub enabled: bool,
    /// Font size
    #[serde(default = "default_font_size")]
    pub font_size: f32,
}

fn default_enabled() -> bool {
    true
}
fn default_font_size() -> f32 {
    16.0
}

impl Default for OverlaySettings {
    fn default() -> Self {
        Self {
            enabled: default_enabled(),
            font_size: default_font_size(),
        }
    }
}

/// Keybindings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyBindings {
    /// Toggle UI visibility
    #[serde(default = "default_toggle_ui")]
    pub toggle_ui: String,
}

fn default_toggle_ui() -> String {
    "f9".to_string()
}

impl Default for KeyBindings {
    fn default() -> Self {
        Self {
            toggle_ui: default_toggle_ui(),
        }
    }
}

/// Main config structure
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RaceConfig {
    #[serde(default)]
    pub server: ServerSettings,
    #[serde(default)]
    pub overlay: OverlaySettings,
    #[serde(default)]
    pub keybindings: KeyBindings,
}

impl RaceConfig {
    pub const CONFIG_FILENAME: &'static str = "speedfog_race.toml";

    /// Get DLL directory path
    pub fn get_dll_directory(hmodule: HINSTANCE) -> Option<PathBuf> {
        let mut buffer = [0u16; 260];
        let len = unsafe { GetModuleFileNameW(hmodule, &mut buffer) } as usize;
        if len == 0 || len >= buffer.len() {
            return None;
        }
        let dll_path = String::from_utf16_lossy(&buffer[..len]);
        PathBuf::from(dll_path).parent().map(|p| p.to_path_buf())
    }

    /// Load config from file next to DLL
    pub fn load(hmodule: HINSTANCE) -> Result<Self, String> {
        let dir = Self::get_dll_directory(hmodule).ok_or("Could not get DLL directory")?;
        let config_path = dir.join(Self::CONFIG_FILENAME);

        if !config_path.exists() {
            return Err(format!("Config file not found: {}", config_path.display()));
        }

        let contents = fs::read_to_string(&config_path)
            .map_err(|e| format!("Failed to read config: {}", e))?;

        let config: RaceConfig =
            toml::from_str(&contents).map_err(|e| format!("Failed to parse config: {}", e))?;

        info!(path = %config_path.display(), "Loaded race config");
        Ok(config)
    }

    /// Check if config is valid for racing
    pub fn is_valid(&self) -> bool {
        !self.server.url.is_empty()
            && !self.server.mod_token.is_empty()
            && !self.server.race_id.is_empty()
    }
}
