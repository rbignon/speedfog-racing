//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress via EMEVD event flags and communicates with the racing server.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::color::parse_hex_color;
use crate::core::protocol::{ParticipantInfo, RaceInfo, SeedInfo};
use crate::core::race_machine::{
    ConnectionStatus, Effect, FrameSnapshot, MachineMessage, RaceMachine, TickInput, ZoneUpdateData,
};
use crate::eldenring::{EventFlagReader, FlagReaderStatus, GameState};
use crate::profile_span;

use super::config::RaceConfig;
use super::death_icon::DeathIcon;
use super::websocket::RaceWebSocketClient;

const DEBUG_REFRESH_INTERVAL: Duration = Duration::from_millis(250);
pub(crate) const LEADERBOARD_REFRESH_INTERVAL_MS: u32 = 250;

// =============================================================================
// RACE STATE
// =============================================================================

/// Pre-allocated buffers reused across frames to avoid per-frame heap allocations.
pub(crate) struct RenderBuffers {
    pub buf_right: String,
    pub buf_left: String,
    pub buf_footer: String,
}

impl Default for RenderBuffers {
    fn default() -> Self {
        Self {
            buf_right: String::with_capacity(16),
            buf_left: String::with_capacity(48),
            buf_footer: String::with_capacity(16),
        }
    }
}

/// Result of reading a single flag for debug display
#[derive(Clone, Copy)]
pub enum FlagReadResult {
    /// Memory read failed
    Unreadable,
    /// Flag is not set
    NotSet,
    /// Flag is set
    Set,
}

/// Debug overlay info
pub struct DebugInfo {
    pub last_sent: Option<String>,
    pub last_received: Option<String>,
    pub flag_reader_status: String,
    pub flag_reader_ok: bool,
    /// Vanilla flag 6 sanity check (category 0 should always exist)
    pub vanilla_sanity: FlagReadResult,
    pub sample_reads: Vec<(u32, FlagReadResult)>,
}

impl Default for DebugInfo {
    fn default() -> Self {
        Self {
            last_sent: None,
            last_received: None,
            flag_reader_status: String::new(),
            flag_reader_ok: false,
            vanilla_sanity: FlagReadResult::Unreadable,
            sample_reads: Vec::new(),
        }
    }
}

/// Pre-resolved name color for the leaderboard row (parsed once on
/// receipt; consumed per-frame by the renderer). `None` means "use the
/// row's status color" (the existing default behavior).
#[derive(Debug, Clone)]
pub(crate) enum ResolvedNameColor {
    Solid([f32; 4]),
    Gradient([f32; 4], [f32; 4]),
}

#[derive(Default)]
pub(crate) struct LeaderboardRowCache {
    pub right_text: String,
    pub gap_text: Option<String>,
    pub computed_gap_ms: Option<i32>,
    pub name_color: Option<ResolvedNameColor>,
}

#[derive(Default)]
pub(crate) struct LeaderboardCache {
    pub rows: Vec<LeaderboardRowCache>,
    pub max_gap_width: f32,
    pub max_right_width: f32,
    pub my_index: Option<usize>,
    pub need_anchor: bool,
    pub top_count: usize,
    pub footer_more: usize,
    pub version: u64,
    pub local_igt_bucket: Option<u32>,
    pub max_width: f32,
    pub spacing: f32,
}

// =============================================================================
// CACHED COLORS
// =============================================================================

/// Pre-parsed overlay colors, computed once at startup.
///
/// The first block is configurable via the toml; the second block is hardcoded
/// from `docs/GRAPHIC_CHARTER.md` and intentionally not exposed.
pub(crate) struct CachedColors {
    // Configurable
    pub bg: [f32; 4],
    pub text: [f32; 4],
    pub text_disabled: [f32; 4],
    pub border: [f32; 4],
    // Charter tokens
    pub gold: [f32; 4],        // #C8A44E
    pub success: [f32; 4],     // #10B981
    pub danger: [f32; 4],      // #EF4444
    pub danger_dark: [f32; 4], // #DC2626
    pub purple: [f32; 4],      // #A78BFA - local player accent
    pub purple_bg: [f32; 4],   // rgba(139,92,246,0.10) - leaderboard row bg
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

