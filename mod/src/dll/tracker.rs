//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress via EMEVD event flags and communicates with the racing server.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::color::parse_hex_color;
use crate::core::protocol::{ExitInfo, ParticipantInfo, RaceInfo, SeedInfo};
use crate::core::traits::GameStateReader;
use crate::eldenring::{EventFlagReader, FlagReaderStatus, GameState};

use super::config::RaceConfig;
use super::hotkey::begin_hotkey_frame;
use super::websocket::{ConnectionStatus, IncomingMessage, RaceWebSocketClient};

// =============================================================================
// RACE STATE
// =============================================================================

/// Zone update data received from server
#[derive(Debug, Clone)]
pub struct ZoneUpdateData {
    pub node_id: String,
    pub display_name: String,
    pub tier: Option<i32>,
    pub exits: Vec<ExitInfo>,
}

/// Current race state from server
#[derive(Debug, Clone, Default)]
pub struct RaceState {
    pub race: Option<RaceInfo>,
    pub seed: Option<SeedInfo>,
    pub participants: Vec<ParticipantInfo>,
    pub race_started_at: Option<Instant>,
    pub current_zone: Option<ZoneUpdateData>,
}

/// Result of reading a single flag for debug display
pub enum FlagReadResult {
    /// Memory read failed
    Unreadable,
    /// Flag is not set
    NotSet,
    /// Flag is set
    Set,
}

/// Debug overlay info
pub struct DebugInfo<'a> {
    pub last_sent: Option<&'a str>,
    pub last_received: Option<&'a str>,
    pub flag_reader_status: FlagReaderStatus,
    /// Vanilla flag 6 sanity check (category 0 should always exist)
    pub vanilla_sanity: FlagReadResult,
    pub sample_reads: Vec<(u32, FlagReadResult)>,
}

// =============================================================================
// CACHED COLORS
// =============================================================================

/// Pre-parsed overlay colors, computed once from config hex strings.
pub(crate) struct CachedColors {
    pub bg: [f32; 4],
    pub text: [f32; 4],
    pub text_disabled: [f32; 4],
    pub border: [f32; 4],
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
    pub(crate) cached_colors: CachedColors,

    // Font data loaded from file (for ImGui registration)
    pub(crate) font_data: Option<Vec<u8>>,

    // Race state
    pub(crate) race_state: RaceState,

    // UI state
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    last_sent_debug: Option<String>,
    last_received_debug: Option<String>,

    // Identity (set from auth_ok)
    my_participant_id: Option<String>,

    // Event flag tracking
    event_ids: Vec<u32>,
    pub(crate) triggered_flags: HashSet<u32>,
    /// Event flags detected while disconnected, pending re-send on reconnection
    pending_event_flags: Vec<(u32, u32)>,

    // Status update throttle
    last_status_update: Instant,

    // Event flag poll throttle (10Hz)
    last_flag_poll: Instant,

    // Ready sent flag
    ready_sent: bool,

    // Temporary status message (yellow banner, auto-expires after 3s)
    status_message: Option<(String, Instant)>,

    // One-time diagnostic log flag
    flags_diagnosed: bool,

    // Item spawner thread handle (prevents double-spawn on reconnect)
    spawner_thread: Option<JoinHandle<()>>,

    // Zone update received during loading screen, waiting for load to finish
    pending_zone_update: Option<ZoneUpdateData>,

    // Transition gate: true once we've observed a loading screen (invalid position)
    // after an event flag was detected. Prevents premature zone reveal when the
    // server's zone_update arrives before the game starts loading.
    saw_loading: bool,
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

        // Pre-parse overlay colors
        let s = &config.overlay;
        let cached_colors = CachedColors {
            bg: parse_hex_color(&s.background_color, s.background_opacity),
            text: parse_hex_color(&s.text_color, 1.0),
            text_disabled: parse_hex_color(&s.text_disabled_color, 1.0),
            border: if s.show_border {
                parse_hex_color(&s.border_color, 1.0)
            } else {
                [0.0, 0.0, 0.0, 0.0]
            },
        };

        // Create WebSocket client
        let mut ws_client = RaceWebSocketClient::new(config.server.clone());
        ws_client.connect();

