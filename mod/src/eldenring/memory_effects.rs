//! Memory race item effects written into the game (`core::memory_effects`):
//! the player's render bit, scale and animation speed (Torrent's too), the
//! LockCamParam rows, and the walk over the characters around for Unseen
//! Foes. Called when the race machine emits `Effect::ApplyMemoryState` (a
//! change, a loading exit, every 250 ms while an effect is live; the walk at
//! most once a second), never per frame.
//!
//! Each setter returns whether the game now holds the value (written, or
//! already there), and logs at info only when the value in the game changed:
//! the first write, the restore, or a refresh against the game resetting it.
//! The foes walk returns how many characters it changed and logs each walk.
//! Every read after PlayerIns is fault-safe (`ReadProcessMemory`); PlayerIns
//! itself is read raw, as the SpEffect apply reads it, and the LockCamParam
//! rows are read and written in process, volatile.
//!
//! ### Layout sources
//!
//! - Render bit: ChrIns + 0x1C5, bit 3 (`enable_render`, fromsoftware-rs
//!   `cs/chr_ins.rs` `ChrInsFlags1c5`; Hexinton "ToggleDraw"; Crowd Control's
//!   invisibility writes the same bit). The game writes bit 1 of that byte
//!   every frame, from its own thread.
//! - Scale: ChrIns + 0x58 is ChrCtrl, which holds the scale, three f32
//!   (x, y, z) at + 0x2D4 (fromsoftware-rs `ChrCtrl.scale_size_*`;
//!   Hexinton "Model width"; Crowd Control's giant and tiny), 1 by default.
//! - Animation speed: libeldenring's `animation_speed` (PlayerIns + 0x190
//!   module container, + 0x28 behavior module, + 0x17C8 f32, 1 by default),
//!   and the same chain on Torrent, the first entry of the summon buddy set
//!   (see Foes below; the game fills its first slots with horses, Torrent
//!   first in a solo world, read in the 1.17.0 executable and checked in
//!   game by docs/RACE_ITEMS.md H.4). Only on 1.17.x, like the foes walk; another
//!   version falls back to libeldenring's `torrent_animation_speed`, whose
//!   group lookup and static slot (the third chr set holder, the summon
//!   buddy set only while no legacy block set is registered) can land on
//!   another character.
//! - Camera: every LockCamParam row's `camDistTarget`, `chrOrgOffset_Y` and
//!   `camFovY`, through libeldenring's in-memory params (Crowd Control
//!   writes row 0 the same way, the TGA table's custom FOV every row).
//! - Foes: WorldChrMan's chr sets (fromsoftware-rs `cs/world_chr_man.rs`,
//!   offsets checked in the 1.17.0 executable): the set count at + 0x1CC58
//!   and as many holders from + 0x1CC60 (`core::foes::CHR_SET_HOLDER_SIZE`;
//!   the game registers a set by inserting its holder in index order and
//!   writing `chr_sets[index]` at + 0x1DED8, an array with holes, not
//!   walked), the player, ghost, summon buddy (Torrent its first entry,
//!   spirit ashes after it) and debug chr sets embedded at WorldChrMan +
//!   0x10EE0, 0x10F38, 0x10F90 and 0x10FE8 (no foes: left out); a ChrSet
//!   holds its capacity at + 0x10 and its entries at + 0x18, every non-null
//!   one walked (the game's own list of the characters it updates, rebuilt
//!   each frame at + 0x1F1B0 on 1.17.0 and 1.17.1 from these holders, takes
//!   the same entries, reading no load status; see `core::foes`). Every
//!   offset is below PlayerIns (+ 0x1E508), the same on 1.17.0 and 1.17.2;
//!   the fields after it moved between the two, and none is used.
//!   libeldenring's static Torrent slot (+ 0x1CC90, the third holder) is the
//!   summon buddy set only while no world block set is registered below it,
//!   so the walk reads the embedded set instead.
//!
//! Unverified by this mod in game until the lot's checks.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU8, Ordering};

