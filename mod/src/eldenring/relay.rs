//! Relay race game access for the shell: the capture of the character a
//! handoff carries (attributes, level and runes, the transferable items
//! held, the graces lit). Read on the shell's relay worker thread, never on
//! the render thread nor per frame. What the reads must pass and what the
//! state holds is decided in `core::relay_capture` and `core::relay_items`;
//! this module only reads, and never writes.
//!
//! ### Sources
//!
//! - Attributes, level and runes: libeldenring's `Pointers::character_stats`
//!   (GameDataMan, +0x8 PlayerGameData, +0x3C: eight `i32` from vigor to
//!   arcane, the level at +0x68 and the runes held at +0x6C).
//! - Items: the held inventory's normal and key lists, as
//!   `race_items::HeldInventory` copies them.
//! - Goods types: `EquipParamGoods.goods_type`; grace flags:
//!   `BonfireWarpParam.eventflag_id` (libeldenring's param codegen), read
//!   once per process.
//! - Graces lit: each grace flag through `EventFlagReader::is_flag_set`.
//!
//! ### Reading off the render thread
//!
//! Every read of game memory goes through `ReadProcessMemory` (libeldenring's
//! `PointerChain`, `race_items::read_bytes`, the event flag reader), which
//! fails instead of faulting on an unmapped address, as the item spawner's
//! thread already reads flags and the IGT. The param rows are the game's
//! static tables, read by value as `race_items` reads them. A load starting
//! during the reads is caught by reading the loaded map before and after them
//! (`core::relay_capture::no_load_between`).

use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::Instant;

use libeldenring::params::{BonfireWarpParam, EquipParamGoods, PARAMS};
use libeldenring::pointers::Pointers;
use tracing::{info, warn};

use super::race_items::HeldInventory;
use super::{EventFlagReader, FlagReaderStatus, GameState};
use crate::core::item_inventory::held_item_ids;
use crate::core::protocol::CharacterState;
use crate::core::relay_capture::{
    build_state, goods_type_map, grace_flag_ids, lit_flags, no_load_between, stats_from_game,
    CaptureFailure,
};
use crate::profile_span;

/// The attributes in the wire order (vigor to arcane), level and runes;
/// `None` when unreadable or negative (`core::relay_capture::stats_from_game`).
pub fn read_stats() -> Option<([u32; 8], u32, u32)> {
    profile_span!("relay.read_stats");
    let stats = Pointers::new().character_stats.read()?;
    stats_from_game(
        [
            stats.vigor,
            stats.mind,
            stats.endurance,
            stats.strength,
            stats.dexterity,
            stats.intelligence,
            stats.faith,
            stats.arcane,
        ],
        stats.level,
        stats.runes,
    )
}

/// The item ids held in the inventory's normal and key lists
/// (`core::item_inventory::held_item_ids`, so empty entries and spent stacks
/// are left out); `None` when the inventory is unreadable
/// (`HeldInventory::read`).
pub fn held_items() -> Option<Vec<u32>> {
    profile_span!("relay.held_items");
    let inventory = HeldInventory::read()?;
    Some(
        held_item_ids(inventory.normal_entries())
            .chain(held_item_ids(inventory.key_entries()))
            .collect(),
    )
}

/// `EquipParamGoods.goods_type` by row id, from one pass over the table at
/// the first call that reads it, then kept for the process: the regulation
/// does not change in a session. `None`, with nothing kept, while the table
/// does not read. Waits for the game's params to be indexed (it forces
/// libeldenring's `PARAMS`, as `race_items::prewarm_params` does): off the
/// render thread only.
pub fn goods_types() -> Option<&'static HashMap<u32, u8>> {
    static GOODS_TYPES: OnceLock<HashMap<u32, u8>> = OnceLock::new();
    if let Some(types) = GOODS_TYPES.get() {
        return Some(types);
    }
    profile_span!("relay.goods_types");
    let params = PARAMS.read();
    // SAFETY: the params live for the whole game session and libeldenring
    // casts each row to its generated struct; one field is copied out of
    // each row and no reference outlives the pass.
    let rows = unsafe { params.iter_param::<EquipParamGoods>("EquipParamGoods") }?;
    let types = goods_type_map(rows.filter_map(|row| Some((row.id, row.param?.goods_type))))?;
    info!(rows = types.len(), "[RELAY] Goods types read");
    Some(GOODS_TYPES.get_or_init(|| types))
}

