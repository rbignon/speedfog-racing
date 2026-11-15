//! Play clock: wall time counted only while the player is in the world.
//!
//! The race machine runs it while the player's position is readable, so
//! loading screens and the main menu do not count: what is timed on it
//! (race item effects, their reminder rows, the ink) keeps its time left
//! through a load. Pure timing: every method takes `now`, nothing reads the
//! clock.

use std::time::{Duration, Instant};

#[derive(Debug, Default, Clone, Copy)]
pub struct PlayClock {
    /// Play time counted up to the last stop.
    banked: Duration,
    /// When the clock started again, while it runs.
    since: Option<Instant>,
}

impl PlayClock {
    /// Run or stop the clock at `now`; called every frame, it only acts on
    /// a change.
    pub fn set_running(&mut self, running: bool, now: Instant) {
        match (running, self.since) {
            (true, None) => self.since = Some(now),
            (false, Some(since)) => {
                self.banked += now.saturating_duration_since(since);
                self.since = None;
            }
            _ => {}
        }
    }

    /// Play time elapsed at `now`: frozen while stopped, advancing between
    /// calls while running.
    pub fn at(&self, now: Instant) -> Duration {
        match self.since {
            Some(since) => self.banked + now.saturating_duration_since(since),
            None => self.banked,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(s: u64) -> Duration {
        Duration::from_secs(s)
    }

    #[test]
    fn stops_while_paused_and_resumes() {
        let t0 = Instant::now();
        let mut clock = PlayClock::default();
        clock.set_running(true, t0);
        // Every frame says so: a clock already running keeps its start.
        clock.set_running(true, t0 + secs(2));
        clock.set_running(false, t0 + secs(5));
        for inside in [5, 12, 25] {
            // Every frame of the pause says so too: nothing more is banked.
            clock.set_running(false, t0 + secs(inside));
            assert_eq!(clock.at(t0 + secs(inside)), secs(5), "at +{inside}s");
        }
        clock.set_running(true, t0 + secs(25));
        // Between ticks the running clock advances.
        assert_eq!(clock.at(t0 + secs(28)), secs(8));
    }
}