    // Death icon texture (loaded during ImGui initialization)
    pub(crate) death_icon: Option<DeathIcon>,

    // Pure race state machine (all decisions, no IO)
    pub(crate) machine: RaceMachine,

    // UI state
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    pub(crate) show_leaderboard: bool,
    /// Set when a frame panicked; rendering and updates stop for the session.
    pub(crate) render_panicked: bool,
    // One-time diagnostic log flag
    flags_diagnosed: bool,

    // Item spawner thread handle (prevents double-spawn on reconnect)
    spawner_thread: Option<JoinHandle<()>>,

    // Items actually spawned this session (in-process guard for reconnects).
    // Set by the spawner thread AFTER items are given to the player, so a stale
    // save that skips spawning leaves this false, allowing retry on the next auth_ok.
    items_spawned: Arc<AtomicBool>,

    // Phantom skin runner thread handle (one per session).
    phantom_skin_thread: Option<JoinHandle<()>>,

    // Phantom skin runner stop flag (currently always false; reserved for
    // future mid-session skin changes).
    phantom_skin_stop: Arc<AtomicBool>,

    // Cached equipped phantom skin name to avoid respawning the runner on
    // every reconnect's auth_ok.
    phantom_skin_name: Option<String>,

    // Throttled debug snapshot to avoid expensive flag reads every frame.
    debug_info: DebugInfo,
    last_debug_refresh: Option<Instant>,

    // Cached leaderboard layout invalidated by participant/status changes.
    pub(crate) leaderboard_cache: LeaderboardCache,

    // Pre-allocated render buffers (reused across frames)
    pub(crate) render_bufs: RenderBuffers,
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

