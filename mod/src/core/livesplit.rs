//! LiveSplit sync: which commands the mod sends LiveSplit, and when.
//!
//! A pure state machine fed by the thread that owns LiveSplit's named pipe:
//! the run as the race machine sees it (`on_run`), the link coming up or
//! dropping (`on_link`, `on_unlink`), LiveSplit's timer as polled through
//! the pipe (`on_poll`), and the periodic game time push (`push_due`). Each
//! entry point returns the pipe commands to write and the overlay statuses
//! to show; nothing here does I/O or reads a clock. The run's IGT reaches
//! every entry point as an `Option`: None while it is unknown (the title
//! screen after a launch, before the save loads), when nothing that depends
//! on it is decided and no game time is pushed.
//!
//! The mod drives LiveSplit only when the open file is for this run (its
//! seed, or its category), and only a timer it owns: one it started in the
//! current attempt, or a Running one it adopted because its split index and
//! game time fit the run. A fresh attempt resets a leftover timer before
//! starting it. Each new depth splits at its arrival IGT; a depth whose
//! arrival was never captured is skipped. A timer the mod does not own waits
//! for the player's reset, which then starts it and catches up; a player
//! reset of an owned timer leaves it stopped until the next attempt.

use LsCommand::{
    AlwaysPauseGameTime, Reset, SetGameTime, SkipSplit, Split, StartTimer, SwitchToGameTime,
};
use SyncOutput::{Command, Status};

/// IGT under which a save counts as a fresh run start, the same bound as the
/// server's fresh-save check.
pub const FRESH_RUN_MAX_IGT_MS: u32 = 60_000;
/// Largest gap between a Running timer's game time and the run's IGT for the
/// mod to adopt that timer as this run's.
pub const ADOPT_TOLERANCE_MS: u32 = 60_000;
/// Custom variable naming the seed a seed file is for.
pub const LS_VAR_SEED: &str = "SpeedFog seed";
/// Custom variable naming the category a category file is for.
pub const LS_VAR_CATEGORY: &str = "SpeedFog category";

// Overlay statuses.
pub const STATUS_LINKED: &str = "LiveSplit linked";
pub const STATUS_UNLINKED: &str = "LiveSplit disconnected";
pub const STATUS_OTHER_RUN: &str = "LiveSplit: these splits are for another run";
pub const STATUS_NOT_SPEEDFOG: &str = "LiveSplit: open SpeedFog splits to track this run";
pub const STATUS_RESET_TO_TRACK: &str = "Reset LiveSplit to track this run";
pub const STATUS_TOO_OLD: &str = "LiveSplit 1.8.31 or later needed";

/// The run, as the LiveSplit sync needs it.
#[derive(Debug, Clone, PartialEq)]
pub struct RunView {
    /// Running past the countdown, not finished or out, on the run's save.
    pub live: bool,
    /// Changes with every new attempt at the run.
    pub attempt: u32,
    /// No arrival recorded in this attempt yet.
    pub fresh: bool,
    /// First IGT on each layer, `total_layers + 1` long: `[L]` for layer L,
    /// `[total_layers]` the finish, `[0]` unused.
    pub arrivals: Vec<Option<u32>>,
    pub seed_number: Option<String>,
    pub category: Option<String>,
}

/// LiveSplit's timer phase, as `gettimerphase` answers it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimerPhase {
    NotRunning,
    Running,
    Paused,
    Ended,
}

/// LiveSplit's state, read when the link comes up.
#[derive(Debug, Clone, PartialEq)]
pub struct LsSnapshot {
    pub phase: TimerPhase,
    /// `getsplitindex`: -1 while NotRunning, else the number of splits done.
    pub split_index: i32,
    /// `getcurrentgametime`, None when unset.
    pub game_time_ms: Option<u32>,
    /// The file's `LS_VAR_SEED` variable.
    pub file_seed: Option<String>,
    /// The file's `LS_VAR_CATEGORY` variable.
    pub file_category: Option<String>,
}

/// A LiveSplit pipe command.
#[derive(Debug, Clone, PartialEq)]
pub enum LsCommand {
    SwitchToGameTime,
    AlwaysPauseGameTime,
    Reset,
    StartTimer,
    /// Game time in milliseconds.
    SetGameTime(u32),
    Split,
    SkipSplit,
}

