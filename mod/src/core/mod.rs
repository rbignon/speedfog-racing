//! Core module - platform-independent types

pub mod aob;
pub mod color;
pub mod constants;
pub mod flag_buffer;
pub mod format;
pub mod igt_fix;
pub mod map_utils;
pub mod profile;
pub mod protocol;
pub mod race_machine;
pub mod types;

pub use color::parse_hex_color;
pub use format::{
    compute_gap, compute_leaderboard_layout, format_gap, format_gap_into, format_time_into,
    is_seed_stale, parse_splits, write_participant_right_text, LeaderboardLayout,
};
pub use map_utils::format_map_id;
pub use protocol::{
    is_permanent_close, ClientMessage, ParticipantInfo, RaceInfo, SeedInfo, ServerMessage,
};
pub use race_machine::{
    BufferedEventFlag, BufferedZoneQuery, ConnectionStatus, Effect, FrameNeeds, FrameSnapshot,
    MachineMessage, RaceState, TickInput, ZoneUpdateData,
};
pub use types::PlayerPosition;
