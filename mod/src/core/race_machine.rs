//! Race state machine - pure, platform-independent race tracking logic.
//!
//! `RaceMachine` owns every piece of race state that is plain data and makes
//! every decision: WS message handling (`handle_message`) and the per-frame
//! flag/zone lifecycle (`tick`). It performs no IO: the Windows shell
//! (`dll/tracker.rs`) reads game memory up front (`FrameSnapshot`,
//! `TickInput`) and executes the returned `Effect`s afterwards. This is what
//! makes the state machine testable under `cargo test` on Linux.

use std::collections::HashMap;
use std::time::Instant;

use crate::core::protocol::{
    ConditionKind, ExitInfo, ParticipantInfo, ParticipantStatus, RaceInfo, RaceStatus, SeedInfo,
};
use crate::core::types::PlayerPosition;

// =============================================================================
// CONNECTION / MESSAGES (moved from dll/websocket.rs)
// =============================================================================

/// Connection status
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionStatus {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error,
}

/// Messages from the WS worker thread to the state machine.
///
/// The WS thread constructs these from `ServerMessage`s; the shell may enrich
/// them before delegation (`RaceStatusChange::current_igt` is always `None`
/// on the wire and filled by the shell with a fresh IGT read, so the
/// machine's freeze decision needs no game access).
#[derive(Debug)]
pub enum MachineMessage {
    StatusChanged(ConnectionStatus),
    AuthOk {
        participant_id: String,
        race: RaceInfo,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
        /// User's equipped phantom skin name, or None when not equipped or
        /// when the server sent the literal "none". Resolved to SpEffect IDs
        /// at apply-time via `seed.phantom_skins[name]`.
        phantom_skin: Option<String>,
        /// Server release version when a newer compatible mod build exists.
        latest_mod_version: Option<String>,
    },
    AuthError(String),
    RaceStart(u32),
    LeaderboardUpdate {
        participants: Vec<ParticipantInfo>,
        leader_splits: Option<HashMap<i32, i32>>,
    },
    RaceStatusChange {
        status: RaceStatus,
        /// Filled by the shell at delegation time (fresh `read_igt`), never
        /// by the WS thread. Consumed by the finish-freeze decision.
        current_igt: Option<u32>,
    },
    /// Server pushed a refreshed RaceInfo (race_ends_at extension, etc.).
    /// Replaces the cached race info wholesale.
    RaceInfoUpdate(RaceInfo),
    PlayerUpdate(ParticipantInfo),
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        original_tier: Option<i32>,
        layer: Option<i32>,
        is_first_visit: bool,
        exits: Vec<ExitInfo>,
        message_id: Option<u64>,
    },
    /// Aggregated death counts per zone for death marker flags
    DeathCounts(HashMap<String, u32>),
    /// Event flag drained from outgoing channel on reconnect, must be re-buffered
    RequeueEventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    EventFlagAck {
        message_id: u64,
    },
    /// Zone query drained from outgoing channel on reconnect, must be re-buffered
    RequeueZoneQuery {
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
        quit_out: bool,
    },
    ZoneQueryAck {
        message_id: u64,
    },
    Error {
        message: String,
        code: Option<ConditionKind>,
    },
    /// Server rejected permanently (4xxx close code or auth failure). Stop reconnecting.
    PermanentError(String),
}

// =============================================================================
// STATE TYPES (moved from dll/tracker.rs)
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

/// A coded server condition, displayed while fresh (the server re-sends
/// it on every rejected message, ~1/s, while the condition holds).
#[derive(Debug, Clone)]
pub struct ServerCondition {
    pub kind: ConditionKind,
    pub message: String,
    pub last_seen: Instant,
}

#[derive(Debug, Clone, Copy)]
pub struct BufferedEventFlag {
    pub flag_id: u32,
    pub igt_ms: u32,
}

#[derive(Debug, Clone)]
pub struct BufferedZoneQuery {
    pub igt_ms: u32,
    pub grace_entity_id: Option<u32>,
    pub map_id: Option<String>,
    pub position: Option<[f32; 3]>,
    pub play_region_id: Option<u32>,
    pub quit_out: bool,
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

/// Cached frame-local memory reads reused by update and rendering.
#[derive(Debug, Clone, Copy, Default)]
pub struct FrameSnapshot {
    pub igt_ms: Option<u32>,
    pub death_count: Option<u32>,
    pub position_readable: bool,
    /// Whether the engine's "world clock stopped" byte is set (`None` =
    /// not read this frame or unreadable). Stands in for "loading screen
    /// displayed" outside frozen-clock seeds; see the reveal logic.
    pub loading_screen: Option<bool>,
}

// =============================================================================
// TICK INTERFACES
// =============================================================================

/// What the machine wants read from the game this frame (two-phase tick:
/// the shell calls `pre_tick`, performs exactly these reads, then `tick`).
#[derive(Debug, Clone, Copy, Default)]
pub struct FrameNeeds {
    pub igt: bool,
    pub deaths: bool,
    /// Read the loading byte (only while a zone reveal is pending).
    pub loading: bool,
    pub poll_flags: bool,
}

/// Inputs to one tick, gathered by the shell.
#[derive(Debug, Default)]
pub struct TickInput {
    pub snapshot: FrameSnapshot,
    pub connected: bool,
    /// Captured grace entity id from the warp hook (loading-exit frames only).
    pub warp_capture: Option<u32>,
    /// Player position (loading-exit frames only), for zone queries.
    pub position: Option<PlayerPosition>,
    /// `(flag_id, is_set)` for every readable flag in `event_ids`. `Some`
    /// when the shell performed reads this frame (`wants_flag_reads`),
    /// `None` otherwise. Unreadable flags are omitted from the vec.
    pub flag_reads: Option<Vec<(u32, bool)>>,
    /// Weapons for the status_update, read by the shell only when
    /// `wants_status_update` said one may fire this frame.
    pub weapons: [Option<i32>; 2],
    /// Whether the flag reader diagnosed OK (None = flags not read).
    pub flag_reader_ok: Option<bool>,
}

/// Side effects for the shell to execute, in order.
#[derive(Debug, PartialEq)]
pub enum Effect {
    SendReady,
    SendStatusUpdate {
        igt_ms: u32,
        death_count: u32,
        weapons: [Option<i32>; 2],
    },
    SendEventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    SendZoneQuery {
        igt_ms: u32,
        message_id: u64,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        quit_out: bool,
    },
    /// Write a flag value into game memory (the shell resolves the category
    /// first and skips the write when unresolvable, as today).
    SetGameFlag {
        flag_id: u32,
        value: bool,
    },
    /// Add a quit-out penalty to the in-game timer (4-byte u32 write; see
    /// `GameState::add_igt_penalty`).
    ApplyIgtPenalty {
        ms: u32,
    },
    /// Clear the warp hook's captured grace entity id.
    ClearWarpCapture,
    /// Spawn runtime items; the shell re-checks its own guards
    /// (items_spawned atomic, spawner thread liveness) exactly as today.
    SpawnItems,
    /// Start the phantom-skin runner; the shell applies its existing
    /// already-running / same-skin guards and owns the thread + stop flag.
    /// `speffects` comes from the seed catalog, resolved by the machine.
    StartPhantomSkin {
        name: String,
        speffects: Vec<i32>,
    },
}

// =============================================================================
// RACE MACHINE
// =============================================================================

use std::collections::HashSet;
use std::time::Duration;
use tracing::{debug, error, info, warn};

use crate::core::flag_buffer::{FlagBuffer, SAVE_RELOAD_IGT_DROP_MS};

/// Pure race state machine. Owns every piece of plain-data race state and
/// makes every decision; performs no IO. Fields are `pub` so the Windows
/// shell and renderer can read them directly (writes go through
/// `handle_message`/`tick`, except the per-frame `frame_snapshot` which the
/// shell refreshes before each tick).
pub struct RaceMachine {
    pub race_state: RaceState,
    pub my_participant_id: Option<String>,
    pub my_participant_index: Option<usize>,
    pub event_ids: Vec<u32>,
    pub triggered_flags: HashSet<u32>,
    pub flag_buffer: FlagBuffer,
    pub in_flight_event_flags: HashMap<u64, BufferedEventFlag>,
    pub in_flight_zone_queries: HashMap<u64, BufferedZoneQuery>,
    pub next_event_message_id: u64,
    /// finish_event from server, sent immediately (no loading screen on boss kill)
    pub finish_event: Option<u32>,
    pub last_status_update: Instant,
    pub last_flag_poll: Instant,
    pub ready_sent: bool,
    /// Temporary status message (yellow banner, auto-expires after 3s)
    pub status_message: Option<(String, Instant)>,
    /// Update-available notice (gold line, auto-expires after 10s)
    pub update_notice: Option<(String, Instant)>,
    /// Last flag reader status discriminant (for transition logging)
    pub last_flag_reader_ok: Option<bool>,
    /// Zone update received, waiting for the loading screen to end before
    /// revealing
    pub pending_zone_update: Option<ZoneUpdateData>,
    /// When the pending zone update was received; anchors the defensive
    /// reveal timeout and the one-shot stall-warn diagnostic
    pub pending_zone_received_at: Option<Instant>,
    /// Snapshot of current_layer taken when leaderboard_update bumps the layer.
    pub pre_reveal_layer: Option<i32>,
    /// One-shot latch for the stall-warn diagnostic, reset on each
    /// zone_update receipt
    pub zone_stall_warned: bool,
    /// Whether position was readable last frame (loading screen exit detection)
    pub was_position_readable: bool,
    /// Quit-out observed; consumed (penalty + zone tag) at the next loading exit.
    pub pending_quit_out: bool,
    /// Has been in-world since race start (or boot, before the first race
    /// start). Guards quit-out arming against boot-time and pre-start save
    /// juggling; cleared on `RaceStart` so a quit-out from before the start
    /// cannot leak a penalty into the first in-race load.
    pub has_been_in_world: bool,
    /// Wrong save loaded (impossible IGT forward jump across an unload):
    /// freeze all race interaction (sends, flag reads/writes, penalty) and
    /// show the persistent banner until the race save returns. This is a
    /// local, IGT-derived heuristic, independent of the server-pushed
    /// `ConditionKind::WrongSave` condition below (same real-world cause,
    /// different detection path).
    pub wrong_save: bool,
    /// Last IGT observed on the believed-good save and when: the recovery
    /// baseline while `wrong_save` is set.
    pub last_good_igt: Option<u32>,
    pub last_good_at: Option<Instant>,
    /// Death count last observed on the frame snapshot: the baseline for
    /// the deathless death edge. `None` until the first readable frame, so
    /// a mid-race (re)start records a baseline instead of a false death.
    pub last_seen_death_count: Option<u32>,
    /// One-shot latch for the deathless "You died" banner; reset on
    /// `RaceStart`.
    pub deathless_banner_shown: bool,
    /// Seed mismatch: config seed_id doesn't match server seed_id
    pub seed_mismatch: bool,
    /// Last auth error message from server (see dll handler ordering guarantee)
    pub last_auth_error: Option<String>,
    /// Permanent error from server (persistent red banner, no auto-dismiss)
    pub permanent_error: Option<String>,
    /// Most recent coded server condition (see `ConditionKind`), displayed
    /// while fresh via `get_blocking_condition`/`get_waiting_line`.
    pub server_condition: Option<ServerCondition>,
    /// IGT frozen when the race ends before the local player finishes
    pub frozen_igt_ms: Option<u32>,
    /// Last observed IGT, used to detect save reloads. Unlike
    /// `last_good_igt` it keeps updating through wrong-save episodes and
    /// survives `RaceStart`, so the per-save flush still catches a stale
    /// setup-phase save on the first in-race observation.
    pub last_observed_igt: Option<u32>,
    /// Cached reads for the current frame (written by the shell each frame)
    pub frame_snapshot: FrameSnapshot,
    /// Bumped on every zone reveal; the shell's exits render cache keys on it.
    pub zone_version: u64,
    pub leaderboard_version: u64,
    pub last_sent_debug: Option<String>,
    pub last_received_debug: Option<String>,
    /// Seed id from the local pack config, for stale-pack detection
    pub config_seed_id: String,
    /// Training mode: the server auto-starts, so `ready` is never sent.
    pub training: bool,
}

impl RaceMachine {
    /// `seed_message_id`: initial value for the message-id counter (the shell
    /// seeds it from wall-clock millis so ids stay unique across sessions).
    pub fn new(seed_message_id: u64, config_seed_id: String, training: bool, now: Instant) -> Self {
        Self {
            race_state: RaceState::default(),
            my_participant_id: None,
            my_participant_index: None,
            event_ids: Vec::new(),
            triggered_flags: HashSet::new(),
            flag_buffer: FlagBuffer::default(),
            in_flight_event_flags: HashMap::new(),
            in_flight_zone_queries: HashMap::new(),
            next_event_message_id: seed_message_id,
            finish_event: None,
            last_status_update: now,
            last_flag_poll: now,
            ready_sent: false,
            status_message: None,
            update_notice: None,
            last_flag_reader_ok: None,
            pending_zone_update: None,
            pending_zone_received_at: None,
            pre_reveal_layer: None,
            zone_stall_warned: false,
            was_position_readable: true,
            pending_quit_out: false,
            has_been_in_world: false,
            wrong_save: false,
            last_good_igt: None,
            last_good_at: None,
            last_seen_death_count: None,
            deathless_banner_shown: false,
            seed_mismatch: false,
            last_auth_error: None,
            permanent_error: None,
            server_condition: None,
            frozen_igt_ms: None,
            last_observed_igt: None,
            frame_snapshot: FrameSnapshot::default(),
            zone_version: 0,
            leaderboard_version: 0,
            last_sent_debug: None,
            last_received_debug: None,
            config_seed_id,
            training,
        }
    }

