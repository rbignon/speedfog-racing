//! Core module - platform-independent types

pub mod aob;
pub mod color;
pub mod constants;
pub mod countdown;
pub mod debug_flags;
pub mod equip_load;
pub mod flag_buffer;
pub mod foes;
pub mod format;
pub mod hunter;
pub mod hunter_spawn;
pub mod igt_fix;
pub mod item_banner;
pub mod item_damage;
pub mod item_feed;
pub mod item_inventory;
pub mod job_queue;
pub mod key_names;
pub mod livesplit;
pub mod map_utils;
pub mod memory_effects;
pub mod play_clock;
pub mod profile;
pub mod protocol;
pub mod race_machine;
pub mod relay;
pub mod relay_apply;
pub mod relay_capture;
pub mod relay_menu;
pub mod relay_view;
pub mod talisman_thief;
pub mod timed_effects;
pub mod types;

pub use color::parse_hex_color;
pub use format::{
    centers_on_player, compute_gap, compute_leaderboard_layout, format_gap, format_gap_into,
    format_time_into, gap_from_player, is_seed_stale, parse_splits, write_participant_right_text,
    GapRunner, LeaderboardLayout, LeaderboardMode, LeaderboardView,
};
pub use livesplit::{LiveSplitSync, LsCommand, LsSnapshot, RunView, SyncOutput, TimerPhase};
pub use map_utils::format_map_id;
pub use protocol::{
    is_permanent_close, ClientMessage, ParticipantInfo, RaceInfo, SeedInfo, ServerMessage,
};
pub use race_machine::{
    BufferedEventFlag, BufferedZoneQuery, ConnectionStatus, Effect, FrameNeeds, FrameSnapshot,
    MachineMessage, RaceState, TickInput, ZoneUpdateData,
};
pub use types::PlayerPosition;