        info!("RaceTracker initialized");

        Some(Self {
            game_state,
            event_flag_reader,
            ws_client,
            config,
            cached_colors,
            font_data,
            race_state: RaceState::default(),
            show_ui: true,
            show_debug: false,
            last_sent_debug: None,
            last_received_debug: None,
            my_participant_id: None,
            event_ids: Vec::new(),
            triggered_flags: HashSet::new(),
            pending_event_flags: Vec::new(),
            last_status_update: Instant::now(),
            last_flag_poll: Instant::now(),
            ready_sent: false,
            status_message: None,
            flags_diagnosed: false,
            spawner_thread: None,
            pending_zone_update: None,
            saw_loading: true, // Start true so first zone_update (from auth) reveals immediately
        })
    }

    fn is_race_running(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == "running")
            .unwrap_or(false)
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

        // Reveal pending zone update once loading screen is finished.
        // Transition gate: after an event flag, we must first observe a loading screen
        // (read_position() returns None) before revealing the zone. This prevents premature
        // reveal when the server's zone_update arrives before the game starts loading.
        if self.pending_zone_update.is_some() {
            if self.game_state.read_position().is_some() {
                if self.saw_loading {
                    let zone = self.pending_zone_update.take().unwrap();
                    info!(name = %zone.display_name, "[RACE] Zone revealed after loading");
                    self.race_state.current_zone = Some(zone);
                }
            } else {
                // Loading screen observed — gate is now open for reveal
                if !self.saw_loading {
                    info!("[RACE] Loading screen detected, zone reveal unlocked");
                    self.saw_loading = true;
                }
            }
        }

        // Event flag polling runs ALWAYS (even when disconnected).
        // Flags are transient in game memory (~seconds), so we must detect them immediately
        // and buffer them for re-send on reconnection.
        if !self.event_ids.is_empty() && self.last_flag_poll.elapsed() >= Duration::from_millis(100)
        {
            self.last_flag_poll = Instant::now();
            let igt_ms = self.game_state.read_igt().unwrap_or(0);
            for &flag_id in &self.event_ids {
                if !self.triggered_flags.contains(&flag_id) {
                    if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                        self.triggered_flags.insert(flag_id);
                        // Reset transition gate: require a loading screen before
                        // revealing the next zone_update
                        self.saw_loading = false;
                        if self.ws_client.is_connected() && self.is_race_running() {
                            self.ws_client.send_event_flag(flag_id, igt_ms);
                            self.last_sent_debug =
                                Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                            info!(flag_id, "[RACE] Event flag triggered");
                        } else {
                            self.pending_event_flags.push((flag_id, igt_ms));
                            info!(
                                flag_id,
                                "[RACE] Event flag buffered (disconnected/not running)"
                            );
                        }
                    }
                }
            }
        }

        // Skip rest if not connected (status updates, ready, diagnostics)
        if !self.ws_client.is_connected() {
            return;
        }

        // Read game state
        let igt_ms = self.game_state.read_igt().unwrap_or(0);
        let deaths = self.game_state.read_deaths().unwrap_or(0);

        // Send ready on (re)connection (skip in training mode — server auto-starts)
        if !self.ready_sent {
            if !self.config.server.training {
                self.ws_client.send_ready();
                self.last_sent_debug = Some("ready".to_string());
                info!("[RACE] Sent ready signal");
            }
            self.ready_sent = true;

            if self.is_race_running() {
                // Drain event flags buffered during disconnection
                for (flag_id, flag_igt) in self.pending_event_flags.drain(..) {
                    self.ws_client.send_event_flag(flag_id, flag_igt);
                    self.last_sent_debug =
                        Some(format!("event_flag({}, igt={})", flag_id, flag_igt));
                    info!(flag_id, "[RACE] Buffered event flag sent");
                }

                // Safety-net rescan: catch any flags still set in memory that polling missed
                for &flag_id in &self.event_ids {
                    if !self.triggered_flags.contains(&flag_id) {
                        if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                            self.triggered_flags.insert(flag_id);
                            self.ws_client.send_event_flag(flag_id, igt_ms);
                            self.last_sent_debug =
                                Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                            info!(flag_id, "[RACE] Event flag re-sent after reconnect");
                        }
                    }
                }
            }
        }

        // One-time flag reader diagnostic (first poll with event_ids)
        if !self.flags_diagnosed && !self.event_ids.is_empty() {
            self.flags_diagnosed = true;
            let status = self.event_flag_reader.diagnose();
            info!("[RACE] Flag reader: {}", status);

            // Test a vanilla flag (category 0 exists in any save) to verify reader works
            let vanilla_test = self.event_flag_reader.is_flag_set(6);
            info!(result = ?vanilla_test, "[RACE] Vanilla flag 6 (sanity check)");

            // Dump category tree to see what the game has loaded
            if let Some(cats) = self.event_flag_reader.dump_categories(5000) {
                let total = cats.len();
                // Show last 20 categories (highest IDs)
                let tail: Vec<_> = cats.iter().rev().take(20).rev().collect();
                info!(
                    total,
                    highest_cats = ?tail,
                    "[RACE] Category tree dump"
                );
                // Check key categories
                let has_9000 = cats.contains(&9000);
                let has_1040292 = cats.contains(&1040292);
                info!(has_9000, has_1040292, "[RACE] Key categories present?");
                // If FogRando category exists, show nearby categories for context
                if has_1040292 {
                    let nearby: Vec<_> = cats
                        .iter()
                        .filter(|&&c| (1040290..=1040299).contains(&c))
                        .collect();
                    info!(
                        fogrando_cats = ?nearby,
                        "[RACE] FogRando category neighborhood"
                    );
                }
            }

            // Test first race event flag
            if let Some(&first_id) = self.event_ids.first() {
                let sample = self.event_flag_reader.is_flag_set(first_id);
                info!(flag_id = first_id, result = ?sample, "[RACE] Sample event flag read");
            }

            // Test a FogRando flag to confirm their category is readable
            let fogrando_sample = self.event_flag_reader.is_flag_set(1040292100);
            info!(result = ?fogrando_sample, "[RACE] FogRando flag 1040292100 read");
        }

        // Send periodic status updates (every 1 second, only when IGT is ticking and race running)
        // During quit-outs IGT is 0 — skip to avoid erroneous data
        if self.last_status_update.elapsed() >= Duration::from_secs(1)
            && igt_ms > 0
            && self.is_race_running()
        {
            self.ws_client.send_status_update(igt_ms, deaths);
            self.last_status_update = Instant::now();
        }
    }

    fn handle_ws_message(&mut self, msg: IncomingMessage) {
        match msg {
            IncomingMessage::StatusChanged(status) => {
                info!(status = ?status, "[WS] Status changed");
                match status {
                    ConnectionStatus::Connected => {
                        self.ready_sent = false; // Reset for reconnection
                        self.set_status("Server connected".to_string());
                    }
                    ConnectionStatus::Reconnecting => {
                        self.set_status("Reconnecting to server...".to_string());
                    }
                    ConnectionStatus::Error => {
                        self.set_status("Server error".to_string());
                    }
                    ConnectionStatus::Disconnected => {
                        self.set_status("Disconnected".to_string());
                    }
                    ConnectionStatus::Connecting => {
                        // Silent — the dot indicator handles initial connection
                    }
                }
            }
            IncomingMessage::AuthOk {
                participant_id,
                race,
                seed,
                participants,
            } => {
                info!(race = %race.name, participant_id = %participant_id, participants = participants.len(), "[WS] Auth OK");
                self.last_received_debug = Some(format!(
                    "auth_ok(race={}, {} players)",
                    race.name,
                    participants.len()
                ));
                self.my_participant_id = Some(participant_id);
                self.event_ids = seed.event_ids.clone();
                // Don't clear triggered_flags on reconnect: they track which flags
                // have already been detected. Pending flags are in pending_event_flags.
                // Reset transition gate: after (re)auth, the server sends the player's
                // current zone — reveal it immediately without requiring a loading cycle.
                self.saw_loading = true;
                self.race_state.race = Some(race);
                self.race_state.seed = Some(seed);
                // Spawn runtime items (gems/AoW) if present in seed
                if let Some(ref seed_info) = self.race_state.seed {
                    if !seed_info.spawn_items.is_empty() {
                        // Guard against double-spawn on reconnect
                        let already_running = self
                            .spawner_thread
                            .as_ref()
                            .is_some_and(|h| !h.is_finished());
                        if already_running {
                            info!(
                                count = seed_info.spawn_items.len(),
                                "[RACE] Spawner thread already running, skipping"
                            );
                        } else {
                            let items = seed_info.spawn_items.clone();
                            let ids: Vec<u32> = items.iter().map(|i| i.id).collect();
                            info!(count = items.len(), item_ids = ?ids, "[RACE] Spawning runtime items");
                            let flag_reader = self.event_flag_reader.clone();
                            self.spawner_thread = Some(std::thread::spawn(move || {
                                crate::eldenring::item_spawner::spawn_items_blocking(
                                    items,
                                    &flag_reader,
                                );
                            }));
                        }
                    }
                }
                self.race_state.participants = participants;
            }
            IncomingMessage::AuthError(msg) => {
                self.last_received_debug = Some(format!("auth_error({})", msg));
                error!(message = %msg, "[WS] Auth failed");
            }
            IncomingMessage::RaceStart => {
                self.last_received_debug = Some("race_start".to_string());
                info!("[WS] Race started!");
                self.race_state.race_started_at = Some(Instant::now());
                // Immediately reflect running status so is_race_running() gates open
                // without waiting for the race_status_change message that follows.
                if let Some(ref mut race) = self.race_state.race {
                    race.status = "running".to_string();
                }
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
            IncomingMessage::ZoneUpdate {
                node_id,
                display_name,
                tier,
                exits,
            } => {
                self.last_received_debug = Some(format!("zone_update({})", display_name));
                info!(node = %node_id, name = %display_name, "[WS] Zone update (pending reveal)");
                // Last-writer-wins: if two flags fire in rapid succession, only the
                // final destination zone is shown (intermediate corridor zones are skipped).
                self.pending_zone_update = Some(ZoneUpdateData {
                    node_id,
                    display_name,
                    tier,
                    exits,
                });
            }
            IncomingMessage::RequeueEventFlag { flag_id, igt_ms } => {
                // Event flag was in the outgoing channel but never transmitted before
                // disconnect. Re-buffer it so it gets sent after reconnection.
                self.pending_event_flags.push((flag_id, igt_ms));
                info!(flag_id, "[WS] Re-queued drained event flag");
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

    pub fn current_zone_info(&self) -> Option<&ZoneUpdateData> {
        self.race_state.current_zone.as_ref()
    }

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        let id = self.my_participant_id.as_ref()?;
        self.race_state.participants.iter().find(|p| &p.id == id)
    }

    /// Set a status message that will be displayed temporarily (3 seconds).
    pub fn set_status(&mut self, message: String) {
        self.status_message = Some((message, Instant::now()));
    }

    /// Get current status message if still valid (within 3 seconds).
    pub fn get_status(&self) -> Option<&str> {
        self.status_message.as_ref().and_then(|(msg, time)| {
            if time.elapsed() < Duration::from_secs(3) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    pub fn debug_info(&self) -> DebugInfo<'_> {
        let flag_reader_status = self.event_flag_reader.diagnose();

        let sample_reads: Vec<(u32, FlagReadResult)> = self
            .event_ids
            .iter()
            .take(5)
            .map(|&flag_id| {
                let result = match self.event_flag_reader.is_flag_set(flag_id) {
                    None => FlagReadResult::Unreadable,
                    Some(false) => FlagReadResult::NotSet,
                    Some(true) => FlagReadResult::Set,
                };
                (flag_id, result)
            })
            .collect();

        let vanilla_sanity = match self.event_flag_reader.is_flag_set(6) {
            None => FlagReadResult::Unreadable,
            Some(false) => FlagReadResult::NotSet,
            Some(true) => FlagReadResult::Set,
        };

        DebugInfo {
            last_sent: self.last_sent_debug.as_deref(),
            last_received: self.last_received_debug.as_deref(),
            flag_reader_status,
            vanilla_sanity,
            sample_reads,
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
