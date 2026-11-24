//! A relay team's boss loot: what a `relay_loot` entry comes to on the save
//! loaded, and the entries waiting to be given. Each entry is the loot of one
//! boss the team killed (its items, its rune SpEffect) with a saved
//! "received" flag of its own. The shell reads the entry's flags in the save
//! and gives through the game's own functions; this module decides what an
//! entry needs from what those reads found (`decide`), carries the decision
//! out through the shell's access (`carry_out`) and orders the entries that
//! wait for a frame (`LootQueue`). The race machine decides on which frame an
//! entry is given (`RaceMachine::maintain_relay_loot`). Pure: nothing here
//! reads the game or logs.

use std::time::{Duration, Instant};

use crate::core::protocol::RelayLootEntry;

/// Units given for one entry at most, all in its frame: a quantity past it
/// is cut (and counted).
pub const LOOT_UNITS_MAX: u32 = 64;
/// An entry nothing was done to is tried again no sooner than this.
pub const LOOT_RETRY: Duration = Duration::from_millis(500);
/// Tries of one entry before it is dropped (the list of the next `auth_ok`
/// brings it back).
pub const LOOT_TRIES_MAX: u32 = 20;

/// What an entry needs on the save loaded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LootAction {
    /// Received already: nothing.
    Skip,
    /// Paid on this save already (by the game, or as the server says):
    /// only the received flag is raised.
    MarkOnly,
    /// Given: its items and runes, then its received flag and its pickup
    /// flags raised.
    Give,
}

/// What an entry needs, from what its flags read in the save (`None`: the
/// flag did not read), for a message `paid` or not. `defeated` is the
/// entry's own flag, the boss's defeat flag; `pickups` its pickup flags.
/// `None`: a flag it needs did not read, decide later.
pub fn decide(
    received: Option<bool>,
    paid: bool,
    defeated: Option<bool>,
    pickups: &[Option<bool>],
) -> Option<LootAction> {
    if received? {
        return Some(LootAction::Skip);
    }
    if paid {
        return Some(LootAction::MarkOnly);
    }
    // A save that never fought the boss has its defeat flag down: a pickup
    // flag up there is up for another reason. Up, the defeat flag may have
    // been written by a take: only a pickup flag up too says the game paid.
    if !defeated? {
        return Some(LootAction::Give);
    }
    if pickups.contains(&Some(true)) {
        return Some(LootAction::MarkOnly);
    }
    if pickups.contains(&None) {
        return None;
    }
    Some(LootAction::Give)
}

/// The (item id, units) to give, in the entry's order, cut at
/// `LOOT_UNITS_MAX` units in all; and the units cut.
pub fn units(entry: &RelayLootEntry) -> (Vec<(u32, u32)>, u32) {
    let mut left = LOOT_UNITS_MAX;
    let mut cut = 0u32;
    let mut out = Vec::new();
    for item in &entry.items {
        let n = item.qty.min(left);
        if n > 0 {
            out.push((item.id, n));
        }
        left -= n;
        cut = cut.saturating_add(item.qty - n);
    }
    (out, cut)
}

/// What became of an entry handed to the shell.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LootOutcome {
    /// Its received flag was up: nothing done.
    AlreadyReceived,
    /// Only its received flag raised.
    Marked,
    /// Given: `units` handed to the game, `failed` refused after a first
    /// give, `cut` past `LOOT_UNITS_MAX`, the rune effect refused
    /// (`rune_refused`); then its flags raised.
    Given {
        units: u32,
        failed: u32,
        cut: u32,
        rune_refused: bool,
    },
    /// Nothing done, to try later: a flag it needed did not read, its
    /// received flag could not be raised, or the game could not take its
    /// first give (the give function or the player not there).
    Unreadable,
}

