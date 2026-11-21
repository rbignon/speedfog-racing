//! What a relay capture's reads make: the checks they must pass and the
//! state they build. The shell reads the game on its worker thread (the
//! attributes, level and runes as the game stores them, the held item ids,
//! the goods param's types, the grace flags and which of them are set, the
//! loaded map before and after the reads); this module decides whether those
//! reads are a character worth sending, and builds the state. A param table
//! that does not read fails no capture: without the goods types no goods is
//! transferable, without the grace rows the state carries no grace. Pure:
//! nothing here reads the game or logs.

use std::collections::HashMap;
use std::time::Duration;

use super::protocol::CharacterState;
use super::relay_items::{fit_to_wire, stats_plausible, transferable_items, PARAM_MASK};

/// Longest the reads of one capture may take. A load (the map unloaded, then
/// loaded again) takes longer, so reads that find the same loaded map before
/// and after them, within this bound, saw no load in between.
pub const READ_WINDOW_MAX: Duration = Duration::from_secs(1);

/// Why a capture gave no state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureFailure {
    /// No map loaded when the reads began (a loading screen, the menu).
    NotLoaded,
    /// The attributes, level or runes could not be read, or read negative.
    StatsUnreadable,
    /// They read outside what a character can have (`stats_plausible`): a
    /// torn read, or a layout that no longer matches the game.
    StatsImplausible {
        attributes: [u32; 8],
        level: u32,
        runes: u32,
    },
    /// The inventory lists could not be read.
    InventoryUnreadable,
    /// The event flag reader is down, or it read none of the grace flags.
    FlagsUnreadable,
    /// The loaded map changed or went away during the reads, or they took
    /// longer than `READ_WINDOW_MAX`: a load may have come in between.
    LoadDuringCapture,
}

/// The attributes (vigor to arcane), level and runes as the game stores them
/// (`i32`), as a state carries them. `None` when any reads negative: never a
/// character's, so the read is unusable.
pub fn stats_from_game(
    attributes: [i32; 8],
    level: i32,
    runes: i32,
) -> Option<([u32; 8], u32, u32)> {
    let mut unsigned = [0u32; 8];
    for (slot, &value) in unsigned.iter_mut().zip(&attributes) {
        *slot = u32::try_from(value).ok()?;
    }
    Some((
        unsigned,
        u32::try_from(level).ok()?,
        u32::try_from(runes).ok()?,
    ))
}

/// Why a param table gave the capture nothing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TableUnread {
    /// The game's param index holds no table of that name.
    NotIndexed,
    /// The table holds no usable row.
    NoUsableRow,
}

/// The goods param's type by row id, from its rows (`(row id, goods_type)`;
/// `None`: the table is not indexed). A row id past the bits under an item
/// id's category nibble names no item and is left out.
pub fn goods_type_map(
    rows: Option<impl IntoIterator<Item = (u64, u8)>>,
) -> Result<HashMap<u32, u8>, TableUnread> {
    let types: HashMap<u32, u8> = rows
        .ok_or(TableUnread::NotIndexed)?
        .into_iter()
        .filter_map(|(id, ty)| {
            u32::try_from(id)
                .ok()
                .filter(|&id| id <= PARAM_MASK)
                .map(|id| (id, ty))
        })
        .collect();
    if types.is_empty() {
        return Err(TableUnread::NoUsableRow);
    }
    Ok(types)
}

/// The grace flags to scan, from the event flag id of every grace row
/// (`None`: the table is not indexed): nonzero, sorted, each once.
pub fn grace_flag_ids(
    flags: Option<impl IntoIterator<Item = u32>>,
) -> Result<Vec<u32>, TableUnread> {
    let mut ids: Vec<u32> = flags
        .ok_or(TableUnread::NotIndexed)?
        .into_iter()
        .filter(|&flag| flag != 0)
        .collect();
    if ids.is_empty() {
        return Err(TableUnread::NoUsableRow);
    }
    ids.sort_unstable();
    ids.dedup();
    Ok(ids)
}

/// The flags of `flags` that `is_set` reads set, in their order, and how
/// many it could not read. An unreadable flag counts as not lit: the event
/// flag reader answers `None` for a flag of a category the game does not hold
/// as well as for a failed read, and one grace row the game does not use must
/// not fail every capture. `FlagsUnreadable` when it read none of them (the
/// reader itself is down).
pub fn lit_flags(
    flags: &[u32],
    mut is_set: impl FnMut(u32) -> Option<bool>,
) -> Result<(Vec<u32>, usize), CaptureFailure> {
    let mut lit = Vec::new();
    let mut unreadable = 0;
    for &flag in flags {
        match is_set(flag) {
            Some(true) => lit.push(flag),
            Some(false) => {}
            None => unreadable += 1,
        }
    }
    if !flags.is_empty() && unreadable == flags.len() {
        return Err(CaptureFailure::FlagsUnreadable);
    }
    Ok((lit, unreadable))
}

