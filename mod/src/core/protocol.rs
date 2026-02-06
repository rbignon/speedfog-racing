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
    StatusUpdate {
        igt_ms: u32,
        current_zone: String,
        death_count: u32,
    },
    /// Player entered a new zone
    ZoneEntered {
        from_zone: String,
        to_zone: String,
        igt_ms: u32,
    },
    /// Player finished the race
    Finished { igt_ms: u32 },
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

/// Seed info from server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SeedInfo {
    pub total_layers: i32,
}

/// Messages received from server
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Authentication successful
    AuthOk {
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
            current_zone: "Limgrave".to_string(),
            death_count: 5,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"status_update""#));
        assert!(json.contains(r#""igt_ms":123456"#));
        assert!(!json.contains("current_layer"));
    }

    #[test]
    fn test_server_auth_ok_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "race": {"id": "123", "name": "Test Race", "status": "open"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { race, seed, .. } => {
                assert_eq!(race.name, "Test Race");
                assert_eq!(seed.total_layers, 5);
            }
            _ => panic!("Expected AuthOk"),
        }
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
                "igt_ms": 60000,
                "death_count": 1
            }]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate { participants } => {
                assert_eq!(participants.len(), 1);
                assert_eq!(participants[0].twitch_username, "player1");
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }
}
