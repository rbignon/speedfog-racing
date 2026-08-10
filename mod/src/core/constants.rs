//! Game constants - memory offsets
//!
//! All magic numbers from Elden Ring that we need for tracking.

// =============================================================================
// MEMORY OFFSETS
// =============================================================================

/// Offset of PlayRegionId within CS::FieldArea structure
pub const FIELD_AREA_PLAY_REGION_ID_OFFSET: usize = 0xE4;

/// Invalid map_id value (during loading screens)
pub const INVALID_MAP_ID: u32 = 0xFFFFFFFF;

/// Offset of death_count in GameDataMan structure
pub const GAMEDATAMAN_DEATH_COUNT_OFFSET: usize = 0x94;

/// GameDataMan + 0xA0: in-game time, u32 milliseconds (the save-select IGT).
pub const GAMEDATAMAN_IGT_OFFSET: usize = 0xA0;

/// PlayerGameData pointer offset within GameDataMan. The ChrAsm sub-structure
/// (currently equipped items) lives under this pointer.
pub const GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET: usize = 0x8;

// ChrAsm offsets inside PlayerGameData. The v5.0 Hexinton CE table layout is
// shifted by 4 bytes versus what we observe on patch 2.6.1: every field in the
// CE table is actually the *previous* field one slot earlier in memory. The
// labels are also inverted between CE and game hands (CE follows the equipment
// screen layout, where the left column shows the right hand's equipment). The
// constants below reflect the layout verified by equipping known weapons in
// each hand on 2.6.1 and matching the in-memory values to ground truth.
//
//   0x328: LEFT slot offset       (CE labels this byte "ArmStyle" - wrong)
//   0x32C: RIGHT slot offset      (CE labels this "LEFT slot" - wrong)
//   0x398: LEFT primary           (CE labels this "Accessory 5" - wrong)
//   0x39C: RIGHT primary          (CE labels this "PrimaryLeftWep")
//   0x3A0: LEFT secondary         (CE labels this "PrimaryRightWep")
//   0x3A4: RIGHT secondary
//   0x3A8: LEFT tertiary
//   0x3AC: RIGHT tertiary
//
// We do not currently track ArmStyle (two-handing mode); the CE-labelled
// ArmStyle byte at 0x328 is actually the LEFT slot offset. Two-handing
// over-reports the inactive hand, but the server filters shields/staves/etc.
// out anyway, so the over-report is benign in practice.
pub const CHRASM_WEP_SLOT_LEFT_OFFSET: usize = 0x328;
pub const CHRASM_WEP_SLOT_RIGHT_OFFSET: usize = 0x32C;
pub const CHRASM_PRIMARY_LEFT_WEP_OFFSET: usize = 0x398;
pub const CHRASM_PRIMARY_RIGHT_WEP_OFFSET: usize = 0x39C;
pub const CHRASM_SECONDARY_LEFT_WEP_OFFSET: usize = 0x3A0;
pub const CHRASM_SECONDARY_RIGHT_WEP_OFFSET: usize = 0x3A4;
pub const CHRASM_TERTIARY_LEFT_WEP_OFFSET: usize = 0x3A8;
pub const CHRASM_TERTIARY_RIGHT_WEP_OFFSET: usize = 0x3AC;

/// EquipParamWeapon row 110000 = "Unarmed" (fists). Mapped to None server-side.
pub const UNARMED_WEAPON_ID: i32 = 110000;

/// CSMenuManImp + 0x18: fade flag word driving blackscreen detection
/// (SoulSplitter's `IsBlackscreenActive`); offset stable across builds.
pub const MENUMAN_BLACKSCREEN_FLAGS_OFFSET: usize = 0x18;
/// CSMenuManImp screen-state value for "in game" (SoulSplitter's
/// `ScreenState`: 0 = InGame, 1 = Loading, 256 = MainMenu).
pub const SCREEN_STATE_IN_GAME: i32 = 0;
