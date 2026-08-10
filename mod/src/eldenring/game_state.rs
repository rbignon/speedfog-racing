//! Elden Ring game-state memory reader
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.
//!
//! The CSMenuManImp screen-state/blackscreen reading (the version-offset
//! table and the fade-flag bit test) is ported from SoulSplitter
//! (https://github.com/FrankvdStam/SoulSplitter, GPLv3; compatible with
//! this crate's AGPL-3.0).

use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use libeldenring::version::{get_version, Version};
use tracing::warn;

use crate::core::constants::{
    CHRASM_PRIMARY_LEFT_WEP_OFFSET, CHRASM_PRIMARY_RIGHT_WEP_OFFSET,
    CHRASM_SECONDARY_LEFT_WEP_OFFSET, CHRASM_SECONDARY_RIGHT_WEP_OFFSET,
    CHRASM_TERTIARY_LEFT_WEP_OFFSET, CHRASM_TERTIARY_RIGHT_WEP_OFFSET, CHRASM_WEP_SLOT_LEFT_OFFSET,
    CHRASM_WEP_SLOT_RIGHT_OFFSET, FIELD_AREA_PLAY_REGION_ID_OFFSET, GAMEDATAMAN_DEATH_COUNT_OFFSET,
    GAMEDATAMAN_IGT_OFFSET, GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET, INVALID_MAP_ID,
    MENUMAN_BLACKSCREEN_FLAGS_OFFSET, SCREEN_STATE_IN_GAME, UNARMED_WEAPON_ID,
};
use crate::core::map_utils::format_map_id;
use crate::core::types::PlayerPosition;
use crate::profile_span;

/// CSMenuManImp screen-state offset per game build (SoulSplitter's
/// `InitializeOffsets`, 0x730 group = app 1.12+ / exe 2.2+). Pre-DLC
/// builds are left unmapped: the platform does not race on them, and an
/// unmapped build only degrades the blackscreen signals (freeze and
/// reveal fall back), it never blocks racing.
fn screen_state_offset(version: Version) -> Option<usize> {
    use Version::*;
    match version {
        V2_02_0 | V2_02_3 | V2_03_0 | V2_04_0 | V2_05_0 | V2_06_0 | V2_06_1 | V2_06_2 => {
            Some(0x730)
        }
        _ => None,
    }
}

/// Elden Ring game state reader
///
/// Uses libeldenring to read from Elden Ring's memory.
pub struct GameState {
    pointers: Pointers,
    play_region_id_ptr: PointerChain<u32>,
    death_count_ptr: PointerChain<u32>,
    /// Byte packing engine event flags 2200-2207; its only moving bit (flag
    /// 2200) means "world clock stopped". Loading proxy for zone reveals
    /// (bounded by a defensive timeout, see `RaceMachine`): permanently ON
    /// on seeds generated with the old FreezeTime weather plugin
    /// (pre-2026-07-15 generator). Also shown in the debug overlay.
    loading_screen_ptr: PointerChain<u8>,
    /// ChrAsm: equipped-weapon resolution. All chains live under
    /// `GameDataMan -> +0x8 (PlayerGameData) -> +<field offset>`.
    wep_slot_left_ptr: PointerChain<i32>,
    wep_slot_right_ptr: PointerChain<i32>,
    weapon_slot_ptrs: [[PointerChain<i32>; 3]; 2],
    /// 4-byte IGT chain for penalty writes. libeldenring's `pointers.igt` is
    /// typed `usize`; writing through it would clobber GameDataMan+0xA4.
    igt_write_ptr: PointerChain<u32>,
    /// CSMenuManImp screen state (see `SCREEN_STATE_IN_GAME`). `None` on
    /// builds without a mapped offset: blackscreen signals degrade.
    screen_state_ptr: Option<PointerChain<i32>>,
    /// CSMenuManImp fade flag word (`is_blackscreen_active`).
    blackscreen_flags_ptr: PointerChain<i32>,
}

