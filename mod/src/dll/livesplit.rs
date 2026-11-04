//! LiveSplit link: the thread that owns LiveSplit's named pipe.
//!
//! The frame thread queues each `RunView` the race machine emits
//! (`send_run`) and stores the frame's IGT (`publish_igt`); the thread feeds
//! both to the pure `LiveSplitSync`, writes the commands it returns, and
//! reads LiveSplit's timer through the pipe. Overlay statuses come back
//! through a channel (`poll_status`). See `docs/LIVESPLIT.md`.
//!
//! Every LiveSplit answer is read on this thread, on the connection that
//! carried its `get*` query, right after writing that query: each `get*`
//! command answers exactly one line, the other commands answer nothing, and
//! LiveSplit handles a connection's lines in order. Nothing is read without
//! a query first, so an answer always follows every command written before.
//!
//! LiveSplit's pipe has no buffer (.NET's default size, 0): a write returns
//! only once LiveSplit has read it, and an answer holds LiveSplit until the
//! mod reads it. So nothing is written while an answer is unread: lines
//! sent before reading go out in one write (`Pipe::send_together`).

use crossbeam_channel::{bounded, Receiver, Sender, TrySendError};
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use tracing::{error, info, warn};

use crate::core::livesplit::{
    livesplit_too_old, parse_timer_phase, parse_timespan, parse_variable, LiveSplitSync, LsCommand,
    LsSnapshot, RunView, SyncOutput, LS_VAR_CATEGORY, LS_VAR_SEED, STATUS_ELEVATED, STATUS_TOO_OLD,
};
use crate::profile_span;

/// LiveSplit's pipe server, always on since LiveSplit 1.8.29; the mod needs
/// 1.8.31 or later, for `getcustomvariablevalue`.
const PIPE_PATH: &str = r"\\.\pipe\LiveSplit";
/// Loop period: how often queued run views reach the sync.
const TICK: Duration = Duration::from_millis(10);
/// Delay between two connection attempts while unlinked.
const RETRY_INTERVAL: Duration = Duration::from_secs(5);
/// Delay before trying again a LiveSplit found too old to link: each try
/// leaves an "Invalid command" line in its log.
const TOO_OLD_RETRY_INTERVAL: Duration = Duration::from_secs(60);
/// How often LiveSplit's timer is read while linked.
const POLL_INTERVAL: Duration = Duration::from_secs(1);
/// Game time push period, about 30 Hz.
const PUSH_INTERVAL: Duration = Duration::from_millis(33);
/// How long Drop waits for the thread to stop before leaving it behind.
const SHUTDOWN_GRACE: Duration = Duration::from_millis(200);
/// Longest answer line accepted: anything longer is no LiveSplit answer.
const MAX_ANSWER_BYTES: u64 = 4096;
/// The IGT atomic's value while the IGT is unknown (the title screen after a
/// launch): a known IGT is never 0, as `RaceMachine::held_igt_ms` takes a
/// zero reading for none.
const IGT_UNKNOWN: u32 = 0;
/// Run views the channel holds; past it the oldest is dropped.
const RUN_QUEUE: usize = 64;

// =============================================================================
// CLIENT
// =============================================================================

/// The frame thread's side of the LiveSplit link. Every method is
/// non-blocking, and allocation-free but for a failure's log line.
pub struct LiveSplitClient {
    run_tx: Sender<RunView>,
    /// The thread's receiver too: on a full channel, takes the oldest view
    /// off to make room for the newest.
    run_rx: Receiver<RunView>,
    status_rx: Receiver<&'static str>,
    igt: Arc<AtomicU32>,
    shutdown: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
}

