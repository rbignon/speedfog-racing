//! Talisman Thief: which of the victim's talismans is taken.
//!
//! The server sends the seed's talisman table (`{id, flag}`, the flag of the
//! removal event the seed adds for that talisman) and a random roll; the
//! victim's mod picks among the talismans it wears and raises that one's
//! flag: the game's event removes it, which empties its slot. The shell reads
//! the four talisman slots; this module only picks.

use super::protocol::TalismanFlag;

/// The talisman the roll takes from `equipped` (the talisman slots in slot
/// order, as EquipParamAccessory ids: -1 for an empty slot): the worn ones
/// the table knows, in slot order, the one at `roll % count`. `None` when
/// the runner wears none of them.
pub fn pick_talisman(equipped: &[i32], table: &[TalismanFlag], roll: u32) -> Option<TalismanFlag> {
    let worn = || {
        equipped.iter().filter_map(|&id| {
            let id = u32::try_from(id).ok()?;
            table.iter().find(|talisman| talisman.id == id).copied()
        })
    };
    let count = worn().count();
    if count == 0 {
        return None;
    }
    worn().nth(roll as usize % count)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table() -> Vec<TalismanFlag> {
        [1000, 1001, 1002, 1003, 1004]
            .into_iter()
            .zip(1_050_290_300..)
            .map(|(id, flag)| TalismanFlag { id, flag })
            .collect()
    }

    fn picked(equipped: &[i32], roll: u32) -> Option<u32> {
        pick_talisman(equipped, &table(), roll).map(|talisman| talisman.id)
    }

    #[test]
    fn the_roll_picks_among_the_worn_talismans_in_slot_order() {
        let equipped = [1003, 1000, 1004, 1001];
        let picks: Vec<_> = (0..5).map(|roll| picked(&equipped, roll)).collect();
        assert_eq!(
            picks,
            [Some(1003), Some(1000), Some(1004), Some(1001), Some(1003)]
        );
        // The pick carries its own flag.
        assert_eq!(
            pick_talisman(&equipped, &table(), 2),
            Some(TalismanFlag {
                id: 1004,
                flag: 1_050_290_304
            })
        );
        assert_eq!(picked(&equipped, u32::MAX), Some(1001));
    }

    #[test]
    fn empty_slots_and_talismans_outside_the_table_are_skipped() {
        // 2000 is no talisman of the table (another mod's, or misread).
        let equipped = [-1, 2000, 1002, -1];
        for roll in [0, 1, 7, u32::MAX] {
            assert_eq!(picked(&equipped, roll), Some(1002), "roll {roll}");
        }
    }

    #[test]
    fn nothing_worn_gives_nothing() {
        assert_eq!(picked(&[-1, -1, -1, -1], 3), None);
        assert_eq!(picked(&[2000, -1, -1, -1], 3), None);
        assert_eq!(picked(&[], 0), None);
    }
}