/// The grace flags (`core::relay_capture::grace_flag_ids` over the
/// `eventflag_id` of every `BonfireWarpParam` row), read and kept as
/// `goods_types` is.
pub fn grace_flags() -> Option<&'static [u32]> {
    static GRACE_FLAGS: OnceLock<Vec<u32>> = OnceLock::new();
    if let Some(flags) = GRACE_FLAGS.get() {
        return Some(flags);
    }
    profile_span!("relay.grace_flags");
    let params = PARAMS.read();
    // SAFETY: as in `goods_types`.
    let rows = unsafe { params.iter_param::<BonfireWarpParam>("BonfireWarpParam") }?;
    let flags = grace_flag_ids(rows.filter_map(|row| row.param.map(|row| row.eventflag_id)))?;
    info!(flags = flags.len(), "[RELAY] Grace flags read");
    Some(GRACE_FLAGS.get_or_init(|| flags))
}

/// Capture the character for a relay state, on the calling (worker)
/// thread: `None` when any read fails or does not pass its check
/// (`core::relay_capture::CaptureFailure`), never a state partly read. The
/// state is fitted to the wire caps. Logs the outcome once, with the counts
/// or the reason and the duration; `generation` is the capture's, for the
/// log.
pub fn capture(
    reader: &EventFlagReader,
    game: &GameState,
    generation: u64,
) -> Option<CharacterState> {
    profile_span!("relay.capture");
    let started = Instant::now();
    let result = read_state(reader, game);
    let elapsed_ms = started.elapsed().as_millis() as u64;
    match result {
        Ok(read) => {
            if read.cut > 0 {
                warn!(
                    generation,
                    cut = read.cut,
                    "[RELAY] State cut to the wire caps"
                );
            }
            info!(
                generation,
                attributes = ?read.state.attributes,
                level = read.state.level,
                runes = read.state.runes,
                held = read.held,
                items = read.state.items.len(),
                graces_scanned = read.graces_scanned,
                graces_unreadable = read.graces_unreadable,
                graces = read.state.grace_flags.len(),
                elapsed_ms,
                "[RELAY] Character read"
            );
            Some(read.state)
        }
        Err(failure) => {
            warn!(
                generation,
                ?failure,
                elapsed_ms,
                "[RELAY] Character not read"
            );
            None
        }
    }
}

/// A capture's state and the counts its log line gives.
struct Read {
    state: CharacterState,
    /// Item ids held, before the transfer filter.
    held: usize,
    graces_scanned: usize,
    graces_unreadable: usize,
    /// Values `fit_to_wire` cut.
    cut: usize,
}

/// The reads of `capture`, in order: the param tables (the first capture of
/// the process reads them, outside the timed window), the loaded map, the
/// stats, the inventory, the grace flags, the loaded map again.
fn read_state(reader: &EventFlagReader, game: &GameState) -> Result<Read, CaptureFailure> {
    let goods_types = goods_types().ok_or(CaptureFailure::ParamsUnreadable)?;
    let grace_flags = grace_flags().ok_or(CaptureFailure::ParamsUnreadable)?;
    let before = game.loaded_map_id().ok_or(CaptureFailure::NotLoaded)?;
    let reads_started = Instant::now();
    let stats = read_stats().ok_or(CaptureFailure::StatsUnreadable)?;
    let held = held_items().ok_or(CaptureFailure::InventoryUnreadable)?;
    // Checked before the scan: a reader with no divisor warns once per flag.
    if !matches!(reader.diagnose(), FlagReaderStatus::Ok { divisor, .. } if divisor != 0) {
        return Err(CaptureFailure::FlagsUnreadable);
    }
    let (lit, graces_unreadable) = {
        profile_span!("relay.grace_scan");
        lit_flags(grace_flags, |flag| reader.is_flag_set(flag))?
    };
    if !no_load_between(before, game.loaded_map_id(), reads_started.elapsed()) {
        return Err(CaptureFailure::LoadDuringCapture);
    }
    let (state, cut) = build_state(stats, held.iter().copied(), goods_types, lit)?;
    Ok(Read {
        state,
        held: held.len(),
        graces_scanned: grace_flags.len(),
        graces_unreadable,
        cut,
    })
}
