//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress via EMEVD event flags and communicates with the racing server.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::protocol::{ParticipantInfo, RaceInfo, SeedInfo};
use crate::core::traits::GameStateReader;
use crate::eldenring::{EventFlagReader, GameState};

use super::config::RaceConfig;
use super::hotkey::begin_hotkey_frame;
use super::websocket::{ConnectionStatus, IncomingMessage, RaceWebSocketClient};

// =============================================================================
// RACE STATE
// =============================================================================

/// Current race state from server
#[derive(Debug, Clone, Default)]
pub struct RaceState {
    pub race: Option<RaceInfo>,
    pub seed: Option<SeedInfo>,
    pub participants: Vec<ParticipantInfo>,
    pub race_started: bool,
}

/// Debug overlay info
pub struct DebugInfo<'a> {
    pub last_sent: Option<&'a str>,
    pub last_received: Option<&'a str>,
}

// =============================================================================
// RACE TRACKER
// =============================================================================

pub struct RaceTracker {
    // Game reader
    game_state: GameState,

    // Event flag reader
    event_flag_reader: EventFlagReader,

    // WebSocket
    pub(crate) ws_client: RaceWebSocketClient,

    // Config
    pub(crate) config: RaceConfig,

    // Font data loaded from file (for ImGui registration)
    pub(crate) font_data: Option<Vec<u8>>,

    // Race state
    pub(crate) race_state: RaceState,

    // UI state
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    last_sent_debug: Option<String>,
    last_received_debug: Option<String>,

    // Event flag tracking
    event_ids: Vec<u32>,
    pub(crate) triggered_flags: HashSet<u32>,

    // Status update throttle
    last_status_update: Instant,

    // Ready sent flag
    ready_sent: bool,
}

impl RaceTracker {
    pub fn new(hmodule: HINSTANCE) -> Option<Self> {
        info!("Initializing RaceTracker...");

        // Load config
        let config = match RaceConfig::load(hmodule) {
            Ok(cfg) => cfg,
            Err(e) => {
                error!(error = %e, "Failed to load config");
                return None;
            }
        };

        if !config.is_valid() {
            error!("Config is invalid (missing server/mod_token/race_id)");
            return None;
        }

        // Load font data
        let dll_dir = RaceConfig::get_dll_directory(hmodule);
        let font_data = dll_dir
            .as_ref()
            .and_then(|dir| load_font_data(dir, &config.overlay.font_path));

        // Init game state
        let game_state = GameState::new();
        game_state.wait_for_game_loaded();

        // Init event flag reader
        let event_flag_reader =
            EventFlagReader::new(game_state.base_addresses().csfd4_virtual_memory_flag);

        // Create WebSocket client
        let mut ws_client = RaceWebSocketClient::new(config.server.clone());
        ws_client.connect();

        info!("RaceTracker initialized");

        Some(Self {
            game_state,
            event_flag_reader,
            ws_client,
            config,
            font_data,
            race_state: RaceState::default(),
            show_ui: true,
            show_debug: false,
            last_sent_debug: None,
            last_received_debug: None,
            event_ids: Vec::new(),
            triggered_flags: HashSet::new(),
            last_status_update: Instant::now(),
            ready_sent: false,
        })
    }

    pub fn update(&mut self) {
        // Process hotkeys at start of frame
        begin_hotkey_frame();

        // Check toggle_ui hotkey
        if self.config.keybindings.toggle_ui.is_just_pressed() {
            self.show_ui = !self.show_ui;
            info!(show_ui = self.show_ui, "[HOTKEY] Toggle UI");
        }

        // Check toggle_debug hotkey
        if self.config.keybindings.toggle_debug.is_just_pressed() {
            self.show_debug = !self.show_debug;
            info!(show_debug = self.show_debug, "[HOTKEY] Toggle debug");
        }

        // Poll WebSocket
        while let Some(msg) = self.ws_client.poll() {
            self.handle_ws_message(msg);
        }

        // Skip game reading if not connected
        if !self.ws_client.is_connected() {
            return;
        }

        // Read game state
        let igt_ms = self.game_state.read_igt().unwrap_or(0);
        let deaths = self.game_state.read_deaths().unwrap_or(0);

        // Send ready once connected (if not already sent)
        if !self.ready_sent {
            self.ws_client.send_ready();
            self.last_sent_debug = Some("ready".to_string());
            self.ready_sent = true;
            info!("[RACE] Sent ready signal");

            // Re-scan all flags for reconnect recovery
            for &flag_id in &self.event_ids {
                if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                    self.triggered_flags.insert(flag_id);
                    self.ws_client.send_event_flag(flag_id, igt_ms);
                    self.last_sent_debug = Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                    info!(flag_id, "[RACE] Event flag re-sent after reconnect");
                }
            }
        }

