//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress via EMEVD event flags and communicates with the racing server.

use hudhook::imgui::FontId;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::color::parse_hex_color;
use crate::core::equip_load::{base_max, load_rate};
use crate::core::foes::FoesRecord;
use crate::core::format::{LeaderboardMode, LeaderboardView};
use crate::core::item_damage::damaged_hp;
use crate::core::job_queue::{Asked, JobQueue, QueuedJob};
use crate::core::memory_effects::{CameraRow, MemoryState};
use crate::core::protocol::{
    CameraVariant, CharacterState, ParticipantInfo, RaceInfo, SeedInfo, TalismanFlag,
};
use crate::core::race_machine::{
    ConnectionStatus, Effect, FrameSnapshot, MachineMessage, RaceMachine, TickInput, ZoneUpdateData,
};
use crate::core::relay_apply::{ApplyEnd, ApplyPlan, ApplyRun};
use crate::core::talisman_thief::pick_talisman;
use crate::core::timed_effects::timed_apply;
use crate::eldenring::equip_change;
use crate::eldenring::hunter::{self, HunterWatch};
use crate::eldenring::memory_effects;
use crate::eldenring::race_items;
use crate::eldenring::relay;
use crate::eldenring::sp_effect_apply;
use crate::eldenring::{EventFlagReader, FlagReaderStatus, GameState};
use crate::profile_span;

use super::config::RaceConfig;
use super::death_icon::DeathIcon;
use super::livesplit::LiveSplitClient;
use super::race_item_icons::RaceItemIcons;
use super::unacked_store::UnackedStore;
use super::websocket::RaceWebSocketClient;

#[cfg(debug_assertions)]
const DEBUG_REFRESH_INTERVAL: std::time::Duration = std::time::Duration::from_millis(250);

/// How long the memory writes stay quiet before a state the game does not
/// hold is written again (`retry_memory_state`).
const MEMORY_RETRY_INTERVAL: Duration = Duration::from_secs(1);
/// Consecutive update() panics before tracking latches off (~5 s at 60 FPS).
pub(crate) const MAX_CONSECUTIVE_UPDATE_PANICS: u32 = 300;
pub(crate) const LEADERBOARD_REFRESH_INTERVAL_MS: u32 = 250;

// =============================================================================
// RACE STATE
// =============================================================================

/// Pre-allocated buffers reused across frames to avoid per-frame heap allocations.
pub(crate) struct RenderBuffers {
    pub buf_right: String,
    pub buf_left: String,
    pub buf_footer: String,
    /// Last rendered "time left" seconds + its formatted text (rebuilt 1x/s).
    pub banner_secs: Option<i64>,
    pub banner_text: String,
    /// Digit (or `GO!`) drawn by the fullscreen countdown.
    pub countdown_label: String,
    /// Seconds left of the reminder row being drawn.
    pub reminder_secs: String,
}

impl Default for RenderBuffers {
    fn default() -> Self {
        Self {
            // String::new() does not allocate: the default value created by
            // the per-frame mem::take is dropped unread, so giving it capacity
            // would be 4 wasted heap allocations per frame. The persistent
            // buffers grow to their working size on first real use.
            buf_right: String::new(),
            buf_left: String::new(),
            buf_footer: String::new(),
            banner_secs: None,
            banner_text: String::new(),
            countdown_label: String::new(),
            reminder_secs: String::new(),
        }
    }
}

/// Result of reading a single flag for debug display
#[cfg(debug_assertions)]
#[derive(Clone, Copy)]
pub enum FlagReadResult {
    /// Memory read failed
    Unreadable,
    /// Flag is not set
    NotSet,
    /// Flag is set
    Set,
}

/// Debug overlay info. The debug overlay only exists in debug builds: a
/// release build has neither the panel nor its `toggle_debug` hotkey.
#[cfg(debug_assertions)]
pub struct DebugInfo {
    pub last_sent: Option<String>,
    pub last_received: Option<String>,
    pub flag_reader_status: String,
    pub flag_reader_ok: bool,
    /// Vanilla flag 6 sanity check (category 0 should always exist)
    pub vanilla_sanity: FlagReadResult,
    pub sample_reads: Vec<(u32, FlagReadResult)>,
    /// Raw loading byte (engine flags 2200-2207, `GameState::read_loading_byte`)
    pub loading_byte: Option<u8>,
    /// Direct screen signal (`GameState::is_screen_in_game`); None = unmapped build
    pub screen_in_game: Option<bool>,
    /// Blackscreen fade active (`GameState::is_blackscreen_active`)
    pub blackscreen: Option<bool>,
    /// Return-to-title Lua bit, debug-only telemetry (live testing showed it
    /// fires on scripted returns, not menu quit-outs, so detection uses the
    /// title screen + IGT regression instead). None = AOB unresolved or
    /// pointer chain null.
    pub quit_out_bit: Option<bool>,
}

