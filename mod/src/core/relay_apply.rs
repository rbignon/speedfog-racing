//! A relay take's world in the receiver's game: which flags to raise, from
//! the take (the state's grace flags, the team's boss defeat flags) and this
//! game's graces, then the writes paced over frames. The shell reads this
//! game's grace flags on its worker thread and hands them here (`plan`);
//! the plan's writes are made on the tracker's frame thread (the Present
//! hook, not the game's own threads), a bounded batch per frame
//! (`ApplyRun`), until they are done, the deadline passes, a loading screen
//! comes, or the take is no longer applying. Pure: nothing here reads or
//! writes the game, or logs.

use std::time::{Duration, Instant};

/// An apply's writes stop this long after it was asked, whatever is left:
/// under the machine's `relay::APPLY_ABANDON`, so the answer always comes
/// before the machine gives the apply up, and the take still fits the
/// server's 30 s.
pub const APPLY_DEADLINE: Duration = Duration::from_secs(15);
/// Most flag raises of an apply in one frame. At the ceiling, the most a
/// state can carry (1000 grace flags) and a team's bosses are raised in
/// about 1 s at 60 fps and 2 s at 30, well inside `APPLY_DEADLINE`. A full
/// batch measured in game took well under `APPLY_FRAME_BUDGET`: this
/// ceiling is what paces an apply.
pub const APPLY_WRITES_PER_FRAME: usize = 16;
/// Wall time a frame's batch may spend writing: once it is spent the batch
/// stops, after at least one write, so a slow write holds no frame long and
/// an apply still moves on every frame. Writes slow enough to hit this on
/// each one would leave a large state cut by `APPLY_DEADLINE`. Measured in
/// game, it is a guard that a normal apply does not reach (docs/RELAY.md
/// has the figures).
pub const APPLY_FRAME_BUDGET: Duration = Duration::from_micros(1500);

/// Name of the environment variable that turns the test-only slow apply on.
pub const SLOW_APPLY_ENV: &str = "SPEEDFOG_RELAY_SLOW_APPLY";

/// The slow apply's interval between two writes, from the value of
/// `SLOW_APPLY_ENV`: a number of milliseconds above 0. Absent, unparsable
/// or 0 means off.
pub fn slow_apply_interval(value: Option<&str>) -> Option<Duration> {
    let ms: u64 = value?.trim().parse().ok()?;
    (ms > 0).then(|| Duration::from_millis(ms))
}

/// One write of an apply, in the order they are made: the grace flags, then
/// the boss defeat flags. A grace an apply cut for good leaves unwritten is
/// lost for the team, since the next handoff captures this runner's graces.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplyStep {
    /// Raise this grace flag.
    Grace(u32),
    /// Raise this boss defeat flag.
    Defeat(u32),
}

impl ApplyStep {
    /// The flag the step raises.
    pub fn target(self) -> u32 {
        match self {
            ApplyStep::Grace(flag) | ApplyStep::Defeat(flag) => flag,
        }
    }
}

/// What a plan found, for its log line.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct PlanCounts {
    /// Boss defeat flags planned.
    pub defeats: usize,
    /// Grace flags planned.
    pub graces: usize,
    /// Grace flags of the state that are no grace of this game, never set.
    pub not_grace: usize,
}

/// The writes of an apply, in order, and what was left out.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ApplyPlan {
    pub steps: Vec<ApplyStep>,
    pub counts: PlanCounts,
    /// The state's grace flags that are no grace of this game, sorted.
    pub not_graces: Vec<u32>,
}

