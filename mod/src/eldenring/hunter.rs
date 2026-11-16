//! The Hunter in the game: Margit spawned behind the player through the
//! game's debug character creator, looked for on the debug chr set, and
//! ended at 0 HP. Called when the race machine emits `Effect::RequestHunter`,
//! `Effect::FindHunter` and `Effect::EndHunter` (`core::hunter` decides
//! when: the looks at most every 250 ms while a spawn is awaited and every
//! second while he hunts or is watched after the last miss), never per
//! frame.
//!
//! No pointer to him is kept between calls: each look and each end walks
//! the debug chr set again, so a load that frees him leaves nothing stale.
//! Every read after WorldChrMan is fault-safe (`ReadProcessMemory`) and
//! every write goes through `WriteProcessMemory` to an address checked just
//! before: an end on a frame that is not loaded (the run ends during a
//! loading screen) logs what it could not read and writes nothing there.
//!
//! ### Layout sources (1.17.x)
//!
//! - Creator: `CS::CSDebugChrCreator` at `[WorldChrMan + 0x1E648]` on 1.17.0
//!   and 1.17.1, `[WorldChrMan + 0x1E658]` on 1.17.2
//!   (`core::hunter_spawn::creator_offset`; static scan of the three
//!   executables: the WorldChrMan constructor stores the 0x1C0-byte object
//!   there and its update calls the creator's vftable slot 2; the
//!   fromsoftware-rs bindings of 1.17.1 and 1.17.2 agree). Any other build
//!   gets no Hunter. The creator is trusted only once its RTTI name reads
//!   `.?AVCSDebugChrCreator@CS@@`: its vftable, the complete object locator
//!   right before it, the type descriptor's RVA at locator + 0xC, the name
//!   at descriptor + 0x10 (Crowd Control checks it the same way).
//! - Request, at these offsets from the creator (fromsoftware-rs
//!   `init_data`, Crowd Control's writer and the Hexinton table agree): the
//!   model name in UTF-16 at 0x100, the NpcParam row at 0xF0, the
//!   NpcThinkParam row at 0xF4, the event entity id at 0xF8 (0), the talk
//!   id at 0xFC (0), the enemy type at 0x178 (u8, 0: enemy), the
//!   CharaInitParam row at 0x17C (-1), the position x, y, z at 0xB0, then
//!   the spawn byte at 0x44 set to 1, last: the game reads the fields once
//!   it sees the byte, on its own WorldChrMan update (x86 keeps the stores
//!   in order). Only logged: the manipulator type at 0x180, the spawn count
//!   at 0x19C and the last character created at 0x1B0 (a cross-check, its
//!   meaning guessed).
//! - Position: the player's physics module (PlayerIns + 0x190, + 0x68), its
//!   position at + 0x70 and its orientation quaternion at + 0x50: the Havok
//!   frame the creator takes (libeldenring's `chunk_position`), not the
//!   world position the race reads (`core::hunter_spawn::placement`).
//! - Debug chr set, where the creator's characters land (TheHunters finds
//!   its spawns there on 1.17.1): embedded at WorldChrMan + 0x10FE8, below
//!   PlayerIns, so the same on every 1.17.x; read as the foes walk reads a
//!   set (`memory_effects`).
//! - Character: its NpcParam row at ChrIns + 0x60 (i32; the Hunter's clone
//!   row is his alone, so the row finds him), its team type at + 0x6C (u8),
//!   its event entity id at + 0x1E8; HP and max HP at + 0x138 and + 0x13C of
//!   its data module (ChrIns + 0x190, + 0), the chain libeldenring reads the
//!   player's HP through. Writing 0 HP kills (Crowd Control's "kill nearby
//!   enemies" does the same).
//!
//! Unverified by this mod in game until the Windows check.

use std::sync::OnceLock;
use std::time::Instant;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;
use libeldenring::version::get_version;
use tracing::{debug, info, warn};

use super::memory_effects::{
    ChrSetHead, CHR_INS_MODULES_OFFSET, CHR_SET_ENTRIES_OFFSET, CHR_SET_HEAD_OFFSET,
    WCM_DEBUG_CHR_SET_OFFSET,
};
use super::race_items::{read_bytes, read_ptr};
use super::scan::module_base_and_size;
use super::sp_effect_apply::{player_ins_offset, read_player_ins};
use crate::core::foes::{CHR_SET_ENTRY_SIZE, MAX_CHR_SET_CAPACITY};
use crate::core::hunter_spawn::{
    creator_offset, model_name, placement, CREATOR_RTTI_NAME, MODEL_NAME_LEN,
};
use crate::profile_span;

