//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress via EMEVD event flags and communicates with the racing server.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::color::parse_hex_color;
use crate::core::flag_buffer::{detect_save_reload, FlagBuffer};
use crate::core::protocol::{ExitInfo, ParticipantInfo, RaceInfo, SeedInfo};
use crate::core::traits::GameStateReader;
use crate::eldenring::{EventFlagReader, FlagReaderStatus, GameState};
use crate::profile_span;

use super::config::RaceConfig;
use super::death_icon::DeathIcon;
use super::hotkey::begin_hotkey_frame;
use super::websocket::{ConnectionStatus, IncomingMessage, RaceWebSocketClient};

/// Defensive timeout: if a zone update hasn't been revealed after this duration
/// (e.g., loading screen flag is unreadable), reveal anyway.
const ZONE_REVEAL_TIMEOUT: Duration = Duration::from_secs(15);
const DEBUG_REFRESH_INTERVAL: Duration = Duration::from_millis(250);
pub(crate) const LEADERBOARD_REFRESH_INTERVAL_MS: u32 = 250;

// =============================================================================
// RACE STATE
// =============================================================================

/// Zone update data received from server
#[derive(Debug, Clone)]
pub struct ZoneUpdateData {
    pub display_name: String,
    pub tier: Option<i32>,
    pub original_tier: Option<i32>,
    pub layer: Option<i32>,
    #[allow(dead_code)] // Kept for future use (e.g., spectator UI)
    pub is_first_visit: bool,
    pub exits: Vec<ExitInfo>,
}

#[derive(Debug, Clone, Copy)]
struct BufferedEventFlag {
    flag_id: u32,
    igt_ms: u32,
}

#[derive(Debug, Clone)]
struct BufferedZoneQuery {
    igt_ms: u32,
    grace_entity_id: Option<u32>,
    map_id: Option<String>,
    position: Option<[f32; 3]>,
    play_region_id: Option<u32>,
}

/// Current race state from server
#[derive(Debug, Clone, Default)]
pub struct RaceState {
    pub race: Option<RaceInfo>,
    pub seed: Option<SeedInfo>,
    pub participants: Vec<ParticipantInfo>,
    pub leader_splits: Option<HashMap<i32, i32>>,
    pub race_started_at: Option<Instant>,
    pub countdown_end: Option<Instant>,
    pub current_zone: Option<ZoneUpdateData>,
    pub death_counts: HashMap<String, u32>,
}

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

/// Cached frame-local memory reads reused by update and rendering.
#[derive(Debug, Clone, Copy, Default)]
pub(crate) struct FrameSnapshot {
    pub igt_ms: Option<u32>,
    pub death_count: Option<u32>,
    pub position_readable: bool,
    pub loading_screen: Option<bool>,
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
    pub displayed: usize,
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

    // Race state
    pub(crate) race_state: RaceState,

    // UI state
    pub(crate) show_ui: bool,
    pub(crate) show_debug: bool,
    pub(crate) show_leaderboard: bool,
    last_sent_debug: Option<String>,
    last_received_debug: Option<String>,

    // Identity (set from auth_ok)
    my_participant_id: Option<String>,
    pub(crate) my_participant_index: Option<usize>,

    // Event flag tracking
    event_ids: Vec<u32>,
    pub(crate) triggered_flags: HashSet<u32>,
    flag_buffer: FlagBuffer,
    in_flight_event_flags: HashMap<u64, BufferedEventFlag>,
    in_flight_zone_queries: HashMap<u64, BufferedZoneQuery>,
    next_event_message_id: u64,
    /// finish_event from server, sent immediately (no loading screen on boss kill)
    finish_event: Option<u32>,

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

    // Last flag reader status discriminant (for transition logging)
    last_flag_reader_ok: Option<bool>,

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

    // Zone update received, waiting for loading screen to end before revealing
    pending_zone_update: Option<ZoneUpdateData>,

    // Snapshot of current_layer taken when leaderboard_update bumps the layer.
    // The UI uses this instead of me.current_layer so the X/Y counter and tier
    // don't update before the zone name is revealed.
    pre_reveal_layer: Option<i32>,

    // When the pending zone update was received (for defensive timeout)
    pending_zone_received_at: Option<Instant>,

    // Whether position was readable last frame (for detecting loading screen exit)
    was_position_readable: bool,

    // Seed mismatch: config seed_id doesn't match server seed_id (stale seed pack)
    pub(crate) seed_mismatch: bool,

    // Last auth error message from server.
    // AuthError is always enqueued before StatusChanged(Error) in the same
    // channel, so this is guaranteed to be populated when the Error handler
    // runs within the same poll() drain loop.
    last_auth_error: Option<String>,

    // Permanent error from server (persistent red banner, no auto-dismiss)
    pub(crate) permanent_error: Option<String>,

