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

use crate::core::protocol::{ExitInfo, ParticipantInfo, RaceInfo, SeedInfo};
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
        status: String,
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
    },
    ZoneQueryAck {
        message_id: u64,
    },
    Error(String),
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
    },
    /// Write a flag value into game memory (the shell resolves the category
    /// first and skips the write when unresolvable, as today).
    SetGameFlag {
        flag_id: u32,
        value: bool,
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

use crate::core::flag_buffer::FlagBuffer;

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
    /// Zone update received, waiting for loading screen to end before revealing
    pub pending_zone_update: Option<ZoneUpdateData>,
    /// Snapshot of current_layer taken when leaderboard_update bumps the layer.
    pub pre_reveal_layer: Option<i32>,
    /// When the pending zone update was received (for defensive timeout)
    pub pending_zone_received_at: Option<Instant>,
    /// Whether position was readable last frame (loading screen exit detection)
    pub was_position_readable: bool,
    /// Seed mismatch: config seed_id doesn't match server seed_id
    pub seed_mismatch: bool,
    /// Last auth error message from server (see dll handler ordering guarantee)
    pub last_auth_error: Option<String>,
    /// Permanent error from server (persistent red banner, no auto-dismiss)
    pub permanent_error: Option<String>,
    /// IGT frozen when the race ends before the local player finishes
    pub frozen_igt_ms: Option<u32>,
    /// Last observed IGT, used to detect save reloads
    pub last_observed_igt: Option<u32>,
    /// Cached reads for the current frame (written by the shell each frame)
    pub frame_snapshot: FrameSnapshot,
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
            pre_reveal_layer: None,
            pending_zone_received_at: None,
            was_position_readable: true,
            seed_mismatch: false,
            last_auth_error: None,
            permanent_error: None,
            frozen_igt_ms: None,
            last_observed_igt: None,
            frame_snapshot: FrameSnapshot::default(),
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
    pub fn am_i_finished(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == "finished")
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
                        let msg = self
                            .last_auth_error
                            .take()
                            .unwrap_or_else(|| "Server maintenance".to_string());
                        self.set_status(msg, now);
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
                    race.status = "running".to_string();
                }
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
                self.last_received_debug = Some(format!("race_status_change({})", status));
                info!(status = %status, "[WS] Race status changed");
                // If race ends and we haven't finished, freeze our current game IGT.
                // The mod's local participant igt_ms is stale (only updated via
                // leaderboard_update on events, not on every status_update).
                // `current_igt` is a fresh read injected by the shell.
                if status == "finished" && !self.am_i_finished() {
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
                    status = %race.status,
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
            MachineMessage::Error(e) => {
                self.last_received_debug = Some(format!("error({})", e));
                warn!(error = %e, "[WS] Error");
                self.set_status(e, now);
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

/// Defensive timeout: if a zone update hasn't been revealed after this duration
/// (e.g., loading screen flag is unreadable), reveal anyway.
const ZONE_REVEAL_TIMEOUT: Duration = Duration::from_secs(15);

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
            poll_flags: !self.event_ids.is_empty()
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
        if self.event_ids.is_empty() {
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

        // Save reload detection: an IGT regression means the player loaded a
        // different save. Reset per-save event-flag state so a pre-set
        // finish_event from a stale save doesn't block the fresh save's real
        // finish (see EVENT_FLAG_TRACKING.md).
        if let Some(current_igt) = self.frame_snapshot.igt_ms {
            if crate::core::flag_buffer::detect_save_reload(self.last_observed_igt, current_igt) {
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

        let position_readable = self.frame_snapshot.position_readable;

        // Reveal pending zone update once the loading screen ends and the
        // player position is readable. The loading flag may clear before the
        // fade-in completes, so position_readable acts as an additional guard.
        // Defensive timeout ensures the zone is always revealed eventually.
        if self.pending_zone_update.is_some() {
            let timed_out = self
                .pending_zone_received_at
                .is_some_and(|t| now.duration_since(t) >= ZONE_REVEAL_TIMEOUT);
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

        // Flags cleared (captured) earlier in this tick: later read consumers
        // must treat them as unset, mirroring the pre-machine behavior where
        // each stage re-read memory after the previous stage's clears.
        let mut cleared: HashSet<u32> = HashSet::new();

        // Loading screen exit: send deferred event_flags (certain) or zone_query (probabilistic)
        if position_readable && !self.was_position_readable {
            // Force one immediate flag scan to catch flags set during loading
            // (e.g. Erdtree burn, Maliketh warp) that the 10Hz poll couldn't read
            // because is_flag_set() returns None while position is unreadable.
            if !self.event_ids.is_empty() {
                let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
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
                    let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
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

            // Remind the player when they load a save (or start a new game)
            // before the race has begun. Auto-dismisses after 3s.
            if self.is_race_setup() {
                self.set_status("Race hasn't started yet".to_string(), now);
            }
        }
        self.was_position_readable = position_readable;

        // Event flag polling runs ALWAYS (even when disconnected).
        // Regular flags are cleared after capture (for re-traversal detection) and
        // deferred until loading exit; finish_event is sent immediately.
        let poll_due = !self.event_ids.is_empty()
            && now.duration_since(self.last_flag_poll) >= Duration::from_millis(100);
        if poll_due {
            if let Some(ref reads) = input.flag_reads {
                self.last_flag_poll = now;
                if let Some(ok) = input.flag_reader_ok {
                    self.last_flag_reader_ok = Some(ok);
                }

                let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
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
        if self.wants_status_update(now, igt_ms) {
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
            },
        );
        Effect::SendZoneQuery {
            igt_ms,
            message_id,
            grace_entity_id,
            map_id,
            position,
            play_region_id,
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

    fn snap(igt: Option<u32>, pos: bool, loading: Option<bool>) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(0),
            position_readable: pos,
            loading_screen: loading,
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
                snap(Some(1000), true, None),
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
        m.tick(tick_in(snap(Some(1200), false, None), true, None), t2);
        let t3 = t2 + ms(30);
        let fx = m.tick(
            tick_in(
                snap(Some(1300), true, None),
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
                snap(Some(1500), true, None),
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
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );

        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true, None),
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
                snap(Some(1000), true, None),
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
            tick_in(snap(Some(20_000), true, None), true, Some(vec![])),
            now + secs(12),
        );
        assert_eq!(sent_flags(&fx), vec![900]);
    }

    #[test]
    fn test_park_and_replay_on_reconnect_with_requeue() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );

        // Defer a regular flag, then lose the connection: parked to pending.
        m.tick(
            tick_in(
                snap(Some(1000), true, None),
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
            tick_in(snap(Some(2000), true, None), true, Some(vec![])),
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
            tick_in(snap(Some(3000), true, None), true, Some(vec![])),
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
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );

        // Capture a finish flag and defer a regular one.
        m.tick(
            tick_in(
                snap(Some(50_000), true, None),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // IGT regression = save reload: per-save state cleared, no sends.
        let fx = m.tick(
            tick_in(snap(Some(1_000), true, None), true, None),
            now + ms(200),
        );
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

        // Still loading: not revealed.
        m.tick(
            tick_in(snap(Some(1000), false, Some(true)), true, None),
            now + ms(200),
        );
        assert!(m.race_state.current_zone.is_none());

        // Loading done + position readable: revealed.
        m.tick(
            tick_in(snap(Some(1200), true, Some(false)), true, Some(vec![])),
            now + ms(300),
        );
        let zone = m.race_state.current_zone.as_ref().expect("revealed");
        assert_eq!(zone.display_name, "Stormveil");
        assert!(m.pending_zone_update.is_none());
        assert!(m.pending_zone_received_at.is_none());
    }

    #[test]
    fn test_zone_reveal_defensive_timeout() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Leyndell", None), now);

        // 14s in, still loading: not revealed.
        m.tick(
            tick_in(snap(Some(1000), false, Some(true)), true, None),
            now + secs(14),
        );
        assert!(m.race_state.current_zone.is_none());

        // 16s in, still loading: revealed anyway (defensive timeout).
        m.tick(
            tick_in(snap(Some(1000), false, Some(true)), true, None),
            now + secs(16),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Leyndell"
        );
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

        // Reveal clears the freeze.
        m.tick(
            tick_in(snap(Some(1200), true, Some(false)), true, Some(vec![])),
            now + ms(300),
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
                status: "finished".to_string(),
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
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );
        m.handle_message(MachineMessage::RaceStart(10), now + ms(20));

        // Defer a flag during countdown.
        m.tick(
            tick_in(
                snap(Some(1000), true, None),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // Loading exit during countdown: nothing sent, deferred parked.
        m.tick(
            tick_in(snap(Some(1100), false, None), true, None),
            now + ms(200),
        );
        let fx = m.tick(
            tick_in(snap(Some(1200), true, None), true, Some(vec![])),
            now + ms(250),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(!m.flag_buffer.has_deferred(), "parked to pending");
    }

    #[test]
    fn test_ack_idempotence() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );

        // Unknown ack: no state change, no panic.
        let fx = m.handle_message(MachineMessage::EventFlagAck { message_id: 999 }, now);
        assert!(fx.is_empty());

        // Send a finish flag, then ack it: removed from in-flight.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true, None),
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
        m.tick(
            tick_in(snap(Some(500), true, None), true, None),
            now + ms(10),
        );

        let has_status = |fx: &[Effect]| {
            fx.iter()
                .any(|e| matches!(e, Effect::SendStatusUpdate { .. }))
        };

        // 1.2s after birth: fires.
        let fx = m.tick(
            tick_in(snap(Some(5000), true, None), true, None),
            now + ms(1200),
        );
        assert!(has_status(&fx));

        // 200ms later: throttled.
        let fx = m.tick(
            tick_in(snap(Some(5200), true, None), true, None),
            now + ms(1400),
        );
        assert!(!has_status(&fx));

        // Another second later: fires again.
        let fx = m.tick(
            tick_in(snap(Some(6300), true, None), true, None),
            now + ms(2400),
        );
        assert!(has_status(&fx));

        // IGT 0 (quit-out): skipped.
        let fx = m.tick(
            tick_in(snap(Some(0), true, None), true, None),
            now + ms(3600),
        );
        assert!(!has_status(&fx));

        // Once I am finished: skipped.
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "finished", 3)],
                leader_splits: None,
            },
            now + ms(3700),
        );
        let fx = m.tick(
            tick_in(snap(Some(9000), true, None), true, None),
            now + ms(4800),
        );
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
}
