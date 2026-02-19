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
