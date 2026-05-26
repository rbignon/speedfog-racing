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

/// PlayerGameData pointer offset within GameDataMan. The ChrAsm sub-structure
/// (currently equipped items) lives under this pointer.
pub const GAMEDATAMAN_PLAYER_GAME_DATA_OFFSET: usize = 0x8;

// ChrAsm offsets inside PlayerGameData. Sourced from the v5.0 Hexinton CE table
// (`ChrAsm (Edit)` group), validated stable across patches 2.4.0..2.6.1.
pub const CHRASM_ARM_STYLE_OFFSET: usize = 0x328;
pub const CHRASM_WEP_SLOT_LEFT_OFFSET: usize = 0x32C;
pub const CHRASM_WEP_SLOT_RIGHT_OFFSET: usize = 0x330;
pub const CHRASM_PRIMARY_LEFT_WEP_OFFSET: usize = 0x39C;
pub const CHRASM_PRIMARY_RIGHT_WEP_OFFSET: usize = 0x3A0;
pub const CHRASM_SECONDARY_LEFT_WEP_OFFSET: usize = 0x3A4;
pub const CHRASM_SECONDARY_RIGHT_WEP_OFFSET: usize = 0x3A8;
pub const CHRASM_TERTIARY_LEFT_WEP_OFFSET: usize = 0x3AC;
pub const CHRASM_TERTIARY_RIGHT_WEP_OFFSET: usize = 0x3B0;

/// ArmStyle values. 2 = two-handed left (masks right hand), 3 = two-handed right
/// (masks left hand), 0 = empty hands.
pub const ARM_STYLE_EMPTY: u8 = 0;
pub const ARM_STYLE_TWO_HANDED_LEFT: u8 = 2;
pub const ARM_STYLE_TWO_HANDED_RIGHT: u8 = 3;

/// EquipParamWeapon row 110000 = "Unarmed" (fists). Mapped to None server-side.
pub const UNARMED_WEAPON_ID: i32 = 110000;
