# LiveSplit

The mod drives [LiveSplit](https://livesplit.org/) through LiveSplit's local
named pipe. With the run's splits file open, LiveSplit starts, splits and
stops on its own, in Game Time equal to the IGT the site records. There is
one split per depth, so one file works for any route through the map, and
two runs on different branches compare segment by segment.

The interface calls a layer a **depth**, numbered from 1 ("Depth 1" is
layer 0, where the run starts); this doc and the code keep the graph's
0-based "layer".

## Requirements

- LiveSplit 1.8.29 or later: its pipe server (`\\.\pipe\LiveSplit`) is
  always on from that version. No component to install, nothing to
  activate.
- No SoulSplitter. It writes the game's timer (its auto start writes 0 into
  the IGT, its blackscreen write-back can lower the IGT the mod reports), so
  SpeedFog runs allow LiveSplit only without it. SpeedFog files name their
  game `SpeedFog`, not "Elden Ring", so a SoulSplitter the player once
  activated for Elden Ring does not wake up on them. Its IGT hook itself
  stacks harmlessly with the mod's (see `docs/IGT_TIMING.md`).
- LiveSplit and the game can start in any order.

## The file

The `.lss` files the site generates are described with the web side.

## Where to download

The download buttons are described with the web side.

## How the mod links

A dedicated thread, `livesplit`, owns the pipe. It tries to open it as soon
as the mod starts, then again at most 5 seconds after its last attempt
whenever it is unlinked: LiveSplit absent or closed, or the pipe dropped
after an answer out of step. A failed attempt costs nothing visible. The
mod log notes each link and each loss, and the first failure of each kind
(not every retry), under the `[LIVESPLIT]` prefix.

On link, the thread reads the file's identity from two custom variables of
the open splits, `SpeedFog seed` (a seed file) and `SpeedFog category` (a
category file), then LiveSplit's timer: its phase, split index and game
time.

**File check.** The mod drives LiveSplit only when the open file is for the
current run:

- a seed file (`SpeedFog seed` set) must name the run's seed number;
- otherwise a category file (`SpeedFog category` set) must name the run's
  category, whatever the seed: a blind run compares against its category;
- a file with neither (the player's own splits) is never driven.

On a match the mod sends `switchto gametime` and `alwayspausegametime`, and
then drives the timer as the sections below describe. On a mismatch it
shows a status and sends nothing. The file is checked again every second,
so opening the run's splits after the link (or another run's) takes effect
within a second, as a new link would.

**Overlay statuses** (each shown for a few seconds):

| Status                                            | When                                                         |
| ------------------------------------------------- | ------------------------------------------------------------ |
| LiveSplit linked                                  | The link is up and the open file is for this run.            |
| LiveSplit disconnected                            | A link that was up dropped.                                  |
| LiveSplit: these splits are for another run       | The file names another seed, or another category.            |
| LiveSplit: open SpeedFog splits to track this run | The file is not a SpeedFog file.                             |
| Reset LiveSplit to track this run                 | LiveSplit runs a timer the mod does not own (see Ownership). |

## Timing

LiveSplit's Game Time is the IGT the mod reports to the server: held over
menu reloads, held during blackscreen fades, quit-out penalties included
(`RaceMachine::live_igt_ms`). LiveSplit's own game time stays paused
(`alwayspausegametime`); the mod sets it with `setgametime` about 30 times a
second while the run is live and the mod owns the timer.

The run is **live** while it runs past its countdown, the local runner has
neither finished nor left it (abandon, disqualification), and the loaded
save is the run's. A wrong save therefore pauses the pushes and the splits;
they resume when the run's save is back. After the final split, or once the
run ends otherwise, the mod stops pushing and leaves the timer as it is
until the next attempt.

