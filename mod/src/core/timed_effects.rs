//! Timed SpEffects the mod applied, on the play clock.
//!
//! The game drops the SpEffects the mod applies at a load: the race machine
//! keeps when each timed one ends, on the play clock (`core::play_clock`),
//! and applies again those with time left at each loading exit. Instant ones
//! (runes, damage, poison) are never tracked. Pure timing: every method takes
//! the play time.
//!
//! `timed_apply` plans how the shell gives an applied SpEffect its time left:
//! which row to apply and the timer to write into its entry.

use std::time::Duration;

/// How close a timer must be to a row's own endurance to count as a fresh
/// application of that row, in seconds.
const FULL_EPS_S: f32 = 0.25;

/// A SpEffect row's timing, read from its param row: its own endurance
/// (`effectEndurance`, seconds), its cycle interval (`motionInterval`,
/// seconds) and, when it cycles another row (`cycleOccurrenceSpEffectId`),
/// that row's id and endurance. The cycled row is the tail: applied again
/// every interval while the row runs, it outlasts the row by its own
/// endurance.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SpEffectTiming {
    pub endurance_s: f32,
    pub interval_s: f32,
    pub tail: Option<(u32, f32)>,
}

/// What the shell applies for a timed SpEffect: the row and the timer its
/// entry gets. `full`: the timer is the row's own endurance, so a fresh
/// application already holds it and nothing needs writing.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TimedApply {
    pub speffect_id: u32,
    pub timer_s: f32,
    pub full: bool,
}

/// Plan the application of `speffect_id`, whose row's timing is `timing`,
/// with `left_s` seconds left. When the time left fits in the tail's
/// endurance plus one cycle interval, the tail row alone carries it, for at
/// most its own endurance (a row left with less than a cycle could run out
/// before its first cycled application, losing the whole tail); otherwise
/// the row runs what the tail will not, capped at its own endurance. A tail
/// without endurance counts as none.
pub fn timed_apply(speffect_id: u32, timing: SpEffectTiming, left_s: f32) -> TimedApply {
    let tail = timing.tail.filter(|&(_, endurance)| endurance > 0.0);
    let (speffect_id, timer_s, endurance) = match tail {
        Some((tail_id, tail_s)) if left_s <= tail_s + timing.interval_s => {
            (tail_id, left_s.min(tail_s), tail_s)
        }
        _ => {
            let row_left = left_s - tail.map_or(0.0, |(_, tail_s)| tail_s);
            let timer_s = if timing.endurance_s > 0.0 {
                row_left.min(timing.endurance_s)
            } else {
                row_left
            };
            (speffect_id, timer_s, timing.endurance_s)
        }
    };
    TimedApply {
        speffect_id,
        timer_s,
        full: (timer_s - endurance).abs() <= FULL_EPS_S,
    }
}

#[derive(Debug, Default)]
pub struct TimedEffects {
    /// SpEffect id and its end on the play clock, one entry per id, in the
    /// order they started.
    running: Vec<(u32, Duration)>,
}

impl TimedEffects {
    /// Track `speffect_id` for `duration` from `play`; an id already running
    /// keeps the later end (the game holds one entry per id).
    pub fn start(&mut self, speffect_id: u32, duration: Duration, play: Duration) {
        let ends_at = play + duration;
        match self.running.iter_mut().find(|(id, _)| *id == speffect_id) {
            Some((_, end)) => *end = (*end).max(ends_at),
            None => self.running.push((speffect_id, ends_at)),
        }
    }

