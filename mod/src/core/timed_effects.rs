//! Timed SpEffects the mod applied, on the play clock.
//!
//! The game drops the SpEffects the mod applies at a load: the race machine
//! keeps when each timed one ends, on the play clock (`core::play_clock`),
//! and applies again those with time left at each loading exit. Instant ones
//! (runes, damage, poison) are never tracked. Pure timing: every method takes
//! the play time.

use std::time::Duration;

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