/// The writes of a take's world. `defeat_flags` are the boss defeat flags to
/// raise (the machine kept only the seed's bosses); `grace_flags` the
/// state's (none without a state); `graces` this game's grace flags, sorted.
/// A grace flag is raised only when it is one of `graces`. Each write comes
/// once.
pub fn plan(defeat_flags: &[u32], grace_flags: &[u32], graces: &[u32]) -> ApplyPlan {
    let mut counts = PlanCounts::default();
    let mut state_graces = grace_flags.to_vec();
    state_graces.sort_unstable();
    state_graces.dedup();
    let (lit, not_graces): (Vec<u32>, Vec<u32>) = state_graces
        .into_iter()
        .partition(|flag| graces.binary_search(flag).is_ok());
    counts.graces = lit.len();
    counts.not_grace = not_graces.len();
    let mut steps: Vec<ApplyStep> = lit.into_iter().map(ApplyStep::Grace).collect();

    let mut defeats = defeat_flags.to_vec();
    defeats.sort_unstable();
    defeats.dedup();
    counts.defeats = defeats.len();
    steps.extend(defeats.into_iter().map(ApplyStep::Defeat));
    ApplyPlan {
        steps,
        counts,
        not_graces,
    }
}

/// Why an apply's writes ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplyEnd {
    /// Every write of the plan was made (a failed one included).
    Complete,
    /// `APPLY_DEADLINE` passed first.
    Deadline,
    /// A frame since the ask read another map or none (a loading screen:
    /// quit-out, death, warp), or the map was unreadable at the ask.
    MapChanged,
    /// The take is no longer applying (given up, replaced, abandoned).
    NotWanted,
}

/// The writes made, by kind.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Written {
    pub defeats: usize,
    pub defeats_failed: usize,
    pub graces: usize,
    pub graces_failed: usize,
}

impl Written {
    fn count(&mut self, step: ApplyStep, made: bool) {
        let (done, failed) = match step {
            ApplyStep::Defeat(_) => (&mut self.defeats, &mut self.defeats_failed),
            ApplyStep::Grace(_) => (&mut self.graces, &mut self.graces_failed),
        };
        if made {
            *done += 1;
        } else {
            *failed += 1;
        }
    }
}

/// An apply from its ask to the end of its writes: it watches the loaded map
/// of every frame from the ask (the plan's reads included), then, once
/// planned, writes a bounded batch per frame. Once ended it never writes
/// again.
pub struct ApplyRun {
    handoff_id: String,
    generation: u64,
    map: Option<u32>,
    asked_at: Instant,
    interrupted: bool,
    steps: Option<Vec<ApplyStep>>,
    next: usize,
    written: Written,
    failed: Vec<u32>,
    /// The step whose write is being tried: still set at the next frame, its
    /// write never returned (a panic the shell's frame caught).
    trying: Option<ApplyStep>,
    ended: Option<ApplyEnd>,
    /// Test aid: the least time between two writes (none: batches as
    /// `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET` say).
    min_interval: Option<Duration>,
    /// When the last write was made, while `min_interval` is set.
    last_write: Option<Instant>,
}

impl std::fmt::Debug for ApplyRun {
    /// The identity and progress only: a plan's steps can run to thousands.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApplyRun")
            .field("handoff_id", &self.handoff_id)
            .field("generation", &self.generation)
            .field("steps", &self.steps.as_ref().map(Vec::len))
            .field("next", &self.next)
            .finish()
    }
}

impl ApplyRun {
    /// The apply asked at `asked_at` for the take `handoff_id`, with the
    /// machine's `generation`, on a frame whose loaded map was `map` (none:
    /// nothing will be written).
    pub fn new(handoff_id: String, generation: u64, map: Option<u32>, asked_at: Instant) -> Self {
        Self {
            handoff_id,
            generation,
            map,
            asked_at,
            interrupted: map.is_none(),
            steps: None,
            next: 0,
            written: Written::default(),
            failed: Vec::new(),
            trying: None,
            ended: None,
            min_interval: None,
            last_write: None,
        }
    }

    /// Paces the writes: at most one write per `interval`, so an apply can
    /// be made long enough to be interrupted by hand in game. The stop rules
    /// and the deadline are unchanged. `None` (the default): no pacing.
    pub fn set_min_interval(&mut self, interval: Option<Duration>) {
        self.min_interval = interval;
    }

