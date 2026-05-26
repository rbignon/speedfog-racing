//! Elden Ring GameStateReader implementation
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

use crate::core::constants::{
    ARM_STYLE_EMPTY, ARM_STYLE_TWO_HANDED_LEFT, ARM_STYLE_TWO_HANDED_RIGHT,
    CHRASM_ARM_STYLE_OFFSET, CHRASM_PRIMARY_LEFT_WEP_OFFSET, CHRASM_PRIMARY_RIGHT_WEP_OFFSET,
    CHRASM_SECONDARY_LEFT_WEP_OFFSET, CHRASM_SECONDARY_RIGHT_WEP_OFFSET,
    CHRASM_TERTIARY_LEFT_WEP_OFFSET, CHRASM_TERTIARY_RIGHT_WEP_OFFSET, CHRASM_WEP_SLOT_LEFT_OFFSET,
    CHRASM_WEP_SLOT_RIGHT_OFFSET, FIELD_AREA_PLAY_REGION_ID_OFFSET, GAMEDATAMAN_DEATH_COUNT_OFFSET,
    GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET, INVALID_MAP_ID, UNARMED_WEAPON_ID,
};
use crate::core::map_utils::format_map_id;
use crate::core::traits::GameStateReader;
use crate::core::types::PlayerPosition;
use crate::profile_span;

/// Elden Ring game state reader
///
/// Uses libeldenring to read from Elden Ring's memory.
pub struct GameState {
    pointers: Pointers,
    play_region_id_ptr: PointerChain<u32>,
    death_count_ptr: PointerChain<u32>,
    /// [[EventFlagMan]+0x28]+0x113: non-zero during cutscenes/loading screens
    loading_screen_ptr: PointerChain<u8>,
    /// ChrAsm: equipped-weapon resolution. All chains live under
    /// `GameDataMan -> +0x8 (PlayerGameData) -> +<field offset>`.
    arm_style_ptr: PointerChain<u8>,
    wep_slot_left_ptr: PointerChain<i32>,
    wep_slot_right_ptr: PointerChain<i32>,
    weapon_slot_ptrs: [[PointerChain<i32>; 3]; 2],
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

        let game_data_man = pointers.base_addresses.game_data_man;
        let chrasm_chain = |offset: usize| -> PointerChain<i32> {
            PointerChain::<i32>::new(&[game_data_man, GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET, offset])
        };
        let arm_style_ptr = PointerChain::<u8>::new(&[
            game_data_man,
            GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET,
            CHRASM_ARM_STYLE_OFFSET,
        ]);
        let wep_slot_left_ptr = chrasm_chain(CHRASM_WEP_SLOT_LEFT_OFFSET);
        let wep_slot_right_ptr = chrasm_chain(CHRASM_WEP_SLOT_RIGHT_OFFSET);
        // Indexed [hand][slot_offset]: hand 0 = left, hand 1 = right;
        // slot_offset 0 = Primary, 1 = Secondary, 2 = Tertiary.
        let weapon_slot_ptrs = [
            [
                chrasm_chain(CHRASM_PRIMARY_LEFT_WEP_OFFSET),
                chrasm_chain(CHRASM_SECONDARY_LEFT_WEP_OFFSET),
                chrasm_chain(CHRASM_TERTIARY_LEFT_WEP_OFFSET),
            ],
            [
                chrasm_chain(CHRASM_PRIMARY_RIGHT_WEP_OFFSET),
                chrasm_chain(CHRASM_SECONDARY_RIGHT_WEP_OFFSET),
                chrasm_chain(CHRASM_TERTIARY_RIGHT_WEP_OFFSET),
            ],
        ];

        Self {
            pointers,
            play_region_id_ptr,
            death_count_ptr,
            loading_screen_ptr,
            arm_style_ptr,
            wep_slot_left_ptr,
            wep_slot_right_ptr,
            weapon_slot_ptrs,
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
        profile_span!("read_deaths");
        self.death_count_ptr.read()
    }

    /// Read the in-game time from game memory
    ///
    /// Returns the IGT in milliseconds.
    pub fn read_igt(&self) -> Option<u32> {
        profile_span!("read_igt");
        // libeldenring reads IGT as usize but it's actually a u32 in milliseconds
        self.pointers.igt.read().map(|v| v as u32)
    }

    /// Check if the game is currently in a loading screen or cutscene.
    ///
    /// Returns `Some(true)` if loading, `Some(false)` if gameplay, `None` if
    /// the pointer chain is unreadable (e.g., game not fully initialized).
    pub fn is_in_loading_screen(&self) -> Option<bool> {
        profile_span!("is_in_loading_screen");
        self.loading_screen_ptr.read().map(|v| v != 0)
    }

    /// Read the currently-equipped weapon IDs for the left and right hands.
    ///
    /// Returns `[left, right]`. Each slot is `None` when:
    /// - The pointer chain is unreadable (game not initialized).
    /// - The hand is empty per `ArmStyle == 0`, or masked by two-handing.
    /// - The slot holds the Unarmed sentinel (110000) or a non-positive sentinel.
    ///
    /// Filtering by weapon type happens server-side, against `weapons.csv`.
    pub fn read_equipped_weapons(&self) -> [Option<i32>; 2] {
        profile_span!("read_equipped_weapons");
        let arm_style = match self.arm_style_ptr.read() {
            Some(v) => v,
            None => return [None, None],
        };
        if arm_style == ARM_STYLE_EMPTY {
            return [None, None];
        }
        let slot_left = self.wep_slot_left_ptr.read();
        let slot_right = self.wep_slot_right_ptr.read();
        let read_hand = |hand_idx: usize, slot: Option<i32>| -> Option<i32> {
            let slot_offset = slot? as usize;
            let chain = self.weapon_slot_ptrs[hand_idx].get(slot_offset)?;
            let raw = chain.read()?;
            if raw <= 0 || raw == UNARMED_WEAPON_ID {
                None
            } else {
                Some(raw)
            }
        };
        let mut left = read_hand(0, slot_left);
        let mut right = read_hand(1, slot_right);
        // Mask the inactive hand under two-handing: per the spec, we only report
        // the weapon actually in use.
        if arm_style == ARM_STYLE_TWO_HANDED_LEFT {
            right = None;
        } else if arm_style == ARM_STYLE_TWO_HANDED_RIGHT {
            left = None;
        }
        [left, right]
    }

    /// Check if the player position is readable without allocating a String
    /// for the map ID. Use this instead of `read_position().is_some()` when
    /// only a boolean check is needed (e.g., loading screen detection).
    pub fn is_position_readable(&self) -> bool {
        profile_span!("is_position_readable");
        let coords = match self.pointers.global_position.read() {
            Some(c) => c,
            None => return false,
        };
        let map_id = match self.pointers.global_position.read_map_id() {
            Some(m) => m,
            None => return false,
        };
        map_id != INVALID_MAP_ID && !(coords[0] == 0.0 && coords[1] == 0.0 && coords[2] == 0.0)
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
        profile_span!("read_position");
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