/// Whether no load can have come between the start of a capture's reads,
/// which found the map `before` loaded, and their end, `elapsed` later, which
/// found `after` (`None`: no map loaded): the same map, read within
/// `READ_WINDOW_MAX`.
pub fn no_load_between(before: u32, after: Option<u32>, elapsed: Duration) -> bool {
    after == Some(before) && elapsed <= READ_WINDOW_MAX
}

/// The state a capture sends, from its reads: the `stats` as read, the
/// transferable ids among `held` (`relay_items::transferable_items`, a goods
/// id looked up in `goods_types` by its param id; one with no row is not
/// transferable), the `grace_flags` lit; fitted to the wire caps
/// (`relay_items::fit_to_wire`), with the count of values that cut. Fails
/// when the stats are not plausible (`relay_items::stats_plausible`): a
/// state the receiver would not write is not worth sending.
pub fn build_state(
    stats: ([u32; 8], u32, u32),
    held: impl Iterator<Item = u32>,
    goods_types: &HashMap<u32, u8>,
    grace_flags: Vec<u32>,
) -> Result<(CharacterState, usize), CaptureFailure> {
    let (attributes, level, runes) = stats;
    let mut state = CharacterState {
        attributes,
        level,
        runes,
        items: Vec::new(),
        grace_flags,
    };
    if !stats_plausible(&state) {
        return Err(CaptureFailure::StatsImplausible {
            attributes,
            level,
            runes,
        });
    }
    state.items = transferable_items(held, |id| goods_types.get(&id).copied());
    let cut = fit_to_wire(&mut state);
    Ok((state, cut))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::relay_items::MAX_STATE_ITEMS;

    const ARMOR: u32 = 0x1000_0000;
    const TALISMAN: u32 = 0x2000_0000;
    const GOODS: u32 = 0x4000_0000;
    const GEM: u32 = 0x8000_0000;

    /// A level 73 character's attributes, as the game stores them.
    const ATTRIBUTES: [i32; 8] = [40, 20, 30, 18, 16, 9, 7, 12];

    fn stats() -> ([u32; 8], u32, u32) {
        stats_from_game(ATTRIBUTES, 73, 12_345).expect("non-negative")
    }

    #[test]
    fn a_negative_stat_is_unreadable() {
        assert_eq!(
            stats_from_game(ATTRIBUTES, 73, 12_345),
            Some(([40, 20, 30, 18, 16, 9, 7, 12], 73, 12_345))
        );
        for idx in 0..8 {
            let mut attributes = ATTRIBUTES;
            attributes[idx] = -1;
            assert_eq!(stats_from_game(attributes, 73, 0), None, "attribute {idx}");
        }
        assert_eq!(stats_from_game(ATTRIBUTES, -1, 0), None);
        assert_eq!(stats_from_game(ATTRIBUTES, 73, i32::MIN), None);
        // The largest i32 converts; plausibility is judged on the state.
        assert_eq!(
            stats_from_game(ATTRIBUTES, 73, i32::MAX).map(|(_, _, runes)| runes),
            Some(2_147_483_647)
        );
    }

    #[test]
    fn a_goods_row_outside_the_item_id_space_is_left_out() {
        let types = goods_type_map(Some([(130, 1), (4000, 5), (0x1000_0000, 5), (u64::MAX, 5)]))
            .expect("rows left");
        assert_eq!(types.len(), 2);
        assert_eq!(types.get(&4000), Some(&5));
        assert_eq!(types.get(&0x0FFF_FFFF), None);
        assert_eq!(
            goods_type_map(Some([(0x0FFF_FFFF, 7)])).map(|t| t.len()),
            Ok(1)
        );
    }

    #[test]
    fn a_goods_table_that_does_not_read_says_why() {
        assert_eq!(
            goods_type_map(None::<[(u64, u8); 0]>),
            Err(TableUnread::NotIndexed)
        );
        assert_eq!(goods_type_map(Some([])), Err(TableUnread::NoUsableRow));
        assert_eq!(
            goods_type_map(Some([(1 << 40, 5)])),
            Err(TableUnread::NoUsableRow)
        );
    }

    #[test]
    fn grace_flags_are_nonzero_sorted_and_unique() {
        assert_eq!(
            grace_flag_ids(Some([76_101, 0, 71_190, 76_101, 0])),
            Ok(vec![71_190, 76_101])
        );
        assert_eq!(
            grace_flag_ids(None::<[u32; 0]>),
            Err(TableUnread::NotIndexed)
        );
        assert_eq!(grace_flag_ids(Some([0, 0])), Err(TableUnread::NoUsableRow));
        assert_eq!(grace_flag_ids(Some([])), Err(TableUnread::NoUsableRow));
    }

    #[test]
    fn an_unreadable_flag_is_not_lit_but_counted() {
        let read = |flag: u32| match flag {
            1 | 3 => Some(true),
            2 => Some(false),
            _ => None,
        };
        assert_eq!(lit_flags(&[1, 2, 3, 4, 5], read), Ok((vec![1, 3], 2)));
        assert_eq!(lit_flags(&[2], read), Ok((vec![], 0)));
        // None read at all: the reader is down, not a character with no grace.
        assert_eq!(
            lit_flags(&[4, 5], read),
            Err(CaptureFailure::FlagsUnreadable)
        );
        assert_eq!(lit_flags(&[], read), Ok((vec![], 0)));
    }

    #[test]
    fn a_load_between_the_reads_fails_the_bracket() {
        const LIMGRAVE: u32 = 0x3C2C_2400;
        let quick = Duration::from_millis(40);
        assert!(no_load_between(LIMGRAVE, Some(LIMGRAVE), quick));
        assert!(no_load_between(LIMGRAVE, Some(LIMGRAVE), READ_WINDOW_MAX));
        // The map went away (a loading screen began) or another one loaded.
        assert!(!no_load_between(LIMGRAVE, None, quick));
        assert!(!no_load_between(LIMGRAVE, Some(0x0A01_0000), quick));
        // Slow reads leave room for a whole load back to the same map.
        assert!(!no_load_between(
            LIMGRAVE,
            Some(LIMGRAVE),
            READ_WINDOW_MAX + Duration::from_millis(1)
        ));
    }

    #[test]
    fn a_torn_stat_read_fails_the_capture() {
        // Attributes zeroed by a load: level no longer their sum minus 79.
        assert_eq!(
            build_state(([0; 8], 73, 5), std::iter::empty(), &HashMap::new(), vec![]),
            Err(CaptureFailure::StatsImplausible {
                attributes: [0; 8],
                level: 73,
                runes: 5,
            })
        );
        let (attributes, _, runes) = stats();
        assert!(matches!(
            build_state(
                (attributes, 74, runes),
                std::iter::empty(),
                &HashMap::new(),
                vec![]
            ),
            Err(CaptureFailure::StatsImplausible { level: 74, .. })
        ));
    }

    #[test]
    fn items_are_filtered_through_the_goods_types_read() {
        let types: HashMap<u32, u8> = [(130, 1), (4000, 5), (4100, 16)].into_iter().collect();
        let held = [
            GOODS | 4100,
            2_000_007,
            GOODS | 130,
            GOODS | 9999,
            50_000_000,
            TALISMAN | 1000,
            GOODS | 4000,
            2_000_007,
        ];
        let (state, cut) = build_state(stats(), held.into_iter(), &types, vec![76_101, 71_190])
            .expect("plausible");
        assert_eq!(cut, 0);
        // The key item (type 1), the goods with no row and the arrows stay.
        assert_eq!(
            state.items,
            vec![2_000_007, TALISMAN | 1000, GOODS | 4000, GOODS | 4100]
        );
        assert_eq!(state.grace_flags, vec![71_190, 76_101]);
        assert_eq!((state.attributes, state.level, state.runes), stats());
    }

    #[test]
    fn without_goods_types_the_rest_of_the_build_still_transfers() {
        // The goods table did not read: no goods id is transferable, every
        // other category is judged as usual, and no grace row means no grace.
        let held = [
            GOODS | 4000,
            ARMOR | 40_000,
            2_000_007,
            TALISMAN | 1000,
            GEM | 10_000,
        ];
        let (state, cut) =
            build_state(stats(), held.into_iter(), &HashMap::new(), Vec::new()).expect("plausible");
        assert_eq!(cut, 0);
        assert_eq!(
            state.items,
            vec![2_000_007, ARMOR | 40_000, TALISMAN | 1000, GEM | 10_000]
        );
        assert!(state.grace_flags.is_empty());
    }

    #[test]
    fn a_state_over_the_wire_caps_is_cut_and_counted() {
        let held = (0..MAX_STATE_ITEMS as u32 + 3).map(|i| TALISMAN | i);
        let (state, cut) = build_state(stats(), held, &HashMap::new(), vec![]).expect("plausible");
        assert_eq!(cut, 3);
        assert_eq!(state.items.len(), MAX_STATE_ITEMS);
        assert_eq!(
            state.items.last(),
            Some(&(TALISMAN | (MAX_STATE_ITEMS as u32 - 1)))
        );
    }
}
