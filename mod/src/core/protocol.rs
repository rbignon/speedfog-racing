//! WebSocket protocol types for SpeedFog Racing
//!
//! Messages exchanged between the mod and the racing server.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Wire-protocol version, independent from the crate release version.
/// Bump rules: breaking change -> major + 1 (minor resets to 0);
/// backward-compatible addition worth signalling -> minor + 1; otherwise
/// unchanged. Keep in sync with PROTOCOL_VERSION in
/// server/speedfog_racing/websocket/schemas.py and docs/PROTOCOL.md.
pub const PROTOCOL_VERSION: &str = "1.2";

// =============================================================================
// CLIENT -> SERVER MESSAGES
// =============================================================================

/// Messages sent from mod to server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Authentication with mod token
    Auth {
        mod_token: String,
        /// Wire-protocol version spoken by this build ("major.minor").
        protocol_version: String,
        /// Crate release version, for server logs and admin display only.
        mod_version: String,
    },
    /// Player is ready to race
    Ready,
    /// Periodic status update.
    ///
    /// `weapons` is `[left_hand, right_hand]` raw EquipParamWeapon runtime IDs
    /// (row + upgrade level). Per slot, `None` means empty hand, two-handed mask,
    /// loading screen, or unreadable memory.
    StatusUpdate {
        igt_ms: u32,
        death_count: u32,
        weapons: [Option<i32>; 2],
    },
    /// EMEVD event flag triggered (fog gate traversal or boss kill)
    EventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    /// Zone query at loading screen exit (server resolves to graph node)
    ZoneQuery {
        igt_ms: u32,
        message_id: u64,
        #[serde(skip_serializing_if = "Option::is_none")]
        grace_entity_id: Option<u32>,
        #[serde(skip_serializing_if = "Option::is_none")]
        map_id: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        position: Option<[f32; 3]>,
        #[serde(skip_serializing_if = "Option::is_none")]
        play_region_id: Option<u32>,
        /// True when this query follows a detected quit-out (reload in
        /// place): the server resumes the current zone instead of guessing.
        #[serde(default, skip_serializing_if = "is_false")]
        quit_out: bool,
    },
    /// Heartbeat response
    Pong,
}

// =============================================================================
// SERVER -> CLIENT MESSAGES
// =============================================================================

/// Visual customization payload for the participant's username on the in-game
/// leaderboard. Only color/gradient is delivered to the mod; backgrounds are
/// web-only.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NameTemplate {
    #[serde(default)]
    pub color: Option<String>,
    #[serde(default)]
    pub gradient: Option<(String, String)>,
}

/// Race lifecycle status. Wire format: lowercase strings, identical to the
/// previous stringly-typed field. `Unknown` preserves the additive protocol
/// convention: a status this build doesn't know deserializes instead of
/// failing, and is treated as "no known state matches" everywhere.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RaceStatus {
    Setup,
    Running,
    Finished,
    #[serde(other)]
    Unknown,
}

impl RaceStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            RaceStatus::Setup => "setup",
            RaceStatus::Running => "running",
            RaceStatus::Finished => "finished",
            RaceStatus::Unknown => "unknown",
        }
    }
}

/// Participant lifecycle status. Same wire/forward-compat contract as
/// [`RaceStatus`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ParticipantStatus {
    Registered,
    Ready,
    Playing,
    Finished,
    Abandoned,
    #[serde(other)]
    Unknown,
}

impl ParticipantStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            ParticipantStatus::Registered => "registered",
            ParticipantStatus::Ready => "ready",
            ParticipantStatus::Playing => "playing",
            ParticipantStatus::Finished => "finished",
            ParticipantStatus::Abandoned => "abandoned",
            ParticipantStatus::Unknown => "unknown",
        }
    }
}

/// Participant info in leaderboard
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantInfo {
    pub id: String,
    pub twitch_username: String,
    pub twitch_display_name: Option<String>,
    pub status: ParticipantStatus,
    pub current_zone: Option<String>,
    pub current_layer: i32,
    #[serde(default)]
    pub current_layer_tier: Option<i32>,
    pub igt_ms: i32,
    pub death_count: i32,
    #[serde(default)]
    pub gap_ms: Option<i32>,
    #[serde(default)]
    pub layer_entry_igt: Option<i32>,
    #[serde(default)]
    pub name_template: Option<NameTemplate>,
}