        // Install warp hook for grace entity ID capture (fast travel zone tracking)
        unsafe {
            let lua_warp = game_state.base_addresses().lua_warp;
            if let Err(e) = crate::eldenring::warp_hook::install(lua_warp) {
                error!(error = %e, "Failed to install warp hook (fast travel zone tracking disabled)");
            }
        }

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
            gold: parse_hex_color("#C8A44E", 1.0),
            success: parse_hex_color("#10B981", 1.0),
            danger: parse_hex_color("#EF4444", 1.0),
            danger_dark: parse_hex_color("#DC2626", 1.0),
            purple: parse_hex_color("#A78BFA", 1.0),
            purple_bg: parse_hex_color("#8B5CF6", 0.10),
        };

        let config_seed_id = config.server.seed_id.clone();
        let config_training = config.server.training;

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
            death_icon: None,
            machine: RaceMachine::new(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis() as u64,
                config_seed_id,
                config_training,
                Instant::now(),
            ),
            show_ui: true,
            show_debug: false,
            show_leaderboard: true,
            render_panicked: false,
            flags_diagnosed: false,
            spawner_thread: None,
            items_spawned: Arc::new(AtomicBool::new(false)),
            phantom_skin_thread: None,
            phantom_skin_stop: Arc::new(AtomicBool::new(false)),
            phantom_skin_name: None,
            debug_info: DebugInfo::default(),
            last_debug_refresh: None,
            leaderboard_cache: LeaderboardCache::default(),
            render_bufs: RenderBuffers::default(),
        })
    }

    /// Returns true if we're in the countdown period before the race effectively starts.
    pub fn is_countdown_active(&self) -> bool {
        self.machine.is_countdown_active(Instant::now())
    }

    pub fn is_race_running(&self) -> bool {
        self.machine.is_race_running()
    }

    pub fn is_race_setup(&self) -> bool {
        self.machine.is_race_setup()
    }

    /// Check if the local player has finished the race.
    pub(crate) fn am_i_finished(&self) -> bool {
        self.machine.am_i_finished()
    }

    pub fn update(&mut self, ui: &hudhook::imgui::Ui) {
        profile_span!("tracker_update");

        // Check toggle_ui hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_ui {
            if hotkey.is_just_pressed(ui) {
                self.show_ui = !self.show_ui;
                info!(show_ui = self.show_ui, "[HOTKEY] Toggle UI");
            }
        }

        // Check toggle_debug hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_debug {
            if hotkey.is_just_pressed(ui) {
                self.show_debug = !self.show_debug;
                info!(show_debug = self.show_debug, "[HOTKEY] Toggle debug");
            }
        }

        // Check toggle_leaderboard hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_leaderboard {
            if hotkey.is_just_pressed(ui) {
                self.show_leaderboard = !self.show_leaderboard;
                info!(
                    show_leaderboard = self.show_leaderboard,
                    "[HOTKEY] Toggle leaderboard"
                );
            }
        }

        {
            profile_span!("ws_poll");
            // Poll WebSocket
            while let Some(msg) = self.ws_client.poll() {
                self.handle_ws_message(msg);
            }
        }

        // Gather tick inputs: the machine decides what to read, the shell
        // performs the game-memory reads, the machine consumes them.
        let now = Instant::now();
        let connected = self.ws_client.is_connected();
        let needs = self.machine.pre_tick(now, self.show_ui, connected);

        let snapshot = {
            profile_span!("frame_snapshot");
            FrameSnapshot {
                igt_ms: needs.igt.then(|| self.game_state.read_igt()).flatten(),
                death_count: needs
                    .deaths
                    .then(|| self.game_state.read_deaths())
                    .flatten(),
                position_readable: self.game_state.is_position_readable(),
                loading_screen: if needs.loading {
                    self.game_state.is_in_loading_screen()
                } else {
                    None
                },
            }
        };

        // Warp capture + position: read on loading-exit frames only.
        let loading_exit = snapshot.position_readable && !self.machine.was_position_readable;
        let (warp_capture, position) = if loading_exit {
            profile_span!("loading_exit_scan");
            let grace_id = crate::eldenring::warp_hook::get_captured_grace_entity_id();
            (
                (grace_id > 0).then_some(grace_id),
                self.game_state.read_position(),
            )
        } else {
            (None, None)
        };

        // Flag reads: 10Hz poll cadence, loading-exit scan, or reconnect rescan.
        let mut flag_reads = None;
        let mut flag_reader_ok = None;
        if self
            .machine
            .wants_flag_reads(needs, snapshot.position_readable, connected)
        {
            profile_span!("event_flag_poll");
            let status = self.event_flag_reader.diagnose();
            let current_ok = matches!(status, FlagReaderStatus::Ok { .. });
            // Log flag reader status transitions (not every read)
            if self.machine.last_flag_reader_ok != Some(current_ok) {
                if current_ok {
                    info!("[RACE] Flag reader recovered (Ok)");
                } else {
                    warn!("[RACE] Flag reader degraded: {}", status);
                }
            }
            flag_reader_ok = Some(current_ok);

            // Resolve category page once (all event_ids share the same category)
            let ids: Vec<u32> = self.machine.event_ids.clone();
            let page = self.event_flag_reader.resolve_category(ids[0]);
            let page_ref = page.as_ref();
            let reads: Vec<(u32, bool)> = ids
                .iter()
                .filter_map(|&flag_id| {
                    self.event_flag_reader
                        .is_flag_set_cached(flag_id, page_ref)
                        .map(|set| (flag_id, set))
                })
                .collect();
            flag_reads = Some(reads);
        }

        // Weapons: read only when a status_update may fire this frame.
        // Skip the read during loading screens: ChrAsm may hold stale or
        // in-flight values while the player struct is being repopulated.
        let weapons = if connected
            && self
                .machine
                .wants_status_update(now, snapshot.igt_ms.unwrap_or(0))
        {
            if self.game_state.is_in_loading_screen() == Some(true) {
                [None, None]
            } else {
                self.game_state.read_equipped_weapons()
            }
        } else {
            [None, None]
        };

        let input = TickInput {
            snapshot,
            connected,
            warp_capture,
            position,
            flag_reads,
            weapons,
            flag_reader_ok,
        };
        let effects = self.machine.tick(input, now);
        self.execute_effects(effects);

        if self.show_debug
            && self
                .last_debug_refresh
                .is_none_or(|t| t.elapsed() >= DEBUG_REFRESH_INTERVAL)
        {
            self.refresh_debug_info();
        }

        // One-time flag reader diagnostic (first connected frame with event_ids).
        // Kept in the shell: raw reader access, diagnostics only.
        if connected && !self.flags_diagnosed && !self.machine.event_ids.is_empty() {
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
                let has_1050294 = cats.contains(&1050294);
                info!(
                    has_9000,
                    has_1040292, has_1050294, "[RACE] Key categories present?"
                );
                // Show neighborhood if either base is present
                if has_1040292 || has_1050294 {
                    let nearby: Vec<_> = cats
                        .iter()
                        .filter(|&&c| {
                            (1040290..=1040299).contains(&c) || (1050290..=1050299).contains(&c)
                        })
                        .collect();
                    info!(
                        cats = ?nearby,
                        "[RACE] SpeedFog category neighborhood"
                    );
                }
            }

            // Test first race event flag
            if let Some(&first_id) = self.machine.event_ids.first() {
                let sample = self.event_flag_reader.is_flag_set(first_id);
                info!(flag_id = first_id, result = ?sample, "[RACE] Sample event flag read");
            }

            // Test a FogRando flag to confirm their category is readable
            let fogrando_sample = self.event_flag_reader.is_flag_set(1040292100);
            info!(result = ?fogrando_sample, "[RACE] FogRando flag 1040292100 read");
        }
    }

    fn handle_ws_message(&mut self, mut msg: MachineMessage) {
        // The finish-freeze decision needs a fresh IGT; inject it here so the
        // machine stays free of game reads (the WS thread always sends None).
        if let MachineMessage::RaceStatusChange {
            ref mut current_igt,
            ..
        } = msg
        {
            *current_igt = self.game_state.read_igt();
        }
        let effects = self.machine.handle_message(msg, Instant::now());
        self.execute_effects(effects);
    }

    /// Execute machine effects: WS sends, game-memory writes, thread spawns.
    fn execute_effects(&mut self, effects: Vec<Effect>) {
        // Death-marker writes share one category page resolution per batch
        // (all death flags live in the same category, as before).
        let mut flag_page = None;
        for effect in effects {
            match effect {
                Effect::SendReady => {
                    self.ws_client.send_ready();
                }
                Effect::SendStatusUpdate {
                    igt_ms,
                    death_count,
                    weapons,
                } => {
                    self.ws_client
                        .send_status_update(igt_ms, death_count, weapons);
                }
                Effect::SendEventFlag {
                    flag_id,
                    igt_ms,
                    message_id,
                } => {
                    self.ws_client.send_event_flag(flag_id, igt_ms, message_id);
                }
                Effect::SendZoneQuery {
                    igt_ms,
                    message_id,
                    grace_entity_id,
                    map_id,
                    position,
                    play_region_id,
                } => {
                    self.ws_client.send_zone_query(
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                        message_id,
                    );
                }
                Effect::SetGameFlag { flag_id, value } => {
                    if flag_page.is_none() {
                        flag_page = Some(self.event_flag_reader.resolve_category(flag_id));
                    }
                    let page_ref = flag_page.as_ref().and_then(|p| p.as_ref());
                    self.event_flag_reader
                        .set_flag_cached(flag_id, value, page_ref);
                }
                Effect::ClearWarpCapture => {
                    crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                }
                Effect::SpawnItems => self.spawn_items_if_needed(),
                Effect::StartPhantomSkin { name, speffects } => {
                    self.start_phantom_skin(name, speffects)
                }
            }
        }
    }

    /// Spawn runtime items (gems/AoW) unless already spawned this session or
    /// a spawner thread is still running (guards unchanged from before the
    /// machine extraction).
    fn spawn_items_if_needed(&mut self) {
        let Some(ref seed_info) = self.machine.race_state.seed else {
            return;
        };
        if seed_info.spawn_items.is_empty() {
            return;
        }
        if self.items_spawned.load(Ordering::Relaxed) {
            info!(
                count = seed_info.spawn_items.len(),
                "[RACE] Items already spawned this session, skipping"
            );
            return;
        }
        // Secondary guard: thread still running from a previous auth_ok
        let already_running = self
            .spawner_thread
            .as_ref()
            .is_some_and(|h| !h.is_finished());
        if already_running {
            info!(
                count = seed_info.spawn_items.len(),
                "[RACE] Spawner thread already running, skipping"
            );
            return;
        }
        let items = seed_info.spawn_items.clone();
        let spawned_flag = seed_info.items_spawned_flag;
        let ids: Vec<u32> = items.iter().map(|i| i.id).collect();
        info!(count = items.len(), item_ids = ?ids, "[RACE] Spawning runtime items");
        let flag_reader = self.event_flag_reader.clone();
        let spawned_flag_ref = Arc::clone(&self.items_spawned);
        self.spawner_thread = Some(std::thread::spawn(move || {
            crate::eldenring::item_spawner::spawn_items_blocking(
                items,
                &flag_reader,
                spawned_flag,
                &spawned_flag_ref,
            );
        }));
    }

    /// Start the phantom-skin runner unless the same skin's runner is still
    /// alive (guards unchanged from before the machine extraction).
    fn start_phantom_skin(&mut self, name: String, speffects: Vec<i32>) {
        let already_running = self.phantom_skin_name.as_ref() == Some(&name)
            && self
                .phantom_skin_thread
                .as_ref()
                .is_some_and(|h| !h.is_finished());
        if already_running {
            info!(
                skin = %name,
                "[PHANTOM_SKIN] Runner already running for this skin, skipping respawn"
            );
            return;
        }
        self.phantom_skin_stop = Arc::new(AtomicBool::new(false));
        self.phantom_skin_name = Some(name.clone());
        self.phantom_skin_thread = Some(crate::eldenring::sp_effect_runner::spawn(
            name,
            speffects,
            Arc::clone(&self.phantom_skin_stop),
        ));
    }

    // Public getters for UI
    pub fn ws_status(&self) -> ConnectionStatus {
        self.ws_client.status()
    }

    pub fn race_info(&self) -> Option<&RaceInfo> {
        self.machine.race_state.race.as_ref()
    }

    pub fn seed_info(&self) -> Option<&SeedInfo> {
        self.machine.race_state.seed.as_ref()
    }

    pub fn participants(&self) -> &[ParticipantInfo] {
        &self.machine.race_state.participants
    }

    pub fn read_igt(&self) -> Option<u32> {
        self.machine
            .frame_snapshot
            .igt_ms
            .or_else(|| self.game_state.read_igt())
    }

    pub fn read_deaths(&self) -> Option<u32> {
        self.machine
            .frame_snapshot
            .death_count
            .or_else(|| self.game_state.read_deaths())
    }

    pub fn current_zone_info(&self) -> Option<&ZoneUpdateData> {
        self.machine.race_state.current_zone.as_ref()
    }

    /// During the zone reveal wait, returns the frozen current_layer from
    /// before the leaderboard update. Returns None outside the wait.
    pub fn pre_reveal_layer(&self) -> Option<i32> {
        self.machine.pre_reveal_layer
    }

    pub fn my_participant_id(&self) -> Option<&String> {
        self.machine.my_participant_id.as_ref()
    }

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        self.machine.my_participant()
    }

    /// Set a status message that will be displayed temporarily (3 seconds).
    pub fn set_status(&mut self, message: String) {
        self.machine.set_status(message, Instant::now());
    }

    /// Get current status message if still valid (within 3 seconds).
    pub fn get_status(&self) -> Option<&str> {
        self.machine.get_status(Instant::now())
    }

    /// Get the update-available notice if still within its 10s display window.
    pub fn get_update_notice(&self) -> Option<&str> {
        self.machine.get_update_notice(Instant::now())
    }

    pub fn debug_info(&self) -> &DebugInfo {
        &self.debug_info
    }

    fn refresh_debug_info(&mut self) {
        let flag_reader_status = self.event_flag_reader.diagnose();
        let flag_reader_ok = matches!(flag_reader_status, FlagReaderStatus::Ok { .. });

        let sample_reads: Vec<(u32, FlagReadResult)> = self
            .machine
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

        self.debug_info = DebugInfo {
            last_sent: self.machine.last_sent_debug.clone(),
            last_received: self.machine.last_received_debug.clone(),
            flag_reader_status: flag_reader_status.to_string(),
            flag_reader_ok,
            vanilla_sanity,
            sample_reads,
        };
        self.last_debug_refresh = Some(Instant::now());
    }
}

