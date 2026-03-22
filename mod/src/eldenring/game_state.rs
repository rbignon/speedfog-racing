//! Elden Ring GameStateReader implementation
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

use crate::core::constants::{
    FIELD_AREA_PLAY_REGION_ID_OFFSET, GAMEDATAMAN_DEATH_COUNT_OFFSET, INVALID_MAP_ID,
};
use crate::core::map_utils::format_map_id;
use crate::core::traits::GameStateReader;
use crate::core::types::PlayerPosition;

/// Elden Ring game state reader
///
/// Uses libeldenring to read from Elden Ring's memory.
pub struct GameState {
    pointers: Pointers,
    play_region_id_ptr: PointerChain<u32>,
    death_count_ptr: PointerChain<u32>,
    /// [[EventFlagMan]+0x28]+0x113: non-zero during cutscenes/loading screens
    loading_screen_ptr: PointerChain<u8>,
}

impl GameState {
    /// Create a new GameState reader
    pub fn new() -> Self {
        let pointers = Pointers::new();

        // Create pointer chain for PlayRegionId (FieldArea + 0xE4)
        let play_region_id_ptr = PointerChain::<u32>::new(&[
            pointers.base_addresses.field_area,
            FIELD_AREA_PLAY_REGION_ID_OFFSET,
        ]);

        // Create pointer chain for death count (GameDataMan + 0x94)
        let death_count_ptr = PointerChain::<u32>::new(&[
            pointers.base_addresses.game_data_man,
            GAMEDATAMAN_DEATH_COUNT_OFFSET,
        ]);

        // Create pointer chain for loading screen flag
        // CE table: "In cut-scene/loading screen" at [[EventFlagMan]+0x28]+0x113
        let loading_screen_ptr = PointerChain::<u8>::new(&[
            pointers.base_addresses.csfd4_virtual_memory_flag,
            0x28,
            0x113,
        ]);

        Self {
            pointers,
            play_region_id_ptr,
            death_count_ptr,
            loading_screen_ptr,
        }
    }

    /// Get base addresses (for creating EventFlagReader)
    pub fn base_addresses(&self) -> &libeldenring::prelude::base_addresses::BaseAddresses {
        &self.pointers.base_addresses
    }

    /// Read the death count from game memory
    ///
    /// Returns the total number of deaths for the current character.
    pub fn read_deaths(&self) -> Option<u32> {
        self.death_count_ptr.read()
    }

    /// Read the in-game time from game memory
    ///
    /// Returns the IGT in milliseconds.
    pub fn read_igt(&self) -> Option<u32> {
        // libeldenring reads IGT as usize but it's actually a u32 in milliseconds
        self.pointers.igt.read().map(|v| v as u32)
    }

    /// Check if the game is currently in a loading screen or cutscene.
    ///
    /// Returns `Some(true)` if loading, `Some(false)` if gameplay, `None` if
    /// the pointer chain is unreadable (e.g., game not fully initialized).
    pub fn is_in_loading_screen(&self) -> Option<bool> {
        self.loading_screen_ptr.read().map(|v| v != 0)
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}

impl GameStateReader for GameState {
    fn wait_for_game_loaded(&self) {
        let poll_interval = Duration::from_millis(100);
        loop {
            if let Some(menu_timer) = self.pointers.menu_timer.read() {
                if menu_timer > 0. {
                    break;
                }
            }
            std::thread::sleep(poll_interval);
        }
    }

    fn read_position(&self) -> Option<PlayerPosition> {
        let [x, y, z, _, _] = self.pointers.global_position.read()?;
        let map_id = self.pointers.global_position.read_map_id()?;

        // Check if position is valid (not during loading screen)
        if map_id == INVALID_MAP_ID || (x == 0.0 && y == 0.0 && z == 0.0) {
            return None;
        }

        Some(PlayerPosition {
            map_id,
            map_id_str: format_map_id(map_id),
            x,
            y,
            z,
            play_region_id: self.play_region_id_ptr.read(),
        })
    }

    fn read_animation(&self) -> Option<u32> {
        self.pointers.cur_anim.read()
    }
}
