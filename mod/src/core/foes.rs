//! Unseen Foes: which characters' render bit the foes walk changes.
//!
//! A character is drawn while bit 3 (`enable_render`) of its ChrIns + 0x1C5
//! is set (fromsoftware-rs `cs/chr_ins.rs`, `ChrInsFlags1c5`). The shell
//! reads each chr set's entry block out of game memory in one read and the
//! render byte of each character on it, then applies what `plan_chr_set`
//! decides; this module only decides. Hiding clears the bit only on a
//! character that has it set, and records it; showing sets it back only on
//! a recorded character met again, so a character the game hides on purpose
//! is never shown. The record holds addresses that are valid only within
//! one loaded world (`FoesRecord::see_player`).

use std::collections::HashSet;

/// Bit of ChrIns + 0x1C5 that draws the character.
pub const RENDER_BIT: u8 = 0x08;
/// One chr set entry: the ChrIns pointer at +0 (null for an empty slot),
/// its load status and flags after it.
pub const CHR_SET_ENTRY_SIZE: usize = 0x10;
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
    /// Characters on the set the walk may change (the player and Torrent
    /// left out), readable or not.
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

/// Decide the render writes for one chr set's entry block (`entries`, as
/// read: `CHR_SET_ENTRY_SIZE` bytes per entry, a trailing partial entry
/// ignored). Empty slots, the local `player` and `torrent` are skipped;
/// `render_byte` reads a character's ChrIns + 0x1C5 (`None` when
/// unreadable). Hiding clears the bit of each character that has it set
/// and records it in `hidden`; a character already cleared is left as it
/// is (a recorded one stays recorded). Showing sets the bit back on each
/// recorded character met with it cleared and drops it from the record;
/// one the game showed again needs no write. Call `finish_walk` once every
/// set is done.
pub fn plan_chr_set(
    entries: &[u8],
    player: usize,
    torrent: usize,
    mut render_byte: impl FnMut(usize) -> Option<u8>,
    hide: bool,
    hidden: &mut HashSet<usize>,
) -> SetPlan {
    let mut plan = SetPlan::default();
    let chrs = entries
        .chunks_exact(CHR_SET_ENTRY_SIZE)
        .map(pointer_at)
        .filter(|&chr| chr != 0 && chr != player && chr != torrent);
    for chr in chrs {
        plan.visited += 1;
        let Some(byte) = render_byte(chr) else {
            plan.unreadable += 1;
            continue;
        };
        let drawn = byte & RENDER_BIT != 0;
        if hide {
            if drawn {
                hidden.insert(chr);
                plan.writes.push(RenderWrite::Hide(chr));
            }
        } else if hidden.remove(&chr) && !drawn {
            plan.writes.push(RenderWrite::Show(chr));
        }
    }
    plan
}

/// End of a walk: a show walk forgets what is left of the record (the
/// characters it did not meet are gone, and their addresses may come back
/// as other characters); a hide walk keeps it for the next walks.
pub fn finish_walk(hide: bool, hidden: &mut HashSet<usize>) {
    if !hide {
        hidden.clear();
    }
}

/// The little-endian pointer at the start of `bytes` (8 bytes at least).
fn pointer_at(bytes: &[u8]) -> usize {
    let mut pointer = [0u8; 8];
    pointer.copy_from_slice(&bytes[..8]);
    u64::from_le_bytes(pointer) as usize
}

/// The characters the mod hid, valid within one loaded world.
#[derive(Debug, Default)]
pub struct FoesRecord {
    /// PlayerIns seen at the previous memory state write: a load recreates
    /// the player, and the other characters with it.
    player_ins: usize,
    pub hidden: HashSet<usize>,
}

