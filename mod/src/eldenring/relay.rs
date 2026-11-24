//! Relay race game access for the shell: the capture of what a handoff
//! carries (the graces lit), the apply of a take (the plan of the flags to
//! raise, the flag raises), the read of the save's token, and the give of
//! the team's boss loot. The capture and the plan read on the shell's relay
//! worker thread, never on the tracker's frame thread nor per frame; the
//! writes are made on the tracker's frame thread (the Present hook, not the
//! game's own threads), `step_writer` a bounded batch per frame. The token is
//! read on the frame thread, on the frames the machine asks for it only
//! (`read_token`), and written there too (`write_token`), its flags and
//! values never logged. A loot entry is read and given on the frame thread,
//! one entry on a frame the machine hands it out (`apply_loot`). What the
//! reads must pass, what a state holds, what an apply writes, what a token
//! read means and what a loot entry needs is decided in
//! `core::relay_capture`, `core::relay_apply`, `core::relay_token` and
//! `core::relay_loot`.
//!
//! ### Sources
//!
//! - Grace flags: `BonfireWarpParam.eventflag_id` (libeldenring's param
//!   codegen), read once per process. A table that does not read fails no
//!   capture: it is warned once and left empty (no grace transfers).
//! - Graces lit: each grace flag through `EventFlagReader::is_flag_set`.
//! - Flag raises: `EventFlagReader::set_flag_cached`.
//! - Token: the token flags through `EventFlagReader::is_flag_set_fast` and
//!   `set_flag_cached`, on their category page resolved once per read or
//!   write.
//! - Loot: its flags through `EventFlagReader::is_flag_set` and `set_flag`
//!   (they sit in several categories), its items through
//!   `item_spawner::inject_one`, its runes through
//!   `sp_effect_apply::apply_speffect`.
//!
//! ### Reading off the frame thread
//!
//! Every read of game memory goes through `ReadProcessMemory` (libeldenring's
//! pointer chains behind the loaded map, the event flag reader), which fails
//! instead of faulting on an unmapped address, as the item spawner's thread
//! already reads flags and the IGT. The param rows are not: they are
//! dereferenced directly (libeldenring hands out references into the game's
//! param tables, which live for the session), as `race_items` reads and
//! writes them; one field is copied out of each row. A load starting during
//! a capture's reads is caught by reading the loaded map before and after
//! them (`core::relay_capture::no_load_between`); during an apply's, by the
//! frame thread's watch of every frame's map since the ask.
//!
//! ### Writing on the tracker's frame thread
//!
//! Every write is made on the tracker's frame thread (the Present hook, not
//! the game's own threads), on frames the take's checks passed, through the
//! event flag reader, as the lock and the race item flags are written. None
//! of these writes is synchronised with the game's own threads, as the race
//! items' and the lock's writes are not: a flag raise is a read-modify-write
//! of a byte the game may write at the same moment, and nothing proves it
//! never does. An apply stops writing at the first frame since its ask that
//! read another map or none (`core::relay_apply::ApplyRun`).

use std::sync::OnceLock;
use std::time::Instant;

use libeldenring::params::{BonfireWarpParam, PARAMS};
use tracing::{info, warn};

use super::{item_spawner, sp_effect_apply, EventFlagReader, FlagReaderStatus, GameState};
use crate::core::protocol::{CharacterState, RelayLootEntry};
use crate::core::relay_apply::{self, ApplyPlan, ApplyStep};
use crate::core::relay_capture::{
    build_state, grace_flag_ids, lit_flags, no_load_between, CaptureFailure,
};
use crate::core::relay_loot::{self, LootOutcome};
use crate::core::relay_token;
use crate::profile_span;