use libeldenring::memedit::PointerChain;
use libeldenring::params::{LockCamParam, PARAMS};
use libeldenring::pointers::{Pointers, SpeedTargetResolution};
use libeldenring::prelude::base_addresses::Version;
use libeldenring::version::get_version;
use once_cell::sync::Lazy;
use tracing::{debug, info, warn};

use super::race_items::{read_bytes, read_ptr};
use super::sp_effect_apply::{player_ins_offset, read_player_ins};
use crate::core::foes::{
    self, FoesRecord, RenderWrite, CHR_SET_ENTRY_SIZE, HOLDER_BLOCK_SIZE, MAX_CHR_SET_CAPACITY,
    RENDER_BIT,
};
use crate::core::memory_effects::CameraRow;
use crate::core::protocol::CameraVariant;
use crate::profile_span;

const CHR_INS_RENDER_FLAGS_OFFSET: usize = 0x1C5;
/// ChrIns + 0x190: its module container; + 0x28 there, the behavior module,
/// whose f32 at + 0x17C8 is the animation speed (libeldenring's chain).
const CHR_INS_MODULES_OFFSET: usize = 0x190;
const MODULES_BEHAVIOR_OFFSET: usize = 0x28;
const BEHAVIOR_ANIM_SPEED_OFFSET: usize = 0x17C8;
const CHR_INS_CHR_CTRL_OFFSET: usize = 0x58;
const CHR_CTRL_SCALE_OFFSET: usize = 0x2D4;

const WCM_PLAYER_CHR_SET_OFFSET: usize = 0x10EE0;
const WCM_GHOST_CHR_SET_OFFSET: usize = 0x10F38;
const WCM_SUMMON_BUDDY_CHR_SET_OFFSET: usize = 0x10F90;
const WCM_DEBUG_CHR_SET_OFFSET: usize = 0x10FE8;
/// The set count, its holders right after it (`core::foes::HOLDER_BLOCK_SIZE`).
const WCM_CHR_SET_COUNT_OFFSET: usize = 0x1CC58;
/// ChrSet + 0x10: its capacity, then its entries pointer at + 0x18.
const CHR_SET_HEAD_OFFSET: usize = 0x10;
const CHR_SET_ENTRIES_OFFSET: usize = 0x18;

/// ChrSet + 0x10 to + 0x20, read in one go.
#[repr(C)]
#[derive(Clone, Copy)]
struct ChrSetHead {
    capacity: u32,
    _pad: u32,
    entries: usize,
}

/// Whether the WorldChrMan offsets this module walks are known: 1.17.x,
/// the game versions they were checked on.
fn chr_set_offsets_known() -> bool {
    matches!(
        get_version(),
        Version::V2_07_0 | Version::V2_07_1 | Version::V2_07_2
    )
}

/// Torrent's animation speed: the first entry of the summon buddy set
/// embedded in WorldChrMan, through the player's chain. None when that
/// entry is empty or unreadable. 1.17.x only (`chr_set_offsets_known`).
fn torrent_animation_speed() -> Option<PointerChain<f32>> {
    let wcm = read_ptr(Pointers::new().base_addresses.world_chr_man)?;
    let torrent = read_ptr(wcm + WCM_SUMMON_BUDDY_CHR_SET_OFFSET + CHR_SET_ENTRIES_OFFSET)
        .and_then(read_ptr)
        .filter(|&chr| chr != 0)?;
    Some(PointerChain::new(&[
        torrent + CHR_INS_MODULES_OFFSET,
        MODULES_BEHAVIOR_OFFSET,
        BEHAVIOR_ANIM_SPEED_OFFSET,
    ]))
}

/// The player's PlayerIns, 0 while the player is not loaded.
fn player_ins() -> usize {
    read_player_ins(&Pointers::new()) as usize
}

