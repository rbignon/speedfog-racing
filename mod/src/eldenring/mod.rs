//! Elden Ring memory reading module
//!
//! This module contains all the code that reads from the Elden Ring process memory,
//! including player position, animation state, and event flag tracking.
//!
//! Game-memory reading and hooking, consumed by the dll shell; the pure
//! race logic in `core::race_machine` receives these reads as plain data.

mod event_flags;
mod game_state;
pub mod item_spawner;
pub mod quitout;
mod scan;
pub mod sp_effect_apply;
pub mod sp_effect_runner;
pub mod warp_hook;

pub use event_flags::{EventFlagReader, FlagReaderStatus};
pub use game_state::GameState;