impl LiveSplitClient {
    /// Spawns the `livesplit` thread, which links to LiveSplit whenever it
    /// runs.
    pub fn start() -> Self {
        let (run_tx, run_rx) = bounded::<RunView>(RUN_QUEUE);
        let (status_tx, status_rx) = bounded::<&'static str>(64);
        let igt = Arc::new(AtomicU32::new(IGT_UNKNOWN));
        let shutdown = Arc::new(AtomicBool::new(false));

        let thread_run_rx = run_rx.clone();
        let thread_igt = Arc::clone(&igt);
        let thread_shutdown = Arc::clone(&shutdown);
        let handle = thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                livesplit_thread(thread_run_rx, status_tx, thread_igt, thread_shutdown);
            }));
            if let Err(panic_info) = result {
                error!(
                    "[LIVESPLIT] Thread panic, LiveSplit no longer driven: {}",
                    crate::panic_message(panic_info.as_ref())
                );
            }
        });

        Self {
            run_tx,
            run_rx,
            status_rx,
            igt,
            shutdown,
            handle: Some(handle),
        }
    }

    /// Queues a run view for the thread (rare: on the run's transitions).
    /// Views are cumulative and the newest one counts (it holds the latest
    /// arrivals, a final split included), so a full channel (a LiveSplit
    /// stalled for a long while) drops the oldest view, never this one.
    pub fn send_run(&self, view: RunView) {
        let view = match self.run_tx.try_send(view) {
            Ok(()) => return,
            Err(TrySendError::Full(view)) => view,
            Err(e) => {
                warn!("[LIVESPLIT] Failed to queue run view: {}", e);
                return;
            }
        };
        let _ = self.run_rx.try_recv();
        match self.run_tx.try_send(view) {
            Ok(()) => warn!("[LIVESPLIT] Run view queue full, dropped the oldest view"),
            Err(e) => warn!("[LIVESPLIT] Failed to queue run view: {}", e),
        }
    }

    /// Stores the frame's IGT (None while unknown, stored as `IGT_UNKNOWN`),
    /// after the frame's run views were queued: the Release store publishes
    /// them with it (see `LiveSplitSync::push_due`).
    pub fn publish_igt(&self, igt_ms: Option<u32>) {
        self.igt
            .store(igt_ms.unwrap_or(IGT_UNKNOWN), Ordering::Release);
    }

    /// The next overlay status the thread asked for, if any.
    pub fn poll_status(&self) -> Option<&'static str> {
        self.status_rx.try_recv().ok()
    }
}

impl Drop for LiveSplitClient {
    /// Stops the thread without hanging on a frozen LiveSplit: the thread
    /// checks the flag every tick, but a pipe write or read blocks for as
    /// long as LiveSplit does not take it. Past a short grace the thread is
    /// left behind (detached) rather than joined. Runs when the mod is
    /// ejected (hudhook drops the overlay), never at game exit.
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        let Some(handle) = self.handle.take() else {
            return;
        };
        let deadline = Instant::now() + SHUTDOWN_GRACE;
        while !handle.is_finished() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        if handle.is_finished() {
            let _ = handle.join();
        } else {
            warn!("[LIVESPLIT] Thread still blocked on the pipe at shutdown, not waiting");
        }
    }
}

// =============================================================================
// THREAD
// =============================================================================

fn livesplit_thread(
    run_rx: Receiver<RunView>,
    status_tx: Sender<&'static str>,
    igt: Arc<AtomicU32>,
    shutdown: Arc<AtomicBool>,
) {
    #[cfg(feature = "profile-tracy")]
    tracy_client::set_thread_name!("livesplit");

    let mut link = Link {
        sync: LiveSplitSync::new(),
        pipe: None,
        status_tx,
        open_error: None,
        too_old: false,
        file_seed: None,
        file_category: None,
    };
    // The newest view's liveness, and whether the run was live with a known
    // IGT on the previous tick (the moment a timer starts).
    let mut run_live = false;
    let mut was_ready = false;
    let start = Instant::now();
    let mut next_connect = start;
    let mut next_poll = start;
    let mut next_push = start;
    let mut igt_was_known = false;

    while !shutdown.load(Ordering::Relaxed) {
        // The IGT first, then every view queued before it, then the push:
        // a push never gets ahead of an arrival the sync has not seen.
        let igt_ms = Some(igt.load(Ordering::Acquire)).filter(|&v| v != IGT_UNKNOWN);
        // A start or an adoption that waited for the IGT is decided as soon
        // as it is known (the save loaded), not at the next poll.
        let igt_now_known = igt_ms.is_some() && !igt_was_known;
        igt_was_known = igt_ms.is_some();
        while let Ok(view) = run_rx.try_recv() {
            run_live = view.live;
            let out = link.sync.on_run(view, igt_ms);
            link.execute(out);
        }
        // A denied pipe is first met at launch, its status shown during the
        // startup logos: shown again when the timer would start, in game.
        let ready = run_live && igt_ms.is_some();
        if ready && !was_ready && link.open_error == Some(io::ErrorKind::PermissionDenied) {
            let _ = link.status_tx.try_send(STATUS_ELEVATED);
        }
        was_ready = ready;

        let now = Instant::now();
        if link.pipe.is_none() {
            if now >= next_connect {
                next_poll = now + POLL_INTERVAL;
                next_connect = now + link.connect(igt_ms);
            }
        } else {
            if now >= next_poll || igt_now_known {
                next_poll = now + POLL_INTERVAL;
                link.poll(igt_ms);
            }
            if now >= next_push {
                next_push = now + PUSH_INTERVAL;
                if let Some(command) = link.sync.push_due(igt_ms) {
                    link.send(&command);
                }
            }
        }

        thread::sleep(TICK);
    }
}