#[cfg(debug_assertions)]
impl Default for DebugInfo {
    fn default() -> Self {
        Self {
            last_sent: None,
            last_received: None,
            flag_reader_status: String::new(),
            flag_reader_ok: false,
            vanilla_sanity: FlagReadResult::Unreadable,
            sample_reads: Vec::new(),
            loading_byte: None,
            screen_in_game: None,
            blackscreen: None,
            quit_out_bit: None,
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
    pub top_count: usize,
    pub window: Option<std::ops::Range<usize>>,
    pub footer_more: usize,
    pub mode: LeaderboardMode,
    pub version: u64,
    pub local_igt_bucket: Option<u32>,
    pub max_width: f32,
    pub spacing: f32,
}

/// Pre-rendered exit lines for the current zone, rebuilt only when the
/// machine's zone_version changes (reveal) or max_width changes.
#[derive(Default)]
pub(crate) struct ExitsRenderCache {
    pub version: u64,
    pub max_width: f32,
    /// Built while an ink effect hid every destination.
    pub ink: bool,
    pub rows: Vec<ExitRow>,
}

pub(crate) struct ExitRow {
    /// Pre-truncated destination line ("→ Name" or "→ ???").
    pub dest: String,
    pub discovered: bool,
    /// Pre-wrapped direction lines.
    pub lines: Vec<String>,
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
    pub gold: [f32; 4],        // #C8A44E - brass
    pub success: [f32; 4],     // #4AAE8C - verdigris
    pub danger: [f32; 4],      // #DC6A51 - ember
    pub danger_dark: [f32; 4], // #B5462F
    pub purple: [f32; 4],      // #A99BC9 - fog, local player accent
    pub purple_bg: [f32; 4],   // fog at 0.12 - leaderboard row bg
    pub ground: [f32; 4],      // #0F1923 - page ground, alpha set per use
}

/// ImGui font ids for the overlay's faces, registered at ImGui init. The
/// body face (atlas default) carries prose at full size; display carries
/// the race name; mono the data columns (IGT, gaps, counters, debug); and
/// body_small is the body face at the mono pixel size, for names inside
/// mono rows (ImGui top-aligns mixed-size text on a line, so equal pixel
/// sizes are what keep a shared baseline). The countdown face is the display
/// face again, rasterized once at `COUNTDOWN_FONT_ATLAS_PX` and scaled at
/// draw time: its size follows the display, which the atlas cannot.
pub(crate) struct OverlayFonts {
    pub body_small: FontId,
    pub display: FontId,
    pub mono: FontId,
    pub countdown: FontId,
    /// Barlow Condensed at a size the banner title scales from (race items).
    pub banner_title: FontId,
    /// Public Sans at a size the banner lines scale from (race items).
    pub banner_body: FontId,
}

// SAFETY: FontId wraps a raw pointer into the ImGui font atlas, which makes
// it !Send + !Sync and would poison RaceTracker's Send + Sync bounds that
// hudhook's builder requires. The ids are opaque handles: they are only
// created and dereferenced on the render thread, and the ImGui context that
// owns the atlas outlives the tracker.
unsafe impl Send for OverlayFonts {}
unsafe impl Sync for OverlayFonts {}

// =============================================================================
// RELAY WORKER
// =============================================================================

/// A job of the relay worker thread, as the machine asked it. Kept in the
/// queue while its thread runs, so the answer carries the request's identity
/// even from a thread that panicked.
#[derive(Debug)]
enum RelayJob {
    /// `Effect::CaptureRelayState`, answered by
    /// `RaceMachine::relay_state_captured`.
    Capture {
        handoff_id: Option<String>,
        generation: u64,
    },
    /// `Effect::ApplyRelayItems`: its plan read on the worker thread, then
    /// its writes on the game thread (`run_relay_apply`), answered by
    /// `RaceMachine::relay_state_applied` once they ended. It stays the
    /// running job until then, so a job asked meanwhile waits behind the
    /// writes too (a capture never reads the inventory while it is given
    /// to).
    Apply {
        run: ApplyRun,
        request: ApplyRequest,
    },
}

impl QueuedJob for RelayJob {
    fn replaceable(&self) -> bool {
        match self {
            // The machine asks a capture again only once it has given up the
            // previous one (abandoned, or pre-empted by a release).
            RelayJob::Capture { .. } => true,
            // Every apply is answered, exactly once.
            RelayJob::Apply { .. } => false,
        }
    }
}

/// What an apply's plan is made from (the take's state and defeat flags).
struct ApplyRequest {
    items: Vec<u32>,
    flags: Vec<u32>,
    grace_flags: Vec<u32>,
}

impl std::fmt::Debug for ApplyRequest {
    /// The counts only: a state carries up to thousands of ids.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApplyRequest")
            .field("items", &self.items.len())
            .field("flags", &self.flags.len())
            .field("grace_flags", &self.grace_flags.len())
            .finish()
    }
}

/// What a relay worker thread returns, one variant per job.
enum RelayJobDone {
    Captured(Option<CharacterState>),
    Planned(ApplyPlan),
}

// =============================================================================
// RACE TRACKER
// =============================================================================

pub struct RaceTracker {
    // Game reader (shared with the relay worker thread, which reads the
    // loaded map through it)
    game_state: Arc<GameState>,

    // Event flag reader
    event_flag_reader: EventFlagReader,

    // WebSocket
    pub(crate) ws_client: RaceWebSocketClient,

    // LiveSplit pipe link (its own thread)
    livesplit: LiveSplitClient,

    // Config
    pub(crate) config: RaceConfig,
    pub(crate) cached_colors: CachedColors,

    // Font data loaded from file (for ImGui registration)
    pub(crate) font_data: Option<Vec<u8>>,

    // Font ids registered at ImGui init (None until initialize runs)
    pub(crate) overlay_fonts: Option<OverlayFonts>,

    // Death icon texture (loaded during ImGui initialization)
    pub(crate) death_icon: Option<DeathIcon>,

    // Race item icon textures (loaded during ImGui initialization)
    pub(crate) race_item_icons: Option<RaceItemIcons>,

    // Pure race state machine (all decisions, no IO)
    pub(crate) machine: RaceMachine,

    // UI state
    pub(crate) show_ui: bool,
    #[cfg(debug_assertions)]
    pub(crate) show_debug: bool,
    pub(crate) leaderboard_view: LeaderboardView,
    /// Hard latch: a durably-broken update loop; rendering and updates stop
    /// for the session (set after MAX_CONSECUTIVE_UPDATE_PANICS).
    pub(crate) tracking_disabled: bool,
    /// Soft latch: the ImGui draw panicked; the overlay stays hidden but
    /// update() keeps tracking the race.
    pub(crate) overlay_panicked: bool,
    /// Consecutive update() panics; reset on the first clean update.
    pub(crate) consecutive_update_panics: u32,
    // One-time diagnostic log flag
    flags_diagnosed: bool,

    // Item spawner thread handle (prevents double-spawn on reconnect)
    spawner_thread: Option<JoinHandle<()>>,

    // The relay worker's jobs: the one running and those waiting, one at a
    // time so the character is never read by two jobs at once.
    relay_jobs: JobQueue<RelayJob>,
    // The thread of the running relay job, drained by `poll_relay_job` on
    // the game thread.
    relay_thread: Option<JoinHandle<RelayJobDone>>,

    // Items actually spawned this session (in-process guard for reconnects).
    // Set by the spawner thread AFTER items are given to the player, so a stale
    // save that skips spawning leaves this false, allowing retry on the next auth_ok.
    items_spawned: Arc<AtomicBool>,

    // Phantom skin runner thread handle (one per session).
    phantom_skin_thread: Option<JoinHandle<()>>,

    // Phantom skin runner stop flag, flipped when a different skin name
    // arrives so the previous runner stops re-applying its own SpEffect.
    phantom_skin_stop: Arc<AtomicBool>,

    // Cached equipped phantom skin name to avoid respawning the runner on
    // every reconnect's auth_ok.
    phantom_skin_name: Option<String>,

    // Race item game access readied off the render thread (once per
    // process, at the first auth_ok of a race with items).
    race_items_prewarmed: bool,

    // The last equip load rate written and the max load it was computed
    // from: a max read equal to their product means the effect still runs.
    equip_load_last: Option<(f32, f32)>,

    // The memory race item effects as last written into the game, field by
    // field (`apply_memory_state`): a field back at its default is written
    // once, only when an effect was written there.
    memory_written: MemoryState,
    // When a memory state was last written, whoever asked
    // (`retry_memory_state` waits from there).
    memory_retry_at: Instant,

    // The LockCamParam rows' own values, by row id, saved by the Camera's
    // first write; emptied once written back.
    camera_originals: HashMap<u64, CameraRow>,

    // The characters the foes walks hid (`core::foes`).
    foes_record: FoesRecord,

    // The Hunter's last spawn request, for the shell's log lines (never a
    // pointer to him: each look walks the debug chr set again).
    hunter_watch: HunterWatch,

    // Saves the unacknowledged event flags next to the DLL (None when the
    // DLL folder is unknown: nothing survives a restart then).
    unacked_store: Option<UnackedStore>,

    // Throttled debug snapshot to avoid expensive flag reads every frame.
    #[cfg(debug_assertions)]
    debug_info: DebugInfo,
    #[cfg(debug_assertions)]
    last_debug_refresh: Option<Instant>,