impl GameState {
    /// Create a new GameState reader
    pub fn new() -> Self {
        let pointers = Pointers::new();
        let game_data_man = pointers.base_addresses.game_data_man;

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

        // Create pointer chain for IGT penalty writes (GameDataMan + 0xA0).
        // 4-byte u32, distinct from libeldenring's `pointers.igt` (usize).
        let igt_write_ptr = PointerChain::<u32>::new(&[game_data_man, GAMEDATAMAN_IGT_OFFSET]);

        // CSMenuManImp chains for the blackscreen freeze and zone reveal
        // (SoulSplitter's IsBlackscreenActive / ScreenState).
        let cs_menu_man_imp = pointers.base_addresses.cs_menu_man_imp;
        let screen_state_ptr = match screen_state_offset(get_version()) {
            Some(offset) => Some(PointerChain::<i32>::new(&[cs_menu_man_imp, offset])),
            None => {
                warn!(
                    "[IGT] No screen-state offset mapped for this game build; \
                     blackscreen freeze and direct reveal signal disabled"
                );
                None
            }
        };
        let blackscreen_flags_ptr =
            PointerChain::<i32>::new(&[cs_menu_man_imp, MENUMAN_BLACKSCREEN_FLAGS_OFFSET]);

        // Create pointer chain for loading screen flag
        // CE table: "In cut-scene/loading screen" at [[EventFlagMan]+0x28]+0x113
        let loading_screen_ptr = PointerChain::<u8>::new(&[
            pointers.base_addresses.csfd4_virtual_memory_flag,
            0x28,
            0x113,
        ]);

        let chrasm_chain = |offset: usize| -> PointerChain<i32> {
            PointerChain::<i32>::new(&[game_data_man, GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET, offset])
        };
        let wep_slot_left_ptr = chrasm_chain(CHRASM_WEP_SLOT_LEFT_OFFSET);
        let wep_slot_right_ptr = chrasm_chain(CHRASM_WEP_SLOT_RIGHT_OFFSET);
        // Indexed [hand][slot]: hand 0 = game left, hand 1 = game right;
        // slot 0 = Primary, 1 = Secondary, 2 = Tertiary.
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
            wep_slot_left_ptr,
            wep_slot_right_ptr,
            weapon_slot_ptrs,
            igt_write_ptr,
            screen_state_ptr,
            blackscreen_flags_ptr,
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

    /// Raw value of the byte at `[[EventFlagMan]+0x28]+0x113` (the CE table's
    /// "In cut-scene/loading screen"), exposed in the debug overlay only.
    ///
    /// The byte packs the engine-internal event flags 2200-2207 (MSB-first:
    /// bit 7 = flag 2200; same bit order as `EventFlagReader`). The
    /// 2026-07-13 discovery session showed only flag 2200 ever moves, and
    /// that it means "world clock stopped": it is ON during loading screens
    /// and cutscenes, but also permanently ON while the SpeedFog weather
    /// plugin freezes the clock. Zone reveals treat it as a loading proxy
    /// bounded by a defensive timeout (see `RaceMachine`);
    /// `is_world_clock_stopped` is the boolean view.
    pub fn read_loading_byte(&self) -> Option<u8> {
        profile_span!("read_loading_byte");
        self.loading_screen_ptr.read()
    }

    /// Whether the engine's "world clock stopped" byte is nonzero (see
    /// `read_loading_byte` for what the byte really is). ON during loading
    /// screens and cutscenes; permanently ON while the SpeedFog weather
    /// plugin freezes the clock, so callers treating it as "loading screen
    /// displayed" must bound the wait (see the zone reveal timeout in
    /// `RaceMachine`).
    pub fn is_world_clock_stopped(&self) -> Option<bool> {
        profile_span!("is_world_clock_stopped");
        self.loading_screen_ptr.read().map(|v| v != 0)
    }

    /// CSMenuManImp screen state: `Some(true)` = in game, `Some(false)` =
    /// loading screen or main menu, `None` = unmapped build or unreadable
    /// chain (callers fall back to the legacy world-clock proxy). Thin
    /// wrapper over `read_screen_signals`; off the per-frame hot path (debug
    /// panel only), so the redundant screen-state read it implies is fine.
    pub fn is_screen_in_game(&self) -> Option<bool> {
        profile_span!("is_screen_in_game");
        self.read_screen_signals().0
    }

    /// Blackscreen ("meme loading screen") detection, ported from
    /// SoulSplitter's `IsBlackscreenActive`: in-game screen state with the
    /// fade flag word reading bit0=1, bit8=0, bit16=1. `Some(false)` when
    /// simply not fading (or not in game); `None` when the screen-state
    /// signal itself is unavailable. Thin wrapper over `read_screen_signals`;
    /// off the per-frame hot path (debug panel only).
    pub fn is_blackscreen_active(&self) -> Option<bool> {
        profile_span!("is_blackscreen_active");
        self.read_screen_signals().1
    }

    /// Read the CSMenuManImp screen-state and blackscreen-fade signals
    /// together, evaluating the screen-state pointer chain once instead of
    /// twice (the per-frame caller, `RaceTracker::update`'s FrameSnapshot,
    /// needs both; `is_blackscreen_active` depends on `is_screen_in_game`,
    /// so calling both separately there would read the chain twice per
    /// frame). Returns `(screen_in_game, blackscreen)`; see
    /// `is_screen_in_game` / `is_blackscreen_active` for what each value
    /// means in every case (unmapped build, unreadable chain, menu, in-game
    /// clear, in-game fade).
    pub fn read_screen_signals(&self) -> (Option<bool>, Option<bool>) {
        profile_span!("read_screen_signals");
        let Some(state) = self.screen_state_ptr.as_ref().and_then(|ptr| ptr.read()) else {
            return (None, None);
        };
        let in_game = state == SCREEN_STATE_IN_GAME;
        if !in_game {
            return (Some(false), Some(false));
        }
        let blackscreen = self
            .blackscreen_flags_ptr
            .read()
            .map(|flags| flags & 0x1 == 0x1 && flags & 0x100 == 0 && flags & 0x1_0000 == 0x1_0000);
        (Some(true), blackscreen)
    }

    /// Overwrite the in-game timer (blackscreen freeze write-back). Same
    /// 4-byte chain as `add_igt_penalty`; `None` when unwritable.
    pub fn write_igt(&self, ms: u32) -> Option<()> {
        profile_span!("write_igt");
        self.igt_write_ptr.write(ms)
    }

    /// Read the currently-equipped weapon IDs for the left and right hands.
    ///
    /// Returns `[left, right]`. Each slot is `None` when:
    /// - The slot-offset pointer chain is unreadable.
    /// - The active slot index is out of `[0..3)`.
    /// - The slot holds the Unarmed sentinel (110000) or a non-positive value.
    ///
    /// The active slot per hand is the one the player cycles via the d-pad
    /// during gameplay; reading it from memory (rather than always reading
    /// Primary) is what lets us follow mid-race loadout switches. Two-handing
    /// is not detected: the inactive hand is over-reported, but the server's
    /// `wep_type` filter strips the shield/staff/seal that an off-hand
    /// typically holds in that case, neutralizing the effect.
    pub fn read_equipped_weapons(&self) -> [Option<i32>; 2] {
        profile_span!("read_equipped_weapons");
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
        let left = read_hand(0, self.wep_slot_left_ptr.read());
        let right = read_hand(1, self.wep_slot_right_ptr.read());
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

    /// Add `ms` to the in-game timer (quit-out penalty). Returns the new
    /// value, or None when the IGT is unreadable or unwritable (main menu,
    /// loading). 4-byte u32 read-modify-write; the game's own per-frame IGT
    /// accumulation resumes from the written value.
    pub fn add_igt_penalty(&self, ms: u32) -> Option<u32> {
        profile_span!("add_igt_penalty");
        let current = self.igt_write_ptr.read()?;
        let new = current.saturating_add(ms);
        self.igt_write_ptr.write(new)?;
        Some(new)
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}

impl GameState {
    /// Block until the game is fully loaded (menu timer > 0).
    pub fn wait_for_game_loaded(&self) {
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

    /// Read current player position and map data.
    ///
    /// Returns None if position data is not available (e.g., during loading).
    pub fn read_position(&self) -> Option<PlayerPosition> {
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

    /// Read current animation ID.
    #[allow(dead_code)] // RE-documented pointer, kept for future use
    pub fn read_animation(&self) -> Option<u32> {
        self.pointers.cur_anim.read()
    }
}