/// Creator + 0x44: the spawn request byte, 1 while a request waits.
const CREATOR_SPAWN_OFFSET: usize = 0x44;
const CREATOR_POSITION_OFFSET: usize = 0xB0;
const CREATOR_NPC_PARAM_OFFSET: usize = 0xF0;
const CREATOR_THINK_OFFSET: usize = 0xF4;
const CREATOR_EVENT_ENTITY_OFFSET: usize = 0xF8;
const CREATOR_TALK_OFFSET: usize = 0xFC;
const CREATOR_MODEL_NAME_OFFSET: usize = 0x100;
const CREATOR_ENEMY_TYPE_OFFSET: usize = 0x178;
const CREATOR_CHARA_INIT_OFFSET: usize = 0x17C;
const CREATOR_MANIPULATOR_OFFSET: usize = 0x180;
const CREATOR_SPAWN_COUNT_OFFSET: usize = 0x19C;
const CREATOR_LAST_CREATED_OFFSET: usize = 0x1B0;

/// The enemy type the request writes: an enemy, not a player.
const ENEMY_TYPE_ENEMY: u8 = 0;
/// The CharaInitParam row the request writes: none (only a player-type
/// spawn needs one).
const NO_CHARA_INIT: i32 = -1;

/// The complete object locator's pointer sits this far before a vftable.
const VFTABLE_LOCATOR_OFFSET: usize = 8;
/// Locator + 0xC: the type descriptor's RVA in the module (u32).
const LOCATOR_TYPE_DESCRIPTOR_OFFSET: usize = 0xC;
/// Type descriptor + 0x10: its decorated name.
const TYPE_DESCRIPTOR_NAME_OFFSET: usize = 0x10;

const CHR_INS_NPC_PARAM_OFFSET: usize = 0x60;
const CHR_INS_TEAM_TYPE_OFFSET: usize = 0x6C;
const CHR_INS_EVENT_ENTITY_OFFSET: usize = 0x1E8;
/// Module container + 0x0: the data module; + 0x68: the physics module.
const MODULES_DATA_OFFSET: usize = 0x0;
const MODULES_PHYSICS_OFFSET: usize = 0x68;
/// Data module + 0x138: HP, then max HP at + 0x13C (i32 each).
const DATA_HP_OFFSET: usize = 0x138;
const PHYSICS_ORIENTATION_OFFSET: usize = 0x50;
const PHYSICS_POSITION_OFFSET: usize = 0x70;

/// What the shell remembers of the last spawn request between its calls,
/// for its log lines alone (how long after the request, whether he was
/// seen): never a pointer to him. Held by the tracker.
#[derive(Debug, Default)]
pub struct HunterWatch {
    request: Option<Watched>,
}

#[derive(Debug)]
struct Watched {
    npc_param_id: u32,
    at: Instant,
    /// The spawn byte was seen back at 0 (logged once).
    flag_cleared: bool,
    /// The last look that saw him alive.
    seen_at: Option<Instant>,
}

impl Watched {
    fn after_ms(&self, now: Instant) -> u128 {
        now.saturating_duration_since(self.at).as_millis()
    }
}

/// A character of the Hunter's row on the debug chr set.
struct Character {
    /// Its entry's index in the set.
    index: usize,
    chr: usize,
    /// HP and max HP, `None` when unreadable.
    hp: Option<[i32; 2]>,
}

impl Character {
    fn alive(&self) -> bool {
        self.hp.is_some_and(|[hp, _]| hp > 0)
    }
}

/// The creator's offset on this game build, resolved once per process;
/// `None` (logged once) on a build other than 1.17.0, 1.17.1 and 1.17.2.
fn creator_offset_here() -> Option<usize> {
    static OFFSET: OnceLock<Option<usize>> = OnceLock::new();
    *OFFSET.get_or_init(|| {
        let (major, minor, patch): (u32, u32, u32) = get_version().into();
        let offset = creator_offset((major, minor, patch));
        match offset {
            Some(offset) => info!(
                exe_version = format_args!("{major}.{minor}.{patch}"),
                offset = format_args!("0x{offset:X}"),
                "[ITEMS] Hunter creator offset"
            ),
            None => warn!(
                exe_version = format_args!("{major}.{minor}.{patch}"),
                "[ITEMS] Hunter disabled: no debug character creator offset for this game version"
            ),
        }
        offset
    })
}

