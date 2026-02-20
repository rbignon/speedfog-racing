//! Configuration for SpeedFog Racing mod
//!
//! Loads settings from speedfog_race.toml next to the DLL.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tracing::info;
use windows::Win32::Foundation::HINSTANCE;
use windows::Win32::System::LibraryLoader::GetModuleFileNameW;

use super::hotkey::Hotkey;

/// Server connection settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerSettings {
    /// WebSocket server URL (e.g., "wss://speedfog-racing.example.com")
    pub url: String,
    /// Participant's mod token (unique per player per race)
    pub mod_token: String,
    /// Race ID (UUID)
    pub race_id: String,
    /// Training mode — hides leaderboard, uses /ws/training/ endpoint
    #[serde(default)]
    pub training: bool,
    /// Seed ID from seed pack — used to detect stale packs after seed re-roll
    #[serde(default)]
    pub seed_id: String,
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            url: String::new(),
            mod_token: String::new(),
            race_id: String::new(),
            training: false,
            seed_id: String::new(),
        }
    }
}

/// Overlay display settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OverlaySettings {
    /// Enable overlay
    #[serde(default = "default_enabled")]
    pub enabled: bool,

    /// Path to TTF font file.
    ///   - Empty "": uses Windows system font (Segoe UI)
    ///   - Filename only "arial.ttf": looks in C:\Windows\Fonts\ then DLL directory
    ///   - Relative path "fonts/custom.ttf": relative to DLL directory
    ///   - Absolute path "C:\Fonts\MyFont.ttf": uses the specified file
    #[serde(default)]
    pub font_path: String,

    /// Font size in pixels (32.0 recommended for 1080p, 64.0 for 4K)
    #[serde(default = "default_font_size")]
    pub font_size: f32,

    /// Background color as hex "#RRGGBB"
    #[serde(default = "default_background_color")]
    pub background_color: String,

    /// Background opacity (0.0 = fully transparent, 1.0 = fully opaque)
    #[serde(default = "default_background_opacity")]
    pub background_opacity: f32,

    /// Main text color as hex "#RRGGBB"
    #[serde(default = "default_text_color")]
    pub text_color: String,

    /// Secondary/disabled text color as hex "#RRGGBB"
    #[serde(default = "default_text_disabled_color")]
    pub text_disabled_color: String,

    /// Show window border
    #[serde(default)]
    pub show_border: bool,

    /// Border color as hex "#RRGGBB" (only used if show_border = true)
    #[serde(default = "default_border_color")]
    pub border_color: String,

    /// Horizontal margin from the right edge of the screen in pixels.
    #[serde(default = "default_position_offset_x")]
    pub position_offset_x: f32,

    /// Vertical margin from the top edge of the screen in pixels.
    #[serde(default = "default_position_offset_y")]
    pub position_offset_y: f32,
}

fn default_enabled() -> bool {
    true
}
fn default_font_size() -> f32 {
    32.0
}
fn default_background_color() -> String {
    "#141414".to_string()
}
fn default_background_opacity() -> f32 {
    0.3
}
fn default_text_color() -> String {
    "#FFFFFF".to_string()
}
fn default_text_disabled_color() -> String {
    "#808080".to_string()
}
fn default_border_color() -> String {
    "#404040".to_string()
}
fn default_position_offset_x() -> f32 {
    20.0
}
fn default_position_offset_y() -> f32 {
    20.0
}

impl Default for OverlaySettings {
    fn default() -> Self {
        Self {
            enabled: default_enabled(),
            font_path: String::new(),
            font_size: default_font_size(),
            background_color: default_background_color(),
            background_opacity: default_background_opacity(),
            text_color: default_text_color(),
            text_disabled_color: default_text_disabled_color(),
            show_border: false,
            border_color: default_border_color(),
            position_offset_x: default_position_offset_x(),
            position_offset_y: default_position_offset_y(),
        }
    }
}

/// Keybindings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyBindings {
    /// Toggle UI visibility
    #[serde(default)]
    pub toggle_ui: Hotkey,
    /// Toggle debug overlay section
    #[serde(default = "default_toggle_debug")]
    pub toggle_debug: Hotkey,
    /// Toggle leaderboard visibility
    #[serde(default = "default_toggle_leaderboard")]
    pub toggle_leaderboard: Hotkey,
}

fn default_toggle_debug() -> Hotkey {
    Hotkey { key: 0x72 } // F3
}

fn default_toggle_leaderboard() -> Hotkey {
    Hotkey { key: 0x79 } // F10
}

impl Default for KeyBindings {
    fn default() -> Self {
        Self {
            toggle_ui: Hotkey::default(),
            toggle_debug: default_toggle_debug(),
            toggle_leaderboard: default_toggle_leaderboard(),
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
