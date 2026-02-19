//! Core types - platform-independent data structures
//!
//! These types represent game state and are used throughout the tracker.

use super::map_utils::format_map_id;

// =============================================================================
// PLAYER POSITION
// =============================================================================

/// Current player position snapshot
#[derive(Clone, Debug, PartialEq)]
pub struct PlayerPosition {
    pub map_id: u32,
    pub map_id_str: String,
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub play_region_id: Option<u32>,
}

impl PlayerPosition {
    /// Create a new PlayerPosition
    pub fn new(map_id: u32, x: f32, y: f32, z: f32, play_region_id: Option<u32>) -> Self {
        Self {
            map_id,
            map_id_str: format_map_id(map_id),
            x,
            y,
            z,
            play_region_id,
        }
    }

    /// Returns position as a tuple (x, y, z)
    pub fn pos(&self) -> (f32, f32, f32) {
        (self.x, self.y, self.z)
    }

    /// Calculate 3D distance to another position
    pub fn distance_to(&self, other: &PlayerPosition) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        let dz = self.z - other.z;
        (dx * dx + dy * dy + dz * dz).sqrt()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_player_position_new() {
        let pos = PlayerPosition::new(0x3C2C2400, 100.0, 50.0, 200.0, Some(12345));
        assert_eq!(pos.map_id, 0x3C2C2400);
        assert_eq!(pos.map_id_str, "m60_44_36_00");
        assert_eq!(pos.x, 100.0);
        assert_eq!(pos.y, 50.0);
        assert_eq!(pos.z, 200.0);
        assert_eq!(pos.play_region_id, Some(12345));
    }

    #[test]
    fn test_player_position_pos_tuple() {
        let pos = PlayerPosition::new(0, 1.0, 2.0, 3.0, None);
        assert_eq!(pos.pos(), (1.0, 2.0, 3.0));
    }

    #[test]
    fn test_player_position_distance_to() {
        let pos1 = PlayerPosition::new(0, 0.0, 0.0, 0.0, None);
        let pos2 = PlayerPosition::new(0, 3.0, 4.0, 0.0, None);
        assert!((pos1.distance_to(&pos2) - 5.0).abs() < 0.001);

        // Same position = 0 distance
        assert!((pos1.distance_to(&pos1)).abs() < 0.001);
    }
}
