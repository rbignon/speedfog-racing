//! Relay race game access for the shell: the capture of the character a
//! handoff carries (attributes, level and runes, the transferable items
//! held, the graces lit), and the apply of a take (the stat write, the plan
//! of what to give and raise, the gives and flag raises). The capture and
//! the plan read on the shell's relay worker thread, never on the tracker's
//! frame thread nor per frame; the writes are made on the tracker's frame
//! thread (the Present hook, not the game's own threads): `write_stats` on
//! the take's start frame, `step_writer` a bounded batch per frame. What
//! the reads must pass, what a state holds and what an apply writes is
//! decided in `core::relay_capture`, `core::relay_items` and
//! `core::relay_apply`.
//!
//! ### Sources
//!
//! - Attributes, level and runes: libeldenring's `Pointers::character_stats`
//!   (GameDataMan, +0x8 PlayerGameData, +0x3C: eight `i32` from vigor to
//!   arcane, the level at +0x68, the runes held at +0x6C, the rune memory at
//!   +0x70, which is never written).
//! - Items: the held inventory's normal and key lists, as
//!   `race_items::HeldInventory` copies them.
//! - Goods types: `EquipParamGoods.goods_type`; grace flags:
//!   `BonfireWarpParam.eventflag_id` (libeldenring's param codegen), read
//!   once per process. A table that does not read fails no capture: it is
//!   warned once and left empty (no goods, or no grace, transfers).
//! - Graces lit: each grace flag through `EventFlagReader::is_flag_set`.
//! - The rows a give is checked against: `EquipParamWeapon` (with its
//!   `reinforceTypeId`), `ReinforceParamWeapon`, `EquipParamProtector`,
//!   `EquipParamAccessory`, `EquipParamGem`, read once per process as the
//!   goods types are; a table that does not read gives nothing of its
//!   category for the session.
//! - Gives: the game's own give function (`item_spawner::inject_one`); flag
//!   raises: `EventFlagReader::set_flag_cached`.
//!
//! ### Reading off the frame thread
//!
//! Every read of game memory goes through `ReadProcessMemory` (libeldenring's
//! `PointerChain`, `race_items::read_bytes`, the event flag reader), which
//! fails instead of faulting on an unmapped address, as the item spawner's
//! thread already reads flags and the IGT. The param rows are not: they are
//! dereferenced directly (libeldenring hands out references into the game's
//! param tables, which live for the session), as `race_items` reads and
//! writes them; one field is copied out of each row. A load starting
//! during a capture's reads is caught by reading the loaded map before and
//! after them (`core::relay_capture::no_load_between`); during an apply's, by
//! the frame thread's watch of every frame's map since the ask.
//!
//! ### Writing on the tracker's frame thread
//!
//! Every write is made on the tracker's frame thread (the Present hook, not
//! the game's own threads), on frames the take's checks passed: the stats
//! with libeldenring's `PointerChain::write` (`WriteProcessMemory`, which
//! fails instead of faulting), ten `i32` at their offsets, never the whole
//! structure; the gives through the game's own give function, called as the
//! race items call it (the tracker's main loop, on a loaded player); the
//! flags through the event flag reader, as the lock and the race item flags
//! are written. None of these writes is synchronised with the game's own
//! threads, as the race items' and the lock's writes are not: a flag raise
//! is a read-modify-write of a byte the game may write at the same moment,
//! and nothing proves it never does. An apply stops writing at the first
//! frame since its ask that read another map or none
//! (`core::relay_apply::ApplyRun`).

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;
use std::time::Instant;

use libeldenring::memedit::PointerChain;
use libeldenring::params::{BonfireWarpParam, EquipParamGoods, EquipParamWeapon, PARAMS};
use libeldenring::pointers::{CharacterStats, Pointers};
use tracing::{debug, info, warn};

use super::item_spawner::inject_one;
use super::race_items::HeldInventory;
use super::{EventFlagReader, FlagReaderStatus, GameState};
use crate::core::item_inventory::held_item_ids;
use crate::core::protocol::CharacterState;
use crate::core::relay_apply::{self, stat_writes, stats_in_place, ApplyPlan, ApplyStep, ItemRows};
use crate::core::relay_capture::{
    build_state, goods_type_map, grace_flag_ids, lit_flags, no_load_between, param_rows,
    stats_from_game, CaptureFailure, TableUnread,
};
use crate::profile_span;