impl LsCommand {
    /// The pipe line, without its newline.
    pub fn to_line(&self) -> String {
        match self {
            SwitchToGameTime => "switchto gametime".to_string(),
            AlwaysPauseGameTime => "alwayspausegametime".to_string(),
            Reset => "reset".to_string(),
            StartTimer => "starttimer".to_string(),
            SetGameTime(ms) => format!("setgametime {}.{:03}", ms / 1000, ms % 1000),
            Split => "split".to_string(),
            SkipSplit => "skipsplit".to_string(),
        }
    }
}

/// What an entry point asks for: a pipe command, or an overlay status.
#[derive(Debug, Clone, PartialEq)]
pub enum SyncOutput {
    Command(LsCommand),
    Status(&'static str),
}

/// Reads a `gettimerphase` answer.
pub fn parse_timer_phase(s: &str) -> Option<TimerPhase> {
    match s.trim() {
        "NotRunning" => Some(TimerPhase::NotRunning),
        "Running" => Some(TimerPhase::Running),
        "Paused" => Some(TimerPhase::Paused),
        "Ended" => Some(TimerPhase::Ended),
        _ => None,
    }
}

/// Reads a LiveSplit time in the forms of LiveSplit's own parser,
/// `[[[d.]h:]m:]s[.f]`, as milliseconds. A negative or unset (`-`) time, or
/// one past `u32`, is None.
pub fn parse_timespan(s: &str) -> Option<u32> {
    let mut parts = s.trim().rsplit(':');
    let last = parts.next()?;
    let (secs, fraction) = last.split_once('.').unwrap_or((last, ""));
    if !fraction.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let head = &fraction[..fraction.len().min(3)];
    let fraction_ms = if head.is_empty() {
        0
    } else {
        digits(head)? * 10u64.pow(3 - head.len() as u32)
    };
    let mut ms = digits(secs)?.checked_mul(1_000)?.checked_add(fraction_ms)?;
    if let Some(minutes) = parts.next() {
        ms = ms.checked_add(digits(minutes)?.checked_mul(60_000)?)?;
    }
    if let Some(hours) = parts.next() {
        let (days, hours) = hours.split_once('.').unwrap_or(("0", hours));
        let hours = digits(days)?.checked_mul(24)?.checked_add(digits(hours)?)?;
        ms = ms.checked_add(hours.checked_mul(3_600_000)?)?;
    }
    if parts.next().is_some() {
        return None;
    }
    u32::try_from(ms).ok()
}

/// A non-empty run of ASCII digits (no sign).
fn digits(s: &str) -> Option<u64> {
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse().ok()
}

/// Reads a `getcustomvariablevalue` answer: `-` (missing or empty) is None.
pub fn parse_variable(s: &str) -> Option<String> {
    match s.trim() {
        "" | "-" => None,
        value => Some(value.to_string()),
    }
}

/// Whether LiveSplit is too old to link (before 1.8.31, which added
/// `getcustomvariablevalue`), from the first line answering a
/// `getcustomvariablevalue` query and a `gettimerphase` query written back
/// to back. An older LiveSplit drops a command it does not know without an
/// answer, so its first line answers the phase query; a variable's answer
/// (a seed number, a category key or `-`) is never a phase name.
pub fn livesplit_too_old(first_answer: &str) -> bool {
    parse_timer_phase(first_answer).is_some()
}

/// The LiveSplit sync state machine. Every entry point but `on_unlink` ends by
/// reconciling LiveSplit with the run.
#[derive(Debug, Default)]
pub struct LiveSplitSync {
    run: Option<RunView>,
    /// LiveSplit as last read or driven; None while unlinked.
    ls: Option<LsSnapshot>,
    /// The phase LiveSplit last reported (on link or poll), unlike `ls.phase`,
    /// which also follows the commands sent.
    reported_phase: Option<TimerPhase>,
    /// Whether the linked file is for this run; None until a link meets a run.
    file_matches: Option<bool>,
    /// The attempt the ownership flags below belong to.
    seen_attempt: Option<u32>,
    owned: bool,
    awaiting_reset: bool,
    stopped_by_player: bool,
    /// Highest game time sent in this attempt since the mod last started the
    /// timer: game time never goes back on a timer the mod drives.
    pushed_ms: u32,
}

impl LiveSplitSync {
    pub fn new() -> Self {
        Self::default()
    }

