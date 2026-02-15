//! WebSocket protocol types for SpeedFog Racing
//!
//! Messages exchanged between the mod and the racing server.

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
    EventFlag { flag_id: u32, igt_ms: u32 },
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
}

/// Race info from server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RaceInfo {
    pub id: String,
    pub name: String,
    pub status: String,
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
    #[serde(default)]
    pub spawn_items: Vec<SpawnItem>,
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
    /// Race has started
    RaceStart,
    /// Leaderboard update
    LeaderboardUpdate { participants: Vec<ParticipantInfo> },
    /// Race status changed
    RaceStatusChange { status: String },
    /// Single player update
    PlayerUpdate { player: ParticipantInfo },
    /// Zone update (unicast to originating mod)
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        #[serde(default)]
        exits: Vec<ExitInfo>,
    },
    /// Heartbeat ping
    Ping,
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
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"event_flag""#));
        assert!(json.contains(r#""flag_id":9000042"#));
        assert!(json.contains(r#""igt_ms":60000"#));
    }

    #[test]
    fn test_server_auth_ok_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "open"},
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
        let json = r#"{"type": "race_start"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(msg, ServerMessage::RaceStart));
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
            ServerMessage::LeaderboardUpdate { participants } => {
                assert_eq!(participants.len(), 1);
                assert_eq!(participants[0].twitch_username, "player1");
                assert_eq!(participants[0].current_layer_tier, Some(3));
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
                exits,
            } => {
                assert_eq!(node_id, "graveyard_cave_e235");
                assert_eq!(display_name, "Cave of Knowledge");
                assert_eq!(tier, Some(5));
                assert_eq!(exits.len(), 2);
                assert_eq!(exits[0].text, "Soldier of Godrick front");
                assert_eq!(exits[0].to_name, "Road's End Catacombs");
                assert!(!exits[0].discovered);
                assert!(exits[1].discovered);
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
            "race": {"id": "123", "name": "Test Race", "status": "open"},
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
    }
}