/// Draw the player (`shown`) or not. False when the player or its render
/// byte is unreadable.
pub fn set_player_rendered(shown: bool) -> bool {
    profile_span!("race_items.set_player_rendered");
    let player = player_ins();
    if player == 0 {
        return false;
    }
    let Some(before) = set_render_bit(player, shown) else {
        return false;
    };
    if (before & RENDER_BIT != 0) != shown {
        info!(
            shown,
            byte_before = format!("{before:#04x}"),
            "[ITEMS] Player render bit written"
        );
    }
    true
}

/// Set the player's scale on its three axes. False when the player or its
/// ChrCtrl is unreadable, or the write fails.
pub fn set_player_scale(scale: f32) -> bool {
    profile_span!("race_items.set_player_scale");
    let player = player_ins();
    if player == 0 {
        return false;
    }
    let chain =
        PointerChain::<[f32; 3]>::new(&[player + CHR_INS_CHR_CTRL_OFFSET, CHR_CTRL_SCALE_OFFSET]);
    let Some(before) = chain.read() else {
        return false;
    };
    let scale_xyz = [scale; 3];
    if before == scale_xyz {
        return true;
    }
    if chain.write(scale_xyz).is_none() {
        return false;
    }
    info!(?before, scale, "[ITEMS] Player scale written");
    true
}

/// Set the player's animation speed, and Torrent's when it is loaded (a
/// slowed runner does not escape on horseback; Torrent's speed is the
/// gait while mounted). False when the player's is unreadable or
/// unwritable; Torrent not found, or holding no plausible speed (another
/// layout), is only logged at debug level.
pub fn set_anim_speed(speed: f32) -> bool {
    profile_span!("race_items.set_anim_speed");
    let pointers = Pointers::new();
    let Some(before) = pointers.animation_speed.read() else {
        return false;
    };
    if before != speed {
        if pointers.animation_speed.write(speed).is_none() {
            return false;
        }
        info!(before, speed, "[ITEMS] Player animation speed written");
    }
    let torrent = if chr_set_offsets_known() {
        torrent_animation_speed().ok_or("summon buddy set entry empty")
    } else {
        match pointers.torrent_animation_speed.resolve() {
            SpeedTargetResolution::Ready(torrent) => Ok(torrent),
            SpeedTargetResolution::Unavailable(reason) => Err(reason),
        }
    };
    let torrent = match torrent {
        Ok(torrent) => torrent,
        Err(reason) => {
            debug!(
                reason,
                speed, "[ITEMS] Torrent not found, its animation speed not written"
            );
            return true;
        }
    };
    match torrent.read() {
        Some(before) if !(0.01..=100.0).contains(&before) => {
            debug!(
                before,
                speed, "[ITEMS] Torrent animation speed implausible, not written"
            );
        }
        Some(before) if before != speed => {
            if torrent.write(speed).is_some() {
                info!(before, speed, "[ITEMS] Torrent animation speed written");
            } else {
                debug!(speed, "[ITEMS] Torrent animation speed unwritable");
            }
        }
        _ => {}
    }
    true
}