    // ------------------------------------------------------------------
    // Read accessors (state queries used by the shell and renderer)
    // ------------------------------------------------------------------

    /// Returns true if we're in the countdown period before the race effectively starts.
    pub fn is_countdown_active(&self, now: Instant) -> bool {
        self.race_state
            .countdown_end
            .map(|end| now < end)
            .unwrap_or(false)
    }

    pub fn is_race_running(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == RaceStatus::Running)
            .unwrap_or(false)
    }

    /// Configured quit-out penalty, 0 when no race is known (nothing to
    /// penalize outside a race anyway).
    /// IGT for outgoing wire values: the frame value, falling back to the
    /// last good observation when the frame read is the transient 0 of a
    /// repopulating menu reload. Status updates deliberately do NOT use
    /// this: there, 0 means "not in game, skip the send".
    fn effective_igt_ms(&self) -> u32 {
        self.frame_snapshot
            .igt_ms
            .filter(|&v| v > 0)
            .or(self.last_good_igt)
            .unwrap_or(0)
    }

    fn quit_out_penalty_ms(&self) -> u32 {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.quit_out_penalty_ms)
            .unwrap_or(0)
    }

    fn is_deathless(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.deathless)
            .unwrap_or(false)
    }

    pub fn is_race_setup(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == RaceStatus::Setup)
            .unwrap_or(false)
    }

    /// Check if the local player has finished the race.
    /// Once finished, the mod should stop sending status_update and event_flag
    /// to preserve the frozen IGT at finish time.
    pub fn am_i_finished(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == ParticipantStatus::Finished)
            .unwrap_or(false)
    }

    /// Check if the local player has abandoned; mirrors `am_i_finished`.
    pub fn am_i_abandoned(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == ParticipantStatus::Abandoned)
            .unwrap_or(false)
    }

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        let idx = self.my_participant_index?;
        self.race_state.participants.get(idx)
    }

    /// Get current status message if still valid (within 3 seconds).
    pub fn get_status(&self, now: Instant) -> Option<&str> {
        self.status_message.as_ref().and_then(|(msg, time)| {
            if now.duration_since(*time) < Duration::from_secs(3) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    /// Coded blocking condition (red top banner) while fresh.
    pub fn get_blocking_condition(&self, now: Instant) -> Option<&ServerCondition> {
        self.server_condition
            .as_ref()
            .filter(|c| c.kind.is_blocking())
            .filter(|c| now.duration_since(c.last_seen) < SERVER_CONDITION_TTL)
    }

    /// Calm amber waiting line: locally derived when the machine knows
    /// the race has not started, otherwise a fresh waiting condition from
    /// the server. The countdown code stays hidden while the local
    /// countdown UI is active.
    pub fn get_waiting_line(&self, now: Instant) -> Option<&str> {
        if self.is_race_setup() {
            // Only while actually in the world: the reminder is about the
            // loaded game, so it must not cover the title screen or
            // loading screens (the same readable-position signal the
            // loading-exit path keys on).
            return self
                .frame_snapshot
                .position_readable
                .then_some("Race has not started yet");
        }
        self.server_condition
            .as_ref()
            .filter(|c| !c.kind.is_blocking())
            .filter(|c| now.duration_since(c.last_seen) < SERVER_CONDITION_TTL)
            .filter(|c| c.kind != ConditionKind::Countdown || !self.is_countdown_active(now))
            .map(|c| c.message.as_str())
    }

    /// Get the update-available notice if still within its 10s display window.
    pub fn get_update_notice(&self, now: Instant) -> Option<&str> {
        self.update_notice.as_ref().and_then(|(msg, time)| {
            if now.duration_since(*time) < Duration::from_secs(10) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    /// Set a status message that will be displayed temporarily (3 seconds).
    pub fn set_status(&mut self, message: String, now: Instant) {
        self.status_message = Some((message, now));
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
}

impl RaceMachine {
    /// Handle one message from the WS worker. Pure: mutates machine state and
    /// returns the side effects for the shell to execute, in order.
    pub fn handle_message(&mut self, msg: MachineMessage, now: Instant) -> Vec<Effect> {
        let mut effects = Vec::new();
        match msg {
            MachineMessage::StatusChanged(status) => {
                info!(status = ?status, "[WS] Status changed");
                match status {
                    ConnectionStatus::Connected => {
                        self.ready_sent = false; // Reset for reconnection
                        self.set_status("Server connected".to_string(), now);
                    }
                    ConnectionStatus::Reconnecting => {
                        self.flag_buffer.park_deferred();
                        self.set_status("Reconnecting to server...".to_string(), now);
                    }
                    ConnectionStatus::Error => {
                        // The permanent red banner already shows this
                        // failure; no gold flash on top of it.
                        if self.permanent_error.is_none() {
                            let msg = self
                                .last_auth_error
                                .take()
                                .unwrap_or_else(|| "Server maintenance".to_string());
                            self.set_status(msg, now);
                        }
                    }
                    ConnectionStatus::Disconnected => {
                        self.set_status("Disconnected".to_string(), now);
                    }
                    ConnectionStatus::Connecting => {
                        // Silent: the dot indicator handles initial connection
                    }
                }
            }
            MachineMessage::AuthOk {
                participant_id,
                mut race,
                seed,
                participants,
                phantom_skin,
                latest_mod_version,
            } => {
                info!(race = %race.name, participant_id = %participant_id, participants = participants.len(), "[WS] Auth OK");
                if let Some(ref name) = phantom_skin {
                    info!(skin = %name, "[WS] Equipped phantom skin received");
                }
                // Phantom skin runtime application: the machine resolves the
                // seed catalog and emits the intent; the shell owns the runner
                // thread and its skip-if-already-running guard.
                if let Some(ref name) = phantom_skin {
                    match seed.phantom_skins.get(name) {
                        Some(directive) if !directive.speffects.is_empty() => {
                            effects.push(Effect::StartPhantomSkin {
                                name: name.clone(),
                                speffects: directive.speffects.clone(),
                            });
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
                self.seed_mismatch =
                    crate::core::is_seed_stale(&self.config_seed_id, seed.seed_id.as_deref());
                if self.seed_mismatch {
                    warn!(
                        config = %self.config_seed_id,
                        server = ?seed.seed_id,
                        "Seed mismatch: seed pack is outdated"
                    );
                }

                if let Some(latest) = latest_mod_version {
                    info!(latest = %latest, "[WS] Mod update available");
                    // Formatted once at receipt; rendering reads it by reference.
                    self.update_notice = Some((
                        format!(
                            "Mod update available: v{} (you have v{})",
                            latest,
                            env!("CARGO_PKG_VERSION")
                        ),
                        now,
                    ));
                }

                // Spawn runtime items (gems/AoW) if present in seed; the shell
                // re-checks its items_spawned / thread-liveness guards.
                if !seed.spawn_items.is_empty() {
                    effects.push(Effect::SpawnItems);
                }
                self.race_state.seed = Some(seed);
                self.race_state.participants = participants;
                self.bump_leaderboard_version();
            }
            MachineMessage::AuthError(msg) => {
                self.last_received_debug = Some(format!("auth_error({})", msg));
                error!(message = %msg, "[WS] Auth failed");
                self.last_auth_error = Some(msg);
            }
            MachineMessage::RaceStart(countdown_seconds) => {
                self.last_received_debug = Some(format!("race_start(cd={})", countdown_seconds));
                info!(countdown_seconds, "[WS] Race started!");
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
                    race.status = RaceStatus::Running;
                }
                // A quit-out requested before the start is not a race quit-out.
                self.pending_quit_out = false;
                self.deathless_banner_shown = false;
                // Without this, the IGT-regression arming would fire on the
                // first in-race load after a pre-start quit-out (the reloaded
                // save's IGT sits below the last pre-start observation).
                self.has_been_in_world = false;
                // A wrong-save freeze from before the start is stale: the
                // race begins with a clean slate and fresh references, so a
                // pre-start mistake cannot leave the machine frozen forever
                // (the race save's IGT may sit far below the stale baseline).
                self.wrong_save = false;
                self.last_good_igt = None;
                self.last_good_at = None;
                self.bump_leaderboard_version();
            }
            MachineMessage::LeaderboardUpdate {
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
            MachineMessage::RaceStatusChange {
                status,
                current_igt,
            } => {
                self.last_received_debug = Some(format!("race_status_change({})", status.as_str()));
                info!(status = %status.as_str(), "[WS] Race status changed");
                // If race ends and we haven't finished, freeze our current game IGT.
                // The mod's local participant igt_ms is stale (only updated via
                // leaderboard_update on events, not on every status_update).
                // `current_igt` is a fresh read injected by the shell.
                if status == RaceStatus::Finished && !self.am_i_finished() {
                    self.frozen_igt_ms = current_igt;
                    self.frame_snapshot.igt_ms = self.frozen_igt_ms;
                    info!(frozen_igt_ms = ?self.frozen_igt_ms, "[WS] Froze game IGT (race ended, player not finished)");
                }
                if let Some(ref mut race) = self.race_state.race {
                    race.status = status;
                }
                self.bump_leaderboard_version();
            }
            MachineMessage::RaceInfoUpdate(mut race) => {
                self.last_received_debug = Some(format!("race_info_update(name={})", race.name));
                info!(
                    race_ends_at = ?race.race_ends_at,
                    status = %race.status.as_str(),
                    "[WS] Race info updated"
                );
                race.reparse_dates();
                // A reroll changes the race's seed_id mid-session; re-check
                // whether the loaded pack went stale (auth_ok is the only other
                // place this is evaluated). Only act when the payload carries a
                // seed_id, so an older server omitting it can't clear the flag.
                if race.seed_id.is_some() {
                    self.seed_mismatch =
                        crate::core::is_seed_stale(&self.config_seed_id, race.seed_id.as_deref());
                    if self.seed_mismatch {
                        warn!(
                            config = %self.config_seed_id,
                            server = ?race.seed_id,
                            "Seed mismatch after reroll: seed pack is outdated"
                        );
                    }
                }
                self.race_state.race = Some(race);
            }
            MachineMessage::PlayerUpdate(player) => {
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
            MachineMessage::ZoneUpdate {
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
                self.pending_zone_received_at = Some(now);
                self.zone_stall_warned = false;
            }
            MachineMessage::EventFlagAck { message_id } => {
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
            MachineMessage::RequeueEventFlag {
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
            MachineMessage::RequeueZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
                quit_out,
            } => {
                self.in_flight_zone_queries
                    .entry(message_id)
                    .or_insert(BufferedZoneQuery {
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                        quit_out,
                    });
                info!(message_id, "[WS] Re-queued drained zone query");
            }
            MachineMessage::ZoneQueryAck { message_id } => {
                if self.in_flight_zone_queries.remove(&message_id).is_some() {
                    info!(message_id, "[WS] Zone query acknowledged (no zone_update)");
                } else {
                    warn!(message_id, "[WS] Ack for unknown zone query");
                }
            }
            MachineMessage::DeathCounts(counts) => {
                self.last_received_debug = Some(format!("death_counts({} zones)", counts.len()));
                self.race_state.death_counts = counts.clone();
                // Death marker flags: the machine picks flag/value pairs from
                // its seed state; the shell resolves the category page once and
                // writes them, skipping unresolvable flags, exactly as before.
                if let Some(ref seed) = self.race_state.seed {
                    for (node_id, total) in &counts {
                        if let Some(flags) = seed.death_flags.get(node_id) {
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[0],
                                value: *total >= 1,
                            });
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[1],
                                value: *total >= 3,
                            });
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[2],
                                value: *total >= 5,
                            });
                        }
                    }
                }
            }
            MachineMessage::Error { message, code } => {
                self.last_received_debug = Some(format!("error({})", message));
                warn!(error = %message, code = ?code, "[WS] Error");
                match code.filter(|k| *k != ConditionKind::Unknown) {
                    Some(kind) => {
                        self.server_condition = Some(ServerCondition {
                            kind,
                            message,
                            last_seen: now,
                        });
                    }
                    None => self.set_status(message, now),
                }
            }
            MachineMessage::PermanentError(msg) => {
                self.last_received_debug = Some(format!("permanent_error({})", msg));
                error!(message = %msg, "[WS] Permanent error, stopping reconnection");
                self.permanent_error = Some(msg);
            }
        }
        effects
    }
}

/// Defensive timeout for the zone reveal, anchored on zone_update receipt.
/// On frozen-clock event seeds (weather plugin FreezeTime) the loading byte
/// never clears and the reveal falls back to this bound; loads usually last
/// at least this long, so the degraded reveal lands near the loading exit.
const ZONE_REVEAL_TIMEOUT: Duration = Duration::from_secs(5);

/// A same-save reload always comes back BELOW the last observation (the
/// on-disk save lags); a forward jump across an unload beyond this slack
/// means another, further-along save file.
const WRONG_SAVE_FORWARD_SLACK_MS: u32 = 10_000;
/// Recovery window slack: the race save is back when a reload lands in
/// `[last_good - SAVE_RELOAD_IGT_DROP_MS, last_good + elapsed + this]`.
const WRONG_SAVE_RECOVERY_SLACK_MS: u32 = 10_000;

/// Diagnostic only: how long a zone update may stay pending before a
/// one-shot warn! is logged. Both reveal paths require a readable position,
/// so this log is the only trace left when position readability breaks or
/// flickers and reveals silently stop firing.
const ZONE_REVEAL_STALL_WARN: Duration = Duration::from_secs(30);

/// A server condition displays while its last receipt is younger than
/// this; the server re-sends ~1/s while the condition holds, so display
/// drops by itself shortly after resolution.
const SERVER_CONDITION_TTL: Duration = Duration::from_secs(3);

impl RaceMachine {
    /// What the shell should read from the game this frame.
    pub fn pre_tick(&self, now: Instant, show_ui: bool, connected: bool) -> FrameNeeds {
        let live = show_ui || connected;
        FrameNeeds {
            // IGT also needed when a race is set up so save-reload detection
            // and event-flag polling stay correct with UI hidden and WS down.
            igt: live || !self.event_ids.is_empty(),
            deaths: live,
            loading: self.pending_zone_update.is_some(),
            poll_flags: !self.wrong_save
                && !self.event_ids.is_empty()
                && now.duration_since(self.last_flag_poll) >= Duration::from_millis(100),
        }
    }

    /// Whether the shell must read the event flags this frame: 10Hz poll
    /// cadence, loading-screen exit scan, or the reconnect safety-net rescan.
    pub fn wants_flag_reads(
        &self,
        needs: FrameNeeds,
        position_readable: bool,
        connected: bool,
    ) -> bool {
        if self.wrong_save || self.event_ids.is_empty() {
            return false;
        }
        needs.poll_flags
            || (position_readable && !self.was_position_readable)
            || (connected && !self.ready_sent)
    }

    /// Whether a status_update may fire this frame (gates the weapon read).
    pub fn wants_status_update(&self, now: Instant, igt_ms: u32) -> bool {
        now.duration_since(self.last_status_update) >= Duration::from_secs(1)
            && igt_ms > 0
            && !self.wrong_save
            && self.is_race_running()
            && !self.am_i_finished()
            && !self.is_countdown_active(now)
    }

    /// One frame of the race lifecycle. Consumes the shell-gathered inputs
    /// and returns the effects to execute, in order. Mirrors the pre-machine
    /// `RaceTracker::update()` body exactly (minus shell concerns).
    pub fn tick(&mut self, input: TickInput, now: Instant) -> Vec<Effect> {
        let mut effects = Vec::new();
        self.frame_snapshot = input.snapshot;

        // GameDataMan's play_time reads 0 transiently while a menu reload
        // repopulates it (live-observed 2026-07-30); the status-update path
        // already treats 0 as "not in game". A real racing save's IGT is
        // never 0 when readable, so zero readings carry no information for
        // reload classification: skip them entirely (no flush, no arming,
        // no reference updates, no freeze recovery).
        if let Some(current_igt) = self.frame_snapshot.igt_ms.filter(|&v| v > 0) {
            let unload_context =
                !self.frame_snapshot.position_readable || !self.was_position_readable;
            if self.wrong_save {
                // Recovery only: a reload landing back inside the plausible
                // window of the last good observation means the race save
                // is back. Observations from the wrong save are otherwise
                // meaningless: no flush, no arming, no reference updates.
                let elapsed_ms = self
                    .last_good_at
                    .map(|t| now.duration_since(t).as_millis() as u64)
                    .unwrap_or(0);
                let good = self.last_good_igt.unwrap_or(0);
                let low = good.saturating_sub(SAVE_RELOAD_IGT_DROP_MS);
                let high = (good as u64) + elapsed_ms + WRONG_SAVE_RECOVERY_SLACK_MS as u64;
                if unload_context && current_igt >= low && (current_igt as u64) <= high {
                    info!(igt_ms = current_igt, "[RACE] Race save is back, resuming");
                    self.wrong_save = false;
                    self.last_good_igt = Some(current_igt);
                    self.last_good_at = Some(now);
                }
            } else {
                // Save reload detection: an IGT regression means the player loaded a
                // different save. Reset per-save event-flag state so a pre-set
                // finish_event from a stale save doesn't block the fresh save's real
                // finish (see EVENT_FLAG_TRACKING.md).
                if crate::core::flag_buffer::detect_save_reload(self.last_observed_igt, current_igt)
                {
                    info!(
                        prev_igt_ms = self.last_observed_igt,
                        new_igt_ms = current_igt,
                        "[RACE] Save reload detected, clearing per-save event-flag state"
                    );
                    self.triggered_flags.clear();
                    self.flag_buffer.clear_deferred();
                    self.flag_buffer.clear_pending();
                }
                // A forward IGT jump across an unload beyond WRONG_SAVE_FORWARD_SLACK_MS
                // means a different, further-along save was loaded (not the race save):
                // freeze race interaction until the race save returns.
                let forward_jump = self.has_been_in_world
                    && unload_context
                    && self.last_good_igt.is_some_and(|good| {
                        current_igt > good.saturating_add(WRONG_SAVE_FORWARD_SLACK_MS)
                    });
                if forward_jump {
                    warn!(
                        last_good_igt = self.last_good_igt,
                        new_igt_ms = current_igt,
                        "[RACE] Wrong save loaded (impossible IGT jump), freezing race interaction"
                    );
                    self.wrong_save = true;
                    self.pending_quit_out = false;
                } else {
                    // Quit-out detection: an IGT regression within SAVE_RELOAD_IGT_DROP_MS
                    // observed around an unload means a save was loaded from the menu. Death,
                    // fast travel and fog traversals reload the world, not the save;
                    // GameDataMan persists in memory and the IGT stays monotonic.
                    // Only a menu load repopulates it from disk, where the value lags
                    // the last in-memory reading by the post-flush fade time
                    // (live-measured above 1s). Map-scoped probes (MapItemMan null)
                    // proved unusable here: they also trip on cross-map fog loads.
                    // The return-to-title Lua bit (debug overlay) never fires on menu
                    // quit-outs, only on scripted returns such as endings.
                    // Rollbacks beyond SAVE_RELOAD_IGT_DROP_MS are backup restores or
                    // another save: no penalty (the per-save flush in flag_buffer covers them).
                    if self.has_been_in_world
                        && !self.pending_quit_out
                        && unload_context
                        && self.last_observed_igt.is_some_and(|prev| {
                            current_igt < prev && prev - current_igt < SAVE_RELOAD_IGT_DROP_MS
                        })
                    {
                        info!(
                            prev_igt_ms = self.last_observed_igt,
                            new_igt_ms = current_igt,
                            "[RACE] Quit-out detected (IGT regression)"
                        );
                        self.pending_quit_out = true;
                    }
                    self.last_good_igt = Some(current_igt);
                    self.last_good_at = Some(now);
                }
            }
            self.last_observed_igt = Some(current_igt);
        }

        if self.frame_snapshot.position_readable {
            self.has_been_in_world = true;
        }

        let position_readable = self.frame_snapshot.position_readable;

        // Reveal pending zone update once the loading screen ends (loading
        // byte clear) and the player position is readable. The byte really
        // means "world clock stopped" (see is_world_clock_stopped):
        // permanently ON on frozen-clock event seeds (weather plugin
        // FreezeTime), where the defensive timeout bounds the wait instead.
        // Both paths require a readable position, so a reveal can never
        // fire before the world is loaded.
        if self.pending_zone_update.is_some() {
            let pending_for = self.pending_zone_received_at.map(|t| now.duration_since(t));
            let timed_out = pending_for.is_some_and(|d| d >= ZONE_REVEAL_TIMEOUT);
            let loading_done = self.frame_snapshot.loading_screen != Some(true);
            if position_readable && (loading_done || timed_out) {
                let zone = self.pending_zone_update.take().unwrap();
                if loading_done {
                    info!(name = %zone.display_name, "[RACE] Zone revealed");
                } else {
                    warn!(name = %zone.display_name, "[RACE] Zone revealed (timeout, loading byte stuck)");
                }
                self.race_state.current_zone = Some(zone);
                self.zone_version = self.zone_version.wrapping_add(1);
                self.pre_reveal_layer = None;
                self.pending_zone_received_at = None;
                self.zone_stall_warned = false;
            } else if !self.zone_stall_warned
                && pending_for.is_some_and(|d| d >= ZONE_REVEAL_STALL_WARN)
            {
                let zone = self.pending_zone_update.as_ref().unwrap();
                warn!(
                    name = %zone.display_name,
                    pending_secs = pending_for.unwrap().as_secs(),
                    position_readable,
                    "[RACE] Zone reveal still pending (position readability broken or flickering, or player idling in a menu)"
                );
                self.zone_stall_warned = true;
            }
        }

        // Flags cleared (captured) earlier in this tick: later read consumers
        // must treat them as unset, mirroring the pre-machine behavior where
        // each stage re-read memory after the previous stage's clears.
        let mut cleared: HashSet<u32> = HashSet::new();
        // Set when the quit-out penalty below pulls `last_status_update`
        // into the past: without this, the generic periodic check further
        // down (same tick, same `now`) would immediately see the gate open
        // and consume the pull-forward itself, so the *next* tick (the one
        // actually meant to benefit) would see no elapsed time and skip.
        let mut quit_out_status_pulled_forward = false;

        // Loading screen exit: send deferred event_flags (certain) or zone_query (probabilistic)
        if position_readable && !self.was_position_readable {
            let quit_out = std::mem::take(&mut self.pending_quit_out);
            if quit_out
                && self.is_race_running()
                && !self.am_i_finished()
                && !self.is_countdown_active(now)
            {
                let penalty_ms = self.quit_out_penalty_ms();
                if penalty_ms > 0 {
                    effects.push(Effect::ApplyIgtPenalty { ms: penalty_ms });
                    let banner = if penalty_ms % 1000 == 0 {
                        format!("Quit-out: +{}s", penalty_ms / 1000)
                    } else {
                        format!("Quit-out: +{:.1}s", penalty_ms as f32 / 1000.0)
                    };
                    self.set_status(banner, now);
                    // Pull the next periodic status_update forward so the
                    // leaderboard reflects the bumped IGT immediately.
                    self.last_status_update = now
                        .checked_sub(Duration::from_secs(2))
                        .unwrap_or(self.last_status_update);
                    quit_out_status_pulled_forward = true;
                    info!(penalty_ms, "[RACE] Quit-out penalty applied");
                }
            }

            // Force one immediate flag scan to catch flags set during loading
            // (e.g. Erdtree burn, Maliketh warp) that the 10Hz poll couldn't read
            // because is_flag_set() returns None while position is unreadable.
            // Skipped while frozen: no flag writes into a foreign save.
            if !self.event_ids.is_empty() && !self.wrong_save {
                let igt_ms = self.effective_igt_ms();
                if let Some(ref reads) = input.flag_reads {
                    for &(flag_id, is_set) in reads {
                        if !is_set {
                            continue;
                        }
                        if self.finish_event == Some(flag_id) {
                            if !self.triggered_flags.contains(&flag_id) {
                                self.triggered_flags.insert(flag_id);
                                if input.connected
                                    && self.is_race_running()
                                    && !self.am_i_finished()
                                    && !self.is_countdown_active(now)
                                {
                                    effects.push(self.queue_event_flag(flag_id, igt_ms));
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
                            effects.push(Effect::SetGameFlag {
                                flag_id,
                                value: false,
                            });
                            cleared.insert(flag_id);
                            self.flag_buffer.defer(flag_id, igt_ms);
                            info!(flag_id, "[RACE] Event flag caught at loading exit");
                        }
                    }
                }
            }

            if input.connected
                && self.is_race_running()
                && !self.am_i_finished()
                && !self.is_countdown_active(now)
                && !self.wrong_save
            {
                if self.flag_buffer.has_deferred() {
                    // Fog gate traversal: send deferred flags now that loading is done
                    let deferred: Vec<_> = self.flag_buffer.drain_deferred().collect();
                    for (flag_id, igt_ms) in deferred {
                        effects.push(self.queue_event_flag(flag_id, igt_ms));
                        self.last_sent_debug = Some(format!(
                            "event_flag({}, igt={}ms) [deferred]",
                            flag_id, igt_ms
                        ));
                        info!(flag_id, "[RACE] Deferred event flag sent at loading exit");
                    }
                } else {
                    // No fog gate (death/respawn/quit-out/fast-travel)
                    let igt_ms = self.effective_igt_ms();
                    let grace_opt = input.warp_capture;
                    let map_id = input.position.as_ref().map(|p| p.map_id_str.clone());
                    let position = input.position.as_ref().map(|p| [p.x, p.y, p.z]);
                    let play_region_id = input.position.as_ref().and_then(|p| p.play_region_id);

                    if grace_opt.is_some() || map_id.is_some() {
                        effects.push(self.queue_zone_query(
                            igt_ms,
                            grace_opt,
                            map_id.clone(),
                            position,
                            play_region_id,
                            quit_out,
                        ));
                        self.last_sent_debug = Some(format!(
                            "zone_query(grace={:?}, map={:?})",
                            grace_opt, map_id
                        ));
                        info!(?grace_opt, "[RACE] Zone query sent at loading exit");
                    }

                    if grace_opt.is_some() {
                        effects.push(Effect::ClearWarpCapture);
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
                if input.warp_capture.is_some() {
                    effects.push(Effect::ClearWarpCapture);
                }
            }
        }
        self.was_position_readable = position_readable;

        // Event flag polling runs ALWAYS (even when disconnected).
        // Regular flags are cleared after capture (for re-traversal detection) and
        // deferred until loading exit; finish_event is sent immediately.
        let poll_due = !self.event_ids.is_empty()
            && now.duration_since(self.last_flag_poll) >= Duration::from_millis(100);
        // Record the reader health on every read frame (the shell logs the
        // transition when it performs the reads; recording here keeps the
        // transition from being re-logged on subsequent read frames).
        if let Some(ok) = input.flag_reader_ok {
            self.last_flag_reader_ok = Some(ok);
        }
        if poll_due && !self.wrong_save {
            if let Some(ref reads) = input.flag_reads {
                self.last_flag_poll = now;

                let igt_ms = self.effective_igt_ms();
                for &(flag_id, is_set) in reads {
                    if !is_set || cleared.contains(&flag_id) {
                        continue;
                    }
                    if self.finish_event == Some(flag_id) {
                        // finish_event: one-shot, use triggered_flags guard
                        if !self.triggered_flags.contains(&flag_id) {
                            self.triggered_flags.insert(flag_id);
                            if input.connected
                                && self.is_race_running()
                                && !self.am_i_finished()
                                && !self.is_countdown_active(now)
                            {
                                effects.push(self.queue_event_flag(flag_id, igt_ms));
                                self.last_sent_debug = Some(format!(
                                    "event_flag({}, igt={}ms) [finish]",
                                    flag_id, igt_ms
                                ));
                                info!(flag_id, "[RACE] Finish event sent immediately");
                            } else if !self.am_i_finished() {
                                self.flag_buffer.add_pending(flag_id, igt_ms);
                            }
                        }
                    } else {
                        // Regular fog gate: clear after capture so re-traversals are detected
                        effects.push(Effect::SetGameFlag {
                            flag_id,
                            value: false,
                        });
                        cleared.insert(flag_id);
                        self.flag_buffer.defer(flag_id, igt_ms);
                        info!(flag_id, "[RACE] Event flag deferred until loading exit");
                    }
                }
            }
        }

        // Deathless: a strict local death-count increase while racing fires
        // the one-shot "You died" banner. Elimination itself is server-side
        // (the periodic status_update carries the count); this is instant
        // local feedback only, so it also works while disconnected.
        if let Some(deaths) = self.frame_snapshot.death_count {
            if let Some(prev) = self.last_seen_death_count {
                if deaths > prev
                    && !self.deathless_banner_shown
                    && self.is_deathless()
                    && self.is_race_running()
                    && !self.am_i_finished()
                    && !self.am_i_abandoned()
                    && !self.wrong_save
                {
                    self.deathless_banner_shown = true;
                    self.set_status("You died. Race over.".to_string(), now);
                    info!(deaths, "[RACE] Deathless death detected");
                }
            }
            self.last_seen_death_count = Some(deaths);
        }

        // Everything below needs a live connection (ready, replays, status updates).
        if !input.connected {
            return effects;
        }

        let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
        let deaths = self.frame_snapshot.death_count.unwrap_or(0);

        // Send ready on (re)connection (skip in training mode since server auto-starts)
        if !self.ready_sent {
            if !self.training {
                effects.push(Effect::SendReady);
                self.last_sent_debug = Some("ready".to_string());
                info!("[RACE] Sent ready signal");
            }
            self.ready_sent = true;

            if self.is_race_running() && !self.am_i_finished() && !self.is_countdown_active(now) {
                // Replay in-flight event flags (sent but not ACKed before disconnect)
                // with their original message_id for server-side dedup.
                self.replay_in_flight_event_flags(&mut effects);

                // Replay in-flight zone queries (sent but not ACKed before disconnect)
                self.replay_in_flight_zone_queries(&mut effects);

                // Drain event flags buffered during disconnection (never sent)
                let pending: Vec<_> = self.flag_buffer.drain_pending().collect();
                for (flag_id, flag_igt) in pending {
                    effects.push(self.queue_event_flag(flag_id, flag_igt));
                    self.last_sent_debug =
                        Some(format!("event_flag({}, igt={})", flag_id, flag_igt));
                    info!(flag_id, "[RACE] Buffered event flag sent");
                }

                // Safety-net rescan: catch any flags still set in memory that polling missed
                if let Some(ref reads) = input.flag_reads {
                    for &(flag_id, is_set) in reads {
                        if !is_set || cleared.contains(&flag_id) {
                            continue;
                        }
                        if self.finish_event == Some(flag_id) {
                            if !self.triggered_flags.contains(&flag_id) {
                                self.triggered_flags.insert(flag_id);
                                effects.push(self.queue_event_flag(flag_id, igt_ms));
                                self.last_sent_debug =
                                    Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                                info!(flag_id, "[RACE] Finish event re-sent after reconnect");
                            }
                        } else {
                            effects.push(Effect::SetGameFlag {
                                flag_id,
                                value: false,
                            });
                            cleared.insert(flag_id);
                            effects.push(self.queue_event_flag(flag_id, igt_ms));
                            self.last_sent_debug =
                                Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                            info!(flag_id, "[RACE] Event flag re-sent after reconnect");
                        }
                    }
                }
            }
        }

        // Send periodic status updates (every 1 second, only when IGT is ticking and race running)
        // During quit-outs IGT is 0, skip to avoid erroneous data.
        // Stop once finished since IGT is frozen at finish time.
        if !quit_out_status_pulled_forward
            && !self.wrong_save
            && self.wants_status_update(now, igt_ms)
        {
            effects.push(Effect::SendStatusUpdate {
                igt_ms,
                death_count: deaths,
                weapons: input.weapons,
            });
            self.last_status_update = now;
        }

        effects
    }

    /// Register an event flag as in-flight and return its send effect.
    fn queue_event_flag(&mut self, flag_id: u32, igt_ms: u32) -> Effect {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_event_flags
            .insert(message_id, BufferedEventFlag { flag_id, igt_ms });
        Effect::SendEventFlag {
            flag_id,
            igt_ms,
            message_id,
        }
    }

    /// Register a zone query as in-flight and return its send effect.
    fn queue_zone_query(
        &mut self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        quit_out: bool,
    ) -> Effect {
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
                quit_out,
            },
        );
        Effect::SendZoneQuery {
            igt_ms,
            message_id,
            grace_entity_id,
            map_id,
            position,
            play_region_id,
            quit_out,
        }
    }

    /// Replay in-flight event flags (sent but not yet ACKed) with their
    /// original `message_id`, preserving server-side idempotency.
    ///
    /// Entries stay in `in_flight_event_flags` after replay: they are only
    /// removed when the server sends `EventFlagAck` for each one.
    fn replay_in_flight_event_flags(&mut self, effects: &mut Vec<Effect>) {
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
            effects.push(Effect::SendEventFlag {
                flag_id: event.flag_id,
                igt_ms: event.igt_ms,
                message_id,
            });
            info!(
                message_id,
                flag_id = event.flag_id,
                "[RACE] Replaying in-flight event flag"
            );
        }
    }

    fn replay_in_flight_zone_queries(&mut self, effects: &mut Vec<Effect>) {
        if self.in_flight_zone_queries.is_empty() {
            return;
        }

        let mut message_ids: Vec<u64> = self.in_flight_zone_queries.keys().copied().collect();
        message_ids.sort_unstable();
        for message_id in message_ids {
            if let Some(zq) = self.in_flight_zone_queries.get(&message_id) {
                effects.push(Effect::SendZoneQuery {
                    igt_ms: zq.igt_ms,
                    message_id,
                    grace_entity_id: zq.grace_entity_id,
                    map_id: zq.map_id.clone(),
                    position: zq.position,
                    play_region_id: zq.play_region_id,
                    quit_out: zq.quit_out,
                });
                info!(message_id, "[RACE] Replaying in-flight zone query");
            }
        }
    }
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ------------------------------------------------------------------
    // Harness
    // ------------------------------------------------------------------

    fn test_race(status: &str) -> RaceInfo {
        serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"Test Race","status":"{}"}}"#,
            status
        ))
        .unwrap()
    }

    fn test_seed(event_ids: &[u32], finish_event: Option<u32>, death_flags: &str) -> SeedInfo {
        let finish = finish_event
            .map(|f| f.to_string())
            .unwrap_or_else(|| "null".to_string());
        serde_json::from_str(&format!(
            r#"{{"total_layers": 3, "event_ids": {:?}, "finish_event": {}, "death_flags": {}}}"#,
            event_ids, finish, death_flags
        ))
        .unwrap()
    }

    fn test_participant(id: &str, status: &str, layer: i32) -> ParticipantInfo {
        serde_json::from_str(&format!(
            r#"{{"id":"{}","twitch_username":"u_{}","twitch_display_name":null,
                 "status":"{}","current_zone":null,"current_layer":{},
                 "igt_ms":0,"death_count":0}}"#,
            id, id, status, layer
        ))
        .unwrap()
    }

    fn auth_ok(status: &str, event_ids: &[u32], finish: Option<u32>) -> MachineMessage {
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed: test_seed(event_ids, finish, "{}"),
            participants: vec![test_participant("p1", "playing", 1)],
            phantom_skin: None,
            latest_mod_version: None,
        }
    }

    /// Machine authed into a running race with regular flags [100, 200] and
    /// finish flag 900, `now` = machine birth time.
    fn running_machine(now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("running", &[100, 200, 900], Some(900)), now);
        m
    }

    /// Machine authed into a running DEATHLESS race, same shape as
    /// `running_machine` otherwise.
    fn deathless_running_machine(now: Instant) -> RaceMachine {
        deathless_machine("running", now)
    }

    fn deathless_machine(status: &str, now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo = serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"x","status":"{}","deathless":true}}"#,
            status
        ))
        .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        m
    }

    fn snap_deaths(igt: Option<u32>, deaths: u32) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(deaths),
            position_readable: true,
            loading_screen: Some(false),
            ..FrameSnapshot::default()
        }
    }

    fn snap(igt: Option<u32>, pos: bool) -> FrameSnapshot {
        snap_load(igt, pos, Some(false))
    }

    fn snap_load(igt: Option<u32>, pos: bool, loading: Option<bool>) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(0),
            position_readable: pos,
            loading_screen: loading,
            ..FrameSnapshot::default()
        }
    }

    fn tick_in(
        snapshot: FrameSnapshot,
        connected: bool,
        reads: Option<Vec<(u32, bool)>>,
    ) -> TickInput {
        TickInput {
            snapshot,
            connected,
            warp_capture: None,
            position: None,
            flag_reads: reads,
            weapons: [None, None],
            flag_reader_ok: None,
        }
    }

    fn sent_flags(effects: &[Effect]) -> Vec<u32> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendEventFlag { flag_id, .. } => Some(*flag_id),
                _ => None,
            })
            .collect()
    }

    fn sent_message_ids(effects: &[Effect]) -> Vec<u64> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendEventFlag { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .collect()
    }

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    fn secs(v: u64) -> Duration {
        Duration::from_secs(v)
    }

    /// Captures tracing output for log assertions (scoped to the test thread
    /// via `tracing::subscriber::with_default`).
    #[derive(Clone, Default)]
    struct LogCapture(std::sync::Arc<std::sync::Mutex<Vec<u8>>>);

    impl LogCapture {
        fn contents(&self) -> String {
            String::from_utf8_lossy(&self.0.lock().unwrap()).into_owned()
        }
    }

    impl std::io::Write for LogCapture {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogCapture {
        type Writer = LogCapture;
        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    // ------------------------------------------------------------------
    // Quit-out detection latch
    // ------------------------------------------------------------------

    #[test]
    fn first_load_after_boot_does_not_arm() {
        // Mod injected while the player sits at the menu: the first IGT
        // observation has no prior reading to regress from.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.was_position_readable = false;
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(1000), false), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn death_reload_does_not_arm() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);

        // Death load: world reload, not save load. GameDataMan persists in
        // memory, so the IGT keeps its value through the loading screen.
        m.tick(tick_in(snap(Some(5_000), false), true, None), now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn igt_regression_around_unload_arms_latch() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);

        // Menu save-load: the reloaded save's IGT sits below the last
        // in-world observation (the on-disk save lags the in-memory IGT by
        // the post-flush fade).
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(8_500), false), true, None), now);
        assert!(m.pending_quit_out);

        // Full consumption at loading exit: penalty + tagged query.
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
    }

    #[test]
    fn igt_regression_on_loading_exit_frame_arms_and_consumes_same_tick() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);

        // The regressed IGT first becomes readable on the loading-exit frame
        // itself: arming must precede consumption within the same tick.
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert!(!m.pending_quit_out, "latch consumed in the same tick");
    }

    #[test]
    fn igt_regression_in_world_does_not_arm() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // Stable in-world frames: monotonic IGT, a frozen-clock frame (equal
        // value), then a hypothetical in-world regression. None may arm: the
        // first two are not strict regressions, and the last one happens
        // outside an unload context (both frames position-readable).
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);
        m.tick(tick_in(snap(Some(6_000), true), true, None), now);
        m.tick(tick_in(snap(Some(6_000), true), true, None), now);
        m.tick(tick_in(snap(Some(4_000), true), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn fog_traversal_with_deferred_flags_does_not_penalize() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);

        // Fog gate captured by the 10 Hz poll: cleared in memory and
        // deferred until loading exit.
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(5_100), true), true, Some(vec![(100, true)])),
            later,
        );
        // Cross-map load: world reload, not save load, so the IGT stays
        // monotonic through the loading screen.
        m.tick(tick_in(snap(Some(5_200), false), true, None), later);
        let mut input = tick_in(snap(Some(5_300), true), true, None);
        input.flag_reads = Some(vec![]);
        let fx = m.tick(input, later);
        assert_eq!(penalty_ms(&fx), None);
        assert!(sent_flags(&fx).contains(&100), "deferred flag sent at exit");
        assert_eq!(
            sent_zone_query_quit_out(&fx),
            None,
            "fog exit sends event flags, not a zone query"
        );
    }

    // ------------------------------------------------------------------
    // Wrong-save freeze
    // ------------------------------------------------------------------

    /// In-world at 10_000ms, then a reload that lands at `reload_igt`.
    fn reload_to(m: &mut RaceMachine, reload_igt: u32, now: Instant) {
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(reload_igt), false), true, None), now);
    }

    #[test]
    fn forward_jump_across_unload_freezes() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 7_200_000, now);
        assert!(m.wrong_save);
        assert!(!m.pending_quit_out, "no penalty into a foreign save");

        // Frozen: a loading exit produces no sends and no game writes.
        let mut input = tick_in(snap(Some(7_200_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert!(fx.is_empty(), "frozen machine emits nothing, got {fx:?}");

        // Frozen: no periodic status updates either.
        let fx = m.tick(
            tick_in(snap(Some(7_205_000), true), true, None),
            now + secs(5),
        );
        assert!(fx
            .iter()
            .all(|e| !matches!(e, Effect::SendStatusUpdate { .. })));
        assert!(!m.wants_status_update(now + secs(5), 7_205_000));
        assert!(!m.wants_flag_reads(FrameNeeds::default(), true, true));
    }

    #[test]
    fn same_save_reload_does_not_freeze() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 8_500, now); // ordinary quit-out
        assert!(!m.wrong_save);
        assert!(m.pending_quit_out);
    }

    #[test]
    fn wrong_save_recovers_when_race_save_returns() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 7_200_000, now);
        assert!(m.wrong_save);

        // Player keeps playing the wrong save: still frozen.
        m.tick(
            tick_in(snap(Some(7_260_000), true), true, None),
            now + secs(60),
        );
        assert!(m.wrong_save);

        // Reload back into the race save: inside the plausible window of
        // the last good observation (10_000 + elapsed + slack).
        m.tick(tick_in(snap(None, false), true, None), now + secs(90));
        m.tick(
            tick_in(snap(Some(9_000), false), true, None),
            now + secs(90),
        );
        assert!(!m.wrong_save, "race save back, freeze lifted");
        assert!(
            !m.pending_quit_out,
            "the corrective reload is a forward jump from the wrong save, not a quit-out"
        );

        // Life resumes: a loading exit sends again.
        let mut input = tick_in(snap(Some(9_100), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now + secs(90));
        assert!(fx.iter().any(|e| matches!(e, Effect::SendZoneQuery { .. })));
    }

    #[test]
    fn wrong_save_reload_does_not_flush_buffers() {
        // Buffers parked before the wrong-save reload must survive the
        // freeze AND the recovery reload (both would previously flush).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), false, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(10_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(10_200), false), false, None), later);
        let mut input = tick_in(snap(Some(10_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        // Wrong save loaded, then the race save comes back.
        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(tick_in(snap(Some(7_200_000), false), false, None), later);
        assert!(m.wrong_save);
        m.tick(tick_in(snap(None, false), false, None), later + secs(30));
        m.tick(
            tick_in(snap(Some(10_300), false), false, None),
            later + secs(30),
        );
        assert!(!m.wrong_save);
        assert!(
            m.flag_buffer.has_pending(),
            "parked traversal survives the whole wrong-save episode"
        );
    }

    #[test]
    fn wrong_save_recovery_requires_elapsed_real_time() {
        // The recovery window is `[last_good - SAVE_RELOAD_IGT_DROP_MS,
        // last_good + elapsed_wall + WRONG_SAVE_RECOVERY_SLACK_MS]`: an IGT
        // just past the fixed slack must wait for enough real time to pass
        // before it becomes plausible again.
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 200_000, now);
        assert!(m.wrong_save);

        // 25_000 is beyond the fixed window (10_000 + 10_000 slack) right
        // after the freeze: not enough elapsed time to explain it yet.
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(25_000), false), true, None), now);
        assert!(m.wrong_save, "not enough elapsed time to explain this IGT");

        // After 60s of real time the same IGT is plausible again: the
        // elapsed term widens the window and the freeze lifts.
        m.tick(tick_in(snap(None, false), true, None), now + secs(60));
        m.tick(
            tick_in(snap(Some(25_000), false), true, None),
            now + secs(60),
        );
        assert!(
            !m.wrong_save,
            "elapsed real time makes 25_000 plausible now"
        );
    }

    #[test]
    fn forward_jump_at_exact_slack_boundary_does_not_freeze() {
        // Exactly WRONG_SAVE_FORWARD_SLACK_MS forward of the last good IGT:
        // the strict `>` in forward_jump means this is ordinary progress,
        // not a wrong save.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(
            tick_in(
                snap(Some(10_000 + WRONG_SAVE_FORWARD_SLACK_MS), false),
                true,
                None,
            ),
            now,
        );
        assert!(!m.wrong_save, "exact boundary is not a forward jump");
    }

    #[test]
    fn race_start_clears_pre_start_wrong_save_freeze() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        // Wrong 2h save loaded by mistake during setup: freezes.
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(!m.wrong_save, "race start clears a stale pre-start freeze");

        // Fresh race save (IGT near 0), past the countdown: normal life,
        // no freeze, no penalty, sends work.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(1_000), true), true, None),
            after_countdown,
        );
        m.tick(tick_in(snap(None, false), true, None), after_countdown);
        let mut input = tick_in(snap(Some(1_000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert!(!m.wrong_save);
        assert_eq!(penalty_ms(&fx), None);
        assert!(fx.iter().any(|e| matches!(e, Effect::SendZoneQuery { .. })));
    }

    // ------------------------------------------------------------------
    // Message handling basics
    // ------------------------------------------------------------------

    #[test]
    fn test_race_start_sets_running_and_countdown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let fx = m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        assert!(fx.is_empty());
        assert!(m.is_race_setup());

        let fx = m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(fx.is_empty());
        assert!(m.is_race_running());
        assert!(m.is_countdown_active(now));
        assert!(!m.is_countdown_active(now + secs(4)));
    }

    // ------------------------------------------------------------------
    // Flag lifecycle scenarios
    // ------------------------------------------------------------------

    #[test]
    fn test_defer_then_drain_at_loading_exit() {
        let now = Instant::now();
        let mut m = running_machine(now);

        // Regular flag set during the 10Hz poll: cleared in game + deferred,
        // NOT sent yet.
        let t1 = now + ms(150);
        let fx = m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            t1,
        );
        assert!(sent_flags(&fx).is_empty(), "no send before loading exit");
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 100,
            value: false
        }));
        assert!(m.flag_buffer.has_deferred());
        // Regular flags are not tracked in triggered_flags
        assert!(!m.triggered_flags.contains(&100));

        // Loading screen (position unreadable), then exit: deferred flag sent.
        let t2 = t1 + ms(50);
        m.tick(tick_in(snap(Some(1200), false), true, None), t2);
        let t3 = t2 + ms(30);
        let fx = m.tick(
            tick_in(
                snap(Some(1300), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            t3,
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        assert!(!m.flag_buffer.has_deferred());
        assert_eq!(m.in_flight_event_flags.len(), 1);

        // Second identical poll read: nothing new (flag cleared in memory
        // would read false; even a stale true defers again by design).
        let t4 = t3 + ms(150);
        let fx = m.tick(
            tick_in(
                snap(Some(1500), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            t4,
        );
        assert!(sent_flags(&fx).is_empty());
    }

    #[test]
    fn test_finish_flag_sends_immediately() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // First tick marks ready_sent (SendReady fires once).
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        // Sent in the SAME tick, no defer, no game-memory clear for finish.
        assert_eq!(sent_flags(&fx), vec![900]);
        assert!(m.triggered_flags.contains(&900));
        assert!(!fx
            .iter()
            .any(|e| matches!(e, Effect::SetGameFlag { flag_id: 900, .. })));
    }

    #[test]
    fn test_finish_flag_pending_when_gated_then_flushed_on_reconnect() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(MachineMessage::RaceStart(10), now);

        // Finish flag during countdown: buffered pending, no send.
        let fx = m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(m.triggered_flags.contains(&900));

        // Reconnect after the countdown: pending drained.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(11),
        );
        let fx = m.tick(
            tick_in(snap(Some(20_000), true), true, Some(vec![])),
            now + secs(12),
        );
        assert_eq!(sent_flags(&fx), vec![900]);
    }

    #[test]
    fn test_park_and_replay_on_reconnect_with_requeue() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Defer a regular flag, then lose the connection: parked to pending.
        m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        let fx = m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(200),
        );
        assert!(fx.is_empty());
        assert!(!m.flag_buffer.has_deferred(), "deferred parked to pending");

        // Reconnected: pending drained with a fresh message_id.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + ms(300),
        );
        let fx = m.tick(
            tick_in(snap(Some(2000), true), true, Some(vec![])),
            now + ms(350),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        let first_id = sent_message_ids(&fx)[0];
        assert!(m.in_flight_event_flags.contains_key(&first_id));

        // Server reports the message never left the socket: requeued.
        m.handle_message(
            MachineMessage::RequeueEventFlag {
                flag_id: 100,
                igt_ms: 1000,
                message_id: first_id,
            },
            now + ms(400),
        );
        assert!(!m.in_flight_event_flags.contains_key(&first_id));

        // Next reconnect drains it again with a NEW, larger message_id.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + ms(500),
        );
        let fx = m.tick(
            tick_in(snap(Some(3000), true), true, Some(vec![])),
            now + ms(550),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        let second_id = sent_message_ids(&fx)[0];
        assert!(second_id > first_id, "message ids stay monotonic");
    }

    #[test]
    fn test_save_reload_purges_per_save_state() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Capture a finish flag and defer a regular one.
        m.tick(
            tick_in(
                snap(Some(100_000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // IGT regression = save reload: per-save state cleared, no sends.
        let fx = m.tick(tick_in(snap(Some(1_000), true), true, None), now + ms(200));
        assert!(sent_flags(&fx).is_empty());
        assert!(m.triggered_flags.is_empty());
        assert!(!m.flag_buffer.has_deferred());
    }

    // ------------------------------------------------------------------
    // Zone reveal scenarios
    // ------------------------------------------------------------------

    fn zone_update(name: &str, message_id: Option<u64>) -> MachineMessage {
        MachineMessage::ZoneUpdate {
            node_id: "n1".to_string(),
            display_name: name.to_string(),
            tier: Some(2),
            original_tier: Some(2),
            layer: Some(2),
            is_first_visit: true,
            exits: Vec::new(),
            message_id,
        }
    }

    #[test]
    fn test_zone_reveal_waits_for_loading_end() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Stormveil", None), now + ms(100));
        assert!(m.pending_zone_update.is_some());
        assert_eq!(m.zone_version, 0, "no bump before reveal");

        // Still loading: byte set, position unreadable.
        m.tick(
            tick_in(snap_load(Some(1000), false, Some(true)), true, None),
            now + ms(200),
        );
        assert!(m.race_state.current_zone.is_none());

        // World loaded (position readable) but the loading screen still
        // displayed (byte set): not revealed.
        m.tick(
            tick_in(snap_load(Some(1200), true, Some(true)), true, Some(vec![])),
            now + ms(300),
        );
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, None),
            now + secs(3),
        );
        assert!(m.race_state.current_zone.is_none());

        // Byte clear: revealed on that very frame.
        m.tick(
            tick_in(snap_load(Some(2100), true, Some(false)), true, None),
            now + secs(4),
        );
        let zone = m.race_state.current_zone.as_ref().expect("revealed");
        assert_eq!(zone.display_name, "Stormveil");
        assert!(m.pending_zone_update.is_none());
        assert_eq!(m.zone_version, 1, "reveal bumps the render-cache key");
    }

    #[test]
    fn test_zone_reveal_timeout_when_byte_stuck() {
        // Frozen-clock event seeds (weather plugin FreezeTime): the byte
        // never clears, the defensive timeout bounds the wait.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Volcano Manor", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), true, Some(true)), true, None),
            now + ms(200),
        );
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT - ms(50),
        );
        assert!(
            m.race_state.current_zone.is_none(),
            "byte stuck: no reveal before the timeout"
        );

        m.tick(
            tick_in(snap_load(Some(3000), true, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT + ms(50),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Volcano Manor"
        );
    }

    #[test]
    fn test_zone_reveal_timeout_still_requires_position() {
        // The timeout path never reveals while the world is not loaded: a
        // long load on a frozen-clock seed reveals at loading exit, not
        // mid-load.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Leyndell", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), false, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT + secs(3),
        );
        assert!(
            m.race_state.current_zone.is_none(),
            "position unreadable: no reveal even past the timeout"
        );

        // Position becomes readable (timeout long elapsed): reveal fires
        // even though the byte is still stuck.
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, Some(vec![])),
            now + ZONE_REVEAL_TIMEOUT + secs(4),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Leyndell"
        );
    }

    #[test]
    fn test_zone_reveal_byte_unreadable_counts_as_done() {
        // Byte unreadable (game patch moved it, pointer chain broken):
        // position readability alone gates the reveal, as before 1ddfe1c6.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Siofra", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), false, None), true, None),
            now + ms(200),
        );
        assert!(m.race_state.current_zone.is_none(), "position still gates");

        m.tick(
            tick_in(snap_load(Some(2000), true, None), true, Some(vec![])),
            now + ms(400),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Siofra"
        );
    }

    #[test]
    fn test_zone_reveal_instant_on_reconnect_resend() {
        // Reconnect scenario (WEBSOCKET_LIFECYCLE.md): the server resends
        // the zone_update while the player stands in a loaded world (byte
        // clear, position readable): the reveal fires on the next tick.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(1000), true), true, None), now + ms(10));

        m.handle_message(zone_update("Caelid", None), now + secs(10));
        m.tick(
            tick_in(snap(Some(2000), true), true, None),
            now + secs(10) + ms(20),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Caelid"
        );
    }

    #[test]
    fn test_zone_reveal_stall_warns_once() {
        let logs = LogCapture::default();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(logs.clone())
            .with_max_level(tracing::Level::WARN)
            .with_ansi(false)
            .finish();
        let warn_count = |l: &LogCapture| l.contents().matches("Zone reveal still pending").count();

        tracing::subscriber::with_default(subscriber, || {
            let now = Instant::now();
            let mut m = running_machine(now);
            m.handle_message(zone_update("Farum Azula", None), now);

            // Position readability broken: unreadable the whole time, so
            // neither the byte path nor the timeout path can reveal.
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(29),
            );
            assert!(m.race_state.current_zone.is_none());
            assert_eq!(warn_count(&logs), 0, "no stall warn before the threshold");

            // Crossing the threshold: exactly one warn, still no reveal.
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(31),
            );
            assert_eq!(warn_count(&logs), 1, "one stall warn past the threshold");
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(40),
            );
            assert_eq!(
                warn_count(&logs),
                1,
                "stall warn fires once per pending zone"
            );
            assert!(
                m.race_state.current_zone.is_none(),
                "diagnostic only, no reveal while position is unreadable"
            );

            // A new zone_update re-arms the warn, and last-writer-wins
            // re-anchors the stall clock on the latest arrival.
            m.handle_message(zone_update("Liurnia", None), now + secs(41));
            m.handle_message(zone_update("Altus", None), now + secs(50));
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(75),
            );
            assert_eq!(
                warn_count(&logs),
                1,
                "stall clock re-anchored on the latest zone_update"
            );
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(81),
            );
            assert_eq!(warn_count(&logs), 2, "second pending zone warns again");
        });
    }

    #[test]
    fn test_pre_reveal_layer_freezes_until_reveal() {
        let now = Instant::now();
        let mut m = running_machine(now);
        assert_eq!(m.my_participant().unwrap().current_layer, 1);

        // Zone update pending + leaderboard bumps my layer: old layer frozen.
        m.handle_message(zone_update("Caelid", None), now + ms(100));
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "playing", 2)],
                leader_splits: None,
            },
            now + ms(150),
        );
        assert_eq!(m.pre_reveal_layer, Some(1));

        // Still loading (byte set): frozen until the reveal.
        m.tick(
            tick_in(snap_load(Some(1200), true, Some(true)), true, Some(vec![])),
            now + ms(300),
        );
        assert_eq!(m.pre_reveal_layer, Some(1), "frozen until reveal");
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(false)), true, None),
            now + ms(400),
        );
        assert!(m.pre_reveal_layer.is_none());
    }

    // ------------------------------------------------------------------
    // Race lifecycle scenarios
    // ------------------------------------------------------------------

    #[test]
    fn test_frozen_igt_on_race_end_and_reset_on_auth() {
        let now = Instant::now();
        let mut m = running_machine(now);

        // Race ends while I am still playing: IGT frozen from the shell read.
        m.handle_message(
            MachineMessage::RaceStatusChange {
                status: RaceStatus::Finished,
                current_igt: Some(4242),
            },
            now + secs(60),
        );
        assert_eq!(m.frozen_igt_ms, Some(4242));
        assert_eq!(m.frame_snapshot.igt_ms, Some(4242));

        // Reconnect resets the freeze.
        m.handle_message(auth_ok("running", &[100], Some(900)), now + secs(61));
        assert!(m.frozen_igt_ms.is_none());
    }

    #[test]
    fn test_countdown_gates_loading_exit_sends() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        m.handle_message(MachineMessage::RaceStart(10), now + ms(20));

        // Defer a flag during countdown.
        m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // Loading exit during countdown: nothing sent, deferred parked.
        m.tick(tick_in(snap(Some(1100), false), true, None), now + ms(200));
        let fx = m.tick(
            tick_in(snap(Some(1200), true), true, Some(vec![])),
            now + ms(250),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(!m.flag_buffer.has_deferred(), "parked to pending");
    }

    #[test]
    fn test_ack_idempotence() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Unknown ack: no state change, no panic.
        let fx = m.handle_message(MachineMessage::EventFlagAck { message_id: 999 }, now);
        assert!(fx.is_empty());

        // Send a finish flag, then ack it: removed from in-flight.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        let id = sent_message_ids(&fx)[0];
        assert!(m.in_flight_event_flags.contains_key(&id));
        m.handle_message(MachineMessage::EventFlagAck { message_id: id }, now);
        assert!(!m.in_flight_event_flags.contains_key(&id));
    }

    #[test]
    fn test_status_update_cadence_and_gating() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let has_status = |fx: &[Effect]| {
            fx.iter()
                .any(|e| matches!(e, Effect::SendStatusUpdate { .. }))
        };

        // 1.2s after birth: fires.
        let fx = m.tick(tick_in(snap(Some(5000), true), true, None), now + ms(1200));
        assert!(has_status(&fx));

        // 200ms later: throttled.
        let fx = m.tick(tick_in(snap(Some(5200), true), true, None), now + ms(1400));
        assert!(!has_status(&fx));

        // Another second later: fires again.
        let fx = m.tick(tick_in(snap(Some(6300), true), true, None), now + ms(2400));
        assert!(has_status(&fx));

        // IGT 0 (quit-out): skipped.
        let fx = m.tick(tick_in(snap(Some(0), true), true, None), now + ms(3600));
        assert!(!has_status(&fx));

        // Once I am finished: skipped.
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "finished", 3)],
                leader_splits: None,
            },
            now + ms(3700),
        );
        let fx = m.tick(tick_in(snap(Some(9000), true), true, None), now + ms(4800));
        assert!(!has_status(&fx));
    }

    #[test]
    fn test_death_counts_emit_threshold_flags() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: test_race("running"),
                seed: test_seed(&[100], None, r#"{"zone_a": [10, 11, 12]}"#),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );

        let mut counts = HashMap::new();
        counts.insert("zone_a".to_string(), 4u32);
        let fx = m.handle_message(MachineMessage::DeathCounts(counts), now);
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 10,
            value: true
        }));
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 11,
            value: true
        }));
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 12,
            value: false
        }));
        assert_eq!(m.race_state.death_counts.get("zone_a"), Some(&4));
    }

    // ------------------------------------------------------------------
    // Quit-out consumption (penalty + tagged zone query)
    // ------------------------------------------------------------------

    fn sent_zone_query_quit_out(effects: &[Effect]) -> Option<bool> {
        effects.iter().find_map(|e| match e {
            Effect::SendZoneQuery { quit_out, .. } => Some(*quit_out),
            _ => None,
        })
    }

    fn penalty_ms(effects: &[Effect]) -> Option<u32> {
        effects.iter().find_map(|e| match e {
            Effect::ApplyIgtPenalty { ms } => Some(*ms),
            _ => None,
        })
    }

    /// Full quit-out cycle: in-world -> menu -> reload with a regressed IGT.
    /// Returns the loading-exit effects.
    fn quit_out_cycle(m: &mut RaceMachine, now: Instant) -> Vec<Effect> {
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        m.tick(input, now)
    }

    #[test]
    fn quit_out_cycle_applies_penalty_banner_and_tagged_query() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx = quit_out_cycle(&mut m, now);

        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert_eq!(m.get_status(now), Some("Quit-out: +2s"));
        assert!(!m.pending_quit_out, "latch consumed");
    }

    #[test]
    fn quit_out_penalty_pulls_status_update_forward() {
        let now = Instant::now();
        let mut m = running_machine(now);
        quit_out_cycle(&mut m, now);

        // Immediately after the reload tick, a status_update fires without
        // waiting for the periodic 1s gate.
        let fx = m.tick(tick_in(snap(Some(5000), true), true, None), now + ms(50));
        assert!(fx
            .iter()
            .any(|e| matches!(e, Effect::SendStatusUpdate { .. })));
    }

    #[test]
    fn quit_out_custom_and_zero_penalty() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":5000}"#,
        )
        .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), Some(5000));
        assert_eq!(m.get_status(now), Some("Quit-out: +5s"));

        // penalty 0: no penalty effect, no banner, query still tagged.
        let mut m0 = RaceMachine::new(1, String::new(), false, now);
        let mut race0: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":0}"#,
        )
        .unwrap();
        race0.reparse_dates();
        m0.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: race0,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m0, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(m0.get_status(now), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));

        // Non-round-thousand penalty: banner keeps the decimal instead of
        // truncating to "+0s"/"+1s".
        let mut m1 = RaceMachine::new(1, String::new(), false, now);
        let mut race1: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":1500}"#,
        )
        .unwrap();
        race1.reparse_dates();
        m1.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: race1,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m1, now);
        assert_eq!(penalty_ms(&fx), Some(1500));
        assert_eq!(m1.get_status(now), Some("Quit-out: +1.5s"));
    }

    #[test]
    fn no_penalty_when_not_running_or_finished() {
        let now = Instant::now();

        // Race in setup.
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), None, "setup: no query sent");

        // Finished participant.
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: test_race("running"),
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "finished", 1)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), None);
    }

    #[test]
    fn training_quit_out_applies_penalty() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), true, now);
        m.handle_message(auth_ok("running", &[100], Some(900)), now);
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert_eq!(m.get_status(now), Some("Quit-out: +2s"));
    }

    #[test]
    fn large_regression_is_restore_not_quit_out() {
        // A backup restore rolls the IGT back by minutes: no penalty is
        // armed (the flush path is covered by the boundary and purge tests).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(600_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(500_000), false), true, None), now);
        assert!(!m.pending_quit_out, "restore must not arm the penalty");
    }

    #[test]
    fn boundary_regression_is_rollback_not_quit_out() {
        // Regression of exactly SAVE_RELOAD_IGT_DROP_MS: rollback
        // semantics win. The per-save flush fires (pending cleared) and
        // no penalty is armed; flush and penalty are mutually exclusive.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(100_000), true), true, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(100_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(100_200), false), false, None), later);
        let mut input = tick_in(snap(Some(100_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(
            tick_in(snap(Some(100_300 - 60_000), false), false, None),
            later,
        );
        assert!(!m.pending_quit_out, "boundary regression must not arm");
        assert!(
            !m.flag_buffer.has_pending(),
            "boundary regression flushes per-save state"
        );
    }

    #[test]
    fn pending_flags_survive_ordinary_quit_out() {
        // Disconnected -> fog traversal parked as pending -> quit-out:
        // the small regression must NOT flush the pending buffer anymore.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);

        // Traversal while disconnected: flag captured then parked.
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(10_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(10_200), false), false, None), later);
        let mut input = tick_in(snap(Some(10_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(
            m.flag_buffer.has_pending(),
            "traversal parked while offline"
        );

        // Quit-out (2s regression) while still disconnected.
        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(tick_in(snap(Some(8_300), false), false, None), later);
        assert!(
            m.flag_buffer.has_pending(),
            "quit-out must not discard the parked traversal"
        );
        assert!(m.pending_quit_out, "still a quit-out (penalty armed)");
    }

    #[test]
    fn two_quit_out_cycles_pay_twice() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx1 = quit_out_cycle(&mut m, now);
        let fx2 = quit_out_cycle(&mut m, now + secs(10));
        assert_eq!(penalty_ms(&fx1), Some(2000));
        assert_eq!(penalty_ms(&fx2), Some(2000));
    }

    #[test]
    fn plain_reload_sends_untagged_query_and_no_penalty() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // Death-style cycle: no bit, no title screen.
        m.tick(tick_in(snap(Some(1000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        let mut input = tick_in(snap(Some(1000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    #[test]
    fn replayed_zone_query_preserves_quit_out() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx = quit_out_cycle(&mut m, now);
        let message_id = fx
            .iter()
            .find_map(|e| match e {
                Effect::SendZoneQuery { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .unwrap();

        // Not ACKed: still in flight; a replay must keep the tag.
        let mut effects = Vec::new();
        m.replay_in_flight_zone_queries(&mut effects);
        assert!(effects.iter().any(|e| matches!(
            e,
            Effect::SendZoneQuery { message_id: id, quit_out: true, .. } if *id == message_id
        )));
    }

    // ------------------------------------------------------------------
    // Quit-out latch armed before race start
    // ------------------------------------------------------------------

    #[test]
    fn quit_out_armed_before_race_start_does_not_penalize_first_load() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        // Player quits out and reloads while waiting in setup for the race
        // to start: the regression arms the latch.
        m.tick(tick_in(snap(Some(50_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(48_500), false), true, None), now);
        assert!(m.pending_quit_out);

        m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(!m.pending_quit_out, "race start clears the pre-race latch");

        // Load in once running, past the countdown: must NOT be treated as
        // a quit-out, since the armed latch predates the race.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(48_500), true), true, None),
            after_countdown,
        );
        m.tick(tick_in(snap(None, false), true, None), after_countdown);
        let mut input = tick_in(snap(Some(48_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    #[test]
    fn pre_start_igt_regression_does_not_penalize_first_load() {
        // Player loads their save during setup, quits to menu (probe misses
        // the title screen), waits for the start, then loads in after the
        // countdown: the reloaded save's IGT regresses vs the pre-start
        // observation but must not arm the latch.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        m.tick(tick_in(snap(Some(50_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);

        m.handle_message(MachineMessage::RaceStart(3), now);

        // Reload once running, past the countdown, with a regressed IGT.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(48_000), false), true, None),
            after_countdown,
        );
        assert!(!m.pending_quit_out, "pre-start regression must not arm");
        let mut input = tick_in(snap(Some(48_000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    // ------------------------------------------------------------------
    // Transient zero IGT reads (menu/reload repopulation window)
    // ------------------------------------------------------------------

    #[test]
    fn transient_zero_igt_during_reload_is_ignored() {
        // Live log 2026-07-30: GameDataMan's play_time reads 0 transiently
        // while a menu reload repopulates it. Treated as a real observation
        // it misread an ordinary quit-out as a 67s rollback (no penalty),
        // poisoned last_good_igt to 0, and made the real post-reload value
        // look like an impossible forward jump (false wrong-save freeze).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(67_444), true), true, None), now);
        m.tick(tick_in(snap(Some(0), false), true, None), now);
        m.tick(tick_in(snap(Some(66_852), false), true, None), now);
        assert!(!m.wrong_save, "transient 0 must not poison the reference");
        assert!(
            m.pending_quit_out,
            "the real 592ms regression is a quit-out"
        );

        let mut input = tick_in(snap(Some(66_900), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
    }

    #[test]
    fn transient_zero_igt_does_not_flush_buffers() {
        // Same transient while disconnected with a parked traversal: the 0
        // previously read as a 67s rollback and discarded the pending flag.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(67_000), true), false, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(67_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(67_200), false), false, None), later);
        let mut input = tick_in(snap(Some(67_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        m.tick(tick_in(snap(Some(0), false), false, None), later);
        m.tick(tick_in(snap(Some(66_500), false), false, None), later);
        assert!(
            m.flag_buffer.has_pending(),
            "transient 0 must not flush the parked traversal"
        );
        assert!(m.pending_quit_out, "the real regression still arms");
    }

    #[test]
    fn frozen_machine_ignores_injected_flag_reads() {
        // The shell withholds flag reads while frozen (wants_flag_reads),
        // but the pure machine must also defend its own invariant: flag
        // reads injected during a freeze produce no game writes and no
        // sends.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        let later = now + ms(150);
        let fx = m.tick(
            tick_in(snap(Some(7_200_100), true), true, Some(vec![(100, true)])),
            later,
        );
        assert!(
            fx.is_empty(),
            "frozen machine must ignore injected flag reads, got {fx:?}"
        );
        assert!(!m.flag_buffer.has_deferred());
    }

    #[test]
    fn transient_zero_igt_does_not_recover_a_freeze() {
        // With a small last_good the recovery window's low bound saturates
        // to 0: a transient 0 during a reload must not read as "race save
        // is back".
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        m.tick(tick_in(snap(Some(0), false), true, None), now);
        assert!(m.wrong_save, "transient 0 must not clear the freeze");
    }

    // ------------------------------------------------------------------
    // Deathless death banner
    // ------------------------------------------------------------------

    #[test]
    fn deathless_death_fires_banner_once() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        assert_eq!(m.get_status(now), None, "baseline tick must not banner");

        let t1 = now + secs(1);
        m.tick(tick_in(snap_deaths(Some(2000), 1), true, None), t1);
        assert_eq!(m.get_status(t1), Some("You died. Race over."));

        // Second death after the banner expired: latched, no new banner.
        let t2 = t1 + secs(10);
        m.tick(tick_in(snap_deaths(Some(3000), 2), true, None), t2);
        assert_eq!(m.get_status(t2), None);
    }

    #[test]
    fn deathless_banner_skipped_outside_conditions() {
        let now = Instant::now();

        // Not a deathless race.
        let mut m = running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);

        // Deathless but race still in setup.
        let mut m = deathless_machine("setup", now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);

        // Wrong-save guard active: frozen, no banner.
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.wrong_save = true;
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);
    }

    #[test]
    fn deathless_banner_skipped_when_already_finished() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running","deathless":true}"#)
                .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", "finished", 3)],
                phantom_skin: None,
                latest_mod_version: None,
            },
            now,
        );
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);
    }

    #[test]
    fn deathless_first_observation_is_baseline_not_death() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        // Mid-race mod restart: counter already at 5. Must not banner.
        m.tick(tick_in(snap_deaths(Some(1000), 5), true, None), now);
        assert_eq!(m.get_status(now), None);
        // The NEXT increase is a real death.
        m.tick(
            tick_in(snap_deaths(Some(2000), 6), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), Some("You died. Race over."));
    }

    #[test]
    fn race_start_resets_deathless_latch() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert!(m.deathless_banner_shown);
        m.handle_message(MachineMessage::RaceStart(0), now + secs(2));
        assert!(!m.deathless_banner_shown);
    }

    // ------------------------------------------------------------------
    // Server conditions (coded errors) and the waiting line
    // ------------------------------------------------------------------

    fn coded_error(message: &str, kind: ConditionKind) -> MachineMessage {
        MachineMessage::Error {
            message: message.to_string(),
            code: Some(kind),
        }
    }

    #[test]
    fn blocking_condition_displays_then_expires() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Wrong save loaded", ConditionKind::WrongSave),
            now,
        );

        assert_eq!(
            m.get_blocking_condition(now).map(|c| c.message.as_str()),
            Some("Wrong save loaded")
        );
        // Not a transient status: the coded path bypasses set_status.
        assert_eq!(m.get_status(now), None);
        assert_eq!(
            m.get_waiting_line(now),
            None,
            "a blocking condition must not double-render as the waiting line"
        );
        // Fresh again after a re-send, gone 3s after the last one.
        m.handle_message(
            coded_error("Wrong save loaded", ConditionKind::WrongSave),
            now + secs(2),
        );
        assert!(m.get_blocking_condition(now + secs(4)).is_some());
        assert!(m.get_blocking_condition(now + secs(6)).is_none());
    }

    #[test]
    fn waiting_condition_is_not_blocking() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Race not running", ConditionKind::RaceNotRunning),
            now,
        );
        assert!(m.get_blocking_condition(now).is_none());
        assert_eq!(m.get_waiting_line(now), Some("Race not running"));
        assert_eq!(m.get_waiting_line(now + secs(4)), None);
    }

    #[test]
    fn unknown_code_falls_back_to_transient_status() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Some future thing", ConditionKind::Unknown),
            now,
        );
        assert!(m.get_blocking_condition(now).is_none());
        assert_eq!(m.get_status(now), Some("Some future thing"));
    }

    #[test]
    fn waiting_line_derived_from_setup_even_offline() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        // In world, no server condition, disconnected: local derivation.
        m.tick(tick_in(snap(Some(1_000), true), false, None), now);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
        m.handle_message(MachineMessage::RaceStart(0), now);
        assert_eq!(m.get_waiting_line(now + secs(1)), None);
    }

    #[test]
    fn waiting_line_hidden_outside_the_world() {
        // Regression (live 2026-07-31): the derived setup line rendered at
        // the title screen, before any save was loaded. It must only show
        // while the player is actually in the world.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        assert_eq!(m.get_waiting_line(now), None, "title screen: no line");
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
        // Back out of the world (quit to menu): the line hides again.
        m.tick(tick_in(snap(None, false), true, None), now);
        assert_eq!(m.get_waiting_line(now), None, "menu: no line");
    }

    #[test]
    fn countdown_code_suppressed_while_local_countdown_active() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        m.handle_message(MachineMessage::RaceStart(10), now);
        assert!(m.is_countdown_active(now + secs(1)));
        m.handle_message(
            coded_error("Race countdown in progress", ConditionKind::Countdown),
            now + secs(1),
        );
        assert_eq!(m.get_waiting_line(now + secs(1)), None);
        // After the countdown, a fresh countdown condition would display
        // (desync case), pinned via a re-send past the countdown end.
        m.handle_message(
            coded_error("Race countdown in progress", ConditionKind::Countdown),
            now + secs(11),
        );
        assert_eq!(
            m.get_waiting_line(now + secs(11)),
            Some("Race countdown in progress")
        );
    }

    #[test]
    fn auth_error_flash_suppressed_when_permanent_error_shown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::PermanentError("Invalid mod token or race".to_string()),
            now,
        );
        m.handle_message(MachineMessage::StatusChanged(ConnectionStatus::Error), now);
        assert_eq!(
            m.get_status(now),
            None,
            "no gold flash under the red banner"
        );
    }

    #[test]
    fn setup_save_load_no_longer_flashes_transient_status() {
        // The old 3s "Race hasn't started yet" flash is replaced by the
        // persistent derived waiting line.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        assert_eq!(m.get_status(now), None);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
    }
}