/// The attributes in the wire order (vigor to arcane), level and runes;
/// `None` when unreadable or negative (`core::relay_capture::stats_from_game`).
pub fn read_stats() -> Option<([u32; 8], u32, u32)> {
    profile_span!("relay.read_stats");
    stats_in_wire_order(Pointers::new().character_stats.read()?)
}

/// `stats` as a state carries them: the attributes in the wire order, the
/// level, the runes (`None` when one is negative).
fn stats_in_wire_order(stats: CharacterStats) -> Option<([u32; 8], u32, u32)> {
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
/// the first call, then kept for the process: the regulation does not change
/// in a session. A table that does not read (not indexed, or no usable row)
/// is warned once, with its cause, and kept empty: no goods id is
/// transferable for the session, every other category still is. Waits for
/// the game's params to be indexed (it forces libeldenring's `PARAMS`, as
/// `race_items::prewarm_params` does): off the frame thread only.
pub fn goods_types() -> &'static HashMap<u32, u8> {
    static GOODS_TYPES: OnceLock<HashMap<u32, u8>> = OnceLock::new();
    GOODS_TYPES.get_or_init(|| {
        profile_span!("relay.goods_types");
        let params = PARAMS.read();
        // SAFETY: the params live for the whole game session and libeldenring
        // casts each row to its generated struct, a reference into the game's
        // table; one field is copied out of each row and no reference
        // outlives the pass (as `race_items::param_row`'s callers do).
        let rows = unsafe { params.iter_param::<EquipParamGoods>("EquipParamGoods") };
        match goods_type_map(
            rows.map(|rows| rows.filter_map(|row| Some((row.id, row.param?.goods_type)))),
        ) {
            Ok(types) => {
                info!(rows = types.len(), "[RELAY] Goods types read");
                types
            }
            Err(cause) => {
                warn!(
                    table = "EquipParamGoods",
                    ?cause,
                    "[RELAY] Param table unreadable, no goods transfers this session"
                );
                HashMap::new()
            }
        }
    })
}

/// The grace flags (`core::relay_capture::grace_flag_ids` over the
/// `eventflag_id` of every `BonfireWarpParam` row), read and kept as
/// `goods_types` is: a table that does not read is warned once and kept
/// empty, and the states of the session carry no grace.
pub fn grace_flags() -> &'static [u32] {
    static GRACE_FLAGS: OnceLock<Vec<u32>> = OnceLock::new();
    GRACE_FLAGS.get_or_init(|| {
        profile_span!("relay.grace_flags");
        let params = PARAMS.read();
        // SAFETY: as in `goods_types`.
        let rows = unsafe { params.iter_param::<BonfireWarpParam>("BonfireWarpParam") };
        match grace_flag_ids(
            rows.map(|rows| rows.filter_map(|row| row.param.map(|row| row.eventflag_id))),
        ) {
            Ok(flags) => {
                info!(flags = flags.len(), "[RELAY] Grace flags read");
                flags
            }
            Err(cause) => {
                warn!(
                    table = "BonfireWarpParam",
                    ?cause,
                    "[RELAY] Param table unreadable, no grace transfers this session"
                );
                Vec::new()
            }
        }
    })
}

/// Capture the character for a relay state, on the calling (worker)
/// thread: `None` when any read fails or does not pass its check
/// (`core::relay_capture::CaptureFailure`), never a state partly read. The
/// state is fitted to the wire caps. Logs the outcome once, with the counts
/// and the transferable ids (the held ids at debug level) or the reason, and
/// the duration; `generation` is the capture's, for the log.
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
            debug!(generation, held = ?read.held, "[RELAY] Held item ids");
            info!(
                generation,
                attributes = ?read.state.attributes,
                level = read.state.level,
                runes = read.state.runes,
                held = read.held.len(),
                transferable = read.state.items.len(),
                items = ?read.state.items,
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
    /// The item ids held, before the transfer filter.
    held: Vec<u32>,
    graces_scanned: usize,
    graces_unreadable: usize,
    /// Values `fit_to_wire` cut.
    cut: usize,
}