    /// The run changed: an arrival, a new attempt, or its liveness.
    pub fn on_run(&mut self, run: RunView, igt_ms: Option<u32>) -> Vec<SyncOutput> {
        let mut out = Vec::new();
        self.run = Some(run);
        if self.file_matches.is_none() {
            self.check_file(&mut out);
        }
        self.reconcile(igt_ms, &mut out);
        out
    }

    /// The pipe connected and LiveSplit's state was read. The file check
    /// waits for the first `on_run` when no run is known yet.
    pub fn on_link(&mut self, ls: LsSnapshot, igt_ms: Option<u32>) -> Vec<SyncOutput> {
        let mut out = Vec::new();
        self.drop_link();
        self.reported_phase = Some(ls.phase);
        self.ls = Some(ls);
        self.check_file(&mut out);
        self.reconcile(igt_ms, &mut out);
        out
    }

    /// LiveSplit's timer, polled while linked. The answers must be read after
    /// every command returned by earlier calls was written: one thread doing
    /// request and response in turn on one connection, whose lines LiveSplit
    /// handles in order.
    ///
    /// NotRunning after LiveSplit reported another phase means the player
    /// reset it: an owned timer stays stopped until the next attempt, a
    /// foreign one is now free to start. A Running timer whose adoption
    /// waited for the run's IGT is decided on the first poll that knows it.
    pub fn on_poll(
        &mut self,
        phase: TimerPhase,
        split_index: i32,
        game_time_ms: Option<u32>,
        igt_ms: Option<u32>,
    ) -> Vec<SyncOutput> {
        let mut out = Vec::new();
        if let Some(ls) = self.ls.as_mut() {
            if phase == TimerPhase::NotRunning {
                // Against what LiveSplit reported, not the phase the mod's own
                // starttimer set: a NotRunning read before LiveSplit handled
                // that start is no player reset.
                if self.owned && self.reported_phase != Some(TimerPhase::NotRunning) {
                    self.owned = false;
                    self.stopped_by_player = true;
                }
                self.awaiting_reset = false;
            }
            self.reported_phase = Some(phase);
            ls.phase = phase;
            ls.split_index = split_index;
            ls.game_time_ms = game_time_ms;
        }
        self.reconcile(igt_ms, &mut out);
        out
    }

    /// The pipe dropped. No reconcile: there is nothing to drive.
    pub fn on_unlink(&mut self) -> Vec<SyncOutput> {
        let mut out = Vec::new();
        if self.drop_link() {
            out.push(Status(STATUS_UNLINKED));
        }
        out
    }

    /// Game time to push now, or None; never lower than the last value
    /// pushed, and nothing while the IGT is unknown.
    ///
    /// A split takes the higher of its arrival IGT and the last push, so a
    /// push must never get ahead of an arrival it has not seen. The frame
    /// thread queues a `RunView` before it stores that frame's IGT (Release);
    /// the caller loads the IGT (Acquire), feeds every queued `RunView` to
    /// `on_run`, then calls `push_due` with the IGT it loaded.
    pub fn push_due(&mut self, igt_ms: Option<u32>) -> Option<LsCommand> {
        let igt_ms = igt_ms?;
        let ls = self.ls.as_ref()?;
        let run = self.run.as_ref()?;
        // Ownership implies a linked, matching file.
        if !self.owned || !run.live || ls.phase != TimerPhase::Running {
            return None;
        }
        self.pushed_ms = self.pushed_ms.max(igt_ms);
        Some(SetGameTime(self.pushed_ms))
    }

    /// Forgets everything that belongs to the current link; true if one was up.
    fn drop_link(&mut self) -> bool {
        self.reported_phase = None;
        self.file_matches = None;
        self.owned = false;
        self.awaiting_reset = false;
        self.stopped_by_player = false;
        self.ls.take().is_some()
    }

    /// Matches the linked file against the run, once both are known.
    fn check_file(&mut self, out: &mut Vec<SyncOutput>) {
        let (Some(ls), Some(run)) = (&self.ls, &self.run) else {
            return;
        };
        let mismatch = if ls.file_seed.is_some() {
            (run.seed_number != ls.file_seed).then_some(STATUS_OTHER_RUN)
        } else if ls.file_category.is_some() {
            (run.category != ls.file_category).then_some(STATUS_OTHER_RUN)
        } else {
            Some(STATUS_NOT_SPEEDFOG)
        };
        self.file_matches = Some(mismatch.is_none());
        match mismatch {
            None => out.extend([
                Command(SwitchToGameTime),
                Command(AlwaysPauseGameTime),
                Status(STATUS_LINKED),
            ]),
            Some(status) => out.push(Status(status)),
        }
    }