    // Cached leaderboard layout invalidated by participant/status changes.
    pub(crate) leaderboard_cache: LeaderboardCache,

    // Pre-rendered exit lines, invalidated by the machine's zone_version.
    pub(crate) exits_cache: ExitsRenderCache,

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

        // Warm the quit-out AOB scan (debug builds only) and install the IGT
        // truncation-fix hook off the frame path: both walk the whole module
        // image.
        std::thread::spawn(|| {
            #[cfg(debug_assertions)]
            let _ = crate::eldenring::quitout::is_available();
            crate::eldenring::igt_hook::install();
        });

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
            success: parse_hex_color("#4AAE8C", 1.0),
            danger: parse_hex_color("#DC6A51", 1.0),
            danger_dark: parse_hex_color("#B5462F", 1.0),
            purple: parse_hex_color("#A99BC9", 1.0),
            purple_bg: parse_hex_color("#A99BC9", 0.12),
            ground: parse_hex_color("#0F1923", 1.0),
        };

        let config_seed_id = config.server.seed_id.clone();
        let config_training = config.server.training;
        let leaderboard_mode = config.overlay.leaderboard_mode;

        // Create WebSocket client
        let mut ws_client = RaceWebSocketClient::new(config.server.clone());
        ws_client.connect();

        let livesplit = LiveSplitClient::start();

        let mut machine = RaceMachine::new(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
            config_seed_id,
            config_training,
            Instant::now(),
        );
        // Flags a previous launch closed or crashed before the server
        // acknowledged them; then the writer for this launch's.
        if let Some(saved) = dll_dir.as_deref().and_then(UnackedStore::load) {
            machine.restore_unacked(saved);
        }
        let unacked_store = dll_dir.map(UnackedStore::spawn);

        info!("RaceTracker initialized");

