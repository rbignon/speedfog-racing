//! What a relay capture's reads make: the checks they must pass and the
//! state they build. The shell reads the game on its worker thread (the
//! grace flags and which of them are set, the loaded map before and after
//! the reads); this module decides whether those reads are worth sending,
//! and builds the state, fitted to the wire. A grace table that does not
//! read fails no capture: the state then carries no grace. Pure: nothing
//! here reads the game or logs.

use std::time::Duration;

use super::protocol::CharacterState;

/// Longest the reads of one capture may take. A load (the map unloaded, then
/// loaded again) takes longer, so reads that find the same loaded map before
/// and after them, within this bound, saw no load in between.
pub const READ_WINDOW_MAX: Duration = Duration::from_secs(1);

/// Most grace flags a `relay_state` may carry (server cap, beyond which it
/// drops the whole message).
pub const MAX_STATE_GRACES: usize = 1000;
/// Largest grace flag a `relay_state` may carry.
pub const MAX_STATE_INT: u32 = 2_147_483_647;

/// Why a capture gave no state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureFailure {
    /// No map loaded when the reads began (a loading screen, the menu).
    NotLoaded,
    /// The event flag reader is down, or it read none of the grace flags.
    FlagsUnreadable,
    /// The loaded map changed or went away during the reads, or they took
    /// longer than `READ_WINDOW_MAX`: a load may have come in between.
    LoadDuringCapture,
}

/// Why a param table gave the capture nothing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TableUnread {
    /// The game's param index holds no table of that name.
    NotIndexed,
    /// The table holds no usable row.
    NoUsableRow,
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

/// Fits `state` to the server's wire caps: drops the grace flags above
/// `MAX_STATE_INT`, sorts and dedups the rest, keeps the first
/// `MAX_STATE_GRACES`. Returns how many values it dropped or cut
/// (duplicates excluded), for the caller to warn about. Sorted order makes
/// what is kept independent of the order the flags were read in.
pub fn fit_to_wire(state: &mut CharacterState) -> usize {
    let graces = &mut state.grace_flags;
    let before = graces.len();
    graces.retain(|&flag| flag <= MAX_STATE_INT);
    let mut dropped = before - graces.len();
    graces.sort_unstable();
    graces.dedup();
    if graces.len() > MAX_STATE_GRACES {
        dropped += graces.len() - MAX_STATE_GRACES;
        graces.truncate(MAX_STATE_GRACES);
    }
    dropped
}

/// The state a capture sends, from the `grace_flags` it read lit, fitted to
/// the wire caps (`fit_to_wire`), with the count of values that cut.
pub fn build_state(grace_flags: Vec<u32>) -> (CharacterState, usize) {
    let mut state = CharacterState { grace_flags };
    let cut = fit_to_wire(&mut state);
    (state, cut)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(grace_flags: Vec<u32>) -> CharacterState {
        CharacterState { grace_flags }
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
    fn grace_flags_are_sorted_and_deduplicated_without_counting() {
        let mut s = state(vec![76_101, 71_190, 76_101, 71_000]);
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.grace_flags, vec![71_000, 71_190, 76_101]);
        // Already within bounds: unchanged.
        let before = s.clone();
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s, before);
    }

    #[test]
    fn a_grace_flag_past_the_wire_integer_is_dropped_and_counted() {
        let mut s = state(vec![2_147_483_648, MAX_STATE_INT, u32::MAX]);
        assert_eq!(fit_to_wire(&mut s), 2);
        assert_eq!(s.grace_flags, vec![MAX_STATE_INT]);
    }

    #[test]
    fn graces_over_the_cap_are_cut_and_counted() {
        // Exactly the cap: nothing cut.
        let mut s = state((1..=MAX_STATE_GRACES as u32).rev().collect());
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.grace_flags.len(), MAX_STATE_GRACES);
        // Three over, in reverse order: the three highest go, whatever the
        // order they were read in.
        let mut s = state((1..=MAX_STATE_GRACES as u32 + 3).rev().collect());
        assert_eq!(fit_to_wire(&mut s), 3);
        assert_eq!(
            s.grace_flags,
            (1..=MAX_STATE_GRACES as u32).collect::<Vec<_>>()
        );
        // Duplicates go before the cap is applied: 1001 values, 999
        // distinct, nothing cut.
        let mut s = state((1..=999).chain([1, 2]).collect());
        assert_eq!(s.grace_flags.len(), MAX_STATE_GRACES + 1);
        assert_eq!(fit_to_wire(&mut s), 0);
        assert_eq!(s.grace_flags.len(), 999);
    }

    #[test]
    fn a_built_state_carries_the_fitted_graces_and_the_count_cut() {
        assert_eq!(
            build_state(vec![76_101, 71_190, 76_101]),
            (state(vec![71_190, 76_101]), 0)
        );
        let (built, cut) = build_state((0..MAX_STATE_GRACES as u32 + 2).rev().collect());
        assert_eq!(cut, 2);
        assert_eq!(built.grace_flags.len(), MAX_STATE_GRACES);
        assert_eq!(
            built.grace_flags.last(),
            Some(&(MAX_STATE_GRACES as u32 - 1))
        );
        assert_eq!(build_state(Vec::new()), (state(Vec::new()), 0));
    }
}
