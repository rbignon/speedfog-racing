//! Core traits - abstractions for platform-specific implementations
//!
//! These traits define the interface for reading game state. The actual
//! implementations live in the `platform` module and use Windows APIs.
//! For testing, mock implementations can be provided.

use super::types::PlayerPosition;

// =============================================================================
// GAME STATE READER
// =============================================================================

/// Read player state from the game
///
/// This trait abstracts the memory reading operations needed to track
/// the player's position and animation state.
pub trait GameStateReader {
    /// Block until the game is fully loaded (menu timer > 0)
    fn wait_for_game_loaded(&self);

    /// Read current player position and map data
    ///
    /// Returns None if position data is not available (e.g., during loading)
    fn read_position(&self) -> Option<PlayerPosition>;

    /// Read current animation ID
    fn read_animation(&self) -> Option<u32>;
}

// =============================================================================
// TEST MOCKS
// =============================================================================

#[cfg(test)]
pub mod mocks {
    use super::*;

    /// Mock GameStateReader for testing
    pub struct MockGameState {
        pub positions: Vec<Option<PlayerPosition>>,
        pub animations: Vec<Option<u32>>,
        pub frame: std::cell::Cell<usize>,
    }

    impl MockGameState {
        pub fn new(positions: Vec<Option<PlayerPosition>>, animations: Vec<Option<u32>>) -> Self {
            Self {
                positions,
                animations,
                frame: std::cell::Cell::new(0),
            }
        }

        pub fn advance_frame(&self) {
            self.frame.set(self.frame.get() + 1);
        }

        pub fn current_frame(&self) -> usize {
            self.frame.get()
        }
    }

    impl GameStateReader for MockGameState {
        fn wait_for_game_loaded(&self) {
            // No-op in tests
        }

        fn read_position(&self) -> Option<PlayerPosition> {
            self.positions.get(self.frame.get()).cloned().flatten()
        }

        fn read_animation(&self) -> Option<u32> {
            self.animations.get(self.frame.get()).cloned().flatten()
        }
    }
}