/// Carry `action` out on `entry` through the shell's access to the game:
/// `give_unit` gives one unit of an item, `apply_rune` applies a SpEffect to
/// the player, `raise` raises a flag; each returns whether the game took it.
/// A mark raises the received flag only. A give gives every unit of
/// `units(entry)`, then the rune effect when the entry has one, then raises
/// the received flag and every pickup flag. When the first thing tried (the
/// first unit, or the rune effect of an entry with no item) is refused,
/// nothing else is tried and nothing raised: the entry can be given whole
/// later. After that first give, a refusal is counted and the rest goes on:
/// what was given cannot be taken back, so the entry is marked.
pub fn carry_out(
    action: LootAction,
    entry: &RelayLootEntry,
    mut give_unit: impl FnMut(u32) -> bool,
    mut apply_rune: impl FnMut(u32) -> bool,
    mut raise: impl FnMut(u32) -> bool,
) -> LootOutcome {
    match action {
        LootAction::Skip => LootOutcome::AlreadyReceived,
        LootAction::MarkOnly => {
            if raise(entry.received_flag) {
                LootOutcome::Marked
            } else {
                LootOutcome::Unreadable
            }
        }
        LootAction::Give => {
            let (to_give, cut) = units(entry);
            let (mut given, mut failed) = (0u32, 0u32);
            for (id, n) in to_give {
                for _ in 0..n {
                    if give_unit(id) {
                        given += 1;
                    } else if given == 0 {
                        return LootOutcome::Unreadable;
                    } else {
                        failed += 1;
                    }
                }
            }
            let rune_refused = match entry.rune_speffect {
                Some(speffect) if !apply_rune(speffect) => {
                    if given == 0 {
                        return LootOutcome::Unreadable;
                    }
                    true
                }
                _ => false,
            };
            // Every flag, whatever a write did: a flag left down is the
            // shell's to report, the gives are made.
            raise(entry.received_flag);
            for &flag in &entry.pickup_flags {
                raise(flag);
            }
            LootOutcome::Given {
                units: given,
                failed,
                cut,
                rune_refused,
            }
        }
    }
}

/// An entry waiting in the queue.
#[derive(Debug)]
struct Waiting {
    entry: RelayLootEntry,
    paid: bool,
    /// Tries that did nothing so far.
    tries: u32,
    /// Not handed out before this.
    due: Instant,
}

/// The entries waiting for a frame, one per flag, by arrival (an entry
/// tried again goes behind the others).
#[derive(Debug, Default)]
pub struct LootQueue {
    waiting: Vec<Waiting>,
    /// The flag of the entry `next` handed out last, with its tries: what
    /// `retry` counts on.
    out: Option<(u32, u32)>,
}

impl LootQueue {
    /// Queue `entry`; one of the same flag waiting already is replaced in
    /// its place, `paid` kept if either is (the killer's entry stays paid
    /// when the list of a reconnection sends it again).
    pub fn push(&mut self, entry: RelayLootEntry, paid: bool, now: Instant) {
        match self.waiting.iter_mut().find(|w| w.entry.flag == entry.flag) {
            Some(w) => {
                w.entry = entry;
                w.paid |= paid;
            }
            None => self.waiting.push(Waiting {
                entry,
                paid,
                tries: 0,
                due: now,
            }),
        }
    }

    /// The first entry due at `now`, taken out, with its `paid`.
    pub fn next(&mut self, now: Instant) -> Option<(RelayLootEntry, bool)> {
        let index = self.waiting.iter().position(|w| w.due <= now)?;
        let w = self.waiting.remove(index);
        self.out = Some((w.entry.flag, w.tries));
        Some((w.entry, w.paid))
    }

    /// Put back the entry `next` handed out, nothing done to it, due again
    /// `LOOT_RETRY` after `now`. False when this was its last try
    /// (`LOOT_TRIES_MAX`): it is dropped. One of the same flag queued since
    /// it was handed out stays as it is, with the paid of either.
    pub fn retry(&mut self, entry: RelayLootEntry, paid: bool, now: Instant) -> bool {
        let tries = self
            .out
            .take()
            .filter(|&(flag, _)| flag == entry.flag)
            .map_or(0, |(_, tries)| tries)
            + 1;
        if let Some(w) = self.waiting.iter_mut().find(|w| w.entry.flag == entry.flag) {
            w.paid |= paid;
            return true;
        }
        if tries >= LOOT_TRIES_MAX {
            return false;
        }
        self.waiting.push(Waiting {
            entry,
            paid,
            tries,
            due: now + LOOT_RETRY,
        });
        true
    }

    pub fn clear(&mut self) {
        self.waiting.clear();
        self.out = None;
    }