/// The value at `addr`, read with `ReadProcessMemory` (`None` instead of a
/// fault on an unmapped address).
fn read<T>(addr: usize) -> Option<T> {
    PointerChain::<T>::new(&[addr]).read()
}

/// Write `value` at `addr` with `WriteProcessMemory` (false instead of a
/// fault on an unmapped address).
fn write<T>(addr: usize, value: T) -> bool {
    PointerChain::<T>::new(&[addr]).write(value).is_some()
}

/// The creator at WorldChrMan + `offset`, once its RTTI name reads
/// `CSDebugChrCreator`; why not otherwise.
fn verified_creator(wcm: usize, offset: usize) -> Result<usize, &'static str> {
    let creator = read_ptr(wcm + offset).ok_or("creator pointer null or unreadable")?;
    let vftable = read_ptr(creator).ok_or("creator vftable unreadable")?;
    let locator = vftable
        .checked_sub(VFTABLE_LOCATOR_OFFSET)
        .and_then(read_ptr)
        .ok_or("RTTI locator unreadable")?;
    let rva = read::<u32>(locator + LOCATOR_TYPE_DESCRIPTOR_OFFSET)
        .ok_or("RTTI type descriptor unreadable")?;
    let (base, size) = module_base_and_size().ok_or("eldenring.exe module info unavailable")?;
    let name_at = rva as usize + TYPE_DESCRIPTOR_NAME_OFFSET;
    if name_at + CREATOR_RTTI_NAME.len() > size {
        return Err("RTTI type descriptor outside eldenring.exe");
    }
    let name = read_bytes(base + name_at, CREATOR_RTTI_NAME.len()).ok_or("RTTI name unreadable")?;
    if name != CREATOR_RTTI_NAME {
        warn!(
            offset = format_args!("0x{offset:X}"),
            name = %String::from_utf8_lossy(&name),
            "[ITEMS] Hunter creator RTTI name differs"
        );
        return Err("RTTI name is not CSDebugChrCreator");
    }
    Ok(creator)
}

/// A character's physics module.
fn physics(chr: usize) -> Option<usize> {
    read_ptr(chr + CHR_INS_MODULES_OFFSET).and_then(|m| read_ptr(m + MODULES_PHYSICS_OFFSET))
}

/// A character's physics position (x, y, z).
fn position(chr: usize) -> Option<[f32; 3]> {
    read(physics(chr)? + PHYSICS_POSITION_OFFSET)
}

fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    let [dx, dy, dz] = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

/// The characters of NpcParam row `npc_param_id` on the debug chr set, dead
/// or alive. `None` when the set is unreadable.
fn hunters_in_debug_set(wcm: usize, npc_param_id: u32) -> Option<Vec<Character>> {
    let set = wcm + WCM_DEBUG_CHR_SET_OFFSET;
    let head = PointerChain::<ChrSetHead>::new(&[set + CHR_SET_HEAD_OFFSET]).read()?;
    if head.capacity == 0 || head.entries == 0 {
        return Some(Vec::new());
    }
    let capacity = head.capacity.min(MAX_CHR_SET_CAPACITY) as usize;
    let entries = read_bytes(head.entries, capacity * CHR_SET_ENTRY_SIZE)?;
    let mut found = Vec::new();
    for (index, entry) in entries.chunks_exact(CHR_SET_ENTRY_SIZE).enumerate() {
        let mut pointer = [0u8; 8];
        pointer.copy_from_slice(&entry[..8]);
        let chr = u64::from_le_bytes(pointer) as usize;
        if chr == 0 || read::<u32>(chr + CHR_INS_NPC_PARAM_OFFSET) != Some(npc_param_id) {
            continue;
        }
        let hp = read_ptr(chr + CHR_INS_MODULES_OFFSET)
            .and_then(|m| read_ptr(m + MODULES_DATA_OFFSET))
            .and_then(|data| read(data + DATA_HP_OFFSET));
        found.push(Character { index, chr, hp });
    }
    Some(found)
}