/// The sync and the pipe it drives.
struct Link {
    sync: LiveSplitSync,
    /// None while unlinked.
    pipe: Option<Pipe>,
    status_tx: Sender<&'static str>,
    /// The last connection failure logged, so a retry loop logs it once.
    open_error: Option<io::ErrorKind>,
    /// The last attempt found a LiveSplit too old to link, so a run of such
    /// attempts is logged and shown once.
    too_old: bool,
    /// The file identity the sync last checked, from the link's snapshot.
    file_seed: Option<String>,
    file_category: Option<String>,
}

impl Link {
    /// Opens the pipe, checks LiveSplit's version and reads its state; links
    /// on success. Returns how long to wait before the next attempt while
    /// unlinked: longer for a LiveSplit too old to link.
    fn connect(&mut self, igt_ms: Option<u32>) -> Duration {
        profile_span!("livesplit_connect");
        let snapshot = Pipe::open().and_then(|mut pipe| {
            // A pipe write or read blocks while LiveSplit does not take it:
            // this line with no result after it (linked, too old or an
            // error) points there. Not repeated while an old LiveSplit is
            // retried, whose result is logged once.
            if !self.too_old {
                info!("[LIVESPLIT] Pipe open, checking LiveSplit's version");
            }
            if !reads_variables(&mut pipe)? {
                return Ok(None);
            }
            Ok(Some((read_snapshot(&mut pipe)?, pipe)))
        });
        let (ls, pipe) = match snapshot {
            Ok(Some(linked)) => linked,
            Ok(None) => {
                // The pipe is closed: an older LiveSplit is never driven.
                self.open_error = None;
                if !self.too_old {
                    info!(
                        "[LIVESPLIT] LiveSplit older than 1.8.31, not linked; retrying every 60 s"
                    );
                    let _ = self.status_tx.try_send(STATUS_TOO_OLD);
                    self.too_old = true;
                }
                return TOO_OLD_RETRY_INTERVAL;
            }
            Err(e) => {
                if self.open_error != Some(e.kind()) {
                    if e.kind() == io::ErrorKind::PermissionDenied {
                        // Windows lets a program that is not elevated read an
                        // elevated one's pipe, not write to it: the usual
                        // cause, another user account's LiveSplit the rare one.
                        info!(
                            error = %e,
                            "[LIVESPLIT] Pipe denied, likely LiveSplit runs as administrator and the game does not; retrying every 5 s"
                        );
                        let _ = self.status_tx.try_send(STATUS_ELEVATED);
                    } else {
                        info!(error = %e, "[LIVESPLIT] LiveSplit unavailable, retrying every 5 s");
                    }
                    self.open_error = Some(e.kind());
                }
                self.too_old = false;
                return RETRY_INTERVAL;
            }
        };
        self.open_error = None;
        self.too_old = false;
        self.pipe = Some(pipe);
        self.link(ls, igt_ms);
        RETRY_INTERVAL
    }

    /// Feeds LiveSplit's state to the sync as a new link, which checks the
    /// file and resets what belonged to the previous link.
    fn link(&mut self, ls: LsSnapshot, igt_ms: Option<u32>) {
        info!(
            phase = ?ls.phase,
            split_index = ls.split_index,
            game_time_ms = ?ls.game_time_ms,
            file_seed = ?ls.file_seed,
            file_category = ?ls.file_category,
            "[LIVESPLIT] Linked"
        );
        self.file_seed.clone_from(&ls.file_seed);
        self.file_category.clone_from(&ls.file_category);
        let out = self.sync.on_link(ls, igt_ms);
        self.execute(out);
    }

    /// Reads LiveSplit's state and feeds it to the sync. The sync checks the
    /// file on link only, so a poll that finds another file open (the player
    /// opened the run's splits after the link, or another run's) links anew.
    fn poll(&mut self, igt_ms: Option<u32>) {
        profile_span!("livesplit_poll");
        let Some(pipe) = self.pipe.as_mut() else {
            return;
        };
        let ls = match read_snapshot(pipe) {
            Ok(ls) => ls,
            Err(e) => {
                self.unlink(e);
                return;
            }
        };
        if ls.file_seed != self.file_seed || ls.file_category != self.file_category {
            info!("[LIVESPLIT] Splits file changed");
            self.link(ls, igt_ms);
        } else {
            let out = self
                .sync
                .on_poll(ls.phase, ls.split_index, ls.game_time_ms, igt_ms);
            self.execute(out);
        }
    }

    /// Writes the commands and forwards the statuses, in order. A write
    /// error unlinks and drops the rest of the batch: it belonged to the
    /// link that just dropped.
    fn execute(&mut self, outputs: Vec<SyncOutput>) {
        for output in outputs {
            match output {
                SyncOutput::Command(command) => {
                    info!(command = ?command, "[LIVESPLIT] Command");
                    if !self.send(&command) {
                        return;
                    }
                }
                SyncOutput::Status(status) => {
                    let _ = self.status_tx.try_send(status);
                }
            }
        }
    }