    pub fn is_empty(&self) -> bool {
        self.waiting.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;

    use super::*;
    use crate::core::protocol::RelayLootItem;

    /// The entry of boss flag `flag`, with no item and no rune.
    fn entry(flag: u32) -> RelayLootEntry {
        RelayLootEntry {
            flag,
            received_flag: 1_050_297_000,
            pickup_flags: Vec::new(),
            items: Vec::new(),
            rune_speffect: None,
            runes: 0,
        }
    }

    /// An entry with `items` as `(id, qty)`.
    fn entry_with(items: &[(u32, u32)]) -> RelayLootEntry {
        RelayLootEntry {
            items: items
                .iter()
                .map(|&(id, qty)| RelayLootItem { id, qty })
                .collect(),
            ..entry(11_050_850)
        }
    }

    #[test]
    fn what_to_do_with_an_entry() {
        use LootAction::*;
        let (up, down) = (Some(true), Some(false));
        assert_eq!(decide(None, false, up, &[]), None);
        assert_eq!(decide(up, false, up, &[down]), Some(Skip));
        assert_eq!(decide(up, true, down, &[]), Some(Skip));
        assert_eq!(decide(down, true, down, &[down]), Some(MarkOnly)); // the killer, told by the server
        assert_eq!(decide(down, false, None, &[up]), None); // defeat flag unread
        assert_eq!(decide(down, false, down, &[up]), Some(Give)); // a pickup flag up for another reason
        assert_eq!(decide(down, false, down, &[None]), Some(Give)); // pickups not needed when not defeated
        assert_eq!(decide(down, false, up, &[down, up]), Some(MarkOnly)); // the game paid this boss here
        assert_eq!(decide(down, false, up, &[None, up]), Some(MarkOnly)); // one up is enough
        assert_eq!(decide(down, false, up, &[down, None]), None);
        assert_eq!(decide(down, false, up, &[down]), Some(Give)); // defeat flag written by a take
        assert_eq!(decide(down, false, up, &[]), Some(Give)); // a boss with no lot
    }

    #[test]
    fn units_are_cut_at_the_ceiling_and_the_cut_is_counted() {
        let e = entry_with(&[(10, 3), (11, 100), (12, 2)]);
        assert_eq!(units(&e), (vec![(10, 3), (11, 61)], 41));
    }

    #[test]
    fn the_queue_holds_one_entry_per_flag_and_remembers_paid() {
        let t = Instant::now();
        let mut q = LootQueue::default();
        q.push(entry(7), true, t);
        q.push(entry(7), false, t);
        q.push(entry(9), false, t);
        assert_eq!(q.next(t).map(|(e, paid)| (e.flag, paid)), Some((7, true)));
        assert_eq!(q.next(t).map(|(e, _)| e.flag), Some(9));
        assert!(q.next(t).is_none());
    }

    #[test]
    fn a_retried_entry_waits_and_is_dropped_after_its_tries() {
        let mut now = Instant::now();
        let mut q = LootQueue::default();
        q.push(entry(7), false, now);
        for attempt in 1..LOOT_TRIES_MAX {
            let (e, paid) = q.next(now).unwrap();
            assert!(q.retry(e, paid, now), "attempt {attempt}");
            assert!(q
                .next(now + LOOT_RETRY - Duration::from_millis(1))
                .is_none());
            now += LOOT_RETRY;
        }
        let (e, paid) = q.next(now).unwrap();
        assert!(!q.retry(e, paid, now)); // the last try: dropped
        assert!(q.is_empty());
    }

    #[test]
    fn a_retried_entry_goes_behind_the_others_and_keeps_paid() {
        let t = Instant::now();
        let mut q = LootQueue::default();
        q.push(entry(7), true, t);
        q.push(entry(9), false, t);
        q.push(entry(11), false, t);
        let (e, paid) = q.next(t).unwrap();
        assert!(q.retry(e, paid, t));
        let order: Vec<_> = std::iter::from_fn(|| q.next(t))
            .map(|(e, _)| e.flag)
            .collect();
        assert_eq!(order, [9, 11]);
        // Due again after its delay, still paid.
        assert_eq!(q.next(t + LOOT_RETRY), Some((entry(7), true)));
    }

    /// What `carry_out` asked of the game, in order: `("unit", id)`,
    /// `("rune", speffect)`, `("raise", flag)`.
    type Calls = RefCell<Vec<(&'static str, u32)>>;

    /// `carry_out` with gives refused from the `refuse_from`-th unit on (0:
    /// every unit), the rune effect taken or not, every raise taken unless
    /// `raise_ok` is false; the calls made.
    fn run(
        action: LootAction,
        e: &RelayLootEntry,
        refuse_from: Option<usize>,
        rune_ok: bool,
        raise_ok: bool,
    ) -> (LootOutcome, Vec<(&'static str, u32)>) {
        let calls = Calls::default();
        let outcome = carry_out(
            action,
            e,
            |id| {
                let index = calls.borrow().iter().filter(|c| c.0 == "unit").count();
                calls.borrow_mut().push(("unit", id));
                refuse_from.is_none_or(|from| index < from)
            },
            |speffect| {
                calls.borrow_mut().push(("rune", speffect));
                rune_ok
            },
            |flag| {
                calls.borrow_mut().push(("raise", flag));
                raise_ok
            },
        );
        (outcome, calls.into_inner())
    }

    /// An entry with two units of item 10, a rune effect and two pickup
    /// flags.
    fn full_entry() -> RelayLootEntry {
        RelayLootEntry {
            pickup_flags: vec![510_060, 65_420],
            rune_speffect: Some(755_891_000),
            runes: 13_000,
            ..entry_with(&[(10, 2)])
        }
    }

    #[test]
    fn a_give_gives_the_units_then_the_runes_then_raises_the_flags() {
        let (outcome, calls) = run(LootAction::Give, &full_entry(), None, true, true);
        assert_eq!(
            outcome,
            LootOutcome::Given {
                units: 2,
                failed: 0,
                cut: 0,
                rune_refused: false
            }
        );
        assert_eq!(
            calls,
            [
                ("unit", 10),
                ("unit", 10),
                ("rune", 755_891_000),
                ("raise", 1_050_297_000),
                ("raise", 510_060),
                ("raise", 65_420),
            ]
        );
    }

    #[test]
    fn a_first_give_refused_leaves_the_entry_whole() {
        // The first unit, or the rune effect of an entry with no item.
        let (outcome, calls) = run(LootAction::Give, &full_entry(), Some(0), true, true);
        assert_eq!(outcome, LootOutcome::Unreadable);
        assert_eq!(calls, [("unit", 10)]);
        let runes_only = RelayLootEntry {
            items: Vec::new(),
            ..full_entry()
        };
        let (outcome, calls) = run(LootAction::Give, &runes_only, None, false, true);
        assert_eq!(outcome, LootOutcome::Unreadable);
        assert_eq!(calls, [("rune", 755_891_000)]);
    }

    #[test]
    fn a_refusal_after_a_first_give_is_counted_and_the_entry_marked() {
        let (outcome, calls) = run(LootAction::Give, &full_entry(), Some(1), false, true);
        assert_eq!(
            outcome,
            LootOutcome::Given {
                units: 1,
                failed: 1,
                cut: 0,
                rune_refused: true
            }
        );
        assert_eq!(calls.iter().filter(|c| c.0 == "raise").count(), 3);
    }

    #[test]
    fn a_give_counts_what_the_ceiling_cut() {
        let big = entry_with(&[(10, 70)]);
        let (outcome, calls) = run(LootAction::Give, &big, None, true, true);
        assert_eq!(
            outcome,
            LootOutcome::Given {
                units: LOOT_UNITS_MAX,
                failed: 0,
                cut: 6,
                rune_refused: false
            }
        );
        assert_eq!(
            calls.iter().filter(|c| c.0 == "unit").count(),
            LOOT_UNITS_MAX as usize
        );
    }

    #[test]
    fn a_mark_raises_the_received_flag_only_and_a_skip_touches_nothing() {
        let (outcome, calls) = run(LootAction::MarkOnly, &full_entry(), None, true, true);
        assert_eq!(outcome, LootOutcome::Marked);
        assert_eq!(calls, [("raise", 1_050_297_000)]);
        // A mark the game could not take is made later.
        let (outcome, _) = run(LootAction::MarkOnly, &full_entry(), None, true, false);
        assert_eq!(outcome, LootOutcome::Unreadable);
        let (outcome, calls) = run(LootAction::Skip, &full_entry(), None, true, true);
        assert_eq!(outcome, LootOutcome::AlreadyReceived);
        assert!(calls.is_empty());
    }
}