/// Write the Camera into every LockCamParam row (`Some`), or the rows'
/// saved values back (`None`). A row's values are saved into `originals`
/// the first time it is written, while it still holds the regulation's
/// (the params live until the game exits, so a race restart or a quit-out
/// keeps what was written), and each write derives from them, so one
/// variant after another never stacks. Writing them back empties
/// `originals`; with nothing saved, `None` writes nothing and returns
/// false. False too while the params are not indexed yet
/// (`race_items::prewarm_params`) or no row is found.
pub fn set_camera(variant: Option<CameraVariant>, originals: &mut HashMap<u64, CameraRow>) -> bool {
    profile_span!("race_items.set_camera");
    if variant.is_none() && originals.is_empty() {
        return false;
    }
    let Some(params) = Lazy::get(&PARAMS).map(|lock| lock.read()) else {
        return false;
    };
    // SAFETY: as `race_items::param_row`: the rows live for the whole game
    // session; their fields are read and stored one at a time, volatile,
    // and no reference outlives this call.
    let Some(rows) = (unsafe { params.iter_param::<LockCamParam>("LockCamParam") }) else {
        return false;
    };
    let Some(variant) = variant else {
        let mut restored = 0usize;
        for row in rows {
            if let (Some(data), Some(&original)) = (row.param, originals.get(&row.id)) {
                write_camera_row(data, original);
                restored += 1;
            }
        }
        info!(restored, "[ITEMS] Camera rows restored");
        originals.clear();
        return true;
    };
    let saved_before = originals.len();
    let (mut count, mut changed) = (0usize, 0usize);
    for row in rows {
        let Some(data) = row.param else {
            continue;
        };
        count += 1;
        let current = read_camera_row(data);
        let target = originals
            .entry(row.id)
            .or_insert(current)
            .with_variant(variant);
        if current != target {
            write_camera_row(data, target);
            changed += 1;
        }
    }
    if originals.len() > saved_before {
        info!(
            saved = originals.len() - saved_before,
            "[ITEMS] Camera rows saved"
        );
    }
    if changed > 0 {
        info!(
            ?variant,
            rows = count,
            changed,
            "[ITEMS] Camera rows written"
        );
    }
    count > 0
}