/// Hand the game a spawn of the Hunter (model `c<chr_id>`, rows
/// `npc_param_id` and `think_id`) behind the player. True when the request
/// is written, or when a live character of his row is already on the debug
/// chr set (a late spawn of an earlier request: no second Margit). False,
/// with nothing queued, when this build has no creator offset, the player,
/// the creator or its RTTI is unreadable, another request is pending, the
/// player's pose is unreadable, or a field write fails. Every outcome logs
/// an `[ITEMS] Hunter` line.
pub fn request_hunter(
    chr_id: u32,
    npc_param_id: u32,
    think_id: u32,
    watch: &mut HunterWatch,
) -> bool {
    profile_span!("race_items.request_hunter");
    let Some(offset) = creator_offset_here() else {
        return false;
    };
    let pointers = Pointers::new();
    let player = read_player_ins(&pointers) as usize;
    if player == 0 {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter not requested: player not loaded"
        );
        return false;
    }
    let Some(wcm) = read_ptr(pointers.base_addresses.world_chr_man) else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter not requested: WorldChrMan unreadable"
        );
        return false;
    };
    let creator = match verified_creator(wcm, offset) {
        Ok(creator) => creator,
        Err(reason) => {
            warn!(
                npc_param_id,
                reason, "[ITEMS] Hunter not requested: creator not verified"
            );
            return false;
        }
    };
    let Some(spawn_flag) = read::<u8>(creator + CREATOR_SPAWN_OFFSET) else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter not requested: spawn byte unreadable"
        );
        return false;
    };
    info!(
        offset = format_args!("0x{offset:X}"),
        rtti = "CSDebugChrCreator",
        spawn_flag,
        manipulator = ?read::<u32>(creator + CREATOR_MANIPULATOR_OFFSET),
        spawn_count = ?read::<u32>(creator + CREATOR_SPAWN_COUNT_OFFSET),
        enemy_type = ?read::<u8>(creator + CREATOR_ENEMY_TYPE_OFFSET),
        last_created = ?read::<usize>(creator + CREATOR_LAST_CREATED_OFFSET)
            .map(|chr| format!("0x{chr:X}")),
        "[ITEMS] Hunter creator"
    );
    if spawn_flag != 0 {
        warn!(
            npc_param_id,
            spawn_flag, "[ITEMS] Hunter not requested: another spawn is pending"
        );
        return false;
    }
    let Some(found) = hunters_in_debug_set(wcm, npc_param_id) else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter not requested: debug chr set unreadable"
        );
        return false;
    };
    let alive = found.iter().filter(|c| c.alive()).count();
    if alive > 0 {
        info!(
            npc_param_id,
            alive, "[ITEMS] Hunter already on the debug chr set, no new request"
        );
        watch.request = Some(Watched {
            npc_param_id,
            at: Instant::now(),
            flag_cleared: true,
            seen_at: None,
        });
        return true;
    }
    let Some(name) = model_name(chr_id) else {
        warn!(
            chr_id,
            "[ITEMS] Hunter not requested: no model name for this chr id"
        );
        return false;
    };
    let pose = physics(player).and_then(|physics| {
        Some((
            read::<[f32; 3]>(physics + PHYSICS_POSITION_OFFSET)?,
            read::<[f32; 4]>(physics + PHYSICS_ORIENTATION_OFFSET)?,
        ))
    });
    let Some((player_at, orientation)) = pose else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter not requested: player position unreadable"
        );
        return false;
    };
    let Some(placed) = placement(player_at, orientation) else {
        warn!(
            npc_param_id,
            player = ?player_at,
            ?orientation,
            "[ITEMS] Hunter not requested: player position not plausible"
        );
        return false;
    };
    info!(
        player = ?player_at,
        yaw_deg = placed.yaw.to_degrees(),
        spawn = ?placed.spawn,
        "[ITEMS] Hunter placement"
    );
    // The fields first, the spawn byte last: the game reads them once it
    // sees the byte. A failed field write leaves the byte at 0, nothing
    // queued.
    let fields = write::<[u16; MODEL_NAME_LEN]>(creator + CREATOR_MODEL_NAME_OFFSET, name)
        && write(creator + CREATOR_NPC_PARAM_OFFSET, npc_param_id)
        && write(creator + CREATOR_THINK_OFFSET, think_id)
        && write(creator + CREATOR_EVENT_ENTITY_OFFSET, 0u32)
        && write(creator + CREATOR_TALK_OFFSET, 0u32)
        && write(creator + CREATOR_ENEMY_TYPE_OFFSET, ENEMY_TYPE_ENEMY)
        && write(creator + CREATOR_CHARA_INIT_OFFSET, NO_CHARA_INIT)
        && write(creator + CREATOR_POSITION_OFFSET, placed.spawn);
    if !fields || !write(creator + CREATOR_SPAWN_OFFSET, 1u8) {
        warn!(
            npc_param_id,
            fields, "[ITEMS] Hunter not requested: creator write failed"
        );
        return false;
    }
    info!(
        chr_id,
        npc_param_id,
        think_id,
        stale = found.len(),
        "[ITEMS] Hunter request written"
    );
    watch.request = Some(Watched {
        npc_param_id,
        at: Instant::now(),
        flag_cleared: false,
        seen_at: None,
    });
    true
}