    /// Takes or keeps ownership of the timer, then splits it up to the
    /// deepest layer reached. A Running timer that fits the run's splits waits
    /// for a known IGT before it is adopted or refused.
    fn reconcile(&mut self, igt_ms: Option<u32>, out: &mut Vec<SyncOutput>) {
        let (Some(ls), Some(run)) = (self.ls.as_mut(), self.run.as_ref()) else {
            return;
        };
        if self.file_matches != Some(true) {
            return;
        }
        if self.seen_attempt != Some(run.attempt) {
            self.seen_attempt = Some(run.attempt);
            self.owned = false;
            self.awaiting_reset = false;
            self.stopped_by_player = false;
            self.pushed_ms = 0;
        }
        if self.stopped_by_player {
            return;
        }
        let total_layers = run.arrivals.len().saturating_sub(1);
        let target = (1..=total_layers)
            .rev()
            .find(|&layer| run.arrivals[layer].is_some())
            .unwrap_or(0);

        if !self.owned {
            if !run.live {
                return;
            }
            if run.fresh || ls.phase == TimerPhase::NotRunning {
                if ls.phase != TimerPhase::NotRunning {
                    out.push(Command(Reset));
                }
                out.push(Command(StartTimer));
                ls.phase = TimerPhase::Running;
                ls.split_index = 0;
                self.pushed_ms = 0;
            } else {
                let fits_splits =
                    ls.phase == TimerPhase::Running && ls.split_index <= target as i32;
                if fits_splits && igt_ms.is_none() {
                    // The game time check needs the run's IGT: decided once
                    // it is known, never against a placeholder.
                    return;
                }
                let adoptable = fits_splits
                    && ls.game_time_ms.zip(igt_ms).is_some_and(|(game_time, igt)| {
                        game_time.abs_diff(igt) <= ADOPT_TOLERANCE_MS
                    });
                if !adoptable {
                    if !self.awaiting_reset {
                        out.push(Status(STATUS_RESET_TO_TRACK));
                        self.awaiting_reset = true;
                    }
                    return;
                }
            }
            self.owned = true;
        }

        if ls.phase != TimerPhase::Running {
            return;
        }
        let first = usize::try_from(ls.split_index.saturating_add(1))
            .unwrap_or(0)
            .max(1);
        for (layer, arrival) in run.arrivals.iter().enumerate().take(target + 1).skip(first) {
            match arrival {
                Some(igt) => {
                    self.pushed_ms = self.pushed_ms.max(*igt);
                    out.push(Command(SetGameTime(self.pushed_ms)));
                    out.push(Command(Split));
                }
                None => out.push(Command(SkipSplit)),
            }
            ls.split_index = layer as i32;
            if layer == total_layers {
                ls.phase = TimerPhase::Ended;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::LsCommand::{
        AlwaysPauseGameTime, Reset, SetGameTime, SkipSplit, Split, StartTimer, SwitchToGameTime,
    };
    use super::SyncOutput::{Command, Status};
    use super::*;

    const SEED: &str = "s1";
    const LAYERS: usize = 3;

    fn view(
        attempt: u32,
        fresh: bool,
        live: bool,
        arrivals: &[(usize, u32)],
        total_layers: usize,
    ) -> RunView {
        let mut slots = vec![None; total_layers + 1];
        for &(layer, igt) in arrivals {
            slots[layer] = Some(igt);
        }
        RunView {
            live,
            attempt,
            fresh,
            arrivals: slots,
            seed_number: Some(SEED.to_string()),
            category: Some("standard".to_string()),
        }
    }

    fn snap(phase: TimerPhase, index: i32, game_time: Option<u32>) -> LsSnapshot {
        LsSnapshot {
            phase,
            split_index: index,
            game_time_ms: game_time,
            file_seed: Some(SEED.to_string()),
            file_category: None,
        }
    }

    fn cmds(out: &[SyncOutput]) -> Vec<LsCommand> {
        out.iter()
            .filter_map(|o| match o {
                Command(c) => Some(c.clone()),
                Status(_) => None,
            })
            .collect()
    }

    /// A linked sync that started LiveSplit on attempt 1 (owned, index 0).
    fn started() -> LiveSplitSync {
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, true, true, &[], LAYERS), Some(0));
        sync.on_link(snap(TimerPhase::NotRunning, -1, None), Some(0));
        sync
    }

    #[test]
    fn link_on_a_fresh_attempt_switches_to_game_time_and_starts() {
        let mut sync = LiveSplitSync::new();
        assert!(sync
            .on_run(view(1, true, true, &[], LAYERS), Some(2_000))
            .is_empty());
        let out = sync.on_link(snap(TimerPhase::NotRunning, -1, None), Some(2_000));
        assert_eq!(
            cmds(&out),
            [SwitchToGameTime, AlwaysPauseGameTime, StartTimer]
        );
        assert!(out.contains(&Status(STATUS_LINKED)));
    }

    #[test]
    fn fresh_attempt_resets_a_leftover_timer_on_link() {
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(2, true, true, &[], LAYERS), Some(1_000));
        let out = sync.on_link(snap(TimerPhase::Ended, 3, Some(1_800_000)), Some(1_000));
        assert_eq!(
            cmds(&out),
            [SwitchToGameTime, AlwaysPauseGameTime, Reset, StartTimer]
        );
    }