// =============================================================================
// FONT LOADING
// =============================================================================

/// Embedded Source Sans 3 Regular (SIL OFL 1.1). Default overlay font; no
/// filesystem dependency unless the user sets `overlay.font_path`. Chosen
/// over Inter because its digits are tabular by default, which ImGui needs
/// for column-aligned chrono and gap values (it does not apply OpenType
/// `tnum` features).
const EMBEDDED_FONT: &[u8] = include_bytes!("../../assets/fonts/SourceSans3-Regular.ttf");

/// Resolve the overlay TTF bytes.
///
///   - Empty `font_path` → embedded Source Sans 3 (default, no disk access).
///   - Filename only → try `C:\Windows\Fonts\` then DLL directory.
///   - Relative path with separators → relative to DLL directory.
///   - Absolute path → use directly.
///
/// Falls back to `None` only when an explicit `font_path` was set but no
/// candidate exists; ImGui then uses its built-in font.
fn load_font_data(dll_dir: &Path, font_path: &str) -> Option<Vec<u8>> {
    const WINDOWS_FONTS_DIR: &str = r"C:\Windows\Fonts";

    if font_path.is_empty() {
        info!(size = EMBEDDED_FONT.len(), "Using embedded font");
        return Some(EMBEDDED_FONT.to_vec());
    }

    let path = Path::new(font_path);
    let paths_to_try: Vec<PathBuf> = if path.is_absolute() {
        vec![path.to_path_buf()]
    } else if !font_path.contains('/') && !font_path.contains('\\') {
        vec![
            Path::new(WINDOWS_FONTS_DIR).join(font_path),
            dll_dir.join(font_path),
        ]
    } else {
        vec![dll_dir.join(font_path)]
    };

    for full_path in &paths_to_try {
        if full_path.exists() {
            match fs::read(full_path) {
                Ok(data) => {
                    info!(path = %full_path.display(), size = data.len(), "Loaded font override");
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
    warn!(tried_paths = %tried, "Configured font not found, using imgui default");
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_font_data_empty_path_returns_embedded() {
        // Empty font_path uses the bundled font, no filesystem access.
        let dummy = Path::new("/this/path/does/not/exist");
        let data = load_font_data(dummy, "").expect("embedded font should always load");
        assert!(data.len() > 100_000, "embedded TTF should be substantial");
        // TTF magic: 0x00010000 (TrueType) or "OTTO" (CFF/OpenType)
        let magic = &data[0..4];
        assert!(
            magic == [0x00, 0x01, 0x00, 0x00] || magic == b"OTTO" || magic == b"true",
            "expected TTF/OTF magic, got {:?}",
            magic
        );
    }
}