        // Event flag polling (every tick)
        for &flag_id in &self.event_ids {
            if !self.triggered_flags.contains(&flag_id) {
                if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                    self.triggered_flags.insert(flag_id);
                    self.ws_client.send_event_flag(flag_id, igt_ms);
                    self.last_sent_debug = Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                    info!(flag_id, "[RACE] Event flag triggered");
                }
            }
        }

        // Send periodic status updates (every 1 second)
        if self.last_status_update.elapsed() >= Duration::from_secs(1) {
            self.ws_client.send_status_update(igt_ms, deaths);
            self.last_status_update = Instant::now();
        }
    }

    fn handle_ws_message(&mut self, msg: IncomingMessage) {
        match msg {
            IncomingMessage::StatusChanged(status) => {
                info!(status = ?status, "[WS] Status changed");
                if status == ConnectionStatus::Connected {
                    self.ready_sent = false; // Reset for reconnection
                }
            }
            IncomingMessage::AuthOk {
                race,
                seed,
                participants,
            } => {
                info!(race = %race.name, participants = participants.len(), "[WS] Auth OK");
                self.last_received_debug = Some(format!(
                    "auth_ok(race={}, {} players)",
                    race.name,
                    participants.len()
                ));
                self.event_ids = seed.event_ids.clone();
                self.triggered_flags.clear();
                self.race_state.race = Some(race);
                self.race_state.seed = Some(seed);
                self.race_state.participants = participants;
            }
            IncomingMessage::AuthError(msg) => {
                self.last_received_debug = Some(format!("auth_error({})", msg));
                error!(message = %msg, "[WS] Auth failed");
            }
            IncomingMessage::RaceStart => {
                self.last_received_debug = Some("race_start".to_string());
                info!("[WS] Race started!");
                self.race_state.race_started = true;
            }
            IncomingMessage::LeaderboardUpdate(participants) => {
                self.last_received_debug = Some(format!(
                    "leaderboard_update({} players)",
                    participants.len()
                ));
                debug!(count = participants.len(), "[WS] Leaderboard update");
                self.race_state.participants = participants;
            }
            IncomingMessage::RaceStatusChange(status) => {
                self.last_received_debug = Some(format!("race_status_change({})", status));
                info!(status = %status, "[WS] Race status changed");
                if let Some(ref mut race) = self.race_state.race {
                    race.status = status;
                }
            }
            IncomingMessage::PlayerUpdate(player) => {
                // Skip debug capture for player_update (too frequent)
                if let Some(p) = self
                    .race_state
                    .participants
                    .iter_mut()
                    .find(|p| p.id == player.id)
                {
                    *p = player;
                }
            }
            IncomingMessage::Error(e) => {
                self.last_received_debug = Some(format!("error({})", e));
                warn!(error = %e, "[WS] Error");
            }
        }
    }

    // Public getters for UI
    pub fn ws_status(&self) -> ConnectionStatus {
        self.ws_client.status()
    }

    pub fn race_info(&self) -> Option<&RaceInfo> {
        self.race_state.race.as_ref()
    }

    pub fn seed_info(&self) -> Option<&SeedInfo> {
        self.race_state.seed.as_ref()
    }

    pub fn participants(&self) -> &[ParticipantInfo] {
        &self.race_state.participants
    }

    pub fn read_igt(&self) -> Option<u32> {
        self.game_state.read_igt()
    }

    pub fn read_deaths(&self) -> Option<u32> {
        self.game_state.read_deaths()
    }

    pub fn triggered_count(&self) -> usize {
        self.triggered_flags.len()
    }

    pub fn total_flags(&self) -> usize {
        self.event_ids.len()
    }

    pub fn debug_info(&self) -> DebugInfo<'_> {
        DebugInfo {
            last_sent: self.last_sent_debug.as_deref(),
            last_received: self.last_received_debug.as_deref(),
        }
    }
}

// =============================================================================
// FONT LOADING
// =============================================================================

/// Load font data from file, following the same resolution strategy as er-fog-vizu:
///   - Empty path → system default (Segoe UI from C:\Windows\Fonts\)
///   - Filename only → try C:\Windows\Fonts\, then DLL directory
///   - Relative path with separators → relative to DLL directory
///   - Absolute path → use directly
fn load_font_data(dll_dir: &Path, font_path: &str) -> Option<Vec<u8>> {
    const WINDOWS_FONTS_DIR: &str = r"C:\Windows\Fonts";
    const DEFAULT_SYSTEM_FONT: &str = "segoeui.ttf";

    let paths_to_try: Vec<PathBuf> = if font_path.is_empty() {
        vec![Path::new(WINDOWS_FONTS_DIR).join(DEFAULT_SYSTEM_FONT)]
    } else {
        let path = Path::new(font_path);
        if path.is_absolute() {
            vec![path.to_path_buf()]
        } else if !font_path.contains('/') && !font_path.contains('\\') {
            // Filename only: try Windows Fonts first, then DLL dir
            vec![
                Path::new(WINDOWS_FONTS_DIR).join(font_path),
                dll_dir.join(font_path),
            ]
        } else {
            // Relative path with separators: DLL dir only
            vec![dll_dir.join(font_path)]
        }
    };

    for full_path in &paths_to_try {
        if full_path.exists() {
            match fs::read(full_path) {
                Ok(data) => {
                    info!(path = %full_path.display(), size = data.len(), "Loaded font");
                    return Some(data);
                }
                Err(e) => {
                    error!(path = %full_path.display(), error = %e, "Failed to read font file");
                }
            }
        }
    }

    let tried: String = paths_to_try
        .iter()
        .map(|p| p.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");
    warn!(tried_paths = %tried, "Font not found, using imgui default");
    None
}
