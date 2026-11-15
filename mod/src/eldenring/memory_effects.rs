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
//!   module container, + 0x28 behavior module, + 0x17C8 f32, 1 by default)
//!   and `torrent_animation_speed` (the same chain on Torrent, resolved by
//!   group, else from the summon buddy set's first entry).
//! - Camera: every LockCamParam row's `camDistTarget`, `chrOrgOffset_Y` and
//!   `camFovY`, through libeldenring's in-memory params (Crowd Control
//!   writes row 0 the same way, the TGA table's custom FOV every row).
//! - Foes: WorldChrMan's chr sets (fromsoftware-rs `cs/world_chr_man.rs`,
//!   offsets checked in the 1.17.0 executable): the set count at + 0x1CC58,
//!   the set pointers at + 0x1DED8, the player chr set at + 0x10EE0, the
//!   summon buddy set's holder at + 0x1CC90 (libeldenring's
//!   `torrent_enemy_ins`); a ChrSet holds its capacity at + 0x10 and its
//!   entries at + 0x18. Every offset is below PlayerIns (+ 0x1E508), the same
//!   on 1.17.0 and 1.17.2; the fields after it moved between the two, and
//!   none is used.
//!
//! Unverified by this mod in game until the lot's checks.

use std::collections::{HashMap, HashSet};
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
    self, RenderWrite, CHR_SET_ENTRY_SIZE, MAX_CHR_SETS, MAX_CHR_SET_CAPACITY, RENDER_BIT,
};
use crate::core::memory_effects::CameraRow;
use crate::core::protocol::CameraVariant;
use crate::profile_span;

const CHR_INS_RENDER_FLAGS_OFFSET: usize = 0x1C5;
const CHR_INS_CHR_CTRL_OFFSET: usize = 0x58;
const CHR_CTRL_SCALE_OFFSET: usize = 0x2D4;

const WCM_PLAYER_CHR_SET_OFFSET: usize = 0x10EE0;
const WCM_CHR_SET_COUNT_OFFSET: usize = 0x1CC58;
const WCM_TORRENT_CHR_SET_OFFSET: usize = 0x1CC90;
const WCM_CHR_SETS_OFFSET: usize = 0x1DED8;
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

/// The player's PlayerIns, 0 while the player is not loaded.
pub fn player_ins() -> usize {
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
/// unwritable; Torrent not found is only logged at debug level.
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
    match pointers.torrent_animation_speed.resolve() {
        SpeedTargetResolution::Ready(torrent) => match torrent.read() {
            Some(before) if before != speed => {
                if torrent.write(speed).is_some() {
                    info!(before, speed, "[ITEMS] Torrent animation speed written");
                } else {
                    debug!(speed, "[ITEMS] Torrent animation speed unwritable");
                }
            }
            _ => {}
        },
        SpeedTargetResolution::Unavailable(reason) => {
            debug!(
                reason,
                speed, "[ITEMS] Torrent not found, its animation speed not written"
            );
        }
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
/// WorldChrMan's chr sets (`core::foes`), the player chr set, the player and
/// Torrent left out. `hidden` is the record of the characters the mod hid;
/// a show walk forgets it. Returns how many render bits changed. Every read
/// is fault-safe; each set's entries are read in one call. Only on 1.17.x,
/// the game versions whose offsets were checked.
pub fn walk_foes(hide: bool, hidden: &mut HashSet<usize>) -> usize {
    profile_span!("race_items.walk_foes");
    if !matches!(
        get_version(),
        Version::V2_07_0 | Version::V2_07_1 | Version::V2_07_2
    ) {
        warn!("[ITEMS] Foes walk skipped: chr set offsets unknown for this game version");
        return 0;
    }
    let sets_read = read_ptr(Pointers::new().base_addresses.world_chr_man).and_then(|wcm| {
        let count = PointerChain::<u32>::new(&[wcm + WCM_CHR_SET_COUNT_OFFSET]).read()?;
        let count = count.min(MAX_CHR_SETS) as usize;
        let pointers = read_bytes(wcm + WCM_CHR_SETS_OFFSET, count * 8)?;
        Some((wcm, pointers))
    });
    let Some((wcm, set_pointers)) = sets_read else {
        warn!(hide, "[ITEMS] Foes walk skipped: chr sets unreadable");
        return 0;
    };
    let player = read_ptr(wcm + player_ins_offset()).unwrap_or(0);
    let torrent = read_ptr(wcm + WCM_TORRENT_CHR_SET_OFFSET)
        .and_then(|set| read_ptr(set + CHR_SET_ENTRIES_OFFSET))
        .and_then(read_ptr)
        .unwrap_or(0);
    let (mut sets, mut slots, mut visited, mut unreadable, mut changed, mut capped) =
        (0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    for set in foes::chr_sets(&set_pointers, wcm + WCM_PLAYER_CHR_SET_OFFSET) {
        let Some(head) = PointerChain::<ChrSetHead>::new(&[set + CHR_SET_HEAD_OFFSET]).read()
        else {
            continue;
        };
        if head.capacity == 0 || head.entries == 0 {
            continue;
        }
        if head.capacity > MAX_CHR_SET_CAPACITY {
            capped += 1;
        }
        let capacity = head.capacity.min(MAX_CHR_SET_CAPACITY) as usize;
        let Some(entries) = read_bytes(head.entries, capacity * CHR_SET_ENTRY_SIZE) else {
            continue;
        };
        sets += 1;
        slots += capacity;
        let plan = foes::plan_chr_set(
            &entries,
            player,
            torrent,
            |chr| PointerChain::<u8>::new(&[chr + CHR_INS_RENDER_FLAGS_OFFSET]).read(),
            hide,
            hidden,
        );
        visited += plan.visited;
        unreadable += plan.unreadable;
        for write in plan.writes {
            let (chr, shown) = match write {
                RenderWrite::Hide(chr) => (chr, false),
                RenderWrite::Show(chr) => (chr, true),
            };
            if set_render_bit(chr, shown).is_some_and(|before| (before & RENDER_BIT != 0) != shown)
            {
                changed += 1;
            }
        }
    }
    foes::finish_walk(hide, hidden);
    info!(
        hide,
        sets,
        slots,
        visited,
        unreadable,
        changed,
        recorded = hidden.len(),
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