/// Race info from server.
///
/// Carries every race-level field the server may push at any time. Only the
/// fields the mod actually uses are read by the UI today (status, race_ends_at,
/// countdown_seconds); the rest are kept on the struct so a single payload
/// shape covers `auth_ok`, `race_state` and `race_info_update` and so the
/// protocol stays symmetrical with the spectator client.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RaceInfo {
    pub id: String,
    pub name: String,
    pub status: RaceStatus,
    #[serde(default)]
    pub is_public: bool,
    #[serde(default)]
    pub open_registration: bool,
    #[serde(default)]
    pub max_participants: Option<i32>,
    #[serde(default)]
    pub scheduled_at: Option<String>,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub seeds_released_at: Option<String>,
    #[serde(default)]
    pub registration_closes_at: Option<String>,
    #[serde(default)]
    pub race_ends_at: Option<String>,
    #[serde(default)]
    pub private_dag: bool,
    #[serde(default)]
    pub countdown_seconds: u32,
    /// Current seed id of the race. Lets the mod detect that its loaded seed
    /// pack went stale (e.g. after a reroll) outside the `auth_ok` handshake,
    /// by comparing it against the configured pack's seed id.
    #[serde(default)]
    pub seed_id: Option<String>,
    /// IGT penalty (ms) the mod applies per detected quit-out; 0 disables.
    /// Defaults so a server predating the field keeps the feature active.
    #[serde(default = "default_quit_out_penalty_ms")]
    pub quit_out_penalty_ms: u32,
    /// Pre-parsed `race_ends_at` filled by [`RaceInfo::reparse_dates`] after
    /// receipt so the per-frame countdown UI doesn't reparse the string.
    /// Not part of the wire format.
    ///
    /// Call sites that store a freshly deserialized `RaceInfo` MUST call
    /// [`RaceInfo::reparse_dates`] first; otherwise this stays `None` and the
    /// countdown silently doesn't render. Also note that this field
    /// participates in the derived `PartialEq`, so two structurally identical
    /// payloads compare unequal if only one has been reparsed.
    #[serde(skip)]
    pub race_ends_at_dt: Option<DateTime<Utc>>,
}

impl RaceInfo {
    /// Populate non-serde cached fields from their RFC3339 string counterparts.
    /// Call after deserializing or replacing a `RaceInfo` so render code can
    /// read the parsed `DateTime` directly.
    pub fn reparse_dates(&mut self) {
        self.race_ends_at_dt = self
            .race_ends_at
            .as_deref()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .map(|dt| dt.with_timezone(&Utc));
    }
}

/// Item to be spawned at runtime by the mod (e.g., Gem/Ash of War).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SpawnItem {
    pub id: u32,
    #[serde(default = "default_qty")]
    pub qty: u32,
}

fn default_qty() -> u32 {
    1
}

fn is_false(v: &bool) -> bool {
    !*v
}

fn default_quit_out_penalty_ms() -> u32 {
    2000
}

/// Mod-side directives for a phantom skin.
///
/// V1 ships only `speffects`. New keys (e.g. `fxr_ids`) added in future
/// versions are no-ops on older mods, and missing keys default to empty so
/// older seeds without those keys stay compatible.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct PhantomSkin {
    #[serde(default)]
    pub speffects: Vec<i32>,
}

/// Seed info from server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SeedInfo {
    pub total_layers: i32,
    #[serde(default)]
    pub event_ids: Vec<u32>,
    /// Flag ID for the final boss kill, sent immediately (no loading screen).
    #[serde(default)]
    pub finish_event: Option<u32>,
    #[serde(default)]
    pub spawn_items: Vec<SpawnItem>,
    /// Seed ID, compared against config to detect stale seed packs after re-roll
    #[serde(default)]
    pub seed_id: Option<String>,
    /// Death marker event flags per cluster: [flag_low, flag_med, flag_high]
    #[serde(default)]
    pub death_flags: HashMap<String, [u32; 3]>,
    /// Event flag for persistent re-spawn prevention (saved range).
    /// When None (old server), only in-process guard prevents double-spawn.
    #[serde(default)]
    pub items_spawned_flag: Option<u32>,
    /// Per-seed map of skin name -> directives. The mod looks up the equipped
    /// skin name (received in auth_ok.phantom_skin) here to resolve it to
    /// concrete SpEffect IDs etc.
    #[serde(default)]
    pub phantom_skins: HashMap<String, PhantomSkin>,
}