    // IGT captured from game memory when the race ends and the player hasn't
    // finished. The mod's local participant igt_ms is stale (only updated via
    // leaderboard_update on events), so we freeze the live game IGT instead.
    pub(crate) frozen_igt_ms: Option<u32>,

    // Last observed IGT, used to detect save reloads. See EVENT_FLAG_TRACKING.md.
    last_observed_igt: Option<u32>,

    // Cached reads for the current frame.
    pub(crate) frame_snapshot: FrameSnapshot,

    // Throttled debug snapshot to avoid expensive flag reads every frame.
    debug_info: DebugInfo,
    last_debug_refresh: Option<Instant>,

    // Cached leaderboard layout invalidated by participant/status changes.
    pub(crate) leaderboard_cache: LeaderboardCache,
    pub(crate) leaderboard_version: u64,

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
            race_state: RaceState::default(),
            show_ui: true,
            show_debug: false,
            show_leaderboard: true,
            last_sent_debug: None,
            last_received_debug: None,
            my_participant_id: None,
            my_participant_index: None,
            event_ids: Vec::new(),
            triggered_flags: HashSet::new(),
            flag_buffer: FlagBuffer::default(),
            in_flight_event_flags: HashMap::new(),
            in_flight_zone_queries: HashMap::new(),
            next_event_message_id: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
            finish_event: None,
            last_status_update: Instant::now(),
            last_flag_poll: Instant::now(),
            ready_sent: false,
            status_message: None,
            flags_diagnosed: false,
            last_flag_reader_ok: None,
            spawner_thread: None,
            items_spawned: Arc::new(AtomicBool::new(false)),
            phantom_skin_thread: None,
            phantom_skin_stop: Arc::new(AtomicBool::new(false)),
            phantom_skin_name: None,
            pending_zone_update: None,
            pre_reveal_layer: None,
            pending_zone_received_at: None,
            was_position_readable: true,
            seed_mismatch: false,
            last_auth_error: None,
            permanent_error: None,
            frozen_igt_ms: None,
            last_observed_igt: None,
            frame_snapshot: FrameSnapshot::default(),
            debug_info: DebugInfo::default(),
            last_debug_refresh: None,
            leaderboard_cache: LeaderboardCache::default(),
            leaderboard_version: 0,
            render_bufs: RenderBuffers::default(),
        })
    }

    /// Returns true if we're in the countdown period before the race effectively starts.
    pub fn is_countdown_active(&self) -> bool {
        self.race_state
            .countdown_end
            .map(|end| Instant::now() < end)
            .unwrap_or(false)
    }

    pub fn is_race_running(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == "running")
            .unwrap_or(false)
    }

    pub fn is_race_setup(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == "setup")
            .unwrap_or(false)
    }

    /// Check if the local player has finished the race.
    /// Once finished, the mod should stop sending status_update and event_flag
    /// to preserve the frozen IGT at finish time.
    pub(crate) fn am_i_finished(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == "finished")
            .unwrap_or(false)
    }

    pub fn update(&mut self) {
        profile_span!("tracker_update");
        // Process hotkeys at start of frame
        begin_hotkey_frame();

        // Check toggle_ui hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_ui {
            if hotkey.is_just_pressed() {
                self.show_ui = !self.show_ui;
                info!(show_ui = self.show_ui, "[HOTKEY] Toggle UI");
            }
        }

        // Check toggle_debug hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_debug {
            if hotkey.is_just_pressed() {
                self.show_debug = !self.show_debug;
                info!(show_debug = self.show_debug, "[HOTKEY] Toggle debug");
            }
        }

        // Check toggle_leaderboard hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_leaderboard {
            if hotkey.is_just_pressed() {
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

        let need_live_snapshot = self.show_ui || self.ws_client.is_connected();
        // IGT also needed when a race is set up so save-reload detection and
        // event-flag polling stay correct even with UI hidden and WS dropped.
        let need_igt = need_live_snapshot || !self.event_ids.is_empty();
        self.frame_snapshot = {
            profile_span!("frame_snapshot");
            FrameSnapshot {
                igt_ms: need_igt.then(|| self.game_state.read_igt()).flatten(),
                death_count: need_live_snapshot
                    .then(|| self.game_state.read_deaths())
                    .flatten(),
                position_readable: self.game_state.is_position_readable(),
                loading_screen: if self.pending_zone_update.is_some() {
                    self.game_state.is_in_loading_screen()
                } else {
                    None
                },
            }
        };

        // Save reload detection: an IGT regression means the player loaded a
        // different save. Reset per-save event-flag state so a pre-set
        // finish_event from a stale save doesn't block the fresh save's real
        // finish (see EVENT_FLAG_TRACKING.md).
        if let Some(current_igt) = self.frame_snapshot.igt_ms {
            if detect_save_reload(self.last_observed_igt, current_igt) {
                info!(
                    prev_igt_ms = self.last_observed_igt,
                    new_igt_ms = current_igt,
                    "[RACE] Save reload detected, clearing per-save event-flag state"
                );
                self.triggered_flags.clear();
                self.flag_buffer.clear_deferred();
                self.flag_buffer.clear_pending();
            }
            self.last_observed_igt = Some(current_igt);
        }

        // Check position readability once per frame for loading screen detection.
        // Uses is_position_readable() to avoid allocating a map_id String.
        let position_readable = self.frame_snapshot.position_readable;

        // Reveal pending zone update once the loading screen ends and the
        // player position is readable. The loading flag may clear before the
        // fade-in completes, so position_readable acts as an additional guard.
        // Defensive timeout ensures the zone is always revealed eventually.
        if self.pending_zone_update.is_some() {
            let timed_out = self
                .pending_zone_received_at
                .is_some_and(|t| t.elapsed() >= ZONE_REVEAL_TIMEOUT);
            let loading_done = match self.frame_snapshot.loading_screen {
                Some(false) => true,
                Some(true) => false,
                // Flag unreadable: skip this check
                None => true,
            };
            let should_reveal = timed_out || (loading_done && position_readable);
            if should_reveal {
                let zone = self.pending_zone_update.take().unwrap();
                if timed_out {
                    warn!(name = %zone.display_name, "[RACE] Zone revealed (timeout)");
                } else {
                    info!(name = %zone.display_name, "[RACE] Zone revealed");
                }
                self.race_state.current_zone = Some(zone);
                self.pending_zone_received_at = None;
                self.pre_reveal_layer = None;
            }
        }

        // Loading screen exit: send deferred event_flags (certain) or zone_query (probabilistic)
        if position_readable && !self.was_position_readable {
            profile_span!("loading_exit_scan");
            // Force one immediate flag scan to catch flags set during loading
            // (e.g. Erdtree burn, Maliketh warp) that the 10Hz poll couldn't read
            // because is_flag_set() returns None while position is unreadable.
            if !self.event_ids.is_empty() {
                let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
                // Resolve category page once (all event_ids share the same category)
                let event_ids: Vec<u32> = self.event_ids.clone();
                let page = self.event_flag_reader.resolve_category(event_ids[0]);
                let page_ref = page.as_ref();
                for &flag_id in &event_ids {
                    if let Some(true) = self.event_flag_reader.is_flag_set_cached(flag_id, page_ref)
                    {
                        if self.finish_event == Some(flag_id) {
                            if !self.triggered_flags.contains(&flag_id) {
                                self.triggered_flags.insert(flag_id);
                                if self.ws_client.is_connected()
                                    && self.is_race_running()
                                    && !self.am_i_finished()
                                    && !self.is_countdown_active()
                                {
                                    self.send_tracked_event_flag(flag_id, igt_ms);
                                    self.last_sent_debug = Some(format!(
                                        "event_flag({}, igt={}ms) [finish/loading-exit]",
                                        flag_id, igt_ms
                                    ));
                                    info!(flag_id, "[RACE] Finish event caught at loading exit");
                                } else if !self.am_i_finished() {
                                    self.flag_buffer.add_pending(flag_id, igt_ms);
                                }
                            }
                        } else {
                            self.event_flag_reader
                                .set_flag_cached(flag_id, false, page_ref);
                            self.flag_buffer.defer(flag_id, igt_ms);
                            info!(flag_id, "[RACE] Event flag caught at loading exit");
                        }
                    }
                }
            }

            if self.ws_client.is_connected()
                && self.is_race_running()
                && !self.am_i_finished()
                && !self.is_countdown_active()
            {
                if self.flag_buffer.has_deferred() {
                    // Fog gate traversal: send deferred flags now that loading is done
                    let deferred: Vec<_> = self.flag_buffer.drain_deferred().collect();
                    for (flag_id, igt_ms) in deferred {
                        self.send_tracked_event_flag(flag_id, igt_ms);
                        self.last_sent_debug = Some(format!(
                            "event_flag({}, igt={}ms) [deferred]",
                            flag_id, igt_ms
                        ));
                        info!(flag_id, "[RACE] Deferred event flag sent at loading exit");
                    }
                } else {
                    // No fog gate (death/respawn/quit-out/fast-travel)
                    let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
                    let pos = self.game_state.read_position();
                    let grace_id = crate::eldenring::warp_hook::get_captured_grace_entity_id();
                    let grace_opt = if grace_id > 0 { Some(grace_id) } else { None };
                    let map_id = pos.as_ref().map(|p| p.map_id_str.clone());
                    let position = pos.as_ref().map(|p| [p.x, p.y, p.z]);
                    let play_region_id = pos.as_ref().and_then(|p| p.play_region_id);

                    if grace_opt.is_some() || map_id.is_some() {
                        self.send_tracked_zone_query(
                            igt_ms,
                            grace_opt,
                            map_id.clone(),
                            position,
                            play_region_id,
                        );
                        self.last_sent_debug = Some(format!(
                            "zone_query(grace={:?}, map={:?})",
                            grace_opt, map_id
                        ));
                        info!(?grace_opt, "[RACE] Zone query sent at loading exit");
                    }

                    if grace_id > 0 {
                        crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                    }
                }
            } else {
                // Disconnected during a live race: buffer deferred flags for
                // re-send on reconnect (they are already cleared from game
                // memory, so the safety-net rescan cannot recover them).
                if self.is_race_running() && !self.am_i_finished() {
                    let count = self.flag_buffer.park_deferred();
                    if count > 0 {
                        info!(
                            count,
                            "[RACE] Deferred flags moved to pending (disconnected)"
                        );
                    }
                } else {
                    self.flag_buffer.clear_deferred();
                }
                let grace_id = crate::eldenring::warp_hook::get_captured_grace_entity_id();
                if grace_id > 0 {
                    crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                }
            }

            // Remind the player when they load a save (or start a new game)
            // before the race has begun. Auto-dismisses after 3s.
            if self.is_race_setup() {
                self.set_status("Race hasn't started yet".to_string());
            }
        }
        self.was_position_readable = position_readable;

        // Event flag polling runs ALWAYS (even when disconnected).
        // Regular flags are cleared after capture (for re-traversal detection) and
        // deferred until loading exit; finish_event is sent immediately.
        if !self.event_ids.is_empty() && self.last_flag_poll.elapsed() >= Duration::from_millis(100)
        {
            profile_span!("event_flag_poll");
            self.last_flag_poll = Instant::now();

            // Log flag reader status transitions (not every tick)
            let status = self.event_flag_reader.diagnose();
            let current_ok = matches!(status, FlagReaderStatus::Ok { .. });
            if self.last_flag_reader_ok != Some(current_ok) {
                if current_ok {
                    info!("[RACE] Flag reader recovered (Ok)");
                } else {
                    warn!("[RACE] Flag reader degraded: {}", status);
                }
                self.last_flag_reader_ok = Some(current_ok);
            }

            // Snapshot already populated at the top of update() because
            // event_ids is non-empty (see need_igt).
            let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
            // Resolve category page once for all event_ids (same category)
            let poll_ids: Vec<u32> = self.event_ids.clone();
            let page = self.event_flag_reader.resolve_category(poll_ids[0]);
            let page_ref = page.as_ref();
            for &flag_id in &poll_ids {
                if self.finish_event == Some(flag_id) {
                    // finish_event: one-shot, use triggered_flags guard
                    if !self.triggered_flags.contains(&flag_id) {
                        if let Some(true) =
                            self.event_flag_reader.is_flag_set_cached(flag_id, page_ref)
                        {
                            self.triggered_flags.insert(flag_id);
                            if self.ws_client.is_connected()
                                && self.is_race_running()
                                && !self.am_i_finished()
                                && !self.is_countdown_active()
                            {
                                self.send_tracked_event_flag(flag_id, igt_ms);
                                self.last_sent_debug = Some(format!(
                                    "event_flag({}, igt={}ms) [finish]",
                                    flag_id, igt_ms
                                ));
                                info!(flag_id, "[RACE] Finish event sent immediately");
                            } else if !self.am_i_finished() {
                                self.flag_buffer.add_pending(flag_id, igt_ms);
                            }
                        }
                    }
                } else {
                    // Regular fog gate: clear after capture so re-traversals are detected
                    if let Some(true) = self.event_flag_reader.is_flag_set_cached(flag_id, page_ref)
                    {
                        self.event_flag_reader
                            .set_flag_cached(flag_id, false, page_ref);
                        self.flag_buffer.defer(flag_id, igt_ms);
                        info!(flag_id, "[RACE] Event flag deferred until loading exit");
                    }
                }
            }
        }

        if self.show_debug
            && self
                .last_debug_refresh
                .is_none_or(|t| t.elapsed() >= DEBUG_REFRESH_INTERVAL)
        {
            self.refresh_debug_info();
        }

        // Skip rest if not connected (status updates, ready, diagnostics)
        if !self.ws_client.is_connected() {
            return;
        }

        // Read game state
        let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
        let deaths = self.frame_snapshot.death_count.unwrap_or(0);

        // Send ready on (re)connection (skip in training mode since server auto-starts)
        if !self.ready_sent {
            if !self.config.server.training {
                self.ws_client.send_ready();
                self.last_sent_debug = Some("ready".to_string());
                info!("[RACE] Sent ready signal");
            }
            self.ready_sent = true;

            if self.is_race_running() && !self.am_i_finished() && !self.is_countdown_active() {
                // Replay in-flight event flags (sent but not ACKed before disconnect)
                // with their original message_id for server-side dedup.
                self.replay_in_flight_event_flags();

                // Replay in-flight zone queries (sent but not ACKed before disconnect)
                self.replay_in_flight_zone_queries();

                // Drain event flags buffered during disconnection (never sent)
                let pending: Vec<_> = self.flag_buffer.drain_pending().collect();
                for (flag_id, flag_igt) in pending {
                    self.send_tracked_event_flag(flag_id, flag_igt);
                    self.last_sent_debug =
                        Some(format!("event_flag({}, igt={})", flag_id, flag_igt));
                    info!(flag_id, "[RACE] Buffered event flag sent");
                }

                // Safety-net rescan: catch any flags still set in memory that polling missed
                let rescan_ids: Vec<u32> = self.event_ids.clone();
                let rescan_page = self.event_flag_reader.resolve_category(rescan_ids[0]);
                let rp = rescan_page.as_ref();
                for &flag_id in &rescan_ids {
                    if self.finish_event == Some(flag_id) {
                        if !self.triggered_flags.contains(&flag_id) {
                            if let Some(true) =
                                self.event_flag_reader.is_flag_set_cached(flag_id, rp)
                            {
                                self.triggered_flags.insert(flag_id);
                                self.send_tracked_event_flag(flag_id, igt_ms);
                                self.last_sent_debug =
                                    Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                                info!(flag_id, "[RACE] Finish event re-sent after reconnect");
                            }
                        }
                    } else if let Some(true) =
                        self.event_flag_reader.is_flag_set_cached(flag_id, rp)
                    {
                        self.event_flag_reader.set_flag_cached(flag_id, false, rp);
                        self.send_tracked_event_flag(flag_id, igt_ms);
                        self.last_sent_debug =
                            Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                        info!(flag_id, "[RACE] Event flag re-sent after reconnect");
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
            if let Some(&first_id) = self.event_ids.first() {
                let sample = self.event_flag_reader.is_flag_set(first_id);
                info!(flag_id = first_id, result = ?sample, "[RACE] Sample event flag read");
            }

            // Test a FogRando flag to confirm their category is readable
            let fogrando_sample = self.event_flag_reader.is_flag_set(1040292100);
            info!(result = ?fogrando_sample, "[RACE] FogRando flag 1040292100 read");
        }

        // Send periodic status updates (every 1 second, only when IGT is ticking and race running)
        // During quit-outs IGT is 0, skip to avoid erroneous data.
        // Stop once finished since IGT is frozen at finish time.
        if self.last_status_update.elapsed() >= Duration::from_secs(1)
            && igt_ms > 0
            && self.is_race_running()
            && !self.am_i_finished()
            && !self.is_countdown_active()
        {
            // Skip the weapon read during loading screens: ChrAsm may hold stale
            // or in-flight values while the player struct is being repopulated.
            let weapons = if self.game_state.is_in_loading_screen() == Some(true) {
                [None, None]
            } else {
                self.game_state.read_equipped_weapons()
            };
            self.ws_client.send_status_update(igt_ms, deaths, weapons);
            self.last_status_update = Instant::now();
        }
    }

    fn send_tracked_event_flag(&mut self, flag_id: u32, igt_ms: u32) {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_event_flags
            .insert(message_id, BufferedEventFlag { flag_id, igt_ms });
        self.ws_client.send_event_flag(flag_id, igt_ms, message_id);
    }

    fn send_tracked_zone_query(
        &mut self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
    ) {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_zone_queries.insert(
            message_id,
            BufferedZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id: map_id.clone(),
                position,
                play_region_id,
            },
        );
        self.ws_client.send_zone_query(
            igt_ms,
            grace_entity_id,
            map_id,
            position,
            play_region_id,
            message_id,
        );
    }

    /// Replay in-flight event flags (sent but not yet ACKed) with their
    /// original `message_id`, preserving server-side idempotency.
    ///
    /// Entries stay in `in_flight_event_flags` after replay: they are only
    /// removed when the server sends `EventFlagAck` for each one.
    fn replay_in_flight_event_flags(&mut self) {
        if self.in_flight_event_flags.is_empty() {
            return;
        }

        let mut entries: Vec<(u64, BufferedEventFlag)> = self
            .in_flight_event_flags
            .iter()
            .map(|(&k, &v)| (k, v))
            .collect();
        entries.sort_unstable_by_key(|(id, _)| *id);
        for (message_id, event) in entries {
            self.ws_client
                .send_event_flag(event.flag_id, event.igt_ms, message_id);
            info!(
                message_id,
                flag_id = event.flag_id,
                "[RACE] Replaying in-flight event flag"
            );
        }
    }

    fn replay_in_flight_zone_queries(&mut self) {
        if self.in_flight_zone_queries.is_empty() {
            return;
        }

        let mut message_ids: Vec<u64> = self.in_flight_zone_queries.keys().copied().collect();
        message_ids.sort_unstable();
        for message_id in message_ids {
            if let Some(zq) = self.in_flight_zone_queries.get(&message_id) {
                self.ws_client.send_zone_query(
                    zq.igt_ms,
                    zq.grace_entity_id,
                    zq.map_id.clone(),
                    zq.position,
                    zq.play_region_id,
                    message_id,
                );
                info!(message_id, "[RACE] Replaying in-flight zone query");
            }
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
                        self.flag_buffer.park_deferred();
                        self.set_status("Reconnecting to server...".to_string());
                    }
                    ConnectionStatus::Error => {
                        let msg = self
                            .last_auth_error
                            .take()
                            .unwrap_or_else(|| "Server maintenance".to_string());
                        self.set_status(msg);
                    }
                    ConnectionStatus::Disconnected => {
                        self.set_status("Disconnected".to_string());
                    }
                    ConnectionStatus::Connecting => {
                        // Silent: the dot indicator handles initial connection
                    }
                }
            }
            IncomingMessage::AuthOk {
                participant_id,
                mut race,
                seed,
                participants,
                phantom_skin,
            } => {
                info!(race = %race.name, participant_id = %participant_id, participants = participants.len(), "[WS] Auth OK");
                if let Some(ref name) = phantom_skin {
                    info!(skin = %name, "[WS] Equipped phantom skin received");
                }
                // Phantom skin runtime application: spawn a background thread
                // that re-applies the SpEffect on every game-world load.
                // Skipped on subsequent reconnects (same skin already running)
                // and when the seed predates the phantom_skins catalog (empty
                // map -> no-op for any name push).
                if let Some(ref name) = phantom_skin {
                    let already_running = self.phantom_skin_name.as_ref() == Some(name)
                        && self
                            .phantom_skin_thread
                            .as_ref()
                            .is_some_and(|h| !h.is_finished());
                    if already_running {
                        info!(
                            skin = %name,
                            "[PHANTOM_SKIN] Runner already running for this skin, skipping respawn"
                        );
                    } else {
                        match seed.phantom_skins.get(name) {
                            Some(directive) if !directive.speffects.is_empty() => {
                                let ids = directive.speffects.clone();
                                self.phantom_skin_stop = Arc::new(AtomicBool::new(false));
                                self.phantom_skin_name = Some(name.clone());
                                self.phantom_skin_thread =
                                    Some(crate::eldenring::sp_effect_runner::spawn(
                                        name.clone(),
                                        ids,
                                        Arc::clone(&self.phantom_skin_stop),
                                    ));
                            }
                            Some(_) => {
                                warn!(
                                    skin = %name,
                                    "[PHANTOM_SKIN] Seed catalog has the skin but no SpEffects; nothing to apply"
                                );
                            }
                            None => {
                                let available: Vec<&String> = seed.phantom_skins.keys().collect();
                                warn!(
                                    skin = %name,
                                    available = ?available,
                                    "[PHANTOM_SKIN] Skin not in this seed's catalog (older seed?), feature disabled"
                                );
                            }
                        }
                    }
                }
                self.last_received_debug = Some(format!(
                    "auth_ok(race={}, {} players)",
                    race.name,
                    participants.len()
                ));
                self.my_participant_id = Some(participant_id);
                self.my_participant_index = participants
                    .iter()
                    .position(|p| Some(&p.id) == self.my_participant_id.as_ref());
                self.event_ids = seed.event_ids.clone();
                self.finish_event = seed.finish_event;
                // Don't clear triggered_flags on reconnect: finish_event is one-shot.
                // Regular fog gate flags are no longer tracked in triggered_flags;
                // they're cleared in game memory after capture for re-traversal detection.
                race.reparse_dates();
                self.race_state.race = Some(race);
                self.frozen_igt_ms = None;

                // Detect seed mismatch (stale seed pack after re-roll)
                let config_seed_id = &self.config.server.seed_id;
                if !config_seed_id.is_empty() {
                    if let Some(ref server_seed_id) = seed.seed_id {
                        if config_seed_id != server_seed_id {
                            warn!(
                                config = %config_seed_id,
                                server = %server_seed_id,
                                "Seed mismatch: seed pack is outdated"
                            );
                            self.seed_mismatch = true;
                        } else {
                            self.seed_mismatch = false;
                        }
                    }
                }

                self.race_state.seed = Some(seed);
                // Spawn runtime items (gems/AoW) if present in seed
                if let Some(ref seed_info) = self.race_state.seed {
                    if !seed_info.spawn_items.is_empty() {
                        if self.items_spawned.load(Ordering::Relaxed) {
                            info!(
                                count = seed_info.spawn_items.len(),
                                "[RACE] Items already spawned this session, skipping"
                            );
                        } else {
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
                            } else {
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
                        }
                    }
                }
                self.race_state.participants = participants;
                self.bump_leaderboard_version();
            }
            IncomingMessage::AuthError(msg) => {
                self.last_received_debug = Some(format!("auth_error({})", msg));
                error!(message = %msg, "[WS] Auth failed");
                self.last_auth_error = Some(msg);
            }
            IncomingMessage::RaceStart(countdown_seconds) => {
                self.last_received_debug = Some(format!("race_start(cd={})", countdown_seconds));
                info!(countdown_seconds, "[WS] Race started!");
                let now = Instant::now();
                self.race_state.race_started_at = Some(now);
                if countdown_seconds > 0 {
                    self.race_state.countdown_end =
                        Some(now + Duration::from_secs(countdown_seconds as u64));
                } else {
                    self.race_state.countdown_end = None;
                }
                // Immediately reflect running status so is_race_running() gates open
                // without waiting for the race_status_change message that follows.
                if let Some(ref mut race) = self.race_state.race {
                    race.status = "running".to_string();
                }
                self.bump_leaderboard_version();
            }
            IncomingMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                self.last_received_debug = Some(format!(
                    "leaderboard_update({} players)",
                    participants.len()
                ));
                debug!(count = participants.len(), "[WS] Leaderboard update");
                // Snapshot current_layer before it gets bumped by the new
                // participants list, so the UI keeps the old X/Y and tier
                // until the zone name is revealed.
                if self.pre_reveal_layer.is_none() {
                    if let Some(my_id) = &self.my_participant_id {
                        let old_layer = self
                            .race_state
                            .participants
                            .iter()
                            .find(|p| &p.id == my_id)
                            .map(|p| p.current_layer);
                        let new_layer = participants
                            .iter()
                            .find(|p| &p.id == my_id)
                            .map(|p| p.current_layer);
                        if old_layer != new_layer {
                            self.pre_reveal_layer = old_layer;
                        }
                    }
                }
                self.race_state.participants = participants;
                self.race_state.leader_splits = leader_splits;
                self.refresh_my_participant_index();
                self.bump_leaderboard_version();
            }
            IncomingMessage::RaceStatusChange(status) => {
                self.last_received_debug = Some(format!("race_status_change({})", status));
                info!(status = %status, "[WS] Race status changed");
                // If race ends and we haven't finished, freeze our current game IGT.
                // The mod's local participant igt_ms is stale (only updated via
                // leaderboard_update on events, not on every status_update).
                if status == "finished" && !self.am_i_finished() {
                    self.frozen_igt_ms = self.game_state.read_igt();
                    self.frame_snapshot.igt_ms = self.frozen_igt_ms;
                    info!(frozen_igt_ms = ?self.frozen_igt_ms, "[WS] Froze game IGT (race ended, player not finished)");
                }
                if let Some(ref mut race) = self.race_state.race {
                    race.status = status;
                }
                self.bump_leaderboard_version();
            }
            IncomingMessage::RaceInfoUpdate(mut race) => {
                self.last_received_debug = Some(format!("race_info_update(name={})", race.name));
                info!(
                    race_ends_at = ?race.race_ends_at,
                    status = %race.status,
                    "[WS] Race info updated"
                );
                race.reparse_dates();
                self.race_state.race = Some(race);
            }
            IncomingMessage::PlayerUpdate(player) => {
                // Snapshot current_layer on increase (same rationale as LeaderboardUpdate).
                if self.pre_reveal_layer.is_none() {
                    if let Some(my_id) = &self.my_participant_id {
                        if &player.id == my_id {
                            if let Some(old_me) = self.my_participant() {
                                if player.current_layer > old_me.current_layer {
                                    self.pre_reveal_layer = Some(old_me.current_layer);
                                }
                            }
                        }
                    }
                }
                if let Some(p) = self
                    .race_state
                    .participants
                    .iter_mut()
                    .find(|p| p.id == player.id)
                {
                    *p = player;
                }
                self.refresh_my_participant_index();
                self.bump_leaderboard_version();
            }
            IncomingMessage::ZoneUpdate {
                node_id,
                display_name,
                tier,
                original_tier,
                layer,
                is_first_visit,
                exits,
                message_id,
            } => {
                if let Some(mid) = message_id {
                    self.in_flight_zone_queries.remove(&mid);
                }
                self.last_received_debug = Some(format!("zone_update({})", display_name));
                info!(node = %node_id, name = %display_name, first = is_first_visit, "[WS] Zone update (pending reveal)");
                // Last-writer-wins: if two flags fire in rapid succession, only the
                // final destination zone is shown (intermediate corridor zones are skipped).
                self.pending_zone_update = Some(ZoneUpdateData {
                    display_name,
                    tier,
                    original_tier,
                    layer,
                    is_first_visit,
                    exits,
                });
                self.pending_zone_received_at = Some(Instant::now());
            }
            IncomingMessage::EventFlagAck { message_id } => {
                if let Some(event) = self.in_flight_event_flags.remove(&message_id) {
                    info!(
                        message_id,
                        flag_id = event.flag_id,
                        "[WS] Event flag acknowledged"
                    );
                } else {
                    warn!(message_id, "[WS] Ack for unknown event flag");
                }
            }
            IncomingMessage::RequeueEventFlag {
                flag_id,
                igt_ms,
                message_id,
            } => {
                // Event flag was in the outgoing channel but never transmitted.
                // Remove from in-flight (server never saw it) and add to pending
                // buffer for resend with a fresh message_id.
                self.in_flight_event_flags.remove(&message_id);
                self.flag_buffer.add_pending(flag_id, igt_ms);
                info!(flag_id, message_id, "[WS] Re-queued drained event flag");
            }
            IncomingMessage::RequeueZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            } => {
                self.in_flight_zone_queries
                    .entry(message_id)
                    .or_insert(BufferedZoneQuery {
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                    });
                info!(message_id, "[WS] Re-queued drained zone query");
            }
            IncomingMessage::ZoneQueryAck { message_id } => {
                if self.in_flight_zone_queries.remove(&message_id).is_some() {
                    info!(message_id, "[WS] Zone query acknowledged (no zone_update)");
                } else {
                    warn!(message_id, "[WS] Ack for unknown zone query");
                }
            }
            IncomingMessage::DeathCounts(counts) => {
                self.last_received_debug = Some(format!("death_counts({} zones)", counts.len()));
                self.race_state.death_counts = counts.clone();
                if let Some(ref seed) = self.race_state.seed {
                    let page = seed
                        .death_flags
                        .values()
                        .flat_map(|f| f.iter())
                        .next()
                        .and_then(|&fid| self.event_flag_reader.resolve_category(fid));
                    let page_ref = page.as_ref();
                    for (node_id, total) in &counts {
                        if let Some(flags) = seed.death_flags.get(node_id) {
                            self.event_flag_reader
                                .set_flag_cached(flags[0], *total >= 1, page_ref);
                            self.event_flag_reader
                                .set_flag_cached(flags[1], *total >= 3, page_ref);
                            self.event_flag_reader
                                .set_flag_cached(flags[2], *total >= 5, page_ref);
                        }
                    }
                }
            }
            IncomingMessage::Error(e) => {
                self.last_received_debug = Some(format!("error({})", e));
                warn!(error = %e, "[WS] Error");
                self.set_status(e);
            }
            IncomingMessage::PermanentError(msg) => {
                self.last_received_debug = Some(format!("permanent_error({})", msg));
                error!(message = %msg, "[WS] Permanent error, stopping reconnection");
                self.permanent_error = Some(msg);
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
        self.frame_snapshot
            .igt_ms
            .or_else(|| self.game_state.read_igt())
    }

    pub fn read_deaths(&self) -> Option<u32> {
        self.frame_snapshot
            .death_count
            .or_else(|| self.game_state.read_deaths())
    }

    pub fn current_zone_info(&self) -> Option<&ZoneUpdateData> {
        self.race_state.current_zone.as_ref()
    }

    /// During the zone reveal wait, returns the frozen current_layer from
    /// before the leaderboard update. Returns None outside the wait.
    pub fn pre_reveal_layer(&self) -> Option<i32> {
        self.pre_reveal_layer
    }

    pub fn my_participant_id(&self) -> Option<&String> {
        self.my_participant_id.as_ref()
    }

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        let idx = self.my_participant_index?;
        self.race_state.participants.get(idx)
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

    pub fn debug_info(&self) -> &DebugInfo {
        &self.debug_info
    }

    fn refresh_my_participant_index(&mut self) {
        self.my_participant_index = self.my_participant_id.as_ref().and_then(|id| {
            self.race_state
                .participants
                .iter()
                .position(|p| &p.id == id)
        });
    }

    fn bump_leaderboard_version(&mut self) {
        self.leaderboard_version = self.leaderboard_version.wrapping_add(1);
    }

    fn refresh_debug_info(&mut self) {
        let flag_reader_status = self.event_flag_reader.diagnose();
        let flag_reader_ok = matches!(flag_reader_status, FlagReaderStatus::Ok { .. });

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

        self.debug_info = DebugInfo {
            last_sent: self.last_sent_debug.clone(),
            last_received: self.last_received_debug.clone(),
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