        Some(Self {
            game_state: Arc::new(game_state),
            event_flag_reader,
            ws_client,
            livesplit,
            config,
            cached_colors,
            font_data,
            overlay_fonts: None,
            death_icon: None,
            race_item_icons: None,
            machine,
            show_ui: true,
            #[cfg(debug_assertions)]
            show_debug: false,
            leaderboard_view: LeaderboardView::Shown(leaderboard_mode),
            tracking_disabled: false,
            overlay_panicked: false,
            consecutive_update_panics: 0,
            flags_diagnosed: false,
            spawner_thread: None,
            relay_jobs: JobQueue::default(),
            relay_thread: None,
            items_spawned: Arc::new(AtomicBool::new(false)),
            phantom_skin_thread: None,
            phantom_skin_stop: Arc::new(AtomicBool::new(false)),
            phantom_skin_name: None,
            race_items_prewarmed: false,
            equip_load_last: None,
            memory_written: MemoryState::default(),
            memory_retry_at: Instant::now(),
            camera_originals: HashMap::new(),
            foes_record: FoesRecord::default(),
            hunter_watch: HunterWatch::default(),
            unacked_store,
            #[cfg(debug_assertions)]
            debug_info: DebugInfo::default(),
            #[cfg(debug_assertions)]
            last_debug_refresh: None,
            leaderboard_cache: LeaderboardCache::default(),
            exits_cache: ExitsRenderCache::default(),
            render_bufs: RenderBuffers::default(),
        })
    }

    pub fn is_race_running(&self) -> bool {
        self.machine.is_race_running()
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

        // Check toggle_debug hotkey (debug builds only)
        #[cfg(debug_assertions)]
        {
            if let Some(ref hotkey) = self.config.keybindings.toggle_debug {
                if hotkey.is_just_pressed(ui) {
                    self.show_debug = !self.show_debug;
                    info!(show_debug = self.show_debug, "[HOTKEY] Toggle debug");
                }
            }
        }

        // Check toggle_leaderboard hotkey
        if let Some(ref hotkey) = self.config.keybindings.toggle_leaderboard {
            if hotkey.is_just_pressed(ui) {
                self.leaderboard_view = self
                    .leaderboard_view
                    .next(self.config.overlay.leaderboard_mode);
                info!(
                    leaderboard_view = ?self.leaderboard_view,
                    "[HOTKEY] Cycle leaderboard"
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

        self.poll_relay_job();

        // Gather tick inputs: the machine decides what to read, the shell
        // performs the game-memory reads, the machine consumes them.
        let now = Instant::now();
        let connected = self.ws_client.is_connected();
        let needs = self.machine.pre_tick(now, self.show_ui, connected);

        let snapshot = {
            profile_span!("frame_snapshot");
            // One readability read gives both the flag and the map id.
            let map_id = self.game_state.loaded_map_id();
            // Screen-state and blackscreen share one pointer-chain read
            // (`is_blackscreen_active` depends on `is_screen_in_game`);
            // read both through the combined accessor so the chain is
            // evaluated once per frame instead of twice.
            let (screen_in_game, blackscreen) = needs
                .blackscreen
                .then(|| self.game_state.read_screen_signals())
                .unwrap_or_default();
            FrameSnapshot {
                igt_ms: needs.igt.then(|| self.game_state.read_igt()).flatten(),
                death_count: needs
                    .deaths
                    .then(|| self.game_state.read_deaths())
                    .flatten(),
                position_readable: map_id.is_some(),
                map_id,
                hp: needs.hp.then(|| self.game_state.read_hp()).flatten(),
                loading_screen: needs
                    .loading
                    .then(|| self.game_state.is_world_clock_stopped())
                    .flatten(),
                screen_in_game,
                blackscreen,
                debug_flags: needs
                    .debug_flags
                    .then(|| self.game_state.read_debug_flags())
                    .flatten()
                    .map(|bytes| crate::core::debug_flags::mask_from_bytes(&bytes)),
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
            let ids = &self.machine.event_ids;
            let page = self.event_flag_reader.resolve_category(ids[0]);
            let page_ref = page.as_ref();
            let mut reads: Vec<(u32, bool)> = ids
                .iter()
                .filter_map(|&flag_id| {
                    self.event_flag_reader
                        .is_flag_set_cached(flag_id, page_ref)
                        .map(|set| (flag_id, set))
                })
                .collect();
            {
                // A few unreported boss defeat flags per scan, in rotation,
                // while the run is live. They sit in other categories: each
                // read falls back to a full category lookup.
                profile_span!("boss_flag_reads");
                reads.extend(self.machine.boss_flags_to_read().filter_map(|flag_id| {
                    self.event_flag_reader
                        .is_flag_set_cached(flag_id, page_ref)
                        .map(|set| (flag_id, set))
                }));
            }
            {
                // Every race item use flag, while the run is live in a race
                // with items. They share one category, other than the
                // event_ids' one: its page is resolved once for all of them.
                profile_span!("item_use_flag_reads");
                let mut use_flags = self.machine.item_use_flags_to_read().peekable();
                if let Some(&first) = use_flags.peek() {
                    let use_page = self.event_flag_reader.resolve_category(first);
                    let use_page_ref = use_page.as_ref();
                    reads.extend(use_flags.filter_map(|flag_id| {
                        self.event_flag_reader
                            .is_flag_set_cached(flag_id, use_page_ref)
                            .map(|set| (flag_id, set))
                    }));
                }
            }
            flag_reads = Some(reads);
        }

        // Weapons: read only when a status_update may fire this frame.
        // Skip the read during loading screens (position unreadable): ChrAsm
        // may hold stale or in-flight values while the player struct is being
        // repopulated.
        let weapons = if connected
            && snapshot.position_readable
            && self
                .machine
                .wants_status_update(now, snapshot.igt_ms.unwrap_or(0))
        {
            self.game_state.read_equipped_weapons()
        } else {
            [None, None]
        };

        let loaded = snapshot.position_readable;
        let input = TickInput {
            snapshot,
            connected,
            warp_capture,
            position,
            flag_reads,
            weapons,
            flag_reader_ok,
            // The key binding comes with the overlay lot.
            relay_key_down: false,
        };
        let effects = self.machine.tick(input, now);
        self.execute_effects(effects);
        self.run_relay_apply(now);
        self.retry_memory_state(loaded, now);

        {
            profile_span!("livesplit_publish");
            // After every run view of this frame was queued (execute_effects):
            // the LiveSplit thread reads the IGT, then the views queued before it.
            self.livesplit.publish_igt(self.machine.live_igt_ms());
            while let Some(status) = self.livesplit.poll_status() {
                self.machine.set_status(status.to_string(), now);
            }
        }

        #[cfg(debug_assertions)]
        {
            if self.show_debug
                && self
                    .last_debug_refresh
                    .is_none_or(|t| t.elapsed() >= DEBUG_REFRESH_INTERVAL)
            {
                self.refresh_debug_info();
            }
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
        // The category page is resolved from the first SetGameFlag and reused
        // for every SetGameFlag in the batch. A flag of another category
        // (a race item use or removal flag next to fog flag clears) falls
        // back to a full category lookup in `set_flag_fast`, so a mixed
        // batch stays correct, one extra lookup per foreign flag.
        let mut flag_page = None;
        for effect in effects {
            match effect {
                Effect::SendReady => {
                    self.ws_client.send_ready();
                }
                Effect::SendRelayReady { ready } => {
                    self.ws_client.send_relay_ready(ready);
                }
                Effect::SendRelayState {
                    handoff_id,
                    state,
                    igt_ms,
                } => {
                    self.ws_client.send_relay_state(handoff_id, state, igt_ms);
                }
                Effect::CaptureRelayState {
                    handoff_id,
                    generation,
                } => self.request_relay_job(RelayJob::Capture {
                    handoff_id,
                    generation,
                }),
                Effect::WriteCharacterStats {
                    attributes,
                    level,
                    runes,
                } => {
                    // Synchronous, on this frame: the machine reads the next
                    // frame as written. A failed write fails no take.
                    let before = relay::read_stats();
                    if !relay::write_stats(attributes, level, runes) {
                        warn!(
                            ?before,
                            ?attributes,
                            level,
                            runes,
                            "[RELAY] Stats not written (unwritable, or what is there does not read as a character's stats)"
                        );
                    } else {
                        let after = relay::read_stats();
                        if after == Some((attributes, level, runes)) {
                            info!(?before, ?attributes, level, runes, "[RELAY] Stats written");
                        } else {
                            warn!(
                                ?before,
                                ?after,
                                ?attributes,
                                level,
                                runes,
                                "[RELAY] Stats read back differ from the ones written"
                            );
                        }
                    }
                }
                Effect::SetIgt { ms } => {
                    if self.game_state.write_igt(ms).is_some() {
                        info!(ms, "[RELAY] IGT written");
                    } else {
                        warn!(ms, "[RELAY] IGT not written (IGT unwritable)");
                    }
                }
                Effect::ApplyRelayItems {
                    handoff_id,
                    generation,
                    items,
                    flags,
                    grace_flags,
                } => {
                    // The map of this frame, the take's start frame: the
                    // apply writes only while every frame reads it.
                    let run = ApplyRun::new(
                        handoff_id,
                        generation,
                        self.machine.frame_snapshot.map_id,
                        Instant::now(),
                    );
                    self.request_relay_job(RelayJob::Apply {
                        run,
                        request: ApplyRequest {
                            items,
                            flags,
                            grace_flags,
                        },
                    });
                }
                Effect::SendRelayTaken { handoff_id } => {
                    self.ws_client.send_relay_taken(handoff_id);
                }
                Effect::SendRelayHandoffRequest { to_participant_id } => {
                    self.ws_client.send_relay_handoff_request(to_participant_id);
                }
                Effect::SendRelayTakeRequest => {
                    self.ws_client.send_relay_take_request();
                }
                Effect::SendStatusUpdate {
                    igt_ms,
                    death_count,
                    weapons,
                    debug_flags,
                } => {
                    self.ws_client
                        .send_status_update(igt_ms, death_count, weapons, debug_flags);
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
                    quit_out,
                } => {
                    self.ws_client.send_zone_query(
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                        quit_out,
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
                Effect::ApplyIgtPenalty { ms } => match self.game_state.add_igt_penalty(ms) {
                    Some(new_igt) => {
                        info!(ms, new_igt, "[RACE] Quit-out IGT penalty applied");
                    }
                    None => {
                        warn!(ms, "[RACE] Quit-out penalty skipped: IGT unwritable");
                    }
                },
                Effect::FreezeIgt { ms } => {
                    // Per-fade-frame write; debug level, a warn would spam
                    // whole fades when the chain is transiently unwritable.
                    if self.game_state.write_igt(ms).is_none() {
                        debug!(ms, "[IGT] Freeze write failed (IGT unwritable)");
                    }
                }
                Effect::ClearWarpCapture => {
                    crate::eldenring::warp_hook::clear_captured_grace_entity_id();
                }
                Effect::SpawnItems => self.spawn_items_if_needed(),
                Effect::StartPhantomSkin { name, speffects } => {
                    self.start_phantom_skin(name, speffects)
                }
                Effect::LiveSplitRun(view) => self.livesplit.send_run(*view),
                Effect::PersistUnackedFlags(flags) => {
                    if let Some(ref store) = self.unacked_store {
                        store.save(flags);
                    }
                }
                Effect::SendItemReceived { grant_id } => {
                    self.ws_client.send_item_received(grant_id);
                }
                Effect::PrewarmRaceItems => self.prewarm_race_items(),
                Effect::SetGoodsIcon { goods_id, icon_id } => {
                    if race_items::set_goods_icon(goods_id, icon_id) {
                        info!(goods_id, icon_id, "[ITEMS] Goods icon set");
                    } else {
                        warn!(
                            goods_id,
                            icon_id,
                            "[ITEMS] Goods icon not set (params not indexed yet or row missing), the next loading exit or reconnection writes it again"
                        );
                    }
                }
                Effect::SpawnRaceItem { grant_id, goods_id } => {
                    let spawned = self.spawn_race_item(grant_id, goods_id);
                    self.machine
                        .grant_spawn_result(grant_id, spawned, Instant::now());
                }
                Effect::ReportItemInventory { goods } => self.report_item_inventory(goods),
                Effect::ApplySpEffect {
                    speffect_id,
                    left_ms,
                } => Self::apply_item_speffect(speffect_id, left_ms),
                Effect::ApplyItemDamage {
                    base_pct,
                    floor_pct,
                    tail_pct,
                } => Self::apply_item_damage(base_pct, floor_pct, tail_pct),
                Effect::ApplyEquipLoad {
                    speffect_id,
                    load_pct,
                    left_ms,
                } => self.apply_equip_load(speffect_id, load_pct, left_ms),
                Effect::ApplyMemoryState { state, walk_foes } => {
                    self.apply_memory_state(state, walk_foes)
                }
                Effect::StealTalisman {
                    talismans,
                    roll,
                    report_id,
                } => {
                    let stolen = self.steal_talisman(&talismans, roll, report_id);
                    let report = self.machine.talisman_steal_result(report_id, stolen);
                    self.execute_effects(report);
                }
                Effect::SpawnTalisman { talisman_id } => {
                    if race_items::spawn_talisman(talisman_id) {
                        info!(talisman_id, "[ITEMS] Talisman given");
                    } else {
                        warn!(
                            talisman_id,
                            "[ITEMS] Talisman not given (the give function or MapItemMan is unavailable)"
                        );
                    }
                }
                Effect::EquipJunkWeapon { weapon_id } => {
                    // Each step and its outcome are logged inside.
                    if !equip_change::equip_junk_weapon(weapon_id) {
                        warn!(weapon_id, "[ITEMS] Junk weapon not in hand");
                    }
                }
                // Each step and its outcome are logged inside.
                Effect::RequestHunter {
                    chr_id,
                    npc_param_id,
                    think_id,
                } => {
                    let started = hunter::request_hunter(
                        chr_id,
                        npc_param_id,
                        think_id,
                        &mut self.hunter_watch,
                    );
                    self.machine.hunter_request_result(started, Instant::now());
                }
                Effect::FindHunter { npc_param_id } => {
                    let found = hunter::find_hunter(npc_param_id, &mut self.hunter_watch);
                    self.machine.hunter_seen(found, Instant::now());
                }
                Effect::EndHunter { npc_param_id } => {
                    if !hunter::end_hunter(npc_param_id, &mut self.hunter_watch) {
                        warn!(npc_param_id, "[ITEMS] Hunter end incomplete, he may remain");
                    }
                }
                Effect::SendItemReport {
                    report_id,
                    landed,
                    talisman_id,
                } => {
                    self.ws_client
                        .send_item_report(report_id, landed, talisman_id);
                }
            }
        }
    }

    /// Resolve, on a background thread, what race item effects need and
    /// whose lookup scans or waits on the game (the SpEffect apply function,
    /// the param table index), so the first effect does not stall a frame.
    /// Once per process; a reconnection's auth_ok asks again.
    fn prewarm_race_items(&mut self) {
        if self.race_items_prewarmed {
            return;
        }
        self.race_items_prewarmed = true;
        info!("[ITEMS] Prewarming the SpEffect apply function, the equip function and the params");
        std::thread::spawn(sp_effect_apply::prewarm);
        std::thread::spawn(equip_change::prewarm);
        std::thread::spawn(race_items::prewarm_params);
    }

    /// Take one of the talismans the player wears (the Talisman Thief): the
    /// one `pick_talisman` picks among the worn talismans the seed's table
    /// knows, by raising its flag (the seed's event removes it from its
    /// slot). Returns its id, or `None` with nothing written when the slots
    /// are unreadable, no worn talisman is in the table, or the flag write
    /// fails.
    fn steal_talisman(&self, talismans: &[TalismanFlag], roll: u32, report_id: u64) -> Option<u32> {
        profile_span!("steal_talisman");
        let Some(equipped) = race_items::equipped_talismans() else {
            warn!(
                report_id,
                "[ITEMS] Talisman slots unreadable, nothing taken"
            );
            return None;
        };
        let Some(picked) = pick_talisman(&equipped, talismans, roll) else {
            info!(
                report_id,
                ?equipped,
                "[ITEMS] No worn talisman in the table, nothing taken"
            );
            return None;
        };
        if self.event_flag_reader.set_flag(picked.flag, true) {
            info!(
                report_id,
                ?equipped,
                roll,
                talisman_id = picked.id,
                flag = picked.flag,
                "[ITEMS] Talisman removal flag raised"
            );
            Some(picked.id)
        } else {
            warn!(
                report_id,
                talisman_id = picked.id,
                flag = picked.flag,
                "[ITEMS] Talisman removal flag not written, nothing taken"
            );
            None
        }
    }

    /// Give a granted race item's goods unless the inventory already holds
    /// them (a game restart re-sends the grant), then answer `item_received`.
    /// Returns whether the goods are in the inventory, the outcome the
    /// machine needs (`grant_spawn_result`). A spawn that injected nothing,
    /// or an unreadable inventory, sends nothing: the machine tries again at
    /// the next game load or reconnection.
    fn spawn_race_item(&self, grant_id: u64, goods_id: u32) -> bool {
        match race_items::goods_quantity(goods_id) {
            Some(0) => {
                if race_items::spawn_goods(goods_id) {
                    info!(grant_id, goods_id, "[ITEMS] Goods spawned");
                    self.ws_client.send_item_received(grant_id);
                    true
                } else {
                    warn!(grant_id, goods_id, "[ITEMS] Goods spawn failed");
                    false
                }
            }
            Some(quantity) => {
                info!(
                    grant_id,
                    goods_id, quantity, "[ITEMS] Goods already held, spawn skipped"
                );
                self.ws_client.send_item_received(grant_id);
                true
            }
            None => {
                warn!(
                    grant_id,
                    goods_id, "[ITEMS] Inventory unreadable, spawn skipped"
                );
                false
            }
        }
    }

    /// Send `item_inventory` with the catalog goods keys the player holds,
    /// from one read of the inventory, and hand them to the machine (the
    /// held row). An unreadable inventory skips the report: a partial or
    /// empty one would read as items lost.
    fn report_item_inventory(&mut self, goods: Vec<(String, u32)>) {
        let Some(inventory) = race_items::HeldInventory::read() else {
            warn!("[ITEMS] Inventory unreadable, report skipped");
            return;
        };
        let present: Vec<String> = goods
            .into_iter()
            .filter(|&(_, goods_id)| inventory.goods_quantity(goods_id) > 0)
            .map(|(key, _)| key)
            .collect();
        info!(goods = ?present, "[ITEMS] Inventory read");
        self.machine.inventory_read(&present);
        self.ws_client.send_item_inventory(present);
    }

    /// Damage the player along the race item curve (`core::item_damage`),
    /// from the HP and effective max HP read now.
    fn apply_item_damage(base_pct: u8, floor_pct: u8, tail_pct: u8) {
        let Some((hp, max_hp)) = race_items::read_hp() else {
            warn!("[ITEMS] HP unreadable, damage skipped");
            return;
        };
        let new_hp = damaged_hp(hp, max_hp, base_pct, floor_pct, tail_pct);
        if new_hp == hp {
            info!(hp, max_hp, "[ITEMS] Damage leaves HP unchanged");
        } else if race_items::write_hp(new_hp) {
            info!(hp, new_hp, max_hp, "[ITEMS] Damage applied");
        } else {
            warn!(hp, new_hp, max_hp, "[ITEMS] HP unwritable, damage skipped");
        }
    }

    /// Set the equip load effect's rate so the player's current load sits at
    /// `load_pct` percent of the max, then apply it. While a previous one
    /// still runs, the rate is computed from the max without it
    /// (`core::equip_load::base_max`), so a second hit follows the current
    /// equipment instead of cancelling the first. An unreadable load keeps
    /// the row's rate (the seed's, or the last one written). The effect is
    /// then applied as `apply_item_speffect` does.
    fn apply_equip_load(&mut self, speffect_id: u32, load_pct: u8, left_ms: Option<u32>) {
        match race_items::read_equip_load() {
            Some((current, max)) => {
                let base = base_max(max, self.equip_load_last);
                let rate = load_rate(current, base, load_pct);
                if race_items::set_equip_load_rate(speffect_id, rate) {
                    info!(
                        current,
                        max, base, rate, load_pct, "[ITEMS] Equip load rate set"
                    );
                    self.equip_load_last = Some((base, rate));
                } else {
                    warn!(
                        speffect_id,
                        "[ITEMS] Equip load row unwritable, row rate kept"
                    );
                }
            }
            None => warn!(speffect_id, "[ITEMS] Equip load unreadable, row rate kept"),
        }
        Self::apply_item_speffect(speffect_id, left_ms);
    }

    /// Apply a race item's SpEffect. `left_ms: None` (an instant one)
    /// applies the row as it is. A timed one gets its time left
    /// (`core::timed_effects::timed_apply`): written into the entry when the
    /// entry survived (a hit while the same effect runs, or a load the game
    /// kept it through); otherwise the planned row (the cycled tail row when
    /// the time left fits in it) is applied, then its entry's timer written,
    /// unless the row's own endurance already is the time left. A timing
    /// unreadable (params not indexed yet, row missing) applies the row as
    /// it is, with no timer write: it runs its own duration.
    fn apply_item_speffect(speffect_id: u32, left_ms: Option<u32>) {
        let Some(left_ms) = left_ms else {
            if sp_effect_apply::apply_speffect(speffect_id) {
                info!(speffect_id, "[ITEMS] SpEffect applied");
            } else {
                warn!(speffect_id, "[ITEMS] SpEffect not applied");
            }
            return;
        };
        let Some(timing) = race_items::speffect_timing(speffect_id) else {
            if sp_effect_apply::apply_speffect(speffect_id) {
                warn!(
                    speffect_id,
                    left_ms,
                    "[ITEMS] SpEffect applied, timing unreadable (runs its full row duration)"
                );
            } else {
                warn!(speffect_id, left_ms, "[ITEMS] SpEffect not applied");
            }
            return;
        };
        let left_s = Duration::from_millis(u64::from(left_ms)).as_secs_f32();
        let plan = timed_apply(speffect_id, timing, left_s);
        let row = plan.speffect_id;
        let timer_s = plan.timer_s;
        if sp_effect_apply::set_speffect_timer(row, timer_s) {
            info!(
                speffect_id,
                row,
                timer_s,
                left_ms,
                ?timing,
                "[ITEMS] SpEffect timer set"
            );
            return;
        }
        // Applied without its timer, a row with less time left than its own
        // duration would run that whole duration again at every load.
        if !plan.full && !race_items::layout_known() {
            warn!(
                speffect_id,
                row,
                left_ms,
                "[ITEMS] SpEffect not applied again (its timer cannot be set on this game version)"
            );
            return;
        }
        if !sp_effect_apply::apply_speffect(row) {
            warn!(
                speffect_id,
                row,
                timer_s,
                left_ms,
                ?timing,
                "[ITEMS] SpEffect not applied"
            );
            return;
        }
        if plan.full {
            info!(
                speffect_id,
                row,
                timer_s,
                left_ms,
                ?timing,
                "[ITEMS] SpEffect applied"
            );
        } else if sp_effect_apply::set_speffect_timer(row, timer_s) {
            info!(
                speffect_id,
                row,
                timer_s,
                left_ms,
                ?timing,
                "[ITEMS] SpEffect applied, timer set"
            );
        } else {
            warn!(
                speffect_id,
                row,
                timer_s,
                left_ms,
                ?timing,
                "[ITEMS] SpEffect applied, timer not found (runs its full row duration)"
            );
        }
    }

    /// Write the memory race item effects into the game
    /// (`eldenring::memory_effects`). The machine sends the whole state
    /// every 250 ms while one is live: a field is written while it holds an
    /// effect (the game may have reset it), and once when it is back at its
    /// default after an effect was written there; a default is never written
    /// over and over. The Camera's rows go back only when their own values
    /// are saved, and the foes are walked only when `walk_foes`. A failed
    /// write keeps the last value written, so the next state the machine
    /// sends tries again; once every effect ended the machine sends the
    /// defaults once, and `retry_memory_state` writes again a state the
    /// game does not hold.
    /// The foes walks keep their own record of the characters they hid
    /// (`core::foes`), across loads.
    fn apply_memory_state(&mut self, state: MemoryState, walk_foes: bool) {
        profile_span!("apply_memory_state");
        // A retry only once the writes have been quiet for its interval:
        // never beside the machine's own refresh of a live effect.
        self.memory_retry_at = Instant::now();
        let written = &mut self.memory_written;
        if state.player_hidden || written.player_hidden {
            if memory_effects::set_player_rendered(!state.player_hidden) {
                written.player_hidden = state.player_hidden;
            } else if race_items::layout_known() {
                warn!(
                    hidden = state.player_hidden,
                    "[ITEMS] Player render bit not written (unreadable)"
                );
            }
        }
        // 1 is the game's own scale and animation speed.
        if state.scale.is_some() || written.scale.is_some() {
            let scale = state.scale.unwrap_or(1.0);
            if memory_effects::set_player_scale(scale) {
                written.scale = state.scale;
            } else if race_items::layout_known() {
                warn!(scale, "[ITEMS] Player scale not written (unreadable)");
            }
        }
        if state.anim_speed.is_some() || written.anim_speed.is_some() {
            let speed = state.anim_speed.unwrap_or(1.0);
            if memory_effects::set_anim_speed(speed) {
                written.anim_speed = state.anim_speed;
            } else {
                warn!(
                    speed,
                    "[ITEMS] Player animation speed not written (unreadable)"
                );
            }
        }
        // The first-person camera sits inside the body, hidden by the render
        // bit: where that bit is not written (`layout_known`), the variant
        // is left out rather than shown through the player's own model.
        let camera = state
            .camera
            .filter(|&v| v != CameraVariant::FirstPerson || race_items::layout_known());
        if camera.is_none() && self.camera_originals.is_empty() {
            written.camera = state.camera;
        } else if memory_effects::set_camera(camera, &mut self.camera_originals) {
            written.camera = state.camera;
        } else {
            warn!(
                ?camera,
                "[ITEMS] Camera rows not written (params not indexed yet, or no LockCamParam row)"
            );
        }
        if walk_foes {
            memory_effects::walk_foes(state.foes_hidden, &mut self.foes_record);
            written.foes_hidden = state.foes_hidden;
        }
    }

    /// Write again the memory state the machine last sent when the game does
    /// not hold it: its batch was lost (a frame that panicked after the
    /// machine's tick is skipped whole, see `render`), or a write failed.
    /// The machine sends a state when it changes and refreshes it only
    /// while an effect is live, so the defaults that end an effect go out
    /// once: lost, they would never come again, and the camera rows live
    /// until the game exits. One comparison per frame; the write on a loaded
    /// frame, once no state was written for `MEMORY_RETRY_INTERVAL`.
    fn retry_memory_state(&mut self, loaded: bool, now: Instant) {
        let sent = self.machine.memory_state_sent();
        if sent == self.memory_written
            || !loaded
            || now.saturating_duration_since(self.memory_retry_at) < MEMORY_RETRY_INTERVAL
        {
            return;
        }
        info!(?sent, written = ?self.memory_written, "[ITEMS] Memory state written again");
        let walk_foes = sent.foes_hidden != self.memory_written.foes_hidden;
        self.apply_memory_state(sent, walk_foes);
    }

    /// Give the game its defaults back, whatever the machine wants: the
    /// last thing tracking does before it stops for good (`render`), since
    /// nothing would restore them after.
    pub(crate) fn restore_memory_defaults(&mut self) {
        let walk_foes = self.memory_written.foes_hidden;
        self.apply_memory_state(MemoryState::default(), walk_foes);
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
        // Past the guard, so any previous runner is either stale (its skin is
        // no longer ours) or already dead. Stop it before replacing the flag
        // it holds: a stale one left alive keeps
        // re-applying its own SpEffect on every world load, and since the last
        // one applied wins with nothing ordering the two threads, the aura
        // would flip from one loading screen to the next. What is already on
        // the character stays there, but the new runner applies its own on its
        // first tick and nothing re-applies the old one afterwards.
        self.phantom_skin_stop.store(true, Ordering::Relaxed);
        self.phantom_skin_stop = Arc::new(AtomicBool::new(false));
        self.phantom_skin_name = Some(name.clone());
        self.phantom_skin_thread = Some(crate::eldenring::sp_effect_runner::spawn(
            name,
            speffects,
            Arc::clone(&self.phantom_skin_stop),
        ));
    }

    /// Hand `job` to the relay worker: it starts now when no job runs, else
    /// it waits its turn (`core::job_queue`; a capture waiting is replaced by
    /// a newer one).
    fn request_relay_job(&mut self, job: RelayJob) {
        if let Some(running) = self.relay_jobs.running() {
            info!(
                ?running,
                queued = ?job,
                "[RELAY] Worker job queued behind the running one"
            );
        }
        match self.relay_jobs.ask(job) {
            Asked::Runs => self.start_relay_jobs(),
            Asked::Queued {
                replaced: Some(replaced),
            } => info!(?replaced, "[RELAY] Worker job replaced while it waited"),
            Asked::Queued { replaced: None } => {}
        }
    }

    /// Start the queue's running job on a thread of its own (the
    /// `spawner_thread` pattern), unless its thread already runs or it is an
    /// apply already planned (its writes run on the game thread). A thread
    /// the OS does not start fails that job at once (its answer is given now,
    /// on the game thread) and the next job waiting is tried.
    fn start_relay_jobs(&mut self) {
        while self.relay_thread.is_none() {
            let Some(job) = self.relay_jobs.running() else {
                return;
            };
            profile_span!("relay_job_start");
            let spawned = match job {
                RelayJob::Capture { generation, .. } => {
                    let generation = *generation;
                    let reader = self.event_flag_reader.clone();
                    let game = Arc::clone(&self.game_state);
                    std::thread::Builder::new()
                        .name("relay-worker".to_string())
                        .spawn(move || {
                            RelayJobDone::Captured(relay::capture(&reader, &game, generation))
                        })
                }
                RelayJob::Apply { run, .. } if run.is_planned() => return,
                RelayJob::Apply { run, request } => {
                    let generation = run.generation();
                    let items = request.items.clone();
                    let flags = request.flags.clone();
                    let grace_flags = request.grace_flags.clone();
                    std::thread::Builder::new()
                        .name("relay-worker".to_string())
                        .spawn(move || {
                            RelayJobDone::Planned(relay::plan_apply(
                                &items,
                                &flags,
                                &grace_flags,
                                generation,
                            ))
                        })
                }
            };
            match spawned {
                Ok(thread) => {
                    info!(?job, "[RELAY] Worker job started");
                    self.relay_thread = Some(thread);
                }
                Err(error) => {
                    warn!(%error, ?job, "[RELAY] Worker thread not started, job failed");
                    if let Some(job) = self.relay_jobs.finish() {
                        self.answer_relay_job(job, None);
                    }
                }
            }
        }
    }

    /// Give the machine a relay job's answer, on the game thread: `done` is
    /// what its thread returned, `None` for a job that failed (its thread
    /// panicked or never started). An apply comes here only when its plan
    /// never came (nothing written); one planned ends in `run_relay_apply`.
    fn answer_relay_job(&mut self, job: RelayJob, done: Option<RelayJobDone>) {
        match job {
            RelayJob::Capture {
                handoff_id,
                generation,
            } => {
                let state = match done {
                    Some(RelayJobDone::Captured(state)) => state,
                    Some(RelayJobDone::Planned(_)) | None => None,
                };
                let effects = self.machine.relay_state_captured(
                    handoff_id,
                    generation,
                    state,
                    Instant::now(),
                );
                self.execute_effects(effects);
            }
            RelayJob::Apply { run, .. } => self.finish_relay_apply(run, None),
        }
    }

    /// The writes of the running apply, on the game thread, after the
    /// machine's tick (`frame_snapshot` is this frame's): every apply asked
    /// watches this frame's loaded map, from its ask on; the running one,
    /// once planned and its thread joined, writes its next batch
    /// (`core::relay_apply::ApplyRun`), with the loaded map read again right
    /// after a batch that wrote. Once its writes ended (all made, a load
    /// seen, its take no longer applying, the deadline) the machine gets the
    /// answer and the next job starts. Per frame with no relay job: an
    /// `Option` check.
    fn run_relay_apply(&mut self, now: Instant) {
        if self.relay_jobs.running().is_none() {
            return;
        }
        profile_span!("relay_apply_frame");
        let map = self.machine.frame_snapshot.map_id;
        for job in self.relay_jobs.jobs_mut() {
            if let RelayJob::Apply { run, .. } = job {
                run.observe(map);
            }
        }
        if self.relay_thread.is_some() {
            return;
        }
        let Some(RelayJob::Apply { run, .. }) = self.relay_jobs.running_mut() else {
            return;
        };
        if !run.is_planned() {
            return;
        }
        let wanted = self.machine.relay_apply_wanted(run.generation());
        let mut wrote = false;
        let end = {
            let mut write = relay::step_writer(&self.event_flag_reader);
            run.write_frame(wanted, now, |step| {
                wrote = true;
                write(step)
            })
        };
        if end.is_none() && wrote {
            run.observe(self.game_state.loaded_map_id());
        }
        if end.is_none() {
            return;
        }
        if let Some(RelayJob::Apply { run, .. }) = self.relay_jobs.finish() {
            self.finish_relay_apply(run, end);
        }
        self.start_relay_jobs();
    }

    /// Answer the machine for an apply whose writes ended (`end`), or that
    /// never got its plan (`None`: its thread panicked or never started, and
    /// nothing was written), on the game thread, with one log line: the
    /// writes made by kind, those that failed, those left and why, the time
    /// since the ask. Nothing of it is written after this.
    fn finish_relay_apply(&mut self, run: ApplyRun, end: Option<ApplyEnd>) {
        let now = Instant::now();
        let handoff_id = run.handoff_id();
        let generation = run.generation();
        let written = run.written();
        let elapsed_ms = now.saturating_duration_since(run.asked_at()).as_millis() as u64;
        match end {
            Some(ApplyEnd::Complete) if run.failed().is_empty() => info!(
                handoff_id,
                generation,
                ?written,
                elapsed_ms,
                "[RELAY] State applied"
            ),
            Some(end) => warn!(
                handoff_id,
                generation,
                ?end,
                ?written,
                failed = ?run.failed(),
                left = run.left(),
                elapsed_ms,
                "[RELAY] State applied in part"
            ),
            None => warn!(
                handoff_id,
                generation, elapsed_ms, "[RELAY] State not applied (its plan never came)"
            ),
        }
        self.machine
            .relay_state_applied(handoff_id, generation, now);
    }

    /// Hand the relay job whose thread ended to the machine, with the
    /// identity it was asked with (a thread that panicked answers as a failed
    /// job), then start the job waiting next. An apply's plan is kept on its
    /// job instead, whose writes then run on the game thread
    /// (`run_relay_apply`). Per frame with no thread ended: an `Option` check
    /// and an atomic load, nothing allocated, no lock taken.
    fn poll_relay_job(&mut self) {
        if !self
            .relay_thread
            .as_ref()
            .is_some_and(|thread| thread.is_finished())
        {
            return;
        }
        profile_span!("relay_job_poll");
        let Some(thread) = self.relay_thread.take() else {
            return;
        };
        let done = match thread.join() {
            Ok(done) => Some(done),
            Err(panic) => {
                error!(
                    job = ?self.relay_jobs.running(),
                    panic = crate::panic_message(panic.as_ref()),
                    "[RELAY] Worker thread panicked, job failed"
                );
                None
            }
        };
        let done = match done {
            Some(RelayJobDone::Planned(plan)) => match self.relay_jobs.running_mut() {
                Some(RelayJob::Apply { run, .. }) => {
                    run.set_plan(plan.steps);
                    return;
                }
                // A plan comes only from an apply's thread.
                _ => None,
            },
            done => done,
        };
        if let Some(job) = self.relay_jobs.finish() {
            self.answer_relay_job(job, done);
        }
        self.start_relay_jobs();
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

    /// Local IGT for the overlay, held through a menu reload while playing
    /// (`display_igt_ms`).
    pub fn read_igt(&self) -> Option<u32> {
        self.machine.display_igt_ms(
            self.machine
                .frame_snapshot
                .igt_ms
                .or_else(|| self.game_state.read_igt()),
        )
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

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        self.machine.my_participant()
    }

    /// Get current status message if still valid (within 3 seconds).
    pub fn get_status(&self) -> Option<&str> {
        self.machine.get_status(Instant::now())
    }

    /// Get the update-available notice if still within its 10s display window.
    pub fn get_update_notice(&self) -> Option<&str> {
        self.machine.get_update_notice(Instant::now())
    }

    /// Get the coded blocking condition message from the server, if still fresh.
    pub fn get_blocking_condition_message(&self) -> Option<&str> {
        self.machine
            .get_blocking_condition(Instant::now())
            .map(|condition| condition.message.as_str())
    }

    /// Whether the generic cheat banner shows (see `RaceMachine::cheat_warning_active`).
    pub fn cheat_warning_active(&self) -> bool {
        self.machine.cheat_warning_active(Instant::now())
    }

    /// Get the calm waiting-line message, if any.
    pub fn get_waiting_line_message(&self) -> Option<&str> {
        self.machine.get_waiting_line(Instant::now())
    }

    #[cfg(debug_assertions)]
    pub fn debug_info(&self) -> &DebugInfo {
        &self.debug_info
    }

    #[cfg(debug_assertions)]
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
            loading_byte: self.game_state.read_loading_byte(),
            screen_in_game: self.game_state.is_screen_in_game(),
            blackscreen: self.game_state.is_blackscreen_active(),
            quit_out_bit: crate::eldenring::quitout::read_return_title_requested(),
        };
        self.last_debug_refresh = Some(Instant::now());
    }
}

// =============================================================================
// FONT LOADING
// =============================================================================

/// Embedded overlay faces (all SIL OFL 1.1): the site's three roles, from
/// the same instanced latin subsets the web self-hosts (see
/// `docs/GRAPHIC_CHARTER.md`). Public Sans is the body face (overridable via
/// `overlay.font_path`), Barlow Condensed the display face (race name),
/// Spline Sans Mono the data face (IGT, gaps, counters; tabular digits by
/// design, which ImGui needs since it applies no OpenType `tnum`). Source
/// Sans 3 stays as the symbol face merged into each of them: the charter
/// faces lack the geometric shapes and arrows the overlay draws (●, →).
pub(crate) const EMBEDDED_FONT: &[u8] =
    include_bytes!("../../assets/fonts/public-sans-400-latin.ttf");
pub(crate) const EMBEDDED_FONT_DISPLAY: &[u8] =
    include_bytes!("../../assets/fonts/barlow-condensed-600-latin.ttf");
pub(crate) const EMBEDDED_FONT_MONO: &[u8] =
    include_bytes!("../../assets/fonts/spline-sans-mono-400-latin.ttf");
pub(crate) const EMBEDDED_FONT_SYMBOLS: &[u8] =
    include_bytes!("../../assets/fonts/SourceSans3-Regular.ttf");

/// Resolve the overlay body-face TTF bytes.
///
///   - Empty `font_path` → embedded Public Sans (default, no disk access).
///   - Filename only → try `C:\Windows\Fonts\` then DLL directory.
///   - Relative path with separators → relative to DLL directory.
///   - Absolute path → use directly.
///
/// Falls back to `None` only when an explicit `font_path` was set but no
/// candidate exists; the renderer then uses the embedded body face.
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
    warn!(tried_paths = %tried, "Configured font not found, using the embedded body face");
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
        assert_eq!(
            data, EMBEDDED_FONT,
            "empty path must return the embedded body face"
        );
        // TTF magic: 0x00010000 (TrueType) or "OTTO" (CFF/OpenType)
        let magic = &data[0..4];
        assert!(
            magic == [0x00, 0x01, 0x00, 0x00] || magic == b"OTTO" || magic == b"true",
            "expected TTF/OTF magic, got {:?}",
            magic
        );
    }
}