    pub fn handoff_id(&self) -> &str {
        &self.handoff_id
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn asked_at(&self) -> Instant {
        self.asked_at
    }

    /// A loaded map read since the ask (each frame's, and one right after a
    /// batch): another map or none ends the writes for good, even back on
    /// the ask's map.
    pub fn observe(&mut self, map: Option<u32>) {
        if map.is_none() || map != self.map {
            self.interrupted = true;
        }
    }

    /// The plan's writes arrived.
    pub fn set_plan(&mut self, steps: Vec<ApplyStep>) {
        self.steps = Some(steps);
    }

    pub fn is_planned(&self) -> bool {
        self.steps.is_some()
    }

    /// One frame's writes through `write` (true when the write was made),
    /// `wanted` whether the machine still waits for this apply's take,
    /// `spent` the wall time the frame's batch has taken so far. A batch
    /// stops at `APPLY_WRITES_PER_FRAME` writes or once `APPLY_FRAME_BUDGET`
    /// is spent, whichever comes first, after at least one write. The end is
    /// checked before the batch (a load seen, not wanted, the deadline) and
    /// after it (nothing left). `None`: more to write, or not planned yet
    /// (nothing written). A step counts as gone before its write is tried,
    /// so a write that panicked is never tried again; it counts as failed.
    pub fn write_frame(
        &mut self,
        wanted: bool,
        now: Instant,
        mut spent: impl FnMut() -> Duration,
        mut write: impl FnMut(ApplyStep) -> bool,
    ) -> Option<ApplyEnd> {
        // A write that never returned (it panicked) is a failed one.
        if let Some(step) = self.trying.take() {
            self.written.count(step, false);
            self.failed.push(step.target());
        }
        if self.ended.is_some() {
            return self.ended;
        }
        let steps = self.steps.as_ref()?;
        let stop = if self.interrupted {
            Some(ApplyEnd::MapChanged)
        } else if !wanted {
            Some(ApplyEnd::NotWanted)
        } else if now.saturating_duration_since(self.asked_at) >= APPLY_DEADLINE {
            Some(ApplyEnd::Deadline)
        } else {
            None
        };
        if stop.is_none() {
            let paced_out = self.min_interval.is_some_and(|interval| {
                self.last_write
                    .is_some_and(|at| now.saturating_duration_since(at) < interval)
            });
            let per_frame = if self.min_interval.is_some() {
                1
            } else {
                APPLY_WRITES_PER_FRAME
            };
            let batch_end = if paced_out {
                self.next
            } else {
                steps.len().min(self.next + per_frame)
            };
            if self.min_interval.is_some() && self.next < batch_end {
                self.last_write = Some(now);
            }
            while self.next < batch_end {
                let step = steps[self.next];
                self.next += 1;
                self.trying = Some(step);
                let made = write(step);
                self.trying = None;
                self.written.count(step, made);
                if !made {
                    self.failed.push(step.target());
                }
                if spent() >= APPLY_FRAME_BUDGET {
                    break;
                }
            }
        }
        self.ended = stop.or((self.next >= steps.len()).then_some(ApplyEnd::Complete));
        self.ended
    }

    /// The writes made so far.
    pub fn written(&self) -> Written {
        self.written
    }

    /// The flags whose write failed, in order.
    pub fn failed(&self) -> &[u32] {
        &self.failed
    }

    /// Writes of the plan not made.
    pub fn left(&self) -> usize {
        self.steps
            .as_ref()
            .map_or(0, |steps| steps.len().saturating_sub(self.next))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::relay::{APPLY_ABANDON, ROUNDTABLE_MAP_ID};

    const BOSS: u32 = 10_000_800;

    fn ms(n: u64) -> Duration {
        Duration::from_millis(n)
    }

    #[test]
    fn the_writes_come_graces_then_bosses_each_once() {
        let plan = plan(
            &[BOSS, 10_010_800, BOSS],
            &[76_101, 71_190, 76_101],
            &[71_190, 76_101, 76_200],
        );
        assert_eq!(
            plan.steps,
            [
                ApplyStep::Grace(71_190),
                ApplyStep::Grace(76_101),
                ApplyStep::Defeat(BOSS),
                ApplyStep::Defeat(10_010_800),
            ]
        );
        assert_eq!(
            plan.counts,
            PlanCounts {
                defeats: 2,
                graces: 2,
                not_grace: 0,
            }
        );
        assert!(plan.not_graces.is_empty());
    }

    #[test]
    fn a_grace_flag_that_is_no_grace_is_skipped_and_counted() {
        let plan = plan(
            &[],
            &[1_050_290_500, 76_101, 71_190, 76_101],
            &[71_190, 76_101],
        );
        assert_eq!(
            plan.steps,
            [ApplyStep::Grace(71_190), ApplyStep::Grace(76_101)]
        );
        assert_eq!(plan.not_graces, [1_050_290_500]);
        assert_eq!((plan.counts.graces, plan.counts.not_grace), (2, 1));
        // No grace table read: no grace is raised, the bosses still are.
        let none = super::plan(&[BOSS], &[71_190], &[]);
        assert_eq!(none.steps, [ApplyStep::Defeat(BOSS)]);
        assert_eq!(none.counts.not_grace, 1);
    }

    /// A batch clock for writes that cost nothing.
    fn quick() -> Duration {
        Duration::ZERO
    }

    /// A batch clock for writes that each take the whole frame budget.
    fn slow() -> Duration {
        APPLY_FRAME_BUDGET
    }

    /// A run of `n` grace writes asked at `t0` at the Roundtable Hold, planned.
    fn run_of(n: u32, t0: Instant) -> ApplyRun {
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(ROUNDTABLE_MAP_ID), t0);
        run.set_plan((0..n).map(|i| ApplyStep::Grace(71_000 + i)).collect());
        run
    }

    #[test]
    fn no_frame_writes_more_than_the_batch() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        let mut frames = Vec::new();
        for frame in 1..=5u64 {
            let mut writes = 0;
            let end = run.write_frame(true, t0 + ms(16 * frame), quick, |_| {
                writes += 1;
                true
            });
            frames.push((writes, end));
        }
        assert_eq!(
            frames,
            [
                (APPLY_WRITES_PER_FRAME, None),
                (APPLY_WRITES_PER_FRAME, None),
                (40 - 2 * APPLY_WRITES_PER_FRAME, Some(ApplyEnd::Complete)),
                // Ended: nothing more is ever written.
                (0, Some(ApplyEnd::Complete)),
                (0, Some(ApplyEnd::Complete)),
            ]
        );
        assert_eq!(run.written().graces, 40);
        assert_eq!(run.left(), 0);
    }