impl FoesRecord {
    /// Note the PlayerIns of this memory state write. Another one than at
    /// the previous write means a load came in between: the characters the
    /// record names are gone (the new ones come with their render bit set
    /// by the game), so it is forgotten. Returns how many it forgot.
    pub fn see_player(&mut self, player_ins: usize) -> usize {
        if player_ins == self.player_ins {
            return 0;
        }
        self.player_ins = player_ins;
        let forgotten = self.hidden.len();
        self.hidden.clear();
        forgotten
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

    /// A chr set entry block: each pointer in its slot, the load status
    /// and flags after it filled with a marker so a misaligned read cannot
    /// pass for a pointer.
    fn entries(chrs: &[usize]) -> Vec<u8> {
        let mut bytes = Vec::new();
        for &chr in chrs {
            let mut entry = [0xA5u8; CHR_SET_ENTRY_SIZE];
            entry[..8].copy_from_slice(&(chr as u64).to_le_bytes());
            bytes.extend_from_slice(&entry);
        }
        bytes
    }

    fn plan(
        chrs: &[usize],
        bytes: &HashMap<usize, u8>,
        hide: bool,
        hidden: &mut HashSet<usize>,
    ) -> SetPlan {
        plan_chr_set(
            &entries(chrs),
            PLAYER,
            TORRENT,
            |chr| bytes.get(&chr).copied(),
            hide,
            hidden,
        )
    }

    #[test]
    fn hiding_clears_only_drawn_foes_and_records_them() {
        // A drawn foe, a foe the game hides, an unreadable one, empty
        // slots, the player and Torrent.
        let bytes = HashMap::from([
            (0x100, DRAWN),
            (0x200, NOT_DRAWN),
            (PLAYER, DRAWN),
            (TORRENT, DRAWN),
        ]);
        let mut hidden = HashSet::new();
        let plan = plan(
            &[0, 0x100, PLAYER, 0x200, 0, TORRENT, 0x300],
            &bytes,
            true,
            &mut hidden,
        );
        assert_eq!(
            plan,
            SetPlan {
                visited: 3,
                unreadable: 1,
                writes: vec![RenderWrite::Hide(0x100)],
            }
        );
        assert_eq!(hidden, HashSet::from([0x100]));
    }

    #[test]
    fn later_hide_walks_rehide_what_the_game_showed() {
        // 0x100 hidden by the mod and shown again by the game, 0x200 hidden
        // by the mod and still hidden, 0x300 newly loaded, 0x400 hidden by
        // the game.
        let mut hidden = HashSet::from([0x100, 0x200]);
        let bytes = HashMap::from([
            (0x100, DRAWN),
            (0x200, NOT_DRAWN),
            (0x300, DRAWN),
            (0x400, NOT_DRAWN),
        ]);
        let plan = plan(&[0x100, 0x200, 0x300, 0x400], &bytes, true, &mut hidden);
        assert_eq!(
            plan.writes,
            [RenderWrite::Hide(0x100), RenderWrite::Hide(0x300)]
        );
        assert_eq!(hidden, HashSet::from([0x100, 0x200, 0x300]));
    }

    #[test]
    fn showing_restores_only_recorded_foes_then_forgets() {
        // Recorded: 0x100 (still hidden), 0x200 (the game showed it), 0x500
        // (not met: unloaded). 0x300 is hidden by the game, never recorded.
        let mut hidden = HashSet::from([0x100, 0x200, 0x500]);
        let bytes = HashMap::from([(0x100, NOT_DRAWN), (0x200, DRAWN), (0x300, NOT_DRAWN)]);
        let plan = plan(&[0x100, 0x200, 0x300], &bytes, false, &mut hidden);
        assert_eq!(plan.writes, [RenderWrite::Show(0x100)]);
        assert_eq!(plan.visited, 3);
        finish_walk(false, &mut hidden);
        assert!(hidden.is_empty(), "{hidden:?}");
    }

    #[test]
    fn a_hide_walk_keeps_the_record_across_sets() {
        // Two sets: the second walk's set does not hold the first's foe,
        // which stays recorded for the show walk.
        let bytes = HashMap::from([(0x100, DRAWN), (0x200, DRAWN)]);
        let mut hidden = HashSet::new();
        plan(&[0x100], &bytes, true, &mut hidden);
        plan(&[0x200], &bytes, true, &mut hidden);
        finish_walk(true, &mut hidden);
        assert_eq!(hidden, HashSet::from([0x100, 0x200]));
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

    #[test]
    fn a_new_world_forgets_the_record() {
        let mut record = FoesRecord::default();
        assert_eq!(record.see_player(PLAYER), 0);
        record.hidden.extend([0x100, 0x200]);
        // The same world: kept.
        assert_eq!(record.see_player(PLAYER), 0);
        assert_eq!(record.hidden.len(), 2);
        // A load recreated the player: forgotten, and a show walk then
        // changes nothing it did not hide in this world, even at an address
        // the last world's foe had.
        assert_eq!(record.see_player(PLAYER + 0x4000), 2);
        let bytes = HashMap::from([(0x100, NOT_DRAWN)]);
        let plan = plan(&[0x100], &bytes, false, &mut record.hidden);
        assert!(plan.writes.is_empty(), "{plan:?}");
    }
}
