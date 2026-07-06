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
    /// Captured grace entity id from the warp hook, if any.
    pub warp_capture: Option<u32>,
    /// `(flag_id, is_set)` for every flag in `flags_to_poll()`, omitting
    /// flags whose category could not be resolved. Only filled when the
    /// preceding `pre_tick` asked for `poll_flags`.
    pub flag_reads: Vec<(u32, bool)>,
    /// Weapons for the status_update, read by the shell only when
    /// `wants_status_update` said one may fire this frame.
    pub weapons: [Option<i32>; 2],
    /// Whether the flag reader diagnosed OK this poll (None = not polled).
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
}

impl RaceMachine {
    /// `seed_message_id`: initial value for the message-id counter (the shell
    /// seeds it from wall-clock millis so ids stay unique across sessions).
    pub fn new(seed_message_id: u64, config_seed_id: String, now: Instant) -> Self {
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

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    pub(crate) fn test_race(status: &str) -> RaceInfo {
        serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"Test Race","status":"{}"}}"#,
            status
        ))
        .unwrap()
    }

    pub(crate) fn test_seed(event_ids: &[u32], finish_event: Option<u32>) -> SeedInfo {
        let finish = finish_event
            .map(|f| f.to_string())
            .unwrap_or_else(|| "null".to_string());
        serde_json::from_str(&format!(
            r#"{{"total_layers": 3, "event_ids": {:?}, "finish_event": {}}}"#,
            event_ids, finish
        ))
        .unwrap()
    }

    pub(crate) fn auth_ok(status: &str, event_ids: &[u32], finish: Option<u32>) -> MachineMessage {
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed: test_seed(event_ids, finish),
            participants: Vec::new(),
            phantom_skin: None,
            latest_mod_version: None,
        }
    }

    #[test]
    fn test_race_start_sets_running_and_countdown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), now);
        let fx = m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        assert!(fx.is_empty());
        assert!(m.is_race_setup());

        let fx = m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(fx.is_empty());
        assert!(m.is_race_running());
        assert!(m.is_countdown_active(now));
        assert!(!m.is_countdown_active(now + Duration::from_secs(4)));
    }
}
