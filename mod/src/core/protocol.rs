//! WebSocket protocol types for SpeedFog Racing
//!
//! Messages exchanged between the mod and the racing server.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

// =============================================================================
// CLIENT -> SERVER MESSAGES
// =============================================================================

/// Messages sent from mod to server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Authentication with mod token
    Auth { mod_token: String },
    /// Player is ready to race
    Ready,
    /// Periodic status update
    StatusUpdate { igt_ms: u32, death_count: u32 },
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
    },
    /// Heartbeat response
    Pong,
}

// =============================================================================
// SERVER -> CLIENT MESSAGES
// =============================================================================

/// Participant info in leaderboard
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantInfo {
    pub id: String,
    pub twitch_username: String,
    pub twitch_display_name: Option<String>,
    pub status: String,
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
    pub status: String,
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
        race: RaceInfo,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
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
    RaceStatusChange { status: String },
    /// Race-level info changed (race_ends_at extension, etc.) and the cached
    /// RaceInfo on the client must be replaced wholesale with this snapshot.
    RaceInfoUpdate { race: RaceInfo },
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
    /// Generic error from server (e.g., race not running)
    Error { message: String },
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
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"auth""#));
        assert!(json.contains(r#""mod_token":"test123""#));
    }

    #[test]
    fn test_client_status_update_serialize() {
        let msg = ClientMessage::StatusUpdate {
            igt_ms: 123456,
            death_count: 5,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"status_update""#));
        assert!(json.contains(r#""igt_ms":123456"#));
        assert!(json.contains(r#""death_count":5"#));
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
        let json = r#"{"type": "error", "message": "Race not running"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { message } => {
                assert_eq!(message, "Race not running");
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
    fn test_race_info_with_race_ends_at() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "race_ends_at": "2026-04-20T12:00:00Z"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.race_ends_at.as_deref(), Some("2026-04-20T12:00:00Z"));
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
                assert_eq!(race.status, "running");
            }
            _ => panic!("Expected RaceInfoUpdate"),
        }
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
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":120000"#));
        assert!(json.contains(r#""message_id":99"#));
        assert!(json.contains(r#""map_id":"m10_00_00_00""#));
        assert!(!json.contains("grace_entity_id"));
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
}
