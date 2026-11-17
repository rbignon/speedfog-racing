//! The Hunter: Margit sent after the leader, from his spawn to his end.
//!
//! The shell spawns him through the game's debug character creator, looks
//! for him on the debug chr set and ends him (0 HP); this module only
//! decides when, and what the server is told. Pure timing: every method
//! takes the wall time (`now`) and, where the hunt is timed, the play time
//! (`core::play_clock`).
//!
//! His life: a spawn waits until the player has been loaded `SETTLE` since
//! the last loading exit, then he is looked for every `FIND_INTERVAL` for
//! `FIND_WINDOW`. Not seen by then (or the spawn refused), the request
//! missed: he is ended, so a late arrival does not stay, and requested again
//! `RETRY_DELAY` later, up to `MAX_REQUESTS` requests; the last miss is
//! reported not landed, and he is still looked for every `HUNT_CHECK` for
//! `LINGER` after it: one that arrives then is ended, with nothing shown
//! and no other report. Seen, he is reported landed, his banner and
//! reminder show (`HunterStep::Found`), and he hunts for the effect's
//! duration of play time, looked for every `HUNT_CHECK`: a load or a kill
//! that removes him ends the hunt there, otherwise he is ended once his
//! time is up. A quit-out is the exception (`Hunter::quit_out`): reloading
//! the save must not shake him off, so he is brought back once the player
//! settles, through the same requests, for the play time his hunt had
//! left, with no new banner and no new report; missed for good, the hunt
//! ends there. A death or a fog gate still ends it, on his way back too
//! (`Hunter::load`).

use std::time::{Duration, Instant};

use super::item_feed::FeedBanner;
use super::protocol::ItemReminder;

/// Wall time the player stays loaded after a loading exit before a spawn.
pub const SETTLE: Duration = Duration::from_millis(2500);
/// After a spawn request, he is looked for this often...
pub const FIND_INTERVAL: Duration = Duration::from_millis(250);
/// ...for this long, before the request counts as missed.
pub const FIND_WINDOW: Duration = Duration::from_secs(3);
/// A missed request is made again this long after its end.
pub const RETRY_DELAY: Duration = Duration::from_millis(1500);
/// Requests made at most for one Hunter.
pub const MAX_REQUESTS: u8 = 3;
/// While he hunts, he is looked for this often.
pub const HUNT_CHECK: Duration = Duration::from_secs(1);
/// After the last miss, he is still looked for (every `HUNT_CHECK`) this
/// long: a late arrival is ended.
pub const LINGER: Duration = Duration::from_secs(10);

/// What the runner is shown once he is found: the banner, and the reminder
/// row drawn with `icon`.
#[derive(Debug, Default)]
pub struct HunterNotice {
    pub banner: Option<FeedBanner>,
    pub icon: String,
    pub reminder: Option<ItemReminder>,
}

/// One Hunter, as the `hunter` effect sends him.
#[derive(Debug)]
pub struct HunterSpec {
    pub chr_id: u32,
    pub npc_param_id: u32,
    pub think_id: u32,
    /// How long he hunts once found, on the play clock.
    pub duration: Duration,
    pub report_id: u64,
    /// Held until he is found.
    pub notice: HunterNotice,
}

/// What the machine does for the Hunter on a frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HunterStep {
    /// Spawn him (`Effect::RequestHunter`); the shell's answer comes back
    /// through `Hunter::request_result`.
    Request,
    /// Look for him (`Effect::FindHunter`); the shell's answer comes back
    /// through `Hunter::seen`.
    Find,
    /// End him (`Effect::EndHunter`).
    End,
    /// Tell the server whether he spawned (`Effect::SendItemReport`).
    Report { landed: bool },
    /// He was found: show his notice (`Hunter::take_notice`).
    Found,
}

/// Where the Hunter is in his life.
#[derive(Debug, Default)]
enum State {
    /// None sent out, or the last one done.
    #[default]
    Idle,
    /// To be requested, not before `not_before` (and the player settled);
    /// `requests` made so far. `back`: brought back after a quit-out, his
    /// hunt ending at that play time.
    Waiting {
        requests: u8,
        not_before: Instant,
        back: Option<Duration>,
    },
    /// Requested (`requests` so far, this one included), looked for at
    /// `next_find` until `deadline`; `back` as in `Waiting`.
    Looking {
        requests: u8,
        deadline: Instant,
        next_find: Instant,
        back: Option<Duration>,
    },
    /// Found: hunts until `ends_at` (play time), looked for at `next_check`;
    /// `announced` once `Found` and the landed report went out.
    Hunting {
        ends_at: Duration,
        next_check: Instant,
        announced: bool,
    },
    /// Missed for good and reported: still looked for at `next_find` until
    /// `until`, so a late arrival is ended (`stray`: one was seen, ended at
    /// the next tick).
    Lingering {
        until: Instant,
        next_find: Instant,
        stray: bool,
    },
}