/// The reads of `capture`, in order: the param tables (the first capture of
/// the process reads them, outside the timed window), the loaded map, the
/// stats, the inventory, the grace flags, the loaded map again.
fn read_state(reader: &EventFlagReader, game: &GameState) -> Result<Read, CaptureFailure> {
    let goods_types = goods_types();
    let grace_flags = grace_flags();
    let before = game.loaded_map_id().ok_or(CaptureFailure::NotLoaded)?;
    let reads_started = Instant::now();
    let stats = read_stats().ok_or(CaptureFailure::StatsUnreadable)?;
    let held = held_items().ok_or(CaptureFailure::InventoryUnreadable)?;
    let (lit, graces_unreadable) = if grace_flags.is_empty() {
        (Vec::new(), 0)
    } else {
        // Checked before the scan: a reader with no divisor warns once per
        // flag.
        if !matches!(reader.diagnose(), FlagReaderStatus::Ok { divisor, .. } if divisor != 0) {
            return Err(CaptureFailure::FlagsUnreadable);
        }
        profile_span!("relay.grace_scan");
        lit_flags(grace_flags, |flag| reader.is_flag_set(flag))?
    };
    if !no_load_between(before, game.loaded_map_id(), reads_started.elapsed()) {
        return Err(CaptureFailure::LoadDuringCapture);
    }
    let (state, cut) = build_state(stats, held.iter().copied(), goods_types, lit)?;
    Ok(Read {
        state,
        held,
        graces_scanned: grace_flags.len(),
        graces_unreadable,
        cut,
    })
}

/// Write the attributes (vigor to arcane, the wire order), the level and the
/// runes held, on the tracker's frame thread: the stats chain resolved once,
/// then each value as its own `i32` at its offset
/// (`core::relay_apply::stat_writes`), as `race_items::write_hp` writes the
/// HP alone. Nothing else of the
/// structure is written: its padding and the rune memory stay as the game
/// has them. The stats at that address are read first, and nothing is
/// written unless they read as a character's
/// (`core::relay_apply::stats_in_place`). False with nothing written when a
/// value does not fit an `i32`, the chain does not resolve, or the stats
/// there do not read as a character's; false too when a write failed (the
/// others made: the caller reads the stats back).
pub fn write_stats(attributes: [u32; 8], level: u32, runes: u32) -> bool {
    profile_span!("relay.write_stats");
    let Some(writes) = stat_writes(attributes, level, runes) else {
        return false;
    };
    let Some(vigor) = Pointers::new().character_stats.eval() else {
        return false;
    };
    let vigor = vigor as usize;
    let in_place = PointerChain::<CharacterStats>::new(&[vigor])
        .read()
        .and_then(stats_in_wire_order);
    if !stats_in_place(in_place) {
        return false;
    }
    writes.iter().fold(true, |all, &(offset, value)| {
        PointerChain::<i32>::new(&[vigor + offset])
            .write(value)
            .is_some()
            && all
    })
}

/// The rows a give is checked against (`core::relay_apply::ItemRows`), read
/// once per process as `goods_types` is: the weapon rows with their
/// `reinforceTypeId` (one field copied out of each), the other tables by row
/// id alone. A table that does not read is warned once, with its cause, and
/// kept empty: nothing of its category is given for the session. Waits for
/// the game's params to be indexed: off the frame thread only.
pub fn item_rows() -> &'static ItemRows {
    static ITEM_ROWS: OnceLock<ItemRows> = OnceLock::new();
    ITEM_ROWS.get_or_init(|| {
        profile_span!("relay.item_rows");
        fn kept<V>(table: &str, read: Result<HashMap<u32, V>, TableUnread>) -> HashMap<u32, V> {
            read.unwrap_or_else(|cause| {
                warn!(
                    table,
                    ?cause,
                    "[RELAY] Param table unreadable, nothing of its category is given this session"
                );
                HashMap::new()
            })
        }
        let params = PARAMS.read();
        // SAFETY: as in `goods_types`: one field is copied out of each row,
        // no reference outlives the pass.
        let weapons = unsafe { params.iter_param::<EquipParamWeapon>("EquipParamWeapon") };
        let weapons =
            kept(
                "EquipParamWeapon",
                param_rows(weapons.map(|rows| {
                    rows.filter_map(|row| Some((row.id, row.param?.reinforce_type_id)))
                })),
            );
        let ids = |table: &str| -> HashSet<u32> {
            // SAFETY: the params live for the whole game session; only the
            // row ids are read, no row is touched (as `param_has_row`).
            let ids = unsafe { params.iter_param_ids(table) };
            kept(table, param_rows(ids.map(|ids| ids.map(|id| (id, ())))))
                .into_keys()
                .collect()
        };
        let rows = ItemRows {
            weapons,
            reinforce: ids("ReinforceParamWeapon"),
            protectors: ids("EquipParamProtector"),
            accessories: ids("EquipParamAccessory"),
            gems: ids("EquipParamGem"),
        };
        info!(
            weapons = rows.weapons.len(),
            reinforce = rows.reinforce.len(),
            protectors = rows.protectors.len(),
            accessories = rows.accessories.len(),
            gems = rows.gems.len(),
            "[RELAY] Item rows read"
        );
        rows
    })
}