    #[test]
    fn the_slow_apply_reads_a_positive_number_of_milliseconds_only() {
        assert_eq!(slow_apply_interval(Some("250")), Some(ms(250)));
        assert_eq!(slow_apply_interval(Some(" 40 ")), Some(ms(40)));
        for off in [
            None,
            Some(""),
            Some("0"),
            Some("fast"),
            Some("-5"),
            Some("1.5"),
        ] {
            assert_eq!(slow_apply_interval(off), None, "{off:?}");
        }
    }

    #[test]
    fn a_paced_apply_makes_one_write_per_interval_and_completes() {
        let t0 = Instant::now();
        let mut run = run_of(3, t0);
        run.set_min_interval(Some(ms(100)));
        let mut writes = 0;
        let mut at = |run: &mut ApplyRun, t: u64| {
            run.write_frame(true, t0 + ms(t), quick, |_| {
                writes += 1;
                true
            })
        };
        assert_eq!(at(&mut run, 16), None);
        // 50 and 115 are inside the interval of the write at 16 and write
        // nothing; 120 is past it and writes.
        assert_eq!(at(&mut run, 50), None);
        assert_eq!(at(&mut run, 115), None);
        assert_eq!(at(&mut run, 120), None);
        assert_eq!(at(&mut run, 220), Some(ApplyEnd::Complete));
        assert_eq!(writes, 3);
        assert_eq!(run.left(), 0);
    }

    #[test]
    fn a_paced_apply_still_ends_on_its_deadline_with_the_count_left() {
        let t0 = Instant::now();
        let mut run = run_of(1000, t0);
        run.set_min_interval(Some(ms(1000)));
        let mut writes = 0;
        let mut end = None;
        for frame in 0..=20u64 {
            end = run.write_frame(true, t0 + ms(1000 * frame + 16), quick, |_| {
                writes += 1;
                true
            });
            if end.is_some() {
                break;
            }
        }
        assert_eq!(end, Some(ApplyEnd::Deadline));
        assert_eq!(writes, 15);
        assert_eq!(run.left(), 985);
    }