/// The grace flags (`core::relay_capture::grace_flag_ids` over the
/// `eventflag_id` of every `BonfireWarpParam` row), from one pass over the
/// table at the first call, then kept for the process: the regulation does
/// not change in a session. A table that does not read (not indexed, or no
/// usable row) is warned once, with its cause, and kept empty: the states of
/// the session carry no grace. Waits for the game's params to be indexed (it
/// forces libeldenring's `PARAMS`, as `race_items::prewarm_params` does):
/// off the frame thread only.
pub fn grace_flags() -> &'static [u32] {
    static GRACE_FLAGS: OnceLock<Vec<u32>> = OnceLock::new();
    GRACE_FLAGS.get_or_init(|| {
        profile_span!("relay.grace_flags");
        let params = PARAMS.read();
        // SAFETY: the params live for the whole game session and libeldenring
        // casts each row to its generated struct, a reference into the game's
        // table; one field is copied out of each row and no reference
        // outlives the pass (as `race_items::param_row`'s callers do).
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

/// Capture the state of a handoff, on the calling (worker) thread: `None`
/// when any read fails or does not pass its check
/// (`core::relay_capture::CaptureFailure`), never a state partly read. The
/// state is fitted to the wire caps. Logs the outcome once, with the counts
/// or the reason, and the duration; `generation` is the capture's, for the
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
    graces_scanned: usize,
    graces_unreadable: usize,
    /// Values `fit_to_wire` cut.
    cut: usize,
}

/// The reads of `capture`, in order: the grace table (the first capture of
/// the process reads it, outside the timed window), the loaded map, the
/// grace flags, the loaded map again.
fn read_state(reader: &EventFlagReader, game: &GameState) -> Result<Read, CaptureFailure> {
    let grace_flags = grace_flags();
    let before = game.loaded_map_id().ok_or(CaptureFailure::NotLoaded)?;
    let reads_started = Instant::now();
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
    let (state, cut) = build_state(lit);
    Ok(Read {
        state,
        graces_scanned: grace_flags.len(),
        graces_unreadable,
        cut,
    })
}

/// What an apply writes (`core::relay_apply::plan`), on the calling (worker)
/// thread: the take's boss defeat flags and those of the state's grace flags
/// that are graces of this game. Writes nothing. Logs the plan once, with the
/// counts, the grace flags left out, and the duration; `generation` is the
/// apply's, for the log.
pub fn plan_apply(defeat_flags: &[u32], state_graces: &[u32], generation: u64) -> ApplyPlan {
    profile_span!("relay.apply_plan");
    let started = Instant::now();
    let plan = relay_apply::plan(defeat_flags, state_graces, grace_flags());
    let counts = plan.counts;
    info!(
        generation,
        defeats = counts.defeats,
        graces = counts.graces,
        not_grace = counts.not_grace,
        not_graces = ?plan.not_graces,
        elapsed_ms = started.elapsed().as_millis() as u64,
        "[RELAY] Apply planned"
    );
    plan
}

/// The value the relay token flags hold (`bits` flags from `base`, bit `i`
/// in flag `base + i`: `core::relay_token::value_of`), on the tracker's frame
/// thread, on a frame the machine asked for it: `None` when the category page
/// does not resolve or any flag cannot be read. The page is resolved once
/// and each flag read from it (a flag of another category falls back to a
/// full lookup).
pub fn read_token(reader: &EventFlagReader, base: u32, bits: u32) -> Option<u32> {
    profile_span!("relay.read_token");
    let page = reader.resolve_category(base)?;
    let mut unreadable = false;
    let value = relay_token::value_of((0..bits).map_while(|i| {
        let set = reader.is_flag_set_fast(base.wrapping_add(i), &page);
        unreadable |= set.is_none();
        set
    }));
    (!unreadable).then_some(value)
}

/// Write the relay token's flags, each to its value
/// (`core::relay_token::writes`), on the tracker's frame thread: the category
/// page resolved once from the first flag and reused (a flag of another
/// category falls back to a full lookup). Returns how many could not be
/// written. Logs nothing: the flags and their values spell the token.
pub fn write_token(reader: &EventFlagReader, flags: &[(u32, bool)]) -> usize {
    profile_span!("relay.write_token");
    let page = flags
        .first()
        .and_then(|&(flag, _)| reader.resolve_category(flag));
    flags
        .iter()
        .filter(|&&(flag, value)| !reader.set_flag_cached(flag, value, page.as_ref()))
        .count()
}

/// Give one entry of the team's boss loot, on the tracker's frame thread, on
/// the frame the machine handed it out: read in the save the flags its
/// decision needs (`core::relay_loot::decide_reading`, which says which and
/// in what order), then carry out what it decides
/// (`core::relay_loot::carry_out`): the items given one unit at a time
/// through the item spawner, the rune effect through the SpEffect apply
/// function, the flags raised through the event flag reader. A flag that
/// cannot be raised is warned, with its id; a give whose received flag it
/// is says so (`LootOutcome::Given { marked: false, .. }`). `Unreadable`
/// when nothing was done: a flag the decision needs did not read, the game
/// refused the first give, or a mark's received flag could not be raised.
pub fn apply_loot(reader: &EventFlagReader, entry: &RelayLootEntry, paid: bool) -> LootOutcome {
    profile_span!("relay.apply_loot");
    let Some(action) = relay_loot::decide_reading(entry, paid, |flag| reader.is_flag_set(flag))
    else {
        return LootOutcome::Unreadable;
    };
    relay_loot::carry_out(
        action,
        entry,
        item_spawner::inject_one,
        sp_effect_apply::apply_speffect,
        |flag| {
            let raised = reader.set_flag(flag, true);
            if !raised {
                warn!(flag, "[RELAY] Loot flag not raised");
            }
            raised
        },
    )
}

/// The writer of an apply's steps for one frame, on the tracker's frame
/// thread (true when the write was made): a flag is raised through the event
/// flag reader, the category page resolved at the frame's first flag and
/// reused, a flag of another category falling back to a full lookup (as
/// `execute_effects` writes `SetGameFlag`).
pub fn step_writer(reader: &EventFlagReader) -> impl FnMut(ApplyStep) -> bool + '_ {
    let mut page = None;
    move |step| match step {
        ApplyStep::Defeat(flag) | ApplyStep::Grace(flag) => {
            profile_span!("relay.raise_flag");
            let page = page.get_or_insert_with(|| reader.resolve_category(flag));
            reader.set_flag_cached(flag, true, page.as_ref())
        }
    }
}