#[derive(Debug, Default)]
pub struct Hunter {
    /// The last one sent out: kept once he is done, for the machine to read
    /// the ids of the steps that ended him, until the next one or a clear.
    spec: Option<HunterSpec>,
    state: State,
}

impl Hunter {
    /// Send `spec` out: requested at the first `tick` where the player is
    /// settled. `false` when one is already awaited or hunting: the caller
    /// reports this one missed. The watch after a last miss gives way to it.
    pub fn start(&mut self, spec: HunterSpec, now: Instant) -> bool {
        if !matches!(self.state, State::Idle | State::Lingering { .. }) {
            return false;
        }
        self.spec = Some(spec);
        self.state = State::Waiting {
            requests: 0,
            not_before: now,
            back: None,
        };
        true
    }

    /// The player quit out and loaded the save again (the machine's
    /// quit-out latch, at the loading exit): the world he was in is gone.
    /// Hunting, or being brought back already, he is brought back once the
    /// player settles, his hunt ending at the same play time (the play
    /// clock stood still meanwhile); awaited, the request the quit-out
    /// interrupted is made again and does not count. `true` when he is to
    /// be brought back.
    pub fn quit_out(&mut self, now: Instant) -> bool {
        let state = std::mem::take(&mut self.state);
        let (state, back) = match state {
            State::Hunting {
                ends_at,
                announced: true,
                ..
            }
            | State::Waiting {
                back: Some(ends_at),
                ..
            }
            | State::Looking {
                back: Some(ends_at),
                ..
            } => (
                State::Waiting {
                    requests: 0,
                    not_before: now,
                    back: Some(ends_at),
                },
                true,
            ),
            // Seen but neither shown nor reported yet: sent out afresh.
            State::Hunting {
                announced: false, ..
            } => (
                State::Waiting {
                    requests: 0,
                    not_before: now,
                    back: None,
                },
                false,
            ),
            State::Looking {
                requests,
                back: None,
                ..
            } => (
                State::Waiting {
                    requests: requests.saturating_sub(1),
                    not_before: now,
                    back: None,
                },
                false,
            ),
            other => (other, false),
        };
        self.state = state;
        back
    }

    /// A loading exit that was no quit-out (a death, a fog gate, a warp):
    /// while he hunts, the next look no longer finds him and the hunt ends
    /// there (`seen`); on his way back after a quit-out, nothing would look
    /// before his request, so his time is up here: the next `tick` ends the
    /// hunt, with no report (a request already made gets the watch for a
    /// late arrival). `true` when it ended a return.
    pub fn load(&mut self) -> bool {
        match &mut self.state {
            State::Waiting {
                back: Some(ends_at),
                ..
            }
            | State::Looking {
                back: Some(ends_at),
                ..
            } => {
                *ends_at = Duration::ZERO;
                true
            }
            _ => false,
        }
    }