/// Whether a live character of NpcParam row `npc_param_id` (HP above 0) is
/// on the debug chr set. False on a build with no creator offset. An
/// unreadable set answers as the last look did: seen for a Hunter already
/// seen (he keeps hunting until his end), not seen otherwise. Logs, for the
/// watched request: the spawn byte back at 0, his first sighting (`Hunter
/// spawned`), each look that sees him afterwards (`Hunter tick`), and the
/// first that no longer does (`Hunter lost`).
pub fn find_hunter(npc_param_id: u32, watch: &mut HunterWatch) -> bool {
    profile_span!("race_items.find_hunter");
    let Some(offset) = creator_offset_here() else {
        return false;
    };
    // A look that reads nothing is no sign he is gone: one already seen
    // keeps hunting, so his end still comes and kills him.
    let seen = watch
        .request
        .as_ref()
        .is_some_and(|w| w.npc_param_id == npc_param_id && w.seen_at.is_some());
    let Some(wcm) = read_ptr(Pointers::new().base_addresses.world_chr_man) else {
        warn!(
            npc_param_id,
            kept = seen,
            "[ITEMS] Hunter look failed: WorldChrMan unreadable"
        );
        return seen;
    };
    let Some(found) = hunters_in_debug_set(wcm, npc_param_id) else {
        warn!(
            npc_param_id,
            kept = seen,
            "[ITEMS] Hunter look failed: debug chr set unreadable"
        );
        return seen;
    };
    let him = found.iter().find(|c| c.alive());
    let now = Instant::now();
    let Some(watched) = watch
        .request
        .as_mut()
        .filter(|w| w.npc_param_id == npc_param_id)
    else {
        debug!(
            npc_param_id,
            found = him.is_some(),
            "[ITEMS] Hunter looked for, no request watched"
        );
        return him.is_some();
    };
    let player_at = read_ptr(wcm + player_ins_offset()).and_then(position);
    let his_at = him.and_then(|him| position(him.chr));
    let dist = player_at.zip(his_at).map(|(a, b)| distance(a, b));
    let team = him.and_then(|him| read::<u8>(him.chr + CHR_INS_TEAM_TYPE_OFFSET));
    let hp = him.and_then(|him| him.hp);
    if watched.seen_at.is_none() && !watched.flag_cleared {
        let flag = verified_creator(wcm, offset)
            .ok()
            .and_then(|creator| read::<u8>(creator + CREATOR_SPAWN_OFFSET));
        if flag == Some(0) {
            watched.flag_cleared = true;
            info!(
                after_ms = watched.after_ms(now),
                "[ITEMS] Hunter spawn flag cleared"
            );
        }
    }
    match (him, watched.seen_at) {
        (None, None) => {
            debug!(
                after_ms = watched.after_ms(now),
                dead = found.len(),
                "[ITEMS] Hunter not seen yet"
            );
        }
        (Some(him), None) => {
            let last_created = verified_creator(wcm, offset)
                .ok()
                .and_then(|creator| read::<usize>(creator + CREATOR_LAST_CREATED_OFFSET));
            info!(
                chr = format_args!("0x{:X}", him.chr),
                after_ms = watched.after_ms(now),
                npc_param_id,
                event_id = ?read::<u32>(him.chr + CHR_INS_EVENT_ENTITY_OFFSET),
                team = ?team,
                hp = ?hp,
                last_created_match = last_created == Some(him.chr),
                pos = ?his_at,
                dist = ?dist,
                alive = found.iter().filter(|c| c.alive()).count(),
                "[ITEMS] Hunter spawned"
            );
            watched.seen_at = Some(now);
        }
        (Some(_), Some(_)) => {
            info!(dist = ?dist, team = ?team, hp = ?hp, pos = ?his_at, "[ITEMS] Hunter tick");
            watched.seen_at = Some(now);
        }
        (None, Some(seen_at)) => {
            info!(
                reason = if found.is_empty() { "absent" } else { "dead" },
                since_seen_ms = now.saturating_duration_since(seen_at).as_millis(),
                "[ITEMS] Hunter lost"
            );
            watch.request = None;
        }
    }
    him.is_some()
}