/// Exit info in zone_update message
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExitInfo {
    pub text: String,
    pub to_name: String,
    pub discovered: bool,
}

/// Messages received from server
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Authentication successful
    AuthOk {
        participant_id: String,
        // Boxed to keep `ServerMessage` small: `RaceInfo` dwarfs every other
        // variant, so an inline copy would bloat all of them (large_enum_variant).
        race: Box<RaceInfo>,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
        #[serde(default)]
        phantom_skin: Option<String>,
        /// Server release version, present only when a newer compatible mod
        /// build exists (protocol minor ahead). Absent from old servers.
        #[serde(default)]
        latest_mod_version: Option<String>,
    },
    /// Authentication failed
    AuthError { message: String },
    /// Race has started (with optional countdown)
    RaceStart {
        #[serde(default)]
        countdown_seconds: u32,
    },
    /// Leaderboard update
    LeaderboardUpdate {
        participants: Vec<ParticipantInfo>,
        #[serde(default)]
        leader_splits: Option<HashMap<String, i32>>,
    },
    /// Race status changed
    RaceStatusChange { status: RaceStatus },
    /// Race-level info changed (race_ends_at extension, etc.) and the cached
    /// RaceInfo on the client must be replaced wholesale with this snapshot.
    RaceInfoUpdate { race: Box<RaceInfo> },
    /// Single player update
    PlayerUpdate { player: ParticipantInfo },
    /// Zone update (unicast to originating mod)
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        #[serde(default)]
        original_tier: Option<i32>,
        #[serde(default)]
        layer: Option<i32>,
        #[serde(default)]
        is_first_visit: bool,
        #[serde(default)]
        exits: Vec<ExitInfo>,
        #[serde(default)]
        message_id: Option<u64>,
    },
    /// Acknowledges persistence of an event_flag message.
    EventFlagAck { message_id: u64 },
    /// Acknowledges a zone_query that could not produce a zone_update
    /// (unresolved, wrong state, etc.) so the mod can clear in-flight tracking.
    ZoneQueryAck { message_id: u64 },
    /// Aggregated death counts per zone (for conditional death markers)
    DeathCounts { counts: HashMap<String, u32> },
    /// Heartbeat ping
    Ping,
    /// Generic error from server (e.g., race not running). `code` is the
    /// machine-readable condition tag (None on plain errors and old servers).
    Error {
        message: String,
        #[serde(default)]
        code: Option<String>,
    },
    /// Daily-streak update, unicast by the server to a user's connections
    /// after a daily run. The in-game mod has no use for it; it is modeled
    /// here only so the message deserializes cleanly and is dropped by the
    /// catch-all match arm, instead of tripping the parse-failure warning.
    /// The payload (current/best/freeze_count/...) is intentionally ignored.
    DailyStreakUpdate {},
}

// =============================================================================
// HELPERS
// =============================================================================