    /// The steps due at `now` (`play` on the play clock); `settled`: the
    /// player has been loaded `SETTLE` since the last loading exit. Called
    /// on loaded frames only; nothing allocated while no step is due.
    pub fn tick(&mut self, now: Instant, play: Duration, settled: bool) -> Vec<HunterStep> {
        let mut steps = Vec::new();
        match self.state {
            State::Idle => {}
            State::Waiting {
                requests,
                back: Some(ends_at),
                ..
            } if play >= ends_at => {
                // His time ran out before he was back: the hunt is over, and
                // a request already made is watched for a late arrival.
                steps.push(HunterStep::End);
                self.state = if requests > 0 {
                    State::Lingering {
                        until: now + LINGER,
                        next_find: now + HUNT_CHECK,
                        stray: false,
                    }
                } else {
                    State::Idle
                };
            }
            State::Waiting {
                requests,
                not_before,
                back,
            } => {
                if settled && now >= not_before {
                    steps.push(HunterStep::Request);
                    self.state = State::Looking {
                        requests: requests + 1,
                        deadline: now + FIND_WINDOW,
                        next_find: now + FIND_INTERVAL,
                        back,
                    };
                }
            }
            State::Looking {
                requests,
                deadline,
                next_find,
                back,
            } => {
                let time_up = back.is_some_and(|ends_at| play >= ends_at);
                if time_up || now >= deadline {
                    // Missed, or his time ran out on the way back: a late
                    // arrival must not stay.
                    steps.push(HunterStep::End);
                    if time_up || requests >= MAX_REQUESTS {
                        // Brought back, he was reported landed already.
                        if back.is_none() {
                            steps.push(HunterStep::Report { landed: false });
                        }
                        self.state = State::Lingering {
                            until: now + LINGER,
                            next_find: now + HUNT_CHECK,
                            stray: false,
                        };
                    } else {
                        self.state = State::Waiting {
                            requests,
                            not_before: now + RETRY_DELAY,
                            back,
                        };
                    }
                } else if now >= next_find {
                    steps.push(HunterStep::Find);
                    self.state = State::Looking {
                        requests,
                        deadline,
                        next_find: now + FIND_INTERVAL,
                        back,
                    };
                }
            }
            State::Hunting {
                ends_at,
                next_check,
                announced,
            } => {
                if !announced {
                    steps.push(HunterStep::Found);
                    steps.push(HunterStep::Report { landed: true });
                }
                if play >= ends_at {
                    steps.push(HunterStep::End);
                    self.state = State::Idle;
                } else {
                    let check = now >= next_check;
                    if check {
                        steps.push(HunterStep::Find);
                    }
                    self.state = State::Hunting {
                        ends_at,
                        next_check: if check { now + HUNT_CHECK } else { next_check },
                        announced: true,
                    };
                }
            }
            State::Lingering {
                until,
                next_find,
                stray,
            } => {
                if stray {
                    steps.push(HunterStep::End);
                    self.state = State::Idle;
                } else if now >= until {
                    self.state = State::Idle;
                } else if now >= next_find {
                    steps.push(HunterStep::Find);
                    self.state = State::Lingering {
                        until,
                        next_find: now + HUNT_CHECK,
                        stray: false,
                    };
                }
            }
        }
        steps
    }

    /// The shell's answer to a `Request`: `started` when the spawn was handed
    /// to the game. A refused one is a miss at once.
    pub fn request_result(&mut self, started: bool, now: Instant) {
        if let State::Looking { deadline, .. } = &mut self.state {
            if !started {
                *deadline = now;
            }
        }
    }

    /// The shell's answer to a `Find`: `found` when a live character of his
    /// row is around. Found while looked for, he hunts from `play` on, or,
    /// brought back after a quit-out, until his hunt's end, already shown and
    /// reported; gone while hunting (a load or a kill removed him), the hunt
    /// is over, with nothing left to end. Found after the last miss, he
    /// arrived late: the next `tick` ends him, and that is all.
    pub fn seen(&mut self, found: bool, now: Instant, play: Duration) {
        match self.state {
            State::Looking { back, .. } if found => {
                let duration = self.spec.as_ref().map_or(Duration::ZERO, |s| s.duration);
                self.state = State::Hunting {
                    ends_at: back.unwrap_or(play + duration),
                    next_check: now + HUNT_CHECK,
                    announced: back.is_some(),
                };
            }
            State::Hunting { .. } if !found => self.state = State::Idle,
            State::Lingering {
                until, next_find, ..
            } if found => {
                self.state = State::Lingering {
                    until,
                    next_find,
                    stray: true,
                };
            }
            _ => {}
        }
    }

    /// Forget him (the run is over). `true` when he had to be ended: a spawn
    /// was requested and not missed yet, he hunts, or the last miss is still
    /// watched, so he may be there.
    pub fn clear(&mut self) -> bool {
        let end = matches!(
            self.state,
            State::Looking { .. } | State::Hunting { .. } | State::Lingering { .. }
        );
        self.state = State::Idle;
        self.spec = None;
        end
    }

    /// The Hunter sent out last, while he is awaited, hunting, or until the
    /// next one once done.
    pub fn spec(&self) -> Option<&HunterSpec> {
        self.spec.as_ref()
    }

    /// Whether his hunt is on: he was found and still hunts, or he is being
    /// brought back after a quit-out.
    pub fn is_hunting(&self) -> bool {
        matches!(
            self.state,
            State::Hunting { .. }
                | State::Waiting { back: Some(_), .. }
                | State::Looking { back: Some(_), .. }
        )
    }