/// End the Hunter: clear a spawn of his still pending (the spawn byte at 1,
/// once the creator is verified), then bring every live character of
/// NpcParam row `npc_param_id` on the debug chr set to 0 HP, each one's
/// entry checked again right before its write. Safe on a frame that is not
/// loaded: a step whose reads fail is logged and writes nothing. True when
/// nothing of his is left pending or alive as far as the reads tell; false
/// when a step was unreadable or a write failed (logged).
pub fn end_hunter(npc_param_id: u32, watch: &mut HunterWatch) -> bool {
    profile_span!("race_items.end_hunter");
    let watched = watch
        .request
        .take()
        .filter(|w| w.npc_param_id == npc_param_id);
    let Some(offset) = creator_offset_here() else {
        // No request could be made on this build.
        return true;
    };
    let Some(wcm) = read_ptr(Pointers::new().base_addresses.world_chr_man) else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter end skipped: WorldChrMan unreadable"
        );
        return false;
    };
    let now = Instant::now();
    let mut complete = true;
    let (spawn_flag, cancelled) = match verified_creator(wcm, offset) {
        Ok(creator) => match read::<u8>(creator + CREATOR_SPAWN_OFFSET) {
            Some(1) => {
                let cancelled = write(creator + CREATOR_SPAWN_OFFSET, 0u8);
                complete &= cancelled;
                (Some(1), cancelled)
            }
            flag => {
                complete &= flag.is_some();
                (flag, false)
            }
        },
        Err(reason) => {
            warn!(
                npc_param_id,
                reason, "[ITEMS] Hunter end: creator not verified, a pending spawn not cleared"
            );
            complete = false;
            (None, false)
        }
    };
    let seen = watched.as_ref().is_some_and(|w| w.seen_at.is_some());
    if let Some(watched) = watched.as_ref().filter(|w| w.seen_at.is_none()) {
        info!(
            after_ms = watched.after_ms(now),
            spawn_flag = ?spawn_flag,
            cancelled,
            "[ITEMS] Hunter missed"
        );
    } else if cancelled {
        info!(npc_param_id, "[ITEMS] Hunter pending spawn cleared");
    }
    let Some(found) = hunters_in_debug_set(wcm, npc_param_id) else {
        warn!(
            npc_param_id,
            "[ITEMS] Hunter end: debug chr set unreadable, nothing killed"
        );
        return false;
    };
    let runes = Pointers::new().runes.read();
    let alive = found.iter().filter(|c| c.alive()).count();
    let (mut killed, mut skipped) = (0usize, 0usize);
    for him in found.iter().filter(|c| c.alive()) {
        // He may have been freed since the walk: the same pointer in the
        // same entry, with his row, or no write.
        let entry = read_ptr(wcm + WCM_DEBUG_CHR_SET_OFFSET + CHR_SET_ENTRIES_OFFSET)
            .and_then(|entries| read::<usize>(entries + him.index * CHR_SET_ENTRY_SIZE));
        let unchanged = entry == Some(him.chr)
            && read::<u32>(him.chr + CHR_INS_NPC_PARAM_OFFSET) == Some(npc_param_id);
        if !unchanged {
            info!(
                chr = format_args!("0x{:X}", him.chr),
                reason = "entry_changed",
                "[ITEMS] Hunter kill skipped"
            );
            skipped += 1;
            continue;
        }
        let hp = PointerChain::<i32>::new(&[
            him.chr + CHR_INS_MODULES_OFFSET,
            MODULES_DATA_OFFSET,
            DATA_HP_OFFSET,
        ]);
        let hp_before = him.hp.map(|[hp, _]| hp);
        if hp.write(0).is_none() {
            warn!(
                chr = format_args!("0x{:X}", him.chr),
                "[ITEMS] Hunter kill failed: HP unwritable"
            );
            skipped += 1;
            continue;
        }
        killed += 1;
        if seen {
            info!(
                chr = format_args!("0x{:X}", him.chr),
                hp_before = ?hp_before,
                runes = ?runes,
                "[ITEMS] Hunter killed"
            );
        } else {
            info!(
                chr = format_args!("0x{:X}", him.chr),
                hp_before = ?hp_before,
                after_ms = ?watched.as_ref().map(|w| w.after_ms(now)),
                "[ITEMS] Hunter late arrival killed"
            );
        }
    }
    info!(
        npc_param_id,
        killed,
        skipped,
        dead = found.len() - alive,
        "[ITEMS] Hunter end done"
    );
    complete && skipped == 0
}