    #[test]
    fn new_fresh_attempt_resets_the_owned_timer() {
        let mut sync = started();
        sync.on_run(
            view(1, false, true, &[(1, 65_000), (2, 130_000)], LAYERS),
            Some(130_000),
        );
        assert_eq!(sync.push_due(Some(150_000)), Some(SetGameTime(150_000)));
        let out = sync.on_run(view(2, true, true, &[], LAYERS), Some(1_000));
        assert_eq!(cmds(&out), [Reset, StartTimer]);
        // The new timer follows the new attempt's IGT, not the old high mark.
        assert_eq!(sync.push_due(Some(1_000)), Some(SetGameTime(1_000)));
    }

    #[test]
    fn arrival_splits_at_its_capture_igt() {
        let mut sync = started();
        let out = sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_200));
        assert_eq!(out, [Command(SetGameTime(65_000)), Command(Split)]);
    }

    #[test]
    fn depth_jump_skips_the_missing_split() {
        let mut sync = started();
        // Layer 3 is the finish: the run is no longer live, the split still lands.
        let finished = view(1, false, false, &[(1, 65_000), (3, 200_000)], LAYERS);
        let out = sync.on_run(finished, Some(200_000));
        assert_eq!(
            cmds(&out),
            [
                SetGameTime(65_000),
                Split,
                SkipSplit,
                SetGameTime(200_000),
                Split
            ]
        );
    }

    #[test]
    fn revisit_and_unchanged_view_emit_nothing() {
        let mut sync = started();
        let reached = view(1, false, true, &[(1, 65_000), (2, 130_000)], LAYERS);
        assert_eq!(cmds(&sync.on_run(reached.clone(), Some(130_000))).len(), 4);
        assert!(sync
            .on_poll(TimerPhase::Running, 2, Some(130_000), Some(140_000))
            .is_empty());
        // A back-out to layer 1 and back keeps the first arrival per layer.
        assert!(sync.on_run(reached, Some(180_000)).is_empty());
    }

    #[test]
    fn relink_mid_run_catches_up_from_livesplit_index() {
        let mut sync = LiveSplitSync::new();
        sync.on_run(
            view(1, false, true, &[(1, 65_000), (2, 130_000)], LAYERS),
            Some(150_000),
        );
        // LiveSplit kept the game time of the last push before the link dropped.
        let out = sync.on_link(snap(TimerPhase::Running, 1, Some(100_000)), Some(150_000));
        assert_eq!(
            cmds(&out),
            [
                SwitchToGameTime,
                AlwaysPauseGameTime,
                SetGameTime(130_000),
                Split
            ]
        );
        assert_eq!(sync.push_due(Some(150_000)), Some(SetGameTime(150_000)));
    }

    #[test]
    fn foreign_running_timer_asks_for_a_reset_then_starts_on_reset() {
        let mut sync = LiveSplitSync::new();
        let reached = view(1, false, true, &[(1, 65_000)], LAYERS);
        sync.on_run(reached.clone(), Some(120_000));
        let out = sync.on_link(snap(TimerPhase::Running, 0, Some(720_000)), Some(120_000));
        assert_eq!(cmds(&out), [SwitchToGameTime, AlwaysPauseGameTime]);
        assert!(out.contains(&Status(STATUS_RESET_TO_TRACK)));
        assert_eq!(sync.push_due(Some(120_000)), None);
        // Asked once: later polls and views stay silent.
        assert!(sync
            .on_poll(TimerPhase::Running, 0, Some(721_000), Some(121_000))
            .is_empty());
        assert!(sync.on_run(reached, Some(122_000)).is_empty());

        let out = sync.on_poll(TimerPhase::NotRunning, -1, None, Some(123_000));
        assert_eq!(cmds(&out), [StartTimer, SetGameTime(65_000), Split]);
    }

    #[test]
    fn relink_before_the_save_loads_adopts_once_the_igt_is_known() {
        let mut sync = LiveSplitSync::new();
        // A relaunch mid-run: the server's arrivals, the title screen's
        // unknown IGT, LiveSplit still running from before.
        sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), None);
        let out = sync.on_link(snap(TimerPhase::Running, 0, Some(300_000)), None);
        assert_eq!(
            out,
            [
                Command(SwitchToGameTime),
                Command(AlwaysPauseGameTime),
                Status(STATUS_LINKED)
            ]
        );
        assert_eq!(sync.push_due(None), None);
        assert!(sync
            .on_poll(TimerPhase::Running, 0, Some(300_000), None)
            .is_empty());

        // The save loaded near LiveSplit's game time: adopted and caught up.
        let out = sync.on_poll(TimerPhase::Running, 0, Some(300_000), Some(320_000));
        assert_eq!(out, [Command(SetGameTime(65_000)), Command(Split)]);
        assert_eq!(sync.push_due(Some(321_000)), Some(SetGameTime(321_000)));
        // Back at the title screen: no placeholder game time is pushed.
        assert_eq!(sync.push_due(None), None);
    }

    #[test]
    fn relink_before_the_save_loads_asks_for_a_reset_once_the_igt_is_off() {
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), None);
        sync.on_link(snap(TimerPhase::Running, 0, Some(300_000)), None);
        let out = sync.on_poll(TimerPhase::Running, 0, Some(300_000), Some(900_000));
        assert_eq!(out, [Status(STATUS_RESET_TO_TRACK)]);
        assert_eq!(sync.push_due(Some(901_000)), None);

        // A timer no IGT could make the run's is refused at once.
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), None);
        let out = sync.on_link(snap(TimerPhase::Paused, 0, Some(300_000)), None);
        assert!(out.contains(&Status(STATUS_RESET_TO_TRACK)));
    }

    #[test]
    fn timer_split_past_the_run_is_not_adopted() {
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(90_000));
        // The game time fits, but LiveSplit split a depth the run never reached.
        let out = sync.on_link(snap(TimerPhase::Running, 2, Some(90_000)), Some(90_000));
        assert_eq!(cmds(&out), [SwitchToGameTime, AlwaysPauseGameTime]);
        assert!(out.contains(&Status(STATUS_RESET_TO_TRACK)));
    }

    #[test]
    fn timer_adopted_in_a_new_attempt_drops_the_old_high_mark() {
        let mut sync = started();
        assert_eq!(sync.push_due(Some(1_800_000)), Some(SetGameTime(1_800_000)));
        sync.on_unlink();
        // Attempt 2 began while the link was down, LiveSplit running near its IGT.
        sync.on_run(view(2, false, true, &[(1, 30_000)], LAYERS), Some(40_000));
        let out = sync.on_link(snap(TimerPhase::Running, 0, Some(20_000)), Some(40_000));
        assert_eq!(
            cmds(&out),
            [
                SwitchToGameTime,
                AlwaysPauseGameTime,
                SetGameTime(30_000),
                Split
            ]
        );
        assert_eq!(sync.push_due(Some(41_000)), Some(SetGameTime(41_000)));
    }

    #[test]
    fn player_reset_mid_run_stays_stopped_until_next_attempt() {
        let mut sync = started();
        assert!(sync
            .on_poll(TimerPhase::Running, 0, Some(50_000), Some(50_000))
            .is_empty());
        assert!(sync
            .on_poll(TimerPhase::NotRunning, -1, None, Some(60_000))
            .is_empty());
        // Restarted by hand: still not the mod's timer in this attempt.
        assert!(sync
            .on_poll(TimerPhase::Running, 0, Some(0), Some(62_000))
            .is_empty());
        assert!(sync
            .on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000))
            .is_empty());
        assert_eq!(sync.push_due(Some(66_000)), None);

        let out = sync.on_run(view(2, true, true, &[], LAYERS), Some(1_000));
        assert_eq!(cmds(&out), [Reset, StartTimer]);
    }

    #[test]
    fn stale_not_running_poll_after_a_start_is_not_a_player_reset() {
        let mut sync = started();
        // Answered before LiveSplit handled the starttimer: still the phase
        // LiveSplit reported on link, so nothing was reset by the player.
        assert!(sync
            .on_poll(TimerPhase::NotRunning, -1, None, Some(1_000))
            .is_empty());
        assert!(sync
            .on_poll(TimerPhase::Running, 0, Some(1_000), Some(2_000))
            .is_empty());
        let out = sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000));
        assert_eq!(cmds(&out), [SetGameTime(65_000), Split]);
    }

    #[test]
    fn relink_without_unlink_onto_another_seed_is_not_driven() {
        let mut sync = started();
        let other_seed = LsSnapshot {
            file_seed: Some("s2".to_string()),
            ..snap(TimerPhase::Running, 0, Some(5_000))
        };
        assert_eq!(
            sync.on_link(other_seed, Some(5_000)),
            [Status(STATUS_OTHER_RUN)]
        );
        assert_eq!(sync.push_due(Some(6_000)), None);
        assert!(sync
            .on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000))
            .is_empty());
    }

    #[test]
    fn relink_without_unlink_onto_a_stopped_timer_starts_it() {
        let mut sync = started();
        sync.on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000));
        let out = sync.on_link(snap(TimerPhase::NotRunning, -1, None), Some(70_000));
        assert_eq!(
            cmds(&out),
            [
                SwitchToGameTime,
                AlwaysPauseGameTime,
                StartTimer,
                SetGameTime(65_000),
                Split
            ]
        );
    }

    #[test]
    fn paused_timer_is_not_split_until_resumed() {
        let mut sync = started();
        assert!(sync
            .on_poll(TimerPhase::Paused, 0, Some(60_000), Some(61_000))
            .is_empty());
        assert!(sync
            .on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000))
            .is_empty());
        assert_eq!(sync.push_due(Some(66_000)), None);

        let out = sync.on_poll(TimerPhase::Running, 0, Some(60_000), Some(70_000));
        assert_eq!(cmds(&out), [SetGameTime(65_000), Split]);
    }

    #[test]
    fn file_of_another_seed_is_never_driven() {
        let mut sync = LiveSplitSync::new();
        let other_seed = LsSnapshot {
            file_seed: Some("s2".to_string()),
            ..snap(TimerPhase::NotRunning, -1, None)
        };
        // Linked before any run: the check waits for the first view.
        assert!(sync.on_link(other_seed, Some(0)).is_empty());
        assert_eq!(
            sync.on_run(view(1, true, true, &[], LAYERS), Some(0)),
            [Status(STATUS_OTHER_RUN)]
        );
        assert!(sync
            .on_run(view(1, false, true, &[(1, 65_000)], LAYERS), Some(65_000))
            .is_empty());
        assert!(sync
            .on_poll(TimerPhase::NotRunning, -1, None, Some(66_000))
            .is_empty());
        assert_eq!(sync.push_due(Some(66_000)), None);
    }

    #[test]
    fn category_file_matches_any_seed_of_its_category() {
        let category_file = |category: Option<&str>| LsSnapshot {
            file_seed: None,
            file_category: category.map(str::to_string),
            ..snap(TimerPhase::NotRunning, -1, None)
        };

        let mut sync = LiveSplitSync::new();
        let other_seed = RunView {
            seed_number: Some("s7".to_string()),
            ..view(1, true, true, &[], LAYERS)
        };
        sync.on_run(other_seed, Some(0));
        let out = sync.on_link(category_file(Some("standard")), Some(0));
        assert_eq!(
            cmds(&out),
            [SwitchToGameTime, AlwaysPauseGameTime, StartTimer]
        );

        let mut sync = LiveSplitSync::new();
        let sprint = RunView {
            category: Some("sprint".to_string()),
            ..view(1, true, true, &[], LAYERS)
        };
        sync.on_run(sprint, Some(0));
        assert_eq!(
            sync.on_link(category_file(Some("standard")), Some(0)),
            [Status(STATUS_OTHER_RUN)]
        );

        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, true, true, &[], LAYERS), Some(0));
        assert_eq!(
            sync.on_link(category_file(None), Some(0)),
            [Status(STATUS_NOT_SPEEDFOG)]
        );
    }

    #[test]
    fn push_due_is_monotonic_and_stops_when_not_live() {
        let mut sync = started();
        assert_eq!(sync.push_due(Some(5_000)), Some(SetGameTime(5_000)));
        assert_eq!(sync.push_due(Some(4_000)), Some(SetGameTime(5_000)));
        // A wrong save pauses the pushes until the run's save is back.
        sync.on_run(view(1, true, false, &[], LAYERS), Some(6_000));
        assert_eq!(sync.push_due(Some(6_000)), None);
        sync.on_run(view(1, true, true, &[], LAYERS), Some(7_000));
        assert_eq!(sync.push_due(Some(7_000)), Some(SetGameTime(7_000)));
    }

    #[test]
    fn nothing_starts_before_the_run_is_live() {
        let mut sync = LiveSplitSync::new();
        sync.on_run(view(1, true, false, &[], LAYERS), Some(0));
        let out = sync.on_link(snap(TimerPhase::Ended, 3, Some(1_800_000)), Some(0));
        assert_eq!(cmds(&out), [SwitchToGameTime, AlwaysPauseGameTime]);
        assert_eq!(sync.push_due(Some(0)), None);

        let out = sync.on_run(view(1, true, true, &[], LAYERS), Some(0));
        assert_eq!(cmds(&out), [Reset, StartTimer]);
    }

    #[test]
    fn relink_after_a_reset_restarts_and_splits_at_the_arrival_igts() {
        let mut sync = started();
        let reached = view(1, false, true, &[(1, 65_000), (2, 130_000)], LAYERS);
        sync.on_run(reached, Some(130_000));
        assert_eq!(sync.push_due(Some(140_000)), Some(SetGameTime(140_000)));
        // The player reset LiveSplit: stopped for the rest of this link.
        sync.on_poll(TimerPhase::Running, 2, Some(140_000), Some(141_000));
        sync.on_poll(TimerPhase::NotRunning, -1, None, Some(142_000));
        assert_eq!(sync.on_unlink(), [Status(STATUS_UNLINKED)]);
        assert!(sync.on_unlink().is_empty());
        assert_eq!(sync.push_due(Some(145_000)), None);

        // A new link starts a new timer, whose splits take the arrival IGTs,
        // below the old timer's last push.
        let out = sync.on_link(snap(TimerPhase::NotRunning, -1, None), Some(150_000));
        assert_eq!(
            cmds(&out),
            [
                SwitchToGameTime,
                AlwaysPauseGameTime,
                StartTimer,
                SetGameTime(65_000),
                Split,
                SetGameTime(130_000),
                Split
            ]
        );
    }

    #[test]
    fn parse_timespan_reads_days_and_hours() {
        assert_eq!(parse_timespan("00:01:02.5000000"), Some(62_500));
        assert_eq!(parse_timespan("1.02:03:04"), Some(93_784_000));
        assert_eq!(parse_timespan("-"), None);
        assert_eq!(parse_timespan("-00:00:05"), None);
        assert_eq!(parse_timespan("garbage"), None);
        // 50 days does not fit in u32 milliseconds.
        assert_eq!(parse_timespan("50.00:00:00"), None);

        let line = LsCommand::SetGameTime(62_500).to_line();
        assert_eq!(line, "setgametime 62.500");
        let pushed = |line: &str| line.strip_prefix("setgametime ").and_then(parse_timespan);
        assert_eq!(pushed(&line), Some(62_500));
        assert_eq!(
            pushed(&LsCommand::SetGameTime(1_005).to_line()),
            Some(1_005)
        );
    }

    #[test]
    fn a_phase_answering_the_variable_query_means_livesplit_is_too_old() {
        assert!(livesplit_too_old("NotRunning\r\n"));
        assert!(livesplit_too_old("Ended"));
        // The variable's own answers on 1.8.31 or later.
        assert!(!livesplit_too_old("-"));
        assert!(!livesplit_too_old("523847196"));
        assert!(!livesplit_too_old("standard@12"));
    }

    #[test]
    fn livesplit_placeholders_read_as_none() {
        assert_eq!(parse_variable("-"), None);
        assert_eq!(parse_variable(""), None);
        assert_eq!(parse_variable("s1\r\n"), Some("s1".to_string()));
        assert_eq!(parse_timer_phase("Paused\r\n"), Some(TimerPhase::Paused));
        assert_eq!(parse_timer_phase("Stopped"), None);
    }
}