/// Ids left out for want of a row that the warning of `plan_apply` names (the
/// info line lists them all).
const UNLISTED_SHOWN: usize = 8;

/// What an apply writes (`core::relay_apply::plan`), on the calling (worker)
/// thread: the receiver's inventory read now (so a second apply of the same
/// take gives nothing it already gave), the param rows and this game's grace
/// flags. Writes nothing. Logs the plan once, with the ids to give, the ids
/// left out and why, and the duration; `generation` is the apply's, for the
/// log.
pub fn plan_apply(
    items: &[u32],
    defeat_flags: &[u32],
    state_graces: &[u32],
    generation: u64,
) -> ApplyPlan {
    profile_span!("relay.apply_plan");
    let started = Instant::now();
    let goods = goods_types();
    let rows = item_rows();
    let graces = grace_flags();
    let held = held_items();
    let plan = relay_apply::plan(
        items,
        held.as_deref(),
        goods,
        rows,
        defeat_flags,
        state_graces,
        graces,
    );
    let counts = plan.counts;
    if !counts.inventory_read {
        warn!(generation, "[RELAY] Inventory unreadable, no item given");
    }
    // A state this mod built has a row for every id: a skip says a table
    // name or the weapon rule is wrong, which must not pass unseen.
    if counts.no_row + counts.no_level > 0 {
        warn!(
            generation,
            no_row = counts.no_row,
            no_level = counts.no_level,
            first = ?&plan.unlisted[..plan.unlisted.len().min(UNLISTED_SHOWN)],
            "[RELAY] Items left out for want of a param row"
        );
    }
    let gives: Vec<u32> = plan
        .steps
        .iter()
        .filter_map(|step| match *step {
            ApplyStep::Item(id) | ApplyStep::Armor(id) => Some(id),
            ApplyStep::Defeat(_) | ApplyStep::Grace(_) => None,
        })
        .collect();
    info!(
        generation,
        offered = counts.offered,
        refused = counts.refused,
        held = held.as_ref().map(Vec::len),
        missing = counts.missing,
        no_row = counts.no_row,
        no_level = counts.no_level,
        unlisted = ?plan.unlisted,
        items = counts.items,
        armor = counts.armor,
        gives = ?gives,
        defeats = counts.defeats,
        graces = counts.graces,
        not_grace = counts.not_grace,
        not_graces = ?plan.not_graces,
        elapsed_ms = started.elapsed().as_millis() as u64,
        "[RELAY] Apply planned"
    );
    plan
}

/// The writer of an apply's steps for one frame, on the tracker's frame
/// thread (true when the write was made: for a give, that the game function
/// was called, which returns nothing to check): a give is one unit through
/// the game's own give function (`item_spawner::inject_one`; the id carries
/// its category nibble, nothing is equipped); a flag is raised through the
/// event flag reader, the category page resolved at the frame's first flag
/// and reused, a flag of another category falling back to a full lookup (as
/// `execute_effects` writes `SetGameFlag`). The gives follow the race items'
/// precedent (the frame thread, on a loaded player); the race items, refused
/// on relay races, give nothing during a take. The other caller of the give
/// function, the seed's ashes of war, runs on its own thread at the first
/// load of a fresh save, and nothing keeps it from calling the function at
/// the same moment as a take (left as it is: the race items do not guard
/// against it either).
pub fn step_writer(reader: &EventFlagReader) -> impl FnMut(ApplyStep) -> bool + '_ {
    let mut page = None;
    move |step| match step {
        ApplyStep::Item(id) | ApplyStep::Armor(id) => {
            profile_span!("relay.give");
            inject_one(id)
        }
        ApplyStep::Defeat(flag) | ApplyStep::Grace(flag) => {
            profile_span!("relay.raise_flag");
            let page = page.get_or_insert_with(|| reader.resolve_category(flag));
            reader.set_flag_cached(flag, true, page.as_ref())
        }
    }
}