/// Hide (`hide`) or show the characters around: one bounded walk over
/// WorldChrMan's chr sets (`core::foes`), the player, ghost, summon buddy
/// and debug chr sets, the player and Torrent left out. `record` holds the characters the
/// mod hid: a hide walk rebuilds it from what it met (each hide recorded
/// once its write worked), a show walk empties it. Returns how many render
/// bits changed. Every read is fault-safe; each set's entries are read in
/// one call. Only on 1.17.x (`chr_set_offsets_known`).
pub fn walk_foes(hide: bool, record: &mut FoesRecord) -> usize {
    profile_span!("race_items.walk_foes");
    let mut walk = record.walk(hide);
    if !chr_set_offsets_known() {
        warn!("[ITEMS] Foes walk skipped: chr set offsets unknown for this game version");
        walk.missed_set();
        walk.finish();
        return 0;
    }
    let sets_read = read_ptr(Pointers::new().base_addresses.world_chr_man).and_then(|wcm| {
        let block = read_bytes(wcm + WCM_CHR_SET_COUNT_OFFSET, HOLDER_BLOCK_SIZE)?;
        Some((wcm, block))
    });
    let Some((wcm, block)) = sets_read else {
        warn!(hide, "[ITEMS] Foes walk skipped: chr sets unreadable");
        walk.missed_set();
        walk.finish();
        return 0;
    };
    let (set_count, holders) = foes::holders_in(&block);
    // A set registered or dropped meanwhile shifts the holders: the walk may
    // have missed one.
    if PointerChain::<u32>::new(&[wcm + WCM_CHR_SET_COUNT_OFFSET]).read() != Some(set_count) {
        walk.missed_set();
    }
    let player = read_ptr(wcm + player_ins_offset()).unwrap_or(0);
    let torrent = read_ptr(wcm + WCM_SUMMON_BUDDY_CHR_SET_OFFSET + CHR_SET_ENTRIES_OFFSET)
        .and_then(read_ptr)
        .unwrap_or(0);
    let (mut sets, mut skipped, mut slots, mut visited, mut unreadable, mut changed, mut capped) =
        (0usize, 0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    let left_out = [
        wcm + WCM_PLAYER_CHR_SET_OFFSET,
        wcm + WCM_GHOST_CHR_SET_OFFSET,
        wcm + WCM_SUMMON_BUDDY_CHR_SET_OFFSET,
        wcm + WCM_DEBUG_CHR_SET_OFFSET,
    ];
    for set in foes::chr_sets(holders, &left_out) {
        let Some(head) = PointerChain::<ChrSetHead>::new(&[set + CHR_SET_HEAD_OFFSET]).read()
        else {
            skipped += 1;
            walk.missed_set();
            continue;
        };
        if head.capacity == 0 || head.entries == 0 {
            continue;
        }
        if head.capacity > MAX_CHR_SET_CAPACITY {
            capped += 1;
            walk.missed_set();
        }
        let capacity = head.capacity.min(MAX_CHR_SET_CAPACITY) as usize;
        let Some(entries) = read_bytes(head.entries, capacity * CHR_SET_ENTRY_SIZE) else {
            skipped += 1;
            walk.missed_set();
            continue;
        };
        sets += 1;
        slots += capacity;
        let plan = walk.plan_set(&entries, player, torrent, |chr| {
            PointerChain::<u8>::new(&[chr + CHR_INS_RENDER_FLAGS_OFFSET]).read()
        });
        visited += plan.visited;
        unreadable += plan.unreadable;
        for write in plan.writes {
            let (chr, shown) = match write {
                RenderWrite::Hide(chr) => (chr, false),
                RenderWrite::Show(chr) => (chr, true),
            };
            // The record learns only the writes that were made.
            let Some(before) = set_render_bit(chr, shown) else {
                continue;
            };
            walk.written(write);
            if (before & RENDER_BIT != 0) != shown {
                changed += 1;
            }
        }
    }
    let recorded = walk.finish();
    info!(
        hide,
        set_count,
        sets,
        skipped,
        slots,
        visited,
        unreadable,
        changed,
        recorded,
        torrent_found = torrent != 0,
        "[ITEMS] Foes walked"
    );
    if capped > 0 {
        warn!(
            capped,
            max = MAX_CHR_SET_CAPACITY,
            "[ITEMS] Chr sets past the capacity bound, read up to it"
        );
    }
    changed
}

/// Set (`shown`) or clear the render bit of `chr` (a ChrIns), the other
/// bits of its byte untouched. The byte before the change, `None` when it
/// is unreadable (nothing written).
fn set_render_bit(chr: usize, shown: bool) -> Option<u8> {
    let addr = chr + CHR_INS_RENDER_FLAGS_OFFSET;
    PointerChain::<u8>::new(&[addr]).read()?;
    // SAFETY: the fault-safe read above proved the byte mapped; it sits in a
    // ChrIns on the game's heap, which is read-write. The game's thread
    // writes this byte too (bit 1 every frame): a locked read-modify-write
    // changes bit 3 alone and never stores back a stale copy of the other
    // bits, as a read then a write of the byte could.
    let byte = unsafe { AtomicU8::from_ptr(addr as *mut u8) };
    Some(if shown {
        byte.fetch_or(RENDER_BIT, Ordering::SeqCst)
    } else {
        byte.fetch_and(!RENDER_BIT, Ordering::SeqCst)
    })
}

fn read_camera_row(row: &LockCamParam) -> CameraRow {
    // SAFETY: aligned f32 fields of a live param row (see `set_camera`).
    unsafe {
        CameraRow {
            dist: std::ptr::read_volatile(&row.cam_dist_target),
            height: std::ptr::read_volatile(&row.chr_org_offset_y),
            fov_y: std::ptr::read_volatile(&row.cam_fov_y),
        }
    }
}

fn write_camera_row(row: &mut LockCamParam, values: CameraRow) {
    // SAFETY: aligned f32 fields of a live param row (see `set_camera`); the
    // game reads them from its own thread, so the stores are volatile.
    unsafe {
        std::ptr::write_volatile(&mut row.cam_dist_target, values.dist);
        std::ptr::write_volatile(&mut row.chr_org_offset_y, values.height);
        std::ptr::write_volatile(&mut row.cam_fov_y, values.fov_y);
    }
}
