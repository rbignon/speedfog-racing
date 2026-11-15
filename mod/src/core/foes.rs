//! Unseen Foes: which characters' render bit the foes walk changes.
//!
//! A character is drawn while bit 3 (`enable_render`) of its ChrIns + 0x1C5
//! is set (fromsoftware-rs `cs/chr_ins.rs`, `ChrInsFlags1c5`). The shell
//! reads each chr set's entry block out of game memory in one read and the
//! render byte of each character on it, then applies what a `FoesWalk`
//! decides and tells it which writes worked; this module only decides.
//!
//! A walk considers only the characters in the world (entry load status
//! Active). Hiding clears the bit on a character that has it set, recorded
//! once the write worked; showing sets it back only on a recorded character
//! met again with it cleared and not dying, so a character the game hides
//! or is removing is never shown. A hide walk that read every set rebuilds
//! the record from what it met, so the record follows the characters
//! through a load: one the mod hid that survives it (a death, a warp that
//! keeps the map block) stays recorded, one gone is dropped.

use std::collections::HashSet;

/// Bit of ChrIns + 0x1C5 that draws the character.
pub const RENDER_BIT: u8 = 0x08;
/// Bit of ChrIns + 0x1C5 the game sets on a character it kills or removes
/// (fromsoftware-rs `death_flag`).
pub const DEATH_BIT: u8 = 0x80;
/// One chr set entry: the ChrIns pointer at +0 (null for an empty slot),
/// its load status and flags after it.
pub const CHR_SET_ENTRY_SIZE: usize = 0x10;
/// Chr set entry + 0x08: the load status (fromsoftware-rs `ChrLoadStatus`).
const ENTRY_LOAD_STATUS_OFFSET: usize = 0x08;
/// The load status of a character in the world (`Active`; the others are
/// loading, network setup or unloading).
pub const LOAD_STATUS_ACTIVE: u8 = 2;
/// Chr sets WorldChrMan holds at most: a bound on its set count.
pub const MAX_CHR_SETS: u32 = 196;
/// Entries read at most from one chr set: a bound on its capacity, far
/// above the open field set's (about 1500).
pub const MAX_CHR_SET_CAPACITY: u32 = 4096;

/// A change to one character's render bit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RenderWrite {
    /// Clear the bit: the character is no longer drawn.
    Hide(usize),
    /// Set the bit back: the character is drawn again.
    Show(usize),
}

/// What the walk decided for one chr set.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct SetPlan {
    /// Characters on the set the walk may change (active ones, the player
    /// and Torrent left out), readable or not.
    pub visited: usize,
    /// Of those, the ones whose render byte could not be read: left alone.
    pub unreadable: usize,
    pub writes: Vec<RenderWrite>,
}

/// The chr sets to walk from WorldChrMan's set pointer array, as read in
/// one block (8 bytes per set): the non-null ones, the player chr set
/// (`player_set`: the local player and the other players) left out.
pub fn chr_sets(pointers: &[u8], player_set: usize) -> impl Iterator<Item = usize> + '_ {
    pointers
        .chunks_exact(8)
        .map(pointer_at)
        .filter(move |&set| set != 0 && set != player_set)
}

/// The little-endian pointer at the start of `bytes` (8 bytes at least).
fn pointer_at(bytes: &[u8]) -> usize {
    let mut pointer = [0u8; 8];
    pointer.copy_from_slice(&bytes[..8]);
    u64::from_le_bytes(pointer) as usize
}

/// The characters the mod hid, by ChrIns address.
#[derive(Debug, Default)]
pub struct FoesRecord {
    hidden: HashSet<usize>,
}

impl FoesRecord {
    /// How many characters the record holds.
    pub fn len(&self) -> usize {
        self.hidden.len()
    }

    pub fn is_empty(&self) -> bool {
        self.hidden.is_empty()
    }

    /// Start a walk over the chr sets, hiding (`hide`) or showing.
    pub fn walk(&mut self, hide: bool) -> FoesWalk<'_> {
        let unmet = self.hidden.clone();
        FoesWalk {
            record: self,
            hide,
            kept: HashSet::new(),
            unmet,
            whole: true,
        }
    }
}

/// One walk over the chr sets (`FoesRecord::walk`): `plan_set` for each set
/// read, `written` for each of its writes that worked, `missed_set` for each
/// set not read whole, then `finish`.
#[derive(Debug)]
pub struct FoesWalk<'a> {
    record: &'a mut FoesRecord,
    hide: bool,
    /// What a hide walk records: the characters its writes hid, and the
    /// recorded ones it met still hidden or unreadable.
    kept: HashSet<usize>,
    /// The recorded characters not met yet.
    unmet: HashSet<usize>,
    /// Every set read whole so far.
    whole: bool,
}

