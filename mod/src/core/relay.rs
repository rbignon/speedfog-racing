//! Relay races: the pure timing of a runner's lock and of its warp to the
//! Chapel.
//!
//! The seed carries a saved event flag, the lock: while it is on, the fog
//! gates of the seed do not react and fast travel is refused. A second flag
//! warps the player to the start zone (the Chapel) when raised; the seed
//! lowers it itself after the warp. The race machine decides when each is
//! written (`RaceMachine::maintain_relay`); this module holds the constants
//! and the retry timing of the warp flag. Pure: every method takes the wall
//! time (`now`).

use std::time::{Duration, Instant};

/// Map id of the Chapel, the start zone, as the position read gives it
/// (area 10, block 1, no sub-block: `m10_01_00_00`).
pub const CHAPEL_MAP_ID: u32 = 0x0A01_0000;
/// Wall time the player stays loaded after a loading exit before a relay
/// flag is written: a flag written during a loading screen can be missed by
/// the seed's events.
pub const SETTLE: Duration = Duration::from_millis(2500);
/// After the lock is first raised, a runner away from the Chapel is left
/// this long to finish what a gate transition was doing before it is sent
/// back (a loading exit since the lock closes the window too).
pub const GATE_WINDOW: Duration = Duration::from_secs(5);
/// A raised warp flag that started no load is lowered after this long.
pub const WARP_RETRY: Duration = Duration::from_secs(5);
/// Raises of the warp flag before the warp is given up.
pub const WARP_ATTEMPTS: u32 = 3;
/// Warps whose load ended away from the Chapel, in one locked stretch,
/// before the return is given up for good (a loading exit does not reset
/// the count: a wrong Chapel map id would otherwise loop forever).
pub const WARP_LANDINGS_MAX: u32 = 2;
/// How long a `relay_release` is given to capture and answer, from its
/// receipt. Under the server's `RELAY_RELEASE_TIMEOUT_S` (`RELEASE_WINDOW`),
/// so an answer is never sent after the server has cancelled.
pub const RELEASE_CAPTURE_TIMEOUT: Duration = Duration::from_secs(12);
/// The server's wait for an answer to a release: no flip can follow an
/// answer later than this, so a role turning `waiting` that long after one
/// is not that handoff.
pub const RELEASE_WINDOW: Duration = Duration::from_secs(15);

/// A `relay_release` whose answer has not been sent.
#[derive(Debug)]
pub struct PendingRelease {
    pub handoff_id: String,
    /// The teammate the baton goes to, shown when the server flips.
    pub to_name: String,
    /// When the capture is given up.
    pub deadline: Instant,
}

/// A capture the shell was asked for and has not answered.
#[derive(Debug)]
pub struct CaptureInFlight {
    /// The release it answers; `None` for a zone checkpoint.
    pub handoff_id: Option<String>,
    /// The socket dropped since it was asked: its answer is stale.
    pub link_lost: bool,
}

/// A lowered warp flag stays down this long before it is raised again.
const WARP_RELOWER: Duration = Duration::from_millis(100);

/// What the shell must do with the warp flag.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WarpStep {
    /// Write the flag on.
    Raise(u32),
    /// Write the flag off (the raise started no load).
    Lower(u32),
    /// Every attempt went by without a load.
    Failed,
}

/// One warp to the Chapel through a flag the seed's events react to: raised
/// once the player is loaded, ended by the load it starts, lowered and
/// raised again when none starts, given up after `WARP_ATTEMPTS` raises.
#[derive(Debug)]
pub struct FlagWarp {
    flag: u32,
    raises: u32,
    raised_at: Option<Instant>,
    lowered_at: Option<Instant>,
    done: bool,
}

impl FlagWarp {
    pub fn new(flag: u32) -> Self {
        Self {
            flag,
            raises: 0,
            raised_at: None,
            lowered_at: None,
            done: false,
        }
    }

    /// The step due at `now`; `loaded` is whether the player is loaded in
    /// the world this frame.
    pub fn tick(&mut self, loaded: bool, now: Instant) -> Option<WarpStep> {
        if self.done {
            return None;
        }
        if !loaded && self.raises > 0 {
            // A raise started the load (also one that starts between a
            // lower and the next raise): the seed takes it from here.
            self.done = true;
            return None;
        }
        if let Some(raised_at) = self.raised_at {
            if now.saturating_duration_since(raised_at) < WARP_RETRY {
                return None;
            }
            if self.raises >= WARP_ATTEMPTS {
                self.done = true;
                return Some(WarpStep::Failed);
            }
            self.raised_at = None;
            self.lowered_at = Some(now);
            return Some(WarpStep::Lower(self.flag));
        }
        if !loaded {
            return None;
        }
        if self
            .lowered_at
            .is_some_and(|at| now.saturating_duration_since(at) < WARP_RELOWER)
        {
            return None;
        }
        self.raises += 1;
        self.raised_at = Some(now);
        Some(WarpStep::Raise(self.flag))
    }

