//! DLL module - SpeedFog Racing mod

pub mod race_config;
pub mod race_tracker;
pub mod race_ui;
pub mod race_websocket;

// Re-export tracker for lib.rs
pub use race_tracker::RaceTracker;

// Keep old modules for now - will be cleaned in Task 10
pub mod config;
mod frame_state;
pub mod hotkey;
pub mod icon_atlas;
pub mod log_reader;
pub mod logging;
pub mod tracker;
pub mod ui;
pub mod websocket;