/// Returns true if the WebSocket close code represents a permanent error
/// that should not trigger reconnection (application-level rejection).
pub fn is_permanent_close(code: u16) -> bool {
    code >= 4000
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_auth_serialize() {
        let msg = ClientMessage::Auth {
            mod_token: "test123".to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            mod_version: env!("CARGO_PKG_VERSION").to_string(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"auth""#));
        assert!(json.contains(r#""mod_token":"test123""#));
        assert!(json.contains(r#""protocol_version":"1.2""#));
        assert!(json.contains(&format!(r#""mod_version":"{}""#, env!("CARGO_PKG_VERSION"))));
    }

    #[test]
    fn test_client_status_update_serialize() {
        let msg = ClientMessage::StatusUpdate {
            igt_ms: 123456,
            death_count: 5,
            weapons: [Some(2000025), None],
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"status_update""#));
        assert!(json.contains(r#""igt_ms":123456"#));
        assert!(json.contains(r#""death_count":5"#));
        assert!(json.contains(r#""weapons":[2000025,null]"#));
        // Should NOT contain current_zone or current_layer
        assert!(!json.contains("current_zone"));
        assert!(!json.contains("current_layer"));
    }

    #[test]
    fn test_client_event_flag_serialize() {
        let msg = ClientMessage::EventFlag {
            flag_id: 9000042,
            igt_ms: 60000,
            message_id: 42,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"event_flag""#));
        assert!(json.contains(r#""flag_id":9000042"#));
        assert!(json.contains(r#""igt_ms":60000"#));
        assert!(json.contains(r#""message_id":42"#));
    }

    #[test]
    fn test_server_event_flag_ack_deserialize() {
        let json = r#"{"type":"event_flag_ack","message_id":99}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::EventFlagAck { message_id } => assert_eq!(message_id, 99),
            _ => panic!("Expected EventFlagAck"),
        }
    }

    #[test]
    fn test_server_auth_ok_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk {
                participant_id,
                race,
                seed,
                ..
            } => {
                assert_eq!(participant_id, "abc-123");
                assert_eq!(race.name, "Test Race");
                assert_eq!(seed.total_layers, 5);
                // event_ids defaults to empty vec when absent
                assert!(seed.event_ids.is_empty());
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_auth_ok_latest_mod_version() {
        // New server pushing an update notice.
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "latest_mod_version": "1.18.0"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk {
                latest_mod_version, ..
            } => assert_eq!(latest_mod_version.as_deref(), Some("1.18.0")),
            _ => panic!("Expected AuthOk"),
        }

        // Old server: field absent, defaults to None.
        let json_old = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json_old).unwrap();
        match msg {
            ServerMessage::AuthOk {
                latest_mod_version, ..
            } => assert!(latest_mod_version.is_none()),
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_auth_ok_with_event_ids_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "def-456",
            "race": {"id": "456", "name": "Flag Race", "status": "running"},
            "seed": {"total_layers": 3, "event_ids": [9000001, 9000042, 9000100]},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.event_ids, vec![9000001, 9000042, 9000100]);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_seed_info_without_event_ids() {
        // Backward compat: old server sends no event_ids field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.total_layers, 5);
        assert!(seed.event_ids.is_empty());
    }

    #[test]
    fn test_server_race_start_deserialize() {
        // Backward compat: no countdown_seconds field → defaults to 0
        let json = r#"{"type": "race_start"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceStart { countdown_seconds } => {
                assert_eq!(countdown_seconds, 0);
            }
            _ => panic!("Expected RaceStart"),
        }
    }

    #[test]
    fn test_server_race_start_with_countdown() {
        let json = r#"{"type": "race_start", "countdown_seconds": 10}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceStart { countdown_seconds } => {
                assert_eq!(countdown_seconds, 10);
            }
            _ => panic!("Expected RaceStart"),
        }
    }

    #[test]
    fn test_server_leaderboard_update_deserialize() {
        let json = r#"{
            "type": "leaderboard_update",
            "participants": [{
                "id": "1",
                "twitch_username": "player1",
                "twitch_display_name": "Player One",
                "status": "playing",
                "current_zone": "Limgrave",
                "current_layer": 2,
                "current_layer_tier": 3,
                "igt_ms": 60000,
                "death_count": 1
            }]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                assert_eq!(participants.len(), 1);
                assert_eq!(participants[0].twitch_username, "player1");
                assert_eq!(participants[0].current_layer_tier, Some(3));
                assert_eq!(leader_splits, None);
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_server_ping_deserialize() {
        let json = r#"{"type": "ping"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(msg, ServerMessage::Ping));
    }

    #[test]
    fn test_client_pong_serialize() {
        let msg = ClientMessage::Pong;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"pong"}"#);
    }

    #[test]
    fn test_server_zone_update_deserialize() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "graveyard_cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": [
                { "text": "Soldier of Godrick front", "to_name": "Road's End Catacombs", "discovered": false },
                { "text": "Stranded Graveyard first door", "to_name": "Ruin-Strewn Precipice", "discovered": true }
            ]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                node_id,
                display_name,
                tier,
                original_tier,
                layer,
                is_first_visit,
                exits,
                message_id,
            } => {
                assert_eq!(node_id, "graveyard_cave_e235");
                assert_eq!(display_name, "Cave of Knowledge");
                assert_eq!(tier, Some(5));
                assert_eq!(original_tier, None);
                assert_eq!(layer, None);
                assert!(!is_first_visit);
                assert_eq!(exits.len(), 2);
                assert_eq!(exits[0].text, "Soldier of Godrick front");
                assert_eq!(exits[0].to_name, "Road's End Catacombs");
                assert!(!exits[0].discovered);
                assert!(exits[1].discovered);
                assert_eq!(message_id, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_first_visit() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_node",
            "display_name": "Some Cave",
            "tier": 3,
            "is_first_visit": true,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                is_first_visit,
                exits,
                ..
            } => {
                assert!(is_first_visit);
                assert!(exits.is_empty());
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_no_tier() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "start_node",
            "display_name": "Chapel of Anticipation",
            "tier": null,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { tier, exits, .. } => {
                assert_eq!(tier, None);
                assert!(exits.is_empty());
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_seed_info_with_spawn_items() {
        let json = r#"{"total_layers": 5, "event_ids": [100], "spawn_items": [{"id": 10500, "qty": 1}, {"id": 16300}]}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.spawn_items.len(), 2);
        assert_eq!(seed.spawn_items[0].id, 10500);
        assert_eq!(seed.spawn_items[0].qty, 1);
        assert_eq!(seed.spawn_items[1].id, 16300);
        assert_eq!(seed.spawn_items[1].qty, 1); // default
    }

    #[test]
    fn test_seed_info_without_spawn_items() {
        // Backward compat: old server sends no spawn_items field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.spawn_items.is_empty());
    }

    #[test]
    fn test_auth_ok_with_spawn_items() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5, "spawn_items": [{"id": 42, "qty": 2}]},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.spawn_items.len(), 1);
                assert_eq!(seed.spawn_items[0].id, 42);
                assert_eq!(seed.spawn_items[0].qty, 2);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_error_deserialize() {
        // Old server: no code field (wire contract pin).
        let json = r#"{"type": "error", "message": "Race not running"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { message, code } => {
                assert_eq!(message, "Race not running");
                assert_eq!(code, None);
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_server_error_deserialize_with_code() {
        let json = r#"{"type": "error", "message": "Wrong save loaded", "code": "wrong_save"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { code, .. } => {
                assert_eq!(code.as_deref(), Some("wrong_save"));
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_seed_info_with_seed_id() {
        let json = r#"{"total_layers": 5, "seed_id": "abc-123"}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.seed_id, Some("abc-123".to_string()));
    }

    #[test]
    fn test_seed_info_without_seed_id() {
        // Backward compat: old server sends no seed_id field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.seed_id, None);
    }

    #[test]
    fn test_seed_info_with_finish_event() {
        let json = r#"{"total_layers":5,"event_ids":[100,101],"finish_event":102}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.finish_event, Some(102));
    }

    #[test]
    fn test_seed_info_without_finish_event() {
        let json = r#"{"total_layers":5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.finish_event, None);
    }

    #[test]
    fn test_race_info_countdown_seconds_default() {
        // Backward compat: old server sends no countdown_seconds
        let json = r#"{"id": "123", "name": "Test", "status": "running"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.countdown_seconds, 0);
        assert_eq!(info.race_ends_at, None);
    }

    #[test]
    fn test_race_info_with_countdown_seconds() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "countdown_seconds": 10}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.countdown_seconds, 10);
    }

    #[test]
    fn test_race_info_with_seed_id() {
        // seed_id rides on race_info so the mod can spot a stale loaded pack
        // (e.g. after a reroll) outside the auth_ok handshake.
        let json = r#"{"id": "123", "name": "Test", "status": "running", "seed_id": "seed-xyz"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.seed_id.as_deref(), Some("seed-xyz"));
    }

    #[test]
    fn test_race_info_with_race_ends_at() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "race_ends_at": "2026-04-20T12:00:00Z"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.race_ends_at.as_deref(), Some("2026-04-20T12:00:00Z"));
        // Cached parsed field is empty until reparse_dates() is called.
        assert!(info.race_ends_at_dt.is_none());
    }

    #[test]
    fn test_race_info_reparse_dates_populates_cache() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "race_ends_at": "2026-04-20T12:00:00Z"}"#;
        let mut info: RaceInfo = serde_json::from_str(json).unwrap();
        info.reparse_dates();
        let dt = info.race_ends_at_dt.expect("race_ends_at_dt populated");
        assert_eq!(dt.to_rfc3339(), "2026-04-20T12:00:00+00:00");
    }

    #[test]
    fn test_race_info_reparse_dates_handles_missing_and_invalid() {
        // Missing field: cache stays None.
        let mut info: RaceInfo =
            serde_json::from_str(r#"{"id": "123", "name": "Test", "status": "setup"}"#).unwrap();
        info.reparse_dates();
        assert!(info.race_ends_at_dt.is_none());

        // Garbage value: parse fails silently, cache stays None.
        let mut info: RaceInfo = serde_json::from_str(
            r#"{"id": "123", "name": "Test", "status": "setup", "race_ends_at": "not-a-date"}"#,
        )
        .unwrap();
        info.reparse_dates();
        assert!(info.race_ends_at_dt.is_none());
    }

    #[test]
    fn test_race_info_update_deserialize() {
        let json = r#"{
            "type": "race_info_update",
            "race": {
                "id": "123",
                "name": "Test",
                "status": "running",
                "race_ends_at": "2026-04-21T15:00:00Z"
            }
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceInfoUpdate { race } => {
                assert_eq!(race.race_ends_at.as_deref(), Some("2026-04-21T15:00:00Z"));
                assert_eq!(race.status, RaceStatus::Running);
            }
            _ => panic!("Expected RaceInfoUpdate"),
        }
    }

    #[test]
    fn test_server_daily_streak_update_deserialize_ignores_payload() {
        // The mod does not consume daily_streak_update, but it must still
        // deserialize (otherwise it trips the "failed to parse" warning on
        // every broadcast) and drop the payload fields.
        let json = r#"{
            "type": "daily_streak_update",
            "current": 7,
            "best": 12,
            "freeze_count": 2,
            "freeze_consumed_for": "2026-06-06"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg, ServerMessage::DailyStreakUpdate {});
    }

    #[test]
    fn test_auth_ok_with_seed_id() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5, "seed_id": "seed-xyz"},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.seed_id, Some("seed-xyz".to_string()));
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_client_zone_query_grace_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 60000,
            message_id: 42,
            grace_entity_id: Some(10002950),
            map_id: None,
            position: None,
            play_region_id: None,
            quit_out: false,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":60000"#));
        assert!(json.contains(r#""message_id":42"#));
        assert!(json.contains(r#""grace_entity_id":10002950"#));
        assert!(!json.contains("map_id"));
    }

    #[test]
    fn test_client_zone_query_map_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 120000,
            message_id: 99,
            grace_entity_id: None,
            map_id: Some("m10_00_00_00".into()),
            position: Some([100.0, 50.0, 200.0]),
            play_region_id: Some(12345),
            quit_out: false,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":120000"#));
        assert!(json.contains(r#""message_id":99"#));
        assert!(json.contains(r#""map_id":"m10_00_00_00""#));
        assert!(!json.contains("grace_entity_id"));
    }

    #[test]
    fn test_client_zone_query_quit_out_serialization() {
        let mut msg = ClientMessage::ZoneQuery {
            igt_ms: 1000,
            message_id: 7,
            grace_entity_id: None,
            map_id: Some("m10_00_00_00".to_string()),
            position: Some([1.0, 2.0, 3.0]),
            play_region_id: None,
            quit_out: true,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""quit_out":true"#));

        // False is omitted from the wire (old servers never see the field).
        if let ClientMessage::ZoneQuery { quit_out, .. } = &mut msg {
            *quit_out = false;
        }
        let json = serde_json::to_string(&msg).unwrap();
        assert!(!json.contains("quit_out"));
    }

    #[test]
    fn test_race_info_old_server_defaults_quit_out_penalty() {
        // Wire-contract pin: a server that predates the field yields the
        // mod-side default of 2000 ms.
        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running"}"#).unwrap();
        assert_eq!(race.quit_out_penalty_ms, 2000);

        let race: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":0}"#,
        )
        .unwrap();
        assert_eq!(race.quit_out_penalty_ms, 0);
    }

    #[test]
    fn test_server_zone_update_with_original_tier() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 2,
            "original_tier": 8,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                tier,
                original_tier,
                ..
            } => {
                assert_eq!(tier, Some(2));
                assert_eq!(original_tier, Some(8));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_with_layer() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "layer": 2,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { layer, .. } => {
                assert_eq!(layer, Some(2));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_layer() {
        // Backward compat: old server sends no layer field
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { layer, .. } => {
                assert_eq!(layer, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_original_tier() {
        // Backward compat: old server sends no original_tier field
        let json = r#"{
            "type": "zone_update",
            "node_id": "start_node",
            "display_name": "Chapel of Anticipation",
            "tier": null,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                tier,
                original_tier,
                ..
            } => {
                assert_eq!(tier, None);
                assert_eq!(original_tier, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_participant_info_tier_defaults_none() {
        // Backward compat: old server sends no current_layer_tier field
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.current_layer_tier, None);
        // gap_ms also defaults to None when absent
        assert_eq!(p.gap_ms, None);
    }

    #[test]
    fn test_participant_info_with_gap_ms() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 2,
            "igt_ms": 90000,
            "death_count": 1,
            "gap_ms": 15000
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.gap_ms, Some(15000));
    }

    #[test]
    fn test_participant_info_gap_ms_null() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "gap_ms": null
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.gap_ms, None);
    }

    #[test]
    fn test_leaderboard_update_with_leader_splits() {
        let json = r#"{
            "type": "leaderboard_update",
            "participants": [],
            "leader_splits": {"0": 0, "1": 30000, "2": 75000}
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                assert!(participants.is_empty());
                let splits = leader_splits.unwrap();
                assert_eq!(splits.get("0"), Some(&0));
                assert_eq!(splits.get("1"), Some(&30000));
                assert_eq!(splits.get("2"), Some(&75000));
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_leaderboard_update_without_leader_splits() {
        // Backward compat: old server sends no leader_splits
        let json = r#"{
            "type": "leaderboard_update",
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate { leader_splits, .. } => {
                assert_eq!(leader_splits, None);
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_participant_info_with_layer_entry_igt() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 2,
            "igt_ms": 90000,
            "death_count": 1,
            "gap_ms": 15000,
            "layer_entry_igt": 80000
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.layer_entry_igt, Some(80000));
    }

    #[test]
    fn test_server_death_counts_deserialize() {
        let json = r#"{
            "type": "death_counts",
            "counts": {"node_a": 4, "node_b": 1}
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::DeathCounts { counts } => {
                assert_eq!(counts.get("node_a"), Some(&4));
                assert_eq!(counts.get("node_b"), Some(&1));
                assert_eq!(counts.len(), 2);
            }
            _ => panic!("Expected DeathCounts"),
        }
    }

    #[test]
    fn test_seed_info_with_death_flags() {
        let json = r#"{
            "total_layers": 5,
            "death_flags": {
                "node_a": [1040292500, 1040292501, 1040292502]
            }
        }"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        let flags = seed.death_flags.get("node_a").unwrap();
        assert_eq!(*flags, [1040292500, 1040292501, 1040292502]);
    }

    #[test]
    fn test_seed_info_without_death_flags() {
        // Backward compat: old server sends no death_flags field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.death_flags.is_empty());
    }

    #[test]
    fn test_seed_info_with_items_spawned_flag() {
        let json = r#"{"total_layers": 5, "event_ids": [100], "items_spawned_flag": 1050290000}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.items_spawned_flag, Some(1050290000));
    }

    #[test]
    fn test_seed_info_without_items_spawned_flag() {
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.items_spawned_flag, None);
    }

    #[test]
    fn test_server_zone_update_with_message_id() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": [],
            "message_id": 42
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, Some(42));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_message_id() {
        // Backward compat: old server sends no message_id field
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_query_ack_deserialize() {
        let json = r#"{"type":"zone_query_ack","message_id":55}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneQueryAck { message_id } => assert_eq!(message_id, 55),
            _ => panic!("Expected ZoneQueryAck"),
        }
    }

    #[test]
    fn test_participant_info_with_name_template_solid() {
        let json = r##"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "name_template": { "color": "#FFFFFF", "gradient": null }
        }"##;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        let nt = info.name_template.expect("name_template present");
        assert_eq!(nt.color.as_deref(), Some("#FFFFFF"));
        assert!(nt.gradient.is_none());
    }

    #[test]
    fn test_participant_info_with_name_template_gradient() {
        let json = r##"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "name_template": { "color": null, "gradient": ["#FFD700","#FFA500"] }
        }"##;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        let nt = info.name_template.unwrap();
        let g = nt.gradient.unwrap();
        assert_eq!(g, ("#FFD700".to_string(), "#FFA500".to_string()));
    }

    #[test]
    fn test_participant_info_without_name_template() {
        let json = r#"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0
        }"#;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert!(info.name_template.is_none());
    }

    #[test]
    fn test_auth_ok_with_phantom_skin() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "phantom_skin": "gold-aura"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, Some("gold-aura".to_string()));
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_without_phantom_skin_field() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, None);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_with_phantom_skin_null() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "phantom_skin": null
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, None);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_seed_info_with_phantom_skins() {
        let json = r#"{
            "total_layers": 5,
            "phantom_skins": {
                "gold-aura": {"speffects": [1450700]},
                "silver-aura": {"speffects": [1450705]}
            }
        }"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.phantom_skins.len(), 2);
        assert_eq!(seed.phantom_skins["gold-aura"].speffects, vec![1450700]);
        assert_eq!(seed.phantom_skins["silver-aura"].speffects, vec![1450705]);
    }

    #[test]
    fn test_seed_info_phantom_skins_defaults_empty() {
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.phantom_skins.is_empty());
    }

    #[test]
    fn test_phantom_skin_speffects_default_empty() {
        let json = r#"{}"#;
        let skin: PhantomSkin = serde_json::from_str(json).unwrap();
        assert!(skin.speffects.is_empty());
    }

    #[test]
    fn test_phantom_skin_unknown_keys_ignored() {
        // Forward-compat: the mod must tolerate future keys it doesn't know about.
        let json = r#"{"speffects": [1], "fxr_ids": [42], "future_field": "anything"}"#;
        let skin: PhantomSkin = serde_json::from_str(json).unwrap();
        assert_eq!(skin.speffects, vec![1]);
    }

    #[test]
    fn test_permanent_close_codes() {
        // Standard close codes: should reconnect
        assert!(!is_permanent_close(1000)); // Normal
        assert!(!is_permanent_close(1001)); // Going away
        assert!(!is_permanent_close(1006)); // Abnormal
        assert!(!is_permanent_close(1011)); // Server error
        assert!(!is_permanent_close(1012)); // Service restart

        // Boundary: 3999 is the last non-permanent code
        assert!(!is_permanent_close(3999));

        // Application close codes: permanent, do not reconnect
        assert!(is_permanent_close(4000)); // Boundary
        assert!(is_permanent_close(4001)); // Auth timeout
        assert!(is_permanent_close(4003)); // Auth error
        assert!(is_permanent_close(4004)); // Not found
        assert!(is_permanent_close(4999)); // Any future 4xxx code
    }

    #[test]
    fn test_status_enums_roundtrip_and_unknown() {
        // Known values keep today's lowercase wire strings.
        assert_eq!(
            serde_json::to_string(&RaceStatus::Running).unwrap(),
            "\"running\""
        );
        assert_eq!(
            serde_json::from_str::<RaceStatus>("\"setup\"").unwrap(),
            RaceStatus::Setup
        );
        assert_eq!(
            serde_json::to_string(&ParticipantStatus::Abandoned).unwrap(),
            "\"abandoned\""
        );
        // A status from a future server maps to Unknown instead of failing.
        assert_eq!(
            serde_json::from_str::<RaceStatus>("\"paused\"").unwrap(),
            RaceStatus::Unknown
        );
        assert_eq!(
            serde_json::from_str::<ParticipantStatus>("\"spectating\"").unwrap(),
            ParticipantStatus::Unknown
        );
    }
}