    /// His banner and reminder, taken once he is found (empty after).
    pub fn take_notice(&mut self) -> HunterNotice {
        self.spec
            .as_mut()
            .map(|spec| std::mem::take(&mut spec.notice))
            .unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ops::Range;

    /// One frame at 60 FPS, rounded up.
    const FRAME: Duration = Duration::from_millis(17);

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    fn secs(v: u64) -> Duration {
        Duration::from_secs(v)
    }

    fn spec(report_id: u64) -> HunterSpec {
        HunterSpec {
            chr_id: 2130,
            npc_param_id: 1_450_855,
            think_id: 1_450_850,
            duration: secs(60),
            report_id,
            notice: HunterNotice::default(),
        }
    }

    /// A run of frames: times are offsets from `t0`, the play clock lags the
    /// wall clock by `lag` (the loads before), the player settled from
    /// `settled_at` on, every spawn handed to the game and every look
    /// finding him while `found` holds the time.
    struct Run {
        t0: Instant,
        lag: Duration,
        settled_at: Duration,
        found: Range<Duration>,
    }

    impl Run {
        fn new(found: Range<Duration>) -> Self {
            Self {
                t0: Instant::now(),
                lag: Duration::ZERO,
                settled_at: Duration::ZERO,
                found,
            }
        }

        /// Frames after `from` up to `until`: the steps, with when.
        fn frames(
            &self,
            h: &mut Hunter,
            from: Duration,
            until: Duration,
        ) -> Vec<(Duration, HunterStep)> {
            let mut steps = Vec::new();
            let mut at = from + FRAME;
            while at <= until {
                let now = self.t0 + at;
                let play = at - self.lag;
                for step in h.tick(now, play, at >= self.settled_at) {
                    steps.push((at, step));
                    match step {
                        HunterStep::Request => h.request_result(true, now),
                        HunterStep::Find => h.seen(self.found.contains(&at), now, play),
                        _ => {}
                    }
                }
                at += FRAME;
            }
            steps
        }
    }

    fn times(steps: &[(Duration, HunterStep)], step: HunterStep) -> Vec<Duration> {
        steps
            .iter()
            .filter(|&&(_, s)| s == step)
            .map(|&(at, _)| at)
            .collect()
    }

    /// `at` falls in the frame starting at `from`.
    fn assert_within_a_frame(at: Duration, from: Duration) {
        assert!(
            (from..from + FRAME).contains(&at),
            "{at:?}, expected within a frame of {from:?}"
        );
    }

    #[test]
    fn spawns_after_the_settle_and_retries() {
        let mut run = Run::new(Duration::ZERO..Duration::ZERO);
        // A loading exit at 0: nothing before the player settled.
        run.settled_at = SETTLE;
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let steps = run.frames(&mut h, Duration::ZERO, secs(30));
        let requests = times(&steps, HunterStep::Request);
        let ends = times(&steps, HunterStep::End);
        let finds = times(&steps, HunterStep::Find);
        assert_eq!(requests.len(), 3, "{steps:?}");
        assert_eq!(ends.len(), 3, "{steps:?}");
        assert_within_a_frame(requests[0], SETTLE);
        for (i, (&request, &end)) in requests.iter().zip(&ends).enumerate() {
            // Looked for every 250 ms for 3 s, then ended: a late arrival
            // must not stay.
            assert_within_a_frame(end, request + FIND_WINDOW);
            let looks: Vec<_> = finds
                .iter()
                .copied()
                .filter(|at| (request..end).contains(at))
                .collect();
            assert_eq!(looks.len(), 11, "request {i}: {looks:?}");
            let mut last = request;
            for at in looks {
                assert_within_a_frame(at, last + FIND_INTERVAL);
                last = at;
            }
            // Requested again 1.5 s after a miss.
            if let Some(&next) = requests.get(i + 1) {
                assert_within_a_frame(next, end + RETRY_DELAY);
            }
        }
        // The third miss is reported; only looks follow (the watch after
        // the last miss, see `the_watch_after_the_last_miss_lasts_ten_seconds`).
        let last = ends[2];
        let report = steps
            .iter()
            .position(|&step| step == (last, HunterStep::Report { landed: false }))
            .unwrap();
        assert_eq!(steps[report - 1], (last, HunterStep::End));
        assert!(
            steps[report + 1..]
                .iter()
                .all(|&(_, step)| step == HunterStep::Find),
            "{steps:?}"
        );
        assert!(!h.clear(), "nothing left to end");
        assert!(h.start(spec(14), run.t0 + secs(30)), "a new one can come");
    }

    /// When the last miss of a Hunter never seen falls, from `run`'s start.
    fn last_miss(run: &Run) -> Duration {
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let steps = run.frames(&mut h, Duration::ZERO, secs(30));
        let missed = times(&steps, HunterStep::Report { landed: false });
        assert_eq!(missed.len(), 1, "{steps:?}");
        missed[0]
    }

    #[test]
    fn the_watch_after_the_last_miss_lasts_ten_seconds() {
        let run = Run::new(Duration::ZERO..Duration::ZERO);
        let last = last_miss(&run);
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let steps = run.frames(&mut h, Duration::ZERO, last + secs(60));
        let after: Vec<_> = steps.iter().filter(|&&(at, _)| at > last).collect();
        // Looked for every second, nothing else: nine looks, the tenth
        // would fall when the watch ends.
        assert!(
            after.iter().all(|&&(_, step)| step == HunterStep::Find),
            "{after:?}"
        );
        assert_eq!(after.len(), 9, "{after:?}");
        let mut prev = last;
        for &&(at, _) in &after {
            assert_within_a_frame(at, prev + HUNT_CHECK);
            prev = at;
        }
        assert!(prev < last + LINGER);
        assert!(!h.clear(), "the watch is over: nothing to end");

        // Cleared during the watch: he may be there, so he is ended.
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        run.frames(&mut h, Duration::ZERO, last + secs(5));
        assert!(h.clear());
    }

    #[test]
    fn a_late_arrival_after_the_last_miss_is_ended() {
        let mut run = Run::new(Duration::ZERO..Duration::ZERO);
        let last = last_miss(&run);
        // He shows up 4 s after the last miss.
        run.found = last + secs(4)..secs(1000);
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let steps = run.frames(&mut h, Duration::ZERO, last + secs(30));
        let after: Vec<_> = steps.iter().copied().filter(|&(at, _)| at > last).collect();
        let seen = *times(&after, HunterStep::Find)
            .iter()
            .find(|&&at| at >= last + secs(4))
            .unwrap();
        // Ended on the next frame, and that is all: never shown, no other
        // report.
        assert_eq!(after.last(), Some(&(seen + FRAME, HunterStep::End)));
        assert_eq!(times(&after, HunterStep::End).len(), 1, "{after:?}");
        assert!(times(&steps, HunterStep::Found).is_empty());
        assert_eq!(times(&steps, HunterStep::Report { landed: false }), [last]);
        assert!(times(&steps, HunterStep::Report { landed: true }).is_empty());
        assert!(!h.clear(), "ended: nothing left");
    }

    #[test]
    fn a_new_hunter_supersedes_the_watch() {
        let mut run = Run::new(Duration::ZERO..Duration::ZERO);
        let last = last_miss(&run);
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        run.frames(&mut h, Duration::ZERO, last + secs(2));
        // A new one during the watch is sent out at once.
        let sent = last + secs(2);
        assert!(h.start(spec(14), run.t0 + sent));
        assert_eq!(h.spec().map(|s| s.report_id), Some(14));
        // Requested on the next frame, looked for every 250 ms; seen, he
        // hunts as the new one (shown, reported landed), not ended as a late
        // arrival.
        run.found = sent + secs(1)..secs(1000);
        let steps = run.frames(&mut h, sent, sent + secs(5));
        assert_eq!(steps[0], (sent + FRAME, HunterStep::Request));
        let finds = times(&steps, HunterStep::Find);
        assert_within_a_frame(finds[0], sent + FRAME + FIND_INTERVAL);
        assert_eq!(times(&steps, HunterStep::Found).len(), 1, "{steps:?}");
        assert_eq!(
            times(&steps, HunterStep::Report { landed: true }).len(),
            1,
            "{steps:?}"
        );
        assert!(times(&steps, HunterStep::End).is_empty(), "{steps:?}");
        assert!(h.is_hunting());
    }

    #[test]
    fn a_refused_spawn_is_a_miss_at_once() {
        let run = Run::new(Duration::ZERO..Duration::ZERO);
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let at = FRAME;
        assert_eq!(
            h.tick(run.t0 + at, at, true),
            [HunterStep::Request],
            "settled from the start"
        );
        h.request_result(false, run.t0 + at);
        // Ended (a spawn left pending goes too), asked again 1.5 s later.
        let steps = run.frames(&mut h, at, at + secs(2));
        assert_eq!(steps[0], (at + FRAME, HunterStep::End));
        assert_eq!(times(&steps, HunterStep::Request).len(), 1, "{steps:?}");
        assert_within_a_frame(
            times(&steps, HunterStep::Request)[0],
            at + FRAME + RETRY_DELAY,
        );
    }

    #[test]
    fn found_hunts_for_its_duration() {
        let mut run = Run::new(ms(600)..secs(1000));
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let before = run.frames(&mut h, Duration::ZERO, secs(10));
        // The first look from 600 ms on finds him: the next frame shows him
        // and reports him landed, once.
        let finds = times(&before, HunterStep::Find);
        let seen = *finds.iter().find(|&&at| at >= ms(600)).unwrap();
        assert_eq!(times(&before, HunterStep::Found), [seen + FRAME]);
        assert_eq!(
            times(&before, HunterStep::Report { landed: true }),
            [seen + FRAME]
        );
        assert!(h.is_hunting());
        // Then looked for every second.
        let mut last = seen;
        for &at in finds.iter().filter(|&&at| at > seen) {
            assert_within_a_frame(at, last + HUNT_CHECK);
            last = at;
        }
        assert!(times(&before, HunterStep::End).is_empty(), "{before:?}");

        // A 20 s load from 10 s (no frame, the play clock stopped): his 60 s
        // of play time end 80 s after he was seen.
        run.lag = secs(20);
        let after = run.frames(&mut h, secs(30), secs(100));
        assert_eq!(times(&after, HunterStep::End).len(), 1, "{after:?}");
        assert_within_a_frame(times(&after, HunterStep::End)[0], seen + secs(80));
        assert_eq!(after.last().unwrap().1, HunterStep::End, "nothing after");
        assert!(times(&after, HunterStep::Found).is_empty());
        assert!(times(&after, HunterStep::Report { landed: true }).is_empty());
        assert!(!h.is_hunting());
        assert!(!h.clear(), "already ended");
    }

    #[test]
    fn a_load_that_removes_the_hunter_ends_it() {
        let mut run = Run::new(Duration::ZERO..secs(20));
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        let before = run.frames(&mut h, Duration::ZERO, secs(5));
        assert_eq!(times(&before, HunterStep::Found).len(), 1, "{before:?}");
        // A 20 s load: he is gone at the first look after it.
        run.lag = secs(20);
        let after = run.frames(&mut h, secs(25), secs(90));
        assert_eq!(after, [(secs(25) + FRAME, HunterStep::Find)]);
        assert!(!h.is_hunting());
        assert!(!h.clear(), "gone: nothing to end");
    }

    #[test]
    fn a_second_hunter_is_missed_while_one_hunts() {
        let run = Run::new(secs(1)..secs(1000));
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        // Awaited: before his spawn, then looked for.
        assert!(!h.start(spec(14), run.t0));
        run.frames(&mut h, Duration::ZERO, ms(500));
        assert!(!h.is_hunting());
        assert!(!h.start(spec(15), run.t0 + ms(500)));
        // Hunting.
        run.frames(&mut h, ms(500), secs(5));
        assert!(h.is_hunting());
        assert!(!h.start(spec(16), run.t0 + secs(5)));
        // The first one's spec stayed.
        assert_eq!(h.spec().map(|s| s.report_id), Some(13));
        // Done: the next one comes.
        let steps = run.frames(&mut h, secs(5), secs(70));
        assert_eq!(times(&steps, HunterStep::End).len(), 1);
        assert!(h.start(spec(17), run.t0 + secs(70)));
        assert_eq!(h.spec().map(|s| s.report_id), Some(17));
    }

    #[test]
    fn clearing_ends_him_once_a_spawn_was_requested() {
        let run = Run::new(secs(1)..secs(1000));
        // Before the spawn: nothing to end.
        let mut h = Hunter::default();
        h.start(spec(13), run.t0);
        assert!(!h.clear());
        assert!(h.spec().is_none());
        // Looked for, then hunting: ended.
        for until in [ms(500), secs(5)] {
            let mut h = Hunter::default();
            h.start(spec(13), run.t0);
            run.frames(&mut h, Duration::ZERO, until);
            assert!(h.clear(), "{until:?}");
            assert!(run.frames(&mut h, until, until + secs(5)).is_empty());
        }
    }

    /// A Hunter seen at the first look, hunting until `quit` with no load
    /// before; then a quit-out whose unload lasts `unload`, `quit_out`
    /// told at the loading exit: that exit, and when he was seen.
    fn quit_out_while_hunting(
        run: &mut Run,
        h: &mut Hunter,
        quit: Duration,
        unload: Duration,
    ) -> (Duration, Duration) {
        assert!(h.start(spec(13), run.t0));
        let before = run.frames(h, Duration::ZERO, quit);
        let found = times(&before, HunterStep::Found);
        assert_eq!(found.len(), 1, "{before:?}");
        // Shown on the frame after the look that saw him.
        let seen = found[0] - FRAME;
        assert_eq!(times(&before, HunterStep::Find)[0], seen);
        assert!(h.is_hunting());
        let exit = quit + unload;
        run.lag = unload;
        run.settled_at = exit + SETTLE;
        assert!(h.quit_out(run.t0 + exit), "brought back");
        assert!(h.is_hunting(), "the hunt goes on");
        (exit, seen)
    }

    #[test]
    fn a_quit_out_brings_him_back_for_the_time_left() {
        let mut run = Run::new(Duration::ZERO..secs(1000));
        let mut h = Hunter::default();
        let (exit, seen) = quit_out_while_hunting(&mut run, &mut h, secs(10), secs(20));
        let after = run.frames(&mut h, exit, secs(200));
        // Requested once the player settled, found at the first look: no
        // new banner, no new report.
        assert_within_a_frame(times(&after, HunterStep::Request)[0], exit + SETTLE);
        assert_eq!(times(&after, HunterStep::Request).len(), 1, "{after:?}");
        assert!(times(&after, HunterStep::Found).is_empty(), "{after:?}");
        assert!(
            !after
                .iter()
                .any(|(_, step)| matches!(step, HunterStep::Report { .. })),
            "{after:?}"
        );
        // Ended when his 60 s of play end, the 20 s unload not counted.
        assert_eq!(times(&after, HunterStep::End).len(), 1, "{after:?}");
        assert_within_a_frame(times(&after, HunterStep::End)[0], seen + secs(80));
        assert!(!h.is_hunting());
        assert!(!h.clear(), "already ended");
    }

    #[test]
    fn missed_on_his_way_back_the_hunt_ends_quietly() {
        // Seen before the quit-out only.
        let mut run = Run::new(Duration::ZERO..secs(10));
        let mut h = Hunter::default();
        let (exit, _) = quit_out_while_hunting(&mut run, &mut h, secs(10), secs(20));
        let after = run.frames(&mut h, exit, exit + secs(30));
        // Three requests, each missed and ended; the hunt holds until the
        // last one, and no report goes out: he was reported landed.
        let requests = times(&after, HunterStep::Request);
        let ends = times(&after, HunterStep::End);
        assert_eq!(requests.len(), 3, "{after:?}");
        assert_eq!(ends.len(), 3, "{after:?}");
        assert_within_a_frame(requests[0], exit + SETTLE);
        assert!(
            !after
                .iter()
                .any(|(_, step)| matches!(step, HunterStep::Report { .. })),
            "{after:?}"
        );
        assert!(!h.is_hunting());
        // The watch after the last miss follows, as after a first spawn.
        assert!(after
            .iter()
            .filter(|&&(at, _)| at > ends[2])
            .all(|&(_, step)| step == HunterStep::Find));
        assert!(
            !h.quit_out(run.t0 + exit + secs(30)),
            "nothing to bring back"
        );
    }

    #[test]
    fn his_time_running_out_before_he_is_back_ends_the_hunt() {
        let mut run = Run::new(Duration::ZERO..secs(1000));
        let mut h = Hunter::default();
        // Quit out with about 1 s of his 60 s left: the settle is longer.
        let (exit, seen) = quit_out_while_hunting(&mut run, &mut h, secs(59), secs(20));
        let after = run.frames(&mut h, exit, exit + secs(30));
        assert_eq!(after.len(), 1, "{after:?}");
        assert_eq!(after[0].1, HunterStep::End);
        assert_within_a_frame(after[0].0, seen + secs(80));
        assert!(!h.is_hunting());
        assert!(!h.clear(), "nothing requested since the quit-out");
    }

    #[test]
    fn a_quit_out_while_he_is_looked_for_requests_him_again() {
        let mut run = Run::new(Duration::ZERO..Duration::ZERO);
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        // Quit out during the first look.
        let before = run.frames(&mut h, Duration::ZERO, secs(1));
        assert_eq!(times(&before, HunterStep::Request).len(), 1);
        let exit = secs(21);
        run.lag = secs(20);
        run.settled_at = exit + SETTLE;
        assert!(!h.quit_out(run.t0 + exit), "not hunting yet");
        // The interrupted request does not count: three more, then the miss
        // is reported.
        let after = run.frames(&mut h, exit, exit + secs(30));
        assert_eq!(times(&after, HunterStep::Request).len(), 3, "{after:?}");
        assert_within_a_frame(times(&after, HunterStep::Request)[0], exit + SETTLE);
        assert_eq!(times(&after, HunterStep::Report { landed: false }).len(), 1);
    }

    #[test]
    fn a_second_quit_out_on_his_way_back_keeps_his_end() {
        let mut run = Run::new(Duration::ZERO..secs(1000));
        let mut h = Hunter::default();
        let (exit, seen) = quit_out_while_hunting(&mut run, &mut h, secs(10), secs(20));
        // Quit out again 1 s after the exit, before his request: another
        // 20 s unload.
        assert!(run.frames(&mut h, exit, exit + secs(1)).is_empty());
        let exit2 = exit + secs(21);
        run.lag = secs(40);
        run.settled_at = exit2 + SETTLE;
        assert!(h.quit_out(run.t0 + exit2));
        let after = run.frames(&mut h, exit2, secs(300));
        assert_within_a_frame(times(&after, HunterStep::Request)[0], exit2 + SETTLE);
        // His 60 s of play end with 40 s of unloads not counted.
        assert_eq!(times(&after, HunterStep::End).len(), 1, "{after:?}");
        assert_within_a_frame(times(&after, HunterStep::End)[0], seen + secs(100));
        assert!(times(&after, HunterStep::Found).is_empty());
    }

    #[test]
    fn a_quit_out_before_he_is_shown_sends_him_out_afresh() {
        let run = Run::new(Duration::ZERO..secs(1000));
        let mut h = Hunter::default();
        assert!(h.start(spec(13), run.t0));
        // Seen by the first look, quit out before the next tick shows him.
        let at = FRAME;
        assert_eq!(h.tick(run.t0 + at, at, true), [HunterStep::Request]);
        h.request_result(true, run.t0 + at);
        let look = at + FIND_INTERVAL + FRAME;
        assert_eq!(h.tick(run.t0 + look, look, true), [HunterStep::Find]);
        h.seen(true, run.t0 + look, look);
        assert!(!h.quit_out(run.t0 + look), "never shown: not brought back");
        // Requested again from the start, then shown and reported once.
        let steps = run.frames(&mut h, look, look + secs(5));
        assert_eq!(times(&steps, HunterStep::Request).len(), 1, "{steps:?}");
        assert_eq!(times(&steps, HunterStep::Found).len(), 1, "{steps:?}");
        assert_eq!(
            times(&steps, HunterStep::Report { landed: true }).len(),
            1,
            "{steps:?}"
        );
    }

    #[test]
    fn a_load_on_his_way_back_ends_the_hunt() {
        // A death or a fog gate right after the quit-out's exit, before he
        // is back: the hunt ends at once, quietly, never requested.
        let mut run = Run::new(Duration::ZERO..secs(1000));
        let mut h = Hunter::default();
        let (exit, _) = quit_out_while_hunting(&mut run, &mut h, secs(10), secs(20));
        assert!(run.frames(&mut h, exit, exit + secs(1)).is_empty());
        let exit2 = exit + secs(6);
        run.lag = secs(25);
        run.settled_at = exit2 + SETTLE;
        assert!(h.load());
        let after = run.frames(&mut h, exit2, exit2 + secs(30));
        assert_eq!(after, [(exit2 + FRAME, HunterStep::End)]);
        assert!(!h.is_hunting());
        // A load while he hunts is left to the next look (`seen`).
        let mut h = Hunter::default();
        let run = Run::new(Duration::ZERO..secs(1000));
        assert!(h.start(spec(13), run.t0));
        run.frames(&mut h, Duration::ZERO, secs(2));
        assert!(!h.load());
        assert!(h.is_hunting());
    }
}