    /// Writes one command; on a write error unlinks and returns false.
    fn send(&mut self, command: &LsCommand) -> bool {
        let Some(pipe) = self.pipe.as_mut() else {
            return false;
        };
        match pipe.send(&command.to_line()) {
            Ok(()) => true,
            Err(e) => {
                self.unlink(e);
                false
            }
        }
    }

    /// Drops the pipe after an I/O error; the next tick tries to relink.
    fn unlink(&mut self, e: io::Error) {
        info!(error = %e, "[LIVESPLIT] Link lost");
        self.pipe = None;
        let out = self.sync.on_unlink();
        self.execute(out);
    }
}

/// Whether LiveSplit answers `getcustomvariablevalue` (1.8.31 or later),
/// read on a new connection. The variable query and `gettimerphase` go out
/// together: an older LiveSplit drops the first without an answer, so the
/// first line read answers the second (`livesplit_too_old`). A newer one
/// answers both, and both answers are read, which keeps every later answer
/// in step with its query.
///
/// In one write, never two: the second write would wait for LiveSplit to
/// read it, while LiveSplit waits for the mod to read its first answer.
fn reads_variables(pipe: &mut Pipe) -> io::Result<bool> {
    let variable_query = format!("getcustomvariablevalue {LS_VAR_SEED}");
    pipe.send_together(&[&variable_query, "gettimerphase"])?;
    if livesplit_too_old(pipe.read_answer(&variable_query)?) {
        return Ok(false);
    }
    let answer = pipe.read_answer("gettimerphase")?;
    parse_timer_phase(answer).ok_or_else(|| unexpected("gettimerphase", answer))?;
    Ok(true)
}

/// LiveSplit's state: the file's identity, then the timer. An answer that
/// is no phase or no index means the connection is out of step: it is an
/// error, which drops the link (a new connection starts in step).
fn read_snapshot(pipe: &mut Pipe) -> io::Result<LsSnapshot> {
    let file_seed = parse_variable(pipe.query(&format!("getcustomvariablevalue {LS_VAR_SEED}"))?);
    let file_category =
        parse_variable(pipe.query(&format!("getcustomvariablevalue {LS_VAR_CATEGORY}"))?);
    let answer = pipe.query("gettimerphase")?;
    let phase = parse_timer_phase(answer).ok_or_else(|| unexpected("gettimerphase", answer))?;
    let answer = pipe.query("getsplitindex")?;
    let split_index = answer
        .trim()
        .parse::<i32>()
        .map_err(|_| unexpected("getsplitindex", answer))?;
    let game_time_ms = parse_timespan(pipe.query("getcurrentgametime")?);
    Ok(LsSnapshot {
        phase,
        split_index,
        game_time_ms,
        file_seed,
        file_category,
    })
}

fn unexpected(query: &str, answer: &str) -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        format!("unexpected answer to {query}: {answer:?}"),
    )
}

// =============================================================================
// PIPE
// =============================================================================

/// A synchronous connection to LiveSplit's pipe. The reader is a clone of
/// the writer's handle: synchronous I/O on one file object is serialized,
/// which is fine on a single thread that reads only right after a query.
struct Pipe {
    writer: File,
    reader: BufReader<File>,
    /// Reused buffers: the line being written, the last answer read.
    line: Vec<u8>,
    answer: String,
}

impl Pipe {
    fn open() -> io::Result<Self> {
        let writer = OpenOptions::new().read(true).write(true).open(PIPE_PATH)?;
        let reader = BufReader::new(writer.try_clone()?);
        Ok(Self {
            writer,
            reader,
            line: Vec::new(),
            answer: String::new(),
        })
    }

    /// Writes one command line.
    fn send(&mut self, command: &str) -> io::Result<()> {
        self.send_together(&[command])
    }

    /// Writes command lines in a single write, which returns once LiveSplit
    /// has read them all (see the module doc).
    fn send_together(&mut self, commands: &[&str]) -> io::Result<()> {
        self.line.clear();
        for command in commands {
            self.line.extend_from_slice(command.as_bytes());
            self.line.push(b'\n');
        }
        self.writer.write_all(&self.line)
    }

    /// Writes a `get*` query and reads its one-line answer (`read_answer`).
    fn query(&mut self, query: &str) -> io::Result<&str> {
        self.send(query)?;
        self.read_answer(query)
    }

    /// Reads the next line, the answer to `query`, written earlier, without
    /// the line ending. A missing line ending (LiveSplit closed the pipe, or
    /// the line is too long to be an answer) is an error.
    fn read_answer(&mut self, query: &str) -> io::Result<&str> {
        self.answer.clear();
        (&mut self.reader)
            .take(MAX_ANSWER_BYTES)
            .read_line(&mut self.answer)?;
        if !self.answer.ends_with('\n') {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                format!("no answer to {query}"),
            ));
        }
        Ok(self.answer.trim_end())
    }
}