Game time never goes back while the mod drives a timer in one attempt: a
push holds the highest value sent since the mod started that timer. After a
backup restore (the game's IGT drops), LiveSplit holds that value, as the
server keeps the highest IGT, so split times recorded after such a restore
may differ from the site's.

## Start and attempts

An attempt with no depth reached yet is **fresh**. When a fresh attempt is
live, the mod takes the timer: one still Running, Paused or Ended from
earlier is reset first (`reset`), then the mod sends `starttimer` and game
time. The pipe's reset opens no dialog and records the attempt as a manual
reset does (attempt history, golds, a PB when it finished faster). An
attempt that is not fresh when the link comes up is caught up instead (see
Ownership).

A new attempt is:

- a real race start (setup to running, a re-run after a race reset
  included); a solo session's `race_start`, which the server resends after
  every reconnect, is no start;
- a fresh character in the same launch: a save load that drops the IGT to
  at most 60 seconds (`FRESH_RUN_MAX_IGT_MS`); a backup restore further in
  is the same attempt;
- a new game process (a relaunch, the Set Seed reset loop): the sync starts
  over.

Since a fresh attempt always takes the timer, a relaunch, or a pipe drop
and relink, before the first fog of an attempt restarts LiveSplit's timer:
one more attempt in LiveSplit's history, no split lost.

## Splits

Segment k (0-based) ends at the first arrival on layer k+1, and the last
one ends at the finish (the final boss kill), so a file has `total_layers`
segments.

- **High watermark.** Only a depth deeper than every depth reached in the
  attempt splits: a back-out or a revisit never does.
- **Exact times.** Each split sends `setgametime` with the arrival IGT
  captured with that fog's flag, then `split`, so LiveSplit's split time is
  the arrival IGT the site records. A push never runs ahead of an arrival
  the thread has not seen yet (see Performance).
- **Skipped depths.** A rise of more than one depth at once (a missed
  capture) sends `skipsplit` for each depth in between: an empty split
  time, as the site shows "-".
- **Final split.** The finish is the last split, at the finish IGT.

The arrivals come from the mod's own fog and finish captures (see "LiveSplit
Depth Tracking" in `docs/EVENT_FLAG_TRACKING.md`) and, after a relaunch,
from the local runner's arrival per depth that the server sends in
`auth_ok` (see `docs/PROTOCOL.md`). A timer the player paused is neither
split nor pushed until it runs again; it then catches up.

## Ownership, adoption and catch-up

The mod drives only a timer it owns: one it started in the current attempt,
or a Running one it adopted.

When the link comes up during a live run (LiveSplit opened late, the game
relaunched, the pipe lost and back) with a run that is not fresh:

- a NotRunning timer is started, then caught up;
- a Running timer is **adopted** when it looks like this run's: its split
  index is at most the depths reached, and its game time is within 60
  seconds (`ADOPT_TOLERANCE_MS`) of the run's IGT;
- any other timer (Running but off, Paused, Ended) is not the mod's: it is
  never split or pushed, and the overlay asks once to "Reset LiveSplit to
  track this run". The player's reset frees it: the mod then starts it and
  catches up.

**Catch-up** splits each depth LiveSplit is missing, each with its own
arrival IGT, until LiveSplit's split index matches the depths reached.

## Manual reset

If the player resets a timer the mod owns during a run, the mod leaves it
stopped for the rest of that attempt on that link: no restart, no catch-up,
even if the player starts it again by hand. The next attempt takes it
again, and so does a new link (LiveSplit or the game restarted, or the pipe
dropped), which restarts it and catches up.

A reset in the second or so between the mod's `starttimer` and LiveSplit's
next answer is not recognized as the player's: the timer stays stopped, and
a start by hand is then driven.

## Performance

Per frame, `RaceTracker::update` does, inside
`profile_span!("livesplit_publish")`, one atomic store of the IGT and a
`try_recv` on the status channel. On the run's transitions (its liveness,
a new attempt, a new depth: about 30 per run), `execute_effects` does one
`try_send` of the run view. Nothing on the frame thread formats, allocates,
does I/O or blocks, but for the overlay string of a status (a few per
session).

The `livesplit` thread does the rest. Every 10 ms it loads the IGT, then
applies every run view queued before it, then, while linked, pushes game
time every 33 ms and reads LiveSplit's state every second; while unlinked it
tries the pipe every 5 seconds. The frame thread queues a view before it
stores the frame's IGT (a Release store, read with Acquire), so a push never
gets ahead of an arrival the thread has not applied: that is what keeps
split times exact.

Every answer is read right after its `get*` query, on the same connection
and thread, after every earlier command was written: each `get*` command
answers exactly one line, the others answer nothing, and LiveSplit handles
a connection's lines in order. An answer that is no timer phase or no split
index means the connection is out of step: the link drops, and a new
connection starts in step.

If LiveSplit hangs, only the thread waits: the game keeps running, and run
views queue on the channel (64 of them, far more than a stall should
gather). On shutdown the mod waits at most 200 ms for the thread, then
leaves it behind rather than hang the game's exit on a frozen LiveSplit.

## Code map

- `mod/src/core/livesplit.rs`: `LiveSplitSync`, the pure state machine
  (file check, ownership, start, splits, catch-up, pushes), its types
  (`RunView`, `LsSnapshot`, `LsCommand`) and answer parsers, with Linux
  scenario tests.
- `mod/src/core/race_machine.rs`: the depth tracker (`record_arrival`, its
  single entry point; `record_capture`; `start_attempt`), `live_igt_ms`, and
  `emit_run_view`, which emits `Effect::LiveSplitRun` when the run's
  liveness, attempt or arrivals change.
- `mod/src/dll/livesplit.rs`: `LiveSplitClient`, the frame thread's side,
  and the pipe thread.
- `mod/src/dll/tracker.rs`: the wiring (`send_run` in `execute_effects`,
  `publish_igt` and `poll_status` in `update`).