    #[test]
    fn the_writes_follow_the_plan_and_count_their_failures() {
        let t0 = Instant::now();
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(ROUNDTABLE_MAP_ID), t0);
        let steps = vec![
            ApplyStep::Grace(71_190),
            ApplyStep::Grace(76_101),
            ApplyStep::Defeat(BOSS),
            ApplyStep::Defeat(10_010_800),
        ];
        run.set_plan(steps.clone());
        let mut seen = Vec::new();
        let end = run.write_frame(true, t0 + ms(20), quick, |step| {
            seen.push(step);
            // A grace and a boss flag fail; the run goes on.
            step != ApplyStep::Grace(76_101) && step != ApplyStep::Defeat(BOSS)
        });
        assert_eq!(end, Some(ApplyEnd::Complete));
        assert_eq!(seen, steps);
        assert_eq!(
            run.written(),
            Written {
                defeats: 1,
                defeats_failed: 1,
                graces: 1,
                graces_failed: 1,
            }
        );
        assert_eq!(run.failed(), [76_101, BOSS]);
    }

    #[test]
    fn a_write_that_panicked_is_never_made_again() {
        // The shell's frame catches a panic and goes on with the next frame:
        // a write that may have been made is not tried again.
        let t0 = Instant::now();
        let mut run = run_of(5, t0);
        let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            run.write_frame(true, t0 + ms(16), quick, |step| {
                assert_ne!(step, ApplyStep::Grace(71_002), "the frame panicked");
                true
            })
        }));
        assert!(caught.is_err());
        let mut seen = Vec::new();
        let end = run.write_frame(true, t0 + ms(32), quick, |step| {
            seen.push(step);
            true
        });
        assert_eq!(end, Some(ApplyEnd::Complete));
        assert_eq!(seen, [ApplyStep::Grace(71_003), ApplyStep::Grace(71_004)]);
        // The step it panicked on counts as failed: every step is accounted.
        let written = run.written();
        assert_eq!((written.graces, written.graces_failed), (4, 1));
        assert_eq!(run.failed(), [71_002]);
        assert_eq!(run.left(), 0);
    }

    #[test]
    fn a_slow_write_ends_the_frame_batch() {
        let t0 = Instant::now();
        // The first write of each frame takes the whole budget: one a frame.
        let mut run = run_of(3, t0);
        for (frame, want) in [(1u64, None), (2, None), (3, Some(ApplyEnd::Complete))] {
            let mut writes = 0;
            let end = run.write_frame(true, t0 + ms(16 * frame), slow, |_| {
                writes += 1;
                true
            });
            assert_eq!((writes, end), (1, want), "frame {frame}");
        }
        // Writes that never reach the budget run to the ceiling.
        let mut run = run_of(40, t0);
        let clock = std::cell::Cell::new(Duration::ZERO);
        let mut writes = 0;
        let end = run.write_frame(
            true,
            t0 + ms(16),
            || clock.get(),
            |_| {
                writes += 1;
                clock.set(clock.get() + APPLY_FRAME_BUDGET / (APPLY_WRITES_PER_FRAME as u32 + 1));
                true
            },
        );
        assert_eq!((writes, end), (APPLY_WRITES_PER_FRAME, None));
        // The budget reached mid-batch ends it on that write.
        let mut run = run_of(40, t0);
        let clock = std::cell::Cell::new(Duration::ZERO);
        let mut writes = 0;
        run.write_frame(
            true,
            t0 + ms(16),
            || clock.get(),
            |_| {
                writes += 1;
                clock.set(clock.get() + APPLY_FRAME_BUDGET / 4);
                true
            },
        );
        assert_eq!(writes, 4);
    }

    #[test]
    fn every_frame_writes_at_least_once() {
        // A budget already spent before the first write still lets one
        // through: the apply always moves on, and ends.
        let t0 = Instant::now();
        let mut run = run_of(5, t0);
        let spent_already = || APPLY_FRAME_BUDGET * 10;
        let mut ends = Vec::new();
        for frame in 1..=5u64 {
            ends.push(run.write_frame(true, t0 + ms(16 * frame), spent_already, |_| true));
        }
        assert_eq!(ends[..4], [None, None, None, None]);
        assert_eq!(ends[4], Some(ApplyEnd::Complete));
        assert_eq!(run.written().graces, 5);
    }

    #[test]
    fn nothing_is_written_before_the_plan() {
        let t0 = Instant::now();
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(ROUNDTABLE_MAP_ID), t0);
        let mut writes = 0;
        for frame in 1..=3u64 {
            assert_eq!(
                run.write_frame(true, t0 + ms(16 * frame), quick, |_| {
                    writes += 1;
                    true
                }),
                None
            );
        }
        assert_eq!(writes, 0);
        assert!(!run.is_planned());
        // An empty plan is complete at once.
        run.set_plan(Vec::new());
        assert_eq!(
            run.write_frame(true, t0 + ms(64), quick, |_| panic!("nothing to write")),
            Some(ApplyEnd::Complete)
        );
    }

    #[test]
    fn a_loading_screen_stops_the_writes_for_good() {
        let t0 = Instant::now();
        // During the writes: the map goes away, then comes back.
        let mut run = run_of(40, t0);
        run.observe(Some(ROUNDTABLE_MAP_ID));
        assert_eq!(run.write_frame(true, t0 + ms(16), quick, |_| true), None);
        run.observe(None);
        run.observe(Some(ROUNDTABLE_MAP_ID));
        assert_eq!(
            run.write_frame(true, t0 + ms(32), quick, |_| panic!("written after a load")),
            Some(ApplyEnd::MapChanged)
        );
        assert_eq!(run.written().graces, APPLY_WRITES_PER_FRAME);
        assert_eq!(run.left(), 40 - APPLY_WRITES_PER_FRAME);

        // While the plan was read: nothing is ever written.
        let mut run = ApplyRun::new("h1".to_string(), 7, Some(ROUNDTABLE_MAP_ID), t0);
        run.observe(Some(0x3C2C_2400));
        run.observe(Some(ROUNDTABLE_MAP_ID));
        run.set_plan(vec![ApplyStep::Grace(71_190)]);
        assert_eq!(
            run.write_frame(true, t0 + ms(16), quick, |_| panic!("written after a load")),
            Some(ApplyEnd::MapChanged)
        );

        // No map at the ask: nothing to compare with, nothing written.
        let mut run = ApplyRun::new("h1".to_string(), 7, None, t0);
        run.set_plan(vec![ApplyStep::Grace(71_190)]);
        assert_eq!(
            run.write_frame(true, t0 + ms(16), quick, |_| panic!("written with no map")),
            Some(ApplyEnd::MapChanged)
        );
    }

    #[test]
    fn the_writes_stop_at_the_deadline() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        assert_eq!(
            run.write_frame(true, t0 + APPLY_DEADLINE - ms(1), quick, |_| true),
            None
        );
        assert_eq!(
            run.write_frame(true, t0 + APPLY_DEADLINE, quick, |_| panic!("written late")),
            Some(ApplyEnd::Deadline)
        );
        assert_eq!(run.left(), 40 - APPLY_WRITES_PER_FRAME);
        // The deadline answers before the machine gives the apply up.
        assert!(APPLY_DEADLINE < APPLY_ABANDON);
    }

    #[test]
    fn a_take_no_longer_applying_stops_the_writes() {
        let t0 = Instant::now();
        let mut run = run_of(40, t0);
        assert_eq!(run.write_frame(true, t0 + ms(16), quick, |_| true), None);
        assert_eq!(
            run.write_frame(false, t0 + ms(32), quick, |_| panic!("written for nobody")),
            Some(ApplyEnd::NotWanted)
        );
        // The end holds even if the take were wanted again.
        assert_eq!(
            run.write_frame(true, t0 + ms(48), quick, |_| panic!(
                "written after the end"
            )),
            Some(ApplyEnd::NotWanted)
        );
    }
}