impl FoesWalk<'_> {
    /// Decide the render writes for one chr set's entry block (`entries`, as
    /// read: `CHR_SET_ENTRY_SIZE` bytes per entry, a trailing partial entry
    /// ignored). Empty slots, entries not Active, the local `player` and
    /// `torrent` are skipped; `render_byte` reads a character's ChrIns +
    /// 0x1C5 (`None` when unreadable). Hiding clears the bit of each
    /// character that has it set (recorded by `written`); a recorded one met
    /// already cleared, or unreadable, stays recorded. Showing sets the bit
    /// back on each recorded character met with it cleared, unless it is
    /// dying (`DEATH_BIT`); one the game showed again needs no write.
    pub fn plan_set(
        &mut self,
        entries: &[u8],
        player: usize,
        torrent: usize,
        mut render_byte: impl FnMut(usize) -> Option<u8>,
    ) -> SetPlan {
        let mut plan = SetPlan::default();
        for entry in entries.chunks_exact(CHR_SET_ENTRY_SIZE) {
            let chr = pointer_at(entry);
            if chr == 0
                || chr == player
                || chr == torrent
                || entry[ENTRY_LOAD_STATUS_OFFSET] != LOAD_STATUS_ACTIVE
            {
                continue;
            }
            plan.visited += 1;
            self.unmet.remove(&chr);
            let recorded = self.record.hidden.contains(&chr);
            let Some(byte) = render_byte(chr) else {
                plan.unreadable += 1;
                if self.hide && recorded {
                    self.kept.insert(chr);
                }
                continue;
            };
            let drawn = byte & RENDER_BIT != 0;
            if self.hide {
                if drawn {
                    plan.writes.push(RenderWrite::Hide(chr));
                } else if recorded {
                    self.kept.insert(chr);
                }
            } else if recorded && !drawn && byte & DEATH_BIT == 0 {
                plan.writes.push(RenderWrite::Show(chr));
            }
        }
        plan
    }

    /// A write of `plan_set` that the shell made: a hidden character is
    /// recorded only then.
    pub fn written(&mut self, write: RenderWrite) {
        if let RenderWrite::Hide(chr) = write {
            if self.hide {
                self.kept.insert(chr);
            }
        }
    }

    /// A set the walk could not read whole (its head or entries unreadable,
    /// or past the capacity bound): the recorded characters it did not meet
    /// may be on it.
    pub fn missed_set(&mut self) {
        self.whole = false;
    }

    /// End of the walk; returns how many characters the record holds after
    /// it. A hide walk records what it hid and the recorded characters it
    /// met still hidden; a recorded character it did not meet is gone and
    /// dropped, unless a set was missed (it is kept then). A show walk
    /// empties the record: the characters it met are drawn or left to the
    /// game, the others are gone or out of reach.
    pub fn finish(self) -> usize {
        let FoesWalk {
            record,
            hide,
            mut kept,
            unmet,
            whole,
        } = self;
        if !hide {
            record.hidden.clear();
            return 0;
        }
        if !whole {
            kept.extend(unmet);
        }
        record.hidden = kept;
        record.hidden.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    const PLAYER: usize = 0x7FF0_0000_1000;
    const TORRENT: usize = 0x7FF0_0000_2000;
    const DRAWN: u8 = RENDER_BIT | 0x02;
    const NOT_DRAWN: u8 = 0x02;
    /// Two of the other load statuses: loading in, and on its way out.
    const INITIALIZING: u8 = 1;
    const UNLOADING: u8 = 5;

    /// A chr set entry block: each pointer in its slot with its load
    /// status, the bytes after them filled with a marker so a misaligned
    /// read cannot pass for a pointer.
    fn entries_with_status(chrs: &[(usize, u8)]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for &(chr, status) in chrs {
            let mut entry = [0xA5u8; CHR_SET_ENTRY_SIZE];
            entry[..8].copy_from_slice(&(chr as u64).to_le_bytes());
            entry[ENTRY_LOAD_STATUS_OFFSET] = status;
            bytes.extend_from_slice(&entry);
        }
        bytes
    }

    /// A block of Active entries.
    fn entries(chrs: &[usize]) -> Vec<u8> {
        let chrs: Vec<_> = chrs.iter().map(|&chr| (chr, LOAD_STATUS_ACTIVE)).collect();
        entries_with_status(&chrs)
    }

    /// One whole walk over `sets` as the shell runs it, the player at
    /// `player`, every write working: the writes, in order.
    fn walk(
        record: &mut FoesRecord,
        hide: bool,
        player: usize,
        sets: &[Vec<u8>],
        bytes: &HashMap<usize, u8>,
    ) -> Vec<RenderWrite> {
        let mut walk = record.walk(hide);
        let mut writes = Vec::new();
        for set in sets {
            let plan = walk.plan_set(set, player, TORRENT, |chr| bytes.get(&chr).copied());
            for &write in &plan.writes {
                walk.written(write);
            }
            writes.extend(plan.writes);
        }
        walk.finish();
        writes
    }

    fn record_of(chrs: &[usize]) -> FoesRecord {
        FoesRecord {
            hidden: chrs.iter().copied().collect(),
        }
    }

    #[test]
    fn hiding_clears_only_drawn_active_foes_and_records_them() {
        // A drawn foe, a foe the game hides, an unreadable one, empty
        // slots, the player, Torrent, and drawn foes loading in or out.
        let bytes = HashMap::from([
            (0x100, DRAWN),
            (0x200, NOT_DRAWN),
            (0x400, DRAWN),
            (0x500, DRAWN),
            (PLAYER, DRAWN),
            (TORRENT, DRAWN),
        ]);
        let block = entries_with_status(&[
            (0, LOAD_STATUS_ACTIVE),
            (0x100, LOAD_STATUS_ACTIVE),
            (PLAYER, LOAD_STATUS_ACTIVE),
            (0x200, LOAD_STATUS_ACTIVE),
            (0, 0),
            (TORRENT, LOAD_STATUS_ACTIVE),
            (0x300, LOAD_STATUS_ACTIVE),
            (0x400, INITIALIZING),
            (0x500, UNLOADING),
        ]);
        let mut record = FoesRecord::default();
        let mut walk = record.walk(true);
        let plan = walk.plan_set(&block, PLAYER, TORRENT, |chr| bytes.get(&chr).copied());
        assert_eq!(
            plan,
            SetPlan {
                visited: 3,
                unreadable: 1,
                writes: vec![RenderWrite::Hide(0x100)],
            }
        );
        walk.written(RenderWrite::Hide(0x100));
        assert_eq!(walk.finish(), 1);
        assert_eq!(record.hidden, HashSet::from([0x100]));
    }

    #[test]
    fn only_a_hide_that_worked_is_recorded() {
        // 0x100 and 0x200 drawn, only 0x100's write works; 0x300, recorded
        // and drawn again by the game, fails to hide again: drawn, so no
        // longer the mod's to show.
        let bytes = HashMap::from([(0x100, DRAWN), (0x200, DRAWN), (0x300, DRAWN)]);
        let mut record = record_of(&[0x300]);
        let mut walk = record.walk(true);
        let plan = walk.plan_set(&entries(&[0x100, 0x200, 0x300]), PLAYER, TORRENT, |chr| {
            bytes.get(&chr).copied()
        });
        assert_eq!(
            plan.writes,
            [
                RenderWrite::Hide(0x100),
                RenderWrite::Hide(0x200),
                RenderWrite::Hide(0x300)
            ]
        );
        walk.written(RenderWrite::Hide(0x100));
        walk.finish();
        assert_eq!(record.hidden, HashSet::from([0x100]));
    }

    #[test]
    fn later_hide_walks_rehide_what_the_game_showed() {
        // 0x100 hidden by the mod and shown again by the game, 0x200 hidden
        // by the mod and still hidden, 0x300 newly loaded, 0x400 hidden by
        // the game, 0x500 recorded but unreadable this time.
        let mut record = record_of(&[0x100, 0x200, 0x500]);
        let bytes = HashMap::from([
            (0x100, DRAWN),
            (0x200, NOT_DRAWN),
            (0x300, DRAWN),
            (0x400, NOT_DRAWN),
        ]);
        let set = entries(&[0x100, 0x200, 0x300, 0x400, 0x500]);
        let writes = walk(&mut record, true, PLAYER, &[set], &bytes);
        assert_eq!(writes, [RenderWrite::Hide(0x100), RenderWrite::Hide(0x300)]);
        assert_eq!(record.hidden, HashSet::from([0x100, 0x200, 0x300, 0x500]));
    }

    #[test]
    fn showing_restores_only_recorded_foes_then_forgets() {
        // Recorded: 0x100 (still hidden), 0x200 (the game showed it), 0x500
        // (not met: unloaded). 0x300 is hidden by the game, never recorded.
        let mut record = record_of(&[0x100, 0x200, 0x500]);
        let bytes = HashMap::from([(0x100, NOT_DRAWN), (0x200, DRAWN), (0x300, NOT_DRAWN)]);
        let set = entries(&[0x100, 0x200, 0x300]);
        let writes = walk(&mut record, false, PLAYER, &[set], &bytes);
        assert_eq!(writes, [RenderWrite::Show(0x100)]);
        assert!(record.is_empty(), "{record:?}");
    }

    #[test]
    fn showing_skips_a_dying_foe_and_one_not_active() {
        // Recorded and still hidden: 0x100 dying (the game is removing it),
        // 0x200 unloading, 0x300 loading in again at a recorded address;
        // 0x400 as it should be, drawn back.
        let mut record = record_of(&[0x100, 0x200, 0x300, 0x400]);
        let bytes = HashMap::from([
            (0x100, NOT_DRAWN | DEATH_BIT),
            (0x200, NOT_DRAWN),
            (0x300, NOT_DRAWN),
            (0x400, NOT_DRAWN),
        ]);
        let set = entries_with_status(&[
            (0x100, LOAD_STATUS_ACTIVE),
            (0x200, UNLOADING),
            (0x300, INITIALIZING),
            (0x400, LOAD_STATUS_ACTIVE),
        ]);
        let writes = walk(&mut record, false, PLAYER, &[set], &bytes);
        assert_eq!(writes, [RenderWrite::Show(0x400)]);
        assert!(record.is_empty(), "{record:?}");
    }

    #[test]
    fn a_hide_walk_keeps_the_record_across_sets() {
        // Two sets: the second does not hold the first's foe, which stays
        // recorded for the show walk.
        let bytes = HashMap::from([(0x100, DRAWN), (0x200, DRAWN)]);
        let mut record = FoesRecord::default();
        walk(
            &mut record,
            true,
            PLAYER,
            &[entries(&[0x100]), entries(&[0x200])],
            &bytes,
        );
        assert_eq!(record.hidden, HashSet::from([0x100, 0x200]));
    }

    #[test]
    fn a_hidden_foe_stays_recorded_through_a_load() {
        // Hidden, then a load (a death: a new PlayerIns), the foe kept with
        // its bit still cleared: still recorded, and drawn at the end.
        let mut record = FoesRecord::default();
        let set = entries(&[0x100]);
        walk(
            &mut record,
            true,
            PLAYER,
            std::slice::from_ref(&set),
            &HashMap::from([(0x100, DRAWN)]),
        );
        let respawned = PLAYER + 0x4000;
        let hidden = HashMap::from([(0x100, NOT_DRAWN)]);
        let writes = walk(
            &mut record,
            true,
            respawned,
            std::slice::from_ref(&set),
            &hidden,
        );
        assert!(writes.is_empty(), "{writes:?}");
        assert_eq!(record.hidden, HashSet::from([0x100]));
        let writes = walk(&mut record, false, respawned, &[set], &hidden);
        assert_eq!(writes, [RenderWrite::Show(0x100)]);
    }

    #[test]
    fn a_complete_walk_drops_what_it_did_not_meet() {
        // 0x200 is gone after a load: dropped, so its address coming back
        // as a character the game hides is never drawn.
        let mut record = record_of(&[0x100, 0x200]);
        let bytes = HashMap::from([(0x100, NOT_DRAWN), (0x200, NOT_DRAWN)]);
        walk(&mut record, true, PLAYER, &[entries(&[0x100])], &bytes);
        assert_eq!(record.hidden, HashSet::from([0x100]));
        let writes = walk(&mut record, false, PLAYER, &[entries(&[0x200])], &bytes);
        assert!(writes.is_empty(), "{writes:?}");
    }

    #[test]
    fn a_walk_with_a_missed_set_keeps_what_it_did_not_meet() {
        // 0x200 may sit on the set the walk could not read: kept. 0x300,
        // met drawn and not hidden again, goes; 0x400 is newly hidden.
        let mut record = record_of(&[0x100, 0x200, 0x300]);
        let bytes = HashMap::from([(0x100, NOT_DRAWN), (0x300, DRAWN), (0x400, DRAWN)]);
        let mut walk = record.walk(true);
        let plan = walk.plan_set(&entries(&[0x100, 0x300, 0x400]), PLAYER, TORRENT, |chr| {
            bytes.get(&chr).copied()
        });
        walk.missed_set();
        walk.written(RenderWrite::Hide(0x400));
        assert_eq!(
            plan.writes,
            [RenderWrite::Hide(0x300), RenderWrite::Hide(0x400)]
        );
        assert_eq!(walk.finish(), 3);
        assert_eq!(record.hidden, HashSet::from([0x100, 0x200, 0x400]));
    }

    #[test]
    fn the_set_array_skips_empty_slots_and_the_player_set() {
        const PLAYER_SET: usize = 0x7FF0_0001_0EE0;
        let mut pointers = Vec::new();
        for set in [PLAYER_SET, 0, 0x5000, 0x6000, 0] {
            pointers.extend_from_slice(&(set as u64).to_le_bytes());
        }
        // A trailing partial pointer is no set.
        pointers.extend_from_slice(&[0x11, 0x22, 0x33]);
        assert_eq!(
            chr_sets(&pointers, PLAYER_SET).collect::<Vec<_>>(),
            [0x5000, 0x6000]
        );
    }
}
