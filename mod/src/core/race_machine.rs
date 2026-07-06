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
    StartPhantomSkin {
        name: String,
    },
}
