//! Core module - platform-independent types

pub mod color;
pub mod constants;
pub mod flag_buffer;
pub mod format;
pub mod map_utils;
pub mod profile;
pub mod protocol;
pub mod traits;
pub mod types;

pub use color::parse_hex_color;
pub use format::{compute_gap, format_gap, format_gap_into, parse_splits};
pub use map_utils::format_map_id;
pub use protocol::{
    is_permanent_close, ClientMessage, ParticipantInfo, RaceInfo, SeedInfo, ServerMessage,
};
pub use traits::GameStateReader;
pub use types::PlayerPosition;
