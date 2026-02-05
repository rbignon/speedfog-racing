//! Core module - platform-independent types

pub mod map_utils;
pub mod protocol;
pub mod traits;
pub mod types;

pub use map_utils::format_map_id;
pub use protocol::{ClientMessage, ParticipantInfo, RaceInfo, SeedInfo, ServerMessage};
pub use traits::GameStateReader;
pub use types::PlayerPosition;