    /// The effects with time left at `play`: id and time left; ended ones
    /// are skipped.
    pub fn live(&self, play: Duration) -> impl Iterator<Item = (u32, Duration)> + '_ {
        self.running.iter().filter_map(move |&(id, end)| {
            end.checked_sub(play)
                .filter(|left| !left.is_zero())
                .map(|left| (id, left))
        })
    }

    /// Forget the effects ended at `play`.
    pub fn prune(&mut self, play: Duration) {
        self.running.retain(|&(_, end)| end > play);
    }

    /// Forget every effect (the run is over, or another one starts).
    pub fn clear(&mut self) {
        self.running.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(s: u64) -> Duration {
        Duration::from_secs(s)
    }

    #[test]
    fn the_later_end_wins_per_id() {
        let mut fx = TimedEffects::default();
        fx.start(1, secs(15), Duration::ZERO);
        fx.start(1, secs(15), secs(5));
        // A shorter later application must not cut the running one short.
        fx.start(1, secs(1), secs(6));
        fx.start(2, secs(15), secs(6));
        assert_eq!(
            fx.live(secs(10)).collect::<Vec<_>>(),
            [(1, secs(10)), (2, secs(11))]
        );
    }

    const MUSHROOM: SpEffectTiming = SpEffectTiming {
        endurance_s: 15.0,
        interval_s: 0.5,
        tail: Some((102360, 15.0)),
    };

    #[test]
    fn timed_apply_splits_the_time_left_over_the_cycled_tail() {
        // 30 s in all: the row's own 15 s, then the cycled row's 15 s.
        assert_eq!(
            timed_apply(1450826, MUSHROOM, 30.0),
            TimedApply {
                speffect_id: 1450826,
                timer_s: 15.0,
                full: true
            }
        );
        assert_eq!(
            timed_apply(1450826, MUSHROOM, 25.0),
            TimedApply {
                speffect_id: 1450826,
                timer_s: 10.0,
                full: false
            }
        );
        // Within the tail's own time: the tail row alone.
        assert_eq!(
            timed_apply(1450826, MUSHROOM, 10.0),
            TimedApply {
                speffect_id: 102360,
                timer_s: 10.0,
                full: false
            }
        );
        // More than both: the row capped at its own endurance.
        assert_eq!(
            timed_apply(1450826, MUSHROOM, 40.0),
            TimedApply {
                speffect_id: 1450826,
                timer_s: 15.0,
                full: true
            }
        );
    }

    #[test]
    fn timed_apply_never_leaves_the_row_less_than_a_cycle() {
        // 0.3 s of row could run out before its first cycled application,
        // losing the whole tail: the tail row alone, at its full 15 s.
        assert_eq!(
            timed_apply(1450826, MUSHROOM, 15.3),
            TimedApply {
                speffect_id: 102360,
                timer_s: 15.0,
                full: true
            }
        );
        // More than a cycle of row left: the row, then its tail.
        let plan = timed_apply(1450826, MUSHROOM, 15.6);
        assert_eq!(plan.speffect_id, 1450826);
        assert!((plan.timer_s - 0.6).abs() < 1e-4, "{plan:?}");
        assert!(!plan.full);
    }

    #[test]
    fn timed_apply_full_allows_a_short_tail() {
        // The Lightning's row cycles a 0.1 s one: 14.9 s on a 15 s row is
        // still a fresh application, nothing to write.
        let lightning = SpEffectTiming {
            endurance_s: 15.0,
            interval_s: 0.06,
            tail: Some((4101, 0.1)),
        };
        let plan = timed_apply(1450830, lightning, 15.0);
        assert_eq!(plan.speffect_id, 1450830);
        assert!(plan.full);
    }

    #[test]
    fn timed_apply_without_a_tail() {
        let plain_row = SpEffectTiming {
            endurance_s: 15.0,
            interval_s: 0.0,
            tail: None,
        };
        assert_eq!(
            timed_apply(7, plain_row, 7.0),
            TimedApply {
                speffect_id: 7,
                timer_s: 7.0,
                full: false
            }
        );
        // A tail without endurance counts as none: its -1 s takes nothing
        // off the row's time.
        let no_endurance_tail = SpEffectTiming {
            endurance_s: 15.0,
            interval_s: 0.0,
            tail: Some((8, -1.0)),
        };
        assert_eq!(
            timed_apply(7, no_endurance_tail, 7.0),
            TimedApply {
                speffect_id: 7,
                timer_s: 7.0,
                full: false
            }
        );
    }

    #[test]
    fn live_skips_ended_effects() {
        let mut fx = TimedEffects::default();
        fx.start(1, secs(5), Duration::ZERO);
        fx.start(2, secs(15), Duration::ZERO);
        // One at its very end has no time left.
        assert_eq!(fx.live(secs(5)).collect::<Vec<_>>(), [(2, secs(10))]);
        fx.prune(secs(5));
        assert_eq!(fx.running.len(), 1);
        fx.clear();
        assert_eq!(fx.live(Duration::ZERO).count(), 0);
    }
}
