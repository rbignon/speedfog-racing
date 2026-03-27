//! Elden Ring memory reading module
//!
//! This module contains all the code that reads from the Elden Ring process memory,
//! including player position, animation state, and event flag tracking.
//!
//! The implementations here satisfy the traits defined in `core::traits`.

mod event_flags;
mod game_state;
pub mod item_spawner;
pub mod warp_hook;

pub use event_flags::{EventFlagReader, FlagReaderStatus};
pub use game_state::GameState;
