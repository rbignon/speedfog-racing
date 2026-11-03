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

- LiveSplit 1.8.31 or later: its pipe server (`\\.\pipe\LiveSplit`) is
  always on from 1.8.29, and 1.8.31 added the `getcustomvariablevalue`
  command the mod reads the file's identity with (see "How the mod
  links"). No component to install, nothing to activate.
- No SoulSplitter. It writes the game's timer (its auto start writes 0 into
  the IGT, its blackscreen write-back can lower the IGT the mod reports), so
  SpeedFog runs allow LiveSplit only without it. SpeedFog files name their
  game `SpeedFog`, not "Elden Ring", so a SoulSplitter the player once
  activated for Elden Ring does not wake up on them. Its IGT hook itself
  stacks harmlessly with the mod's (see `docs/IGT_TIMING.md`).
- LiveSplit and the game can start in any order.

## The file

The `.lss` files are built in the browser by `web/src/lib/livesplit.ts`,
from run data the site already serves.

- **GameName** is `SpeedFog`, never "Elden Ring": LiveSplit would wake a
  SoulSplitter the player once activated for Elden Ring.
- **CategoryName** is the category's name; a seed file adds
  " · Seed <n>".
- **Custom variables** `SpeedFog seed` (seed file) or `SpeedFog category`
  (category file). The mod reads them on link to check the file matches the
  run (see "How the mod links").
- **Segments**: one per depth. A seed file names each after the zone the
  viewer's best run left that depth through, else the seed's best counted
  run, else "Depth k". A category file names them "Depth k".
- **Comparisons**: "Personal Best" and "SpeedFog WR". A seed file takes the
  viewer's best run on the seed and the seed's best counted run; a category
  file takes the viewer's Random Seed PB and the Random Seed WR from
  `GET /api/speedrun/livesplit/{category}`. A missing reference leaves its
  comparison empty.
- **Golds** (best segments) are the viewer's fastest time on each depth over
  their runs on the seed (seed file) or the segments of their PB (category
  file).
- **Game Time only**: every time is in Game Time, the IGT the site records.

## Where to download

Five pages, through `downloadSeedSplits` and `downloadCategorySplits`
(`web/src/lib/livesplit-download.ts`):

- **Seed page**, "Play this seed in Set Seed" card, "LiveSplit splits": the
  seed file, for everyone (the viewer's own best run is the PB).
- **Solo session page** (owner, active session), "LiveSplit splits" after
  "Download Pack": the seed file for a Set Seed session, the category file
  for any other. Hidden while the session has no category.
- **Race page**, in the download window ("Before you race"), "Download
  LiveSplit splits": the seed file for a Set Seed race, the category file
  otherwise. Absent while the race has no category.
- **Daily Seed page**, in the same download window, alike.
- **Speedrun board toolbar**, "LiveSplit", before "Start a run": the file of
  the selected category.

A category file takes its layer count from the page when it has one, else
from the endpoint. The data comes from `GET /api/speedrun/livesplit/{category}`
(optional Bearer auth, `404 Unknown category`): the category's name and layer
count, the record (`wr`) and the viewer's best run (`pb`), each with its
per-layer arrival IGTs. A failure shows in the surface's own error line.

## How the mod links

A dedicated thread, `livesplit`, owns the pipe. It tries to open it as soon
as the mod starts, then again at most 5 seconds after its last attempt
whenever it is unlinked: LiveSplit absent or closed, or the pipe dropped
after an answer out of step. A failed attempt costs nothing visible. The
mod log notes each link and each loss, and the first failure of each kind
(not every retry), under the `[LIVESPLIT]` prefix.

On link, the thread first checks LiveSplit's version: it writes
`getcustomvariablevalue SpeedFog seed` and `gettimerphase` back to back,
then reads one line. LiveSplit before 1.8.31 does not know the first
command and drops it without an answer, so that line answers the second: a
timer phase, which no variable's answer (a seed number, a category key or
`-`) ever is (`livesplit_too_old`). The mod then closes the pipe without
linking, shows a status once (until LiveSplit closes or a link comes up),
and tries again every 60 seconds instead of 5: each try leaves an "Invalid
command" line in LiveSplit's log. A newer LiveSplit answers both lines,
and both are read.

The thread then reads the file's identity from two custom variables of the
open splits, `SpeedFog seed` (a seed file) and `SpeedFog category` (a
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
| LiveSplit 1.8.31 or later needed                  | The open LiveSplit is too old to link (see above).           |

## Timing

LiveSplit's Game Time is the IGT the mod reports to the server: held over
menu reloads, held during blackscreen fades, quit-out penalties included
(`RaceMachine::live_igt_ms`). LiveSplit's own game time stays paused
(`alwayspausegametime`); the mod sets it with `setgametime` about 30 times a
second while the run is live and the mod owns the timer. Before a save
loads after a launch, the IGT is unknown: nothing is pushed then, rather
than a placeholder 0.

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

The game time check needs the run's IGT. A link that comes up before it is
known (the title screen after a relaunch, before the save loads) leaves a
Running timer whose split index fits the run alone, without a command or a
status, and the first poll that knows the IGT adopts it or asks for the
reset.

**Catch-up** splits each depth LiveSplit is missing, each with its own
arrival IGT, until LiveSplit's split index matches the depths reached.

## Manual reset

If the player resets a timer the mod owns during a run, the mod leaves it
stopped for the rest of that attempt on that link: no restart, no catch-up,
even if the player starts it again by hand. The next attempt takes it
again, and so does a new link (LiveSplit or the game restarted, the pipe
dropped, or the open splits file changed to one for this run), which
restarts it and catches up.

A reset in the second or so between the mod's `starttimer` and LiveSplit's
next answer is not recognized as the player's: the timer stays stopped, and
a start by hand is then driven.

## Performance

Per frame, `RaceTracker::update` does, inside
`profile_span!("livesplit_publish")`, one atomic store of the IGT (0 while
it is unknown: a known IGT is never 0) and a `try_recv` on the status
channel. On the run's transitions (its liveness,
a new attempt, a new depth: about 30 per run), `emit_run_view` builds a run
view (its allocation, only on such a change) and `execute_effects` does one
`try_send` of it. Nothing else on the frame thread allocates, but for the
overlay string of a status (a few per session), and nothing formats, does
I/O or blocks.

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
gather). Past that, a new view takes the oldest queued one off rather than
being dropped: views are cumulative, so the newest holds every arrival so
far, the final split included.

When the mod is ejected (hudhook drops the overlay), it waits at most
200 ms for the thread, then leaves it behind rather than hang on a frozen
LiveSplit. A game exit waits for nothing: the process ends with the thread.

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