    pub fn is_done(&self) -> bool {
        self.done
    }

    /// The flag this warp warps through.
    pub fn flag(&self) -> u32 {
        self.flag
    }

    /// Whether the flag is on and no load has taken it yet.
    pub fn is_raised(&self) -> bool {
        !self.done && self.raised_at.is_some()
    }

    /// Drop the warp. The step to take when the flag is still on: leaving
    /// it raised would warp the player the next time the seed reads it.
    pub fn abort(&mut self) -> Option<WarpStep> {
        let step = self.is_raised().then_some(WarpStep::Lower(self.flag));
        self.done = true;
        step
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    #[test]
    fn a_warp_that_starts_no_load_is_lowered_and_raised_again() {
        let t0 = Instant::now();
        let mut w = FlagWarp::new(7);
        assert_eq!(w.tick(true, t0), Some(WarpStep::Raise(7)));
        assert_eq!(w.tick(true, t0 + ms(4_999)), None);
        assert_eq!(w.tick(true, t0 + WARP_RETRY), Some(WarpStep::Lower(7)));
        let t1 = t0 + WARP_RETRY;
        assert_eq!(w.tick(true, t1 + ms(50)), None, "stays down a moment");
        assert_eq!(w.tick(true, t1 + ms(100)), Some(WarpStep::Raise(7)));
        let t2 = t1 + ms(100) + WARP_RETRY;
        assert_eq!(w.tick(true, t2), Some(WarpStep::Lower(7)));
        assert_eq!(w.tick(true, t2 + ms(100)), Some(WarpStep::Raise(7)));
        let t3 = t2 + ms(100);
        assert_eq!(w.tick(true, t3 + ms(4_999)), None);
        assert!(!w.is_done());
        assert_eq!(w.tick(true, t3 + WARP_RETRY), Some(WarpStep::Failed));
        assert!(w.is_done());
        assert_eq!(w.tick(true, t3 + WARP_RETRY + ms(100)), None);
    }

    #[test]
    fn a_load_ends_the_warp() {
        let t0 = Instant::now();
        let mut w = FlagWarp::new(7);
        assert_eq!(w.tick(true, t0), Some(WarpStep::Raise(7)));
        assert_eq!(w.tick(false, t0 + ms(16)), None);
        assert!(w.is_done());
        assert_eq!(w.tick(true, t0 + WARP_RETRY * 2), None);
    }

    #[test]
    fn a_load_between_a_lower_and_the_next_raise_ends_the_warp() {
        let t0 = Instant::now();
        let mut w = FlagWarp::new(7);
        w.tick(true, t0);
        assert_eq!(w.tick(true, t0 + WARP_RETRY), Some(WarpStep::Lower(7)));
        assert_eq!(w.tick(false, t0 + WARP_RETRY + ms(50)), None);
        assert!(w.is_done());
        assert_eq!(w.tick(true, t0 + WARP_RETRY + ms(200)), None, "no raise");
    }

    #[test]
    fn a_warp_waits_for_the_player_to_be_loaded() {
        let t0 = Instant::now();
        let mut w = FlagWarp::new(7);
        assert_eq!(w.tick(false, t0), None);
        assert!(!w.is_done());
        assert_eq!(w.tick(true, t0 + ms(16)), Some(WarpStep::Raise(7)));
    }

    #[test]
    fn an_aborted_warp_lowers_a_flag_still_on_and_only_then() {
        let t0 = Instant::now();
        let mut w = FlagWarp::new(7);
        assert_eq!(w.abort(), None, "never raised");
        let mut w = FlagWarp::new(7);
        w.tick(true, t0);
        assert_eq!(w.abort(), Some(WarpStep::Lower(7)));
        assert!(w.is_done());
        let mut w = FlagWarp::new(7);
        w.tick(true, t0);
        w.tick(false, t0 + ms(16));
        assert_eq!(w.abort(), None, "the load took it");
    }
}
