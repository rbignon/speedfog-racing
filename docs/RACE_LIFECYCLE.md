# Race Lifecycle & State Machines

State machines and transition rules for races, participants, seeds, and training sessions.

## Race Status

```
SETUP ──→ RUNNING ──→ FINISHED
  ↑          │            │
  └──────────┴────────────┘  (reset)
```

| Status   | Description                                      |
| -------- | ------------------------------------------------ |
| SETUP    | Created, accepting participants, not yet started |
| RUNNING  | Race in progress                                 |
| FINISHED | Race completed (all done or force-finished)      |

### Transitions

**SETUP → RUNNING** (`POST /races/{id}/start`, organizer only)

- Sets `started_at` to current time.
- Broadcasts `race_start` to mods, `zone_update` for start node (per-mod, localized), `race_status_change` to all, and full `race_state` to each spectator.
- Discord notification: `notify_race_started()` (public normal races only: a speedrun or Set Seed race is announced at creation only) + event status set to ACTIVE (if event exists).

**RUNNING → FINISHED** (four paths)

1. **Auto-finish**: when all participants reach a terminal status (`FINISHED`, `ABANDONED` or `DISQUALIFIED`), `check_race_auto_finish()` transitions the race. Uses optimistic locking (see below). When `late_join_window_minutes` is set and the window is still open, the transition is deferred so a late-joiner can still register even if the currently-registered field has all finished; the hard-close loop performs the deferred close once the window has elapsed (see [Late-join Window & Race Duration](#late-join-window--race-duration)).
2. **Force-finish**: `POST /races/{id}/finish` (organizer). Same optimistic lock mechanism.
3. **Inactivity monitor**: when the last active participant is auto-abandoned (30 min stale IGT, or 30 min no-show on races without `race_duration_minutes`), the monitor calls `check_race_auto_finish()`. Daily-seed races (`Race.daily_date IS NOT NULL`) are skipped: the asynchronous 24h window makes inactivity-based abandonment misleading.

   Event qualifier seeds (`races.event_slot` starting with `qualifier:`) are ordinary week-long races for the lifecycle: the inactivity monitor and the hard-close loop apply to them as to any race. They are kept out of the public listings (`api/helpers.not_event_qualifier`) and live on their event page; the admin in-flight list keeps them so they can be detached. See `EVENTS.md`. Like dailies, they replay against asynchronous ghosts in the in-game overlay (`Race.projects_ghosts`, see the "In-mod replay leaderboard" section of `DAILY_SEED.md`).

4. **Hard-close loop** (`hard_close_loop`, polls every 10s):
   - For races with `race_duration_minutes` set, force-finishes any race past `started_at + race_duration_minutes` (`close_expired_races`); non-terminal participants are swept to `ABANDONED` via `finalize_race`.
   - For races with `late_join_window_minutes` set, finalizes races whose late-join window has elapsed and whose participants are all already terminal (`close_late_join_done_races`), closing the gap left by the auto-finish guard above.

**RUNNING or FINISHED → SETUP** (`POST /races/{id}/reset`, organizer only)

- Refused with 400 "A speedrun race cannot be reset: create a new race instead" for a race in `speedrun` mode (a reset would replay the same seed and the second attempt would count as blind); the race page offers no Reset Race on one. Set Seed, normal, event and daily races reset as described here.
- Closes all WebSocket connections first (`manager.close_room(code=1000)`).
- Transitions status via `_transition_status()` with optimistic lock. Clears `started_at` (but NOT `seeds_released_at`, as seed packs remain downloadable) and sets `seed_played`: the runners played the seed, so a reroll or a deletion keeps it CONSUMED (see "Seen seeds" under Seed Status), and a `normal` community race (neither a Daily Seed nor an event race) counts on no speedrun.fog board until a reroll with a seed report clears it (an unreported one keeps it off, see "Reroll" under Seed Status), since its second attempt is not blind (`race_unranked_reason`; the race page says so under its header, see `SPEEDRUN.md`, and the Reset Race confirm warns the organizer: "Reset this race? All participant progress will be cleared, and the race will count on no Speedrun board unless its seed is re-rolled with a seed report.").
- Resets all participants except disqualified ones via ORM loop (`reset_participant_progress`): `status=REGISTERED, current_zone=None, current_layer=0, igt_ms=0, death_count=0, zone_history=None, finished_at=None, layer_entry_igts={}, last_igt_change_at=None`. The last two are cleared so the re-run starts with clean leaderboard-gap and inactivity state (leaving them stale would keep the previous run's per-layer entry IGTs and activity timestamp).
- When the race was **FINISHED**, resetting it does not reopen or re-score anything: the same participant reset above (`status=REGISTERED`, progress cleared) is the whole story, since there is no per-race rating ledger left to revert. Trait scores self-correct on the next finish (they recompute from live participant state), but permanent victory rewards already granted during the voided run (e.g. `silver-aura`, finish-milestone badges) are one-time souvenirs and are **not** rolled back.
- A disqualified participant keeps its status and run data through the reset (a daily reroll does the same): the disqualification stands until the race staff cancel it. Cheat detections (`debug_flags`) are kept as they are for every participant.
- Mod clients detect the close and reconnect automatically.

### Optimistic Locking

Every Race has a `version` column (integer, starts at 1). All status transitions use:

```sql
UPDATE races
SET status = :new, version = version + 1
WHERE id = :id AND status IN (:allowed) AND version = :v
```

If `rowcount == 0`, the transition was lost to a concurrent update → HTTP 409 or silent no-op (for auto-finish). This prevents duplicate finish broadcasts when two participants finish simultaneously.

### Late-join Window & Race Duration

Two optional fields on Race tune end-of-race behavior:

| Field                      | Type          | Effect                                                                                                                                                                                                                                                             |
| -------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `late_join_window_minutes` | `int \| None` | Players can register up to `started_at + late_join_window_minutes`, and `check_race_auto_finish()` will not close the race before that deadline even if everyone currently registered is already terminal. Required: `<= race_duration_minutes` when both are set. |
| `race_duration_minutes`    | `int \| None` | Hard cap. The hard-close loop force-finishes the race at `started_at + race_duration_minutes`. While set, the inactivity monitor's no-show branch (REGISTERED/READY) is skipped because `finalize_race` will sweep non-terminal participants at the deadline.      |

The two fields are independent: a race may have either, both, or neither.

The deferred-close handoff between auto-finish and hard-close looks like this:

1. A participant finishes during the late-join window → `check_race_auto_finish()` is called → returns `False` because the window is still open → race stays `RUNNING`.
2. The late-join window elapses → `close_late_join_done_races()` (every 10s) re-runs the all-terminal check, transitions to `FINISHED`, calls `finalize_race`.
3. If the race also has `race_duration_minutes` and that deadline arrives first, `close_expired_races()` force-finishes via the same path (any non-terminal participant is bumped to `ABANDONED`).

Both hard-close paths use the same optimistic-lock pattern as `check_race_auto_finish`, so concurrent transitions from `/finish`, the inactivity monitor, or the other hard-close path collapse to a single winner without duplicate finalization side effects: chat messages, notifications, and reward grants.

### Run mode

`Race.mode` (`RunMode`: `normal`, `speedrun`, `set_seed`; default `normal`) is set when the race is created and never changes, like `TrainingSession.mode`. Races of every mode count for the speedrun.fog boards, community races, Daily Seeds and event races alike, except a race that drew a SEEN seed (see "Draws" under Seed Status), a `normal` community race reset after its start (see "RUNNING or FINISHED → SETUP" above) and a `normal` community race re-rolled without a seed report (see "Reroll" under Seed Status); a `set_seed` race is a replay, so its runs are not blind. A `speedrun` race is the community race sure to count: a fresh seed, no reset, and its rerolls keep it on the boards. See `SPEEDRUN.md`.

`POST /api/races` takes it as `mode`:

- `normal`: a seed drawn from `pool_name` (`assign_seed_to_race`), which may be a SEEN seed (see "Draws" under Seed Status).
- `speedrun`: the same pool checks, plus a training pool refused for parity with Speedrun-mode solo runs (unknown, disabled or training pool: 400 "Mode '<pool>' is not available"), then a draw through `draw_speedrun_seed`, so the pool's floor applies (409 "No fresh seed right now"); the seed is CONSUMED.
- `set_seed`: `seed` names a played seed (full number or prefix) and the race takes its pool from it: `pool_name` is ignored and the pool-enabled check skipped, so a retired category's seed stays playable. The seed is found and checked like a Set Seed solo run (404 "Unknown seed", 409 "Ambiguous seed ID", 409 with the not-replayable reason); the race consumes nothing and leaves the seed's status alone.

`seed` is required for `set_seed` and refused for the other modes (422). Every refusal comes before the commit, so it creates no race. `PATCH /api/races/{id}` has no `mode`: such a key is ignored. The Discord announcement of a public open race says "New Speedrun race" or "New Set Seed race" for those modes, and a Set Seed race's also shows its seed number (a drawn seed is never shown); those modes post to the speedrun channel, never ping `@Runner`, post no started or finished embed and get no calendar event, on Discord or events.malenia.win (see "Race Notifications" in `DISCORD_BOT.md`).

### Deathless

`deathless` (bool, default false, editable in SETUP only): when set, the first
death of a PLAYING participant during a RUNNING race transitions them to
`ABANDONED` server-side, from the same `status_update` ingestion path that
already computes the death-count delta. Side effects mirror
`POST /races/{id}/abandon`: public system chat message, public-chat unlock,
leaderboard and race_state broadcasts, auto-finish check. Deaths are still
attributed to the current zone before the transition. Daily Seeds set it
from the per-weekday `daily_seed_schedule.deathless` flag. On a daily,
eliminating a participant who has not yet qualified for the streak also
applies the eager close-day used by manual abandon, and an
elimination-triggered auto-finish posts "The daily seed is over." instead
of the regular finished message.

An eliminated participant (ABANDONED with at least one death in a deathless
race) is labeled "Dead" on the web leaderboard, "DEAD" on the OBS overlay,
and "dead" in the in-game leaderboard. Independently of deathless, the
in-game overlay freezes an abandoned player's own IGT display at the
server-recorded value and shows it in red.

### IGT cutoff

`igt_cutoff_ms` (int, ms, nullable, set by the server only): the in-game
time a run must finish by. A PLAYING participant whose recorded IGT (the
non-decreasing value, so a restored save replaying its lost segment never
trips it early) passes it is transitioned to `ABANDONED` from the
`status_update` ingestion path (`handle_igt_cutoff`), and a finish past it
is the same elimination, judged on the finish's own IGT. Side effects are
the deathless elimination's, with "ran out of time" as the public chat
line; the last run out ends the race through the auto-finish check. A
disqualification or its cancellation recomputes it, and a reset clears it. Event playoff races set it from their finishes (see the Playoff
scoring section of `EVENTS.md`).

---

## Participant Status

```
REGISTERED ──→ READY ──→ PLAYING ──→ FINISHED
     │           │          │
     └───────────┴──────────┴──→ ABANDONED

any status, race RUNNING or FINISHED ──→ DISQUALIFIED ──→ status before (cancel)
```

| Status       | Description                                               |
| ------------ | --------------------------------------------------------- |
| REGISTERED   | Signed up for the race                                    |
| READY        | Mod connected and ready signal sent                       |
| PLAYING      | Currently racing (IGT ticking)                            |
| FINISHED     | Completed the race (boss kill)                            |
| ABANDONED    | Left the race (inactivity, no-show, or voluntary abandon) |
| DISQUALIFIED | Removed from the results by the race staff                |

### Transitions

**REGISTERED → READY**: mod sends `ready` WS message. Broadcasts `leaderboard_update`.

**READY → PLAYING**: auto-triggered on the first `status_update` while the race is RUNNING, provided `igt_ms <= MAX_FRESH_IGT_MS` (60 000ms). If the IGT exceeds the threshold (player loaded a pre-existing save instead of starting a New Game), the server rejects the transition with an `error` message and the participant stays in READY. An `igt_ms` that fails `clamp_igt` (missing, non-int, negative, or above `MAX_IGT_MS` ~24.85 days) is silently dropped and the participant also stays in READY, preventing a stale save with absurd IGT from bypassing the gate. The check repeats on each `status_update`, so the player can fix it by starting a New Game (IGT resets to 0). On successful transition:

- Sets `current_zone` to the start node.
- Appends start node to `zone_history` with `igt_ms=0`.
- `current_layer` remains 0 (start node is layer 0).
- Broadcasts full `leaderboard_update`.

**PLAYING → FINISHED**: `event_flag` message with `flag_id == finish_event`. On transition:

- Sets `current_layer = total_layers` (progress shows N/N).
- Sets `finished_at` to current time.
- Updates the recorded `igt_ms` to the maximum of the reported IGT and the participant's previously recorded IGT (non-decreasing clamp). This ensures that if the player replays a segment after a backup restore (legitimate regression), the finish IGT is based on the furthest point reached, not an intermediate checkpoint. The mod normalizes IGT before it ever reaches the wire (framerate-independent increments, frozen during blackscreen fades); see `IGT_TIMING.md`.
- Calls `check_race_auto_finish()` for the race.
- Implementation note: the finish handler uses two separate DB sessions to avoid nested-session deadlocks in SQLite tests. The `event_flag` handler commits progress, exits its session, then calls `handle_finished()` in a new session.

**REGISTERED / READY / PLAYING → ABANDONED**: six paths:

1. **Inactivity monitor** (PLAYING): background loop checks every 60s for participants with `last_igt_change_at < now - 30min`. Marks them `ABANDONED` and triggers auto-finish check. Daily-seed races are skipped entirely (`Race.daily_date IS NOT NULL`) because their async 24h window makes inactivity meaningless.
2. **No-show monitor** (REGISTERED/READY): same loop also catches participants who never started playing. The cutoff is per-participant: both `Race.started_at < now - 30min` AND `Participant.created_at < now - 30min` must hold (equivalent to `max(started_at, created_at) < now - 30min`). This ensures a late-joiner is not abandoned the moment they register, and an early registrant is not abandoned the moment the race starts. When `late_join_window_minutes` is set, the `started_at` anchor is pushed to the window close: the participant is abandoned only once `started_at + late_join_window_minutes < now - 30min`, so a registrant who plans to connect during the window is not swept while it is still open. Skipped entirely when `race_duration_minutes` is set: the hard-close loop sweeps non-terminal participants at the deadline via `finalize_race`.
3. **Hard-close loop** (REGISTERED/READY/PLAYING): when `close_expired_races` or `close_late_join_done_races` finalizes a race, `finalize_race` moves any remaining non-terminal participant to `ABANDONED`.
4. **Voluntary abandon**: `POST /races/{id}/abandon` (participant). Accepts REGISTERED, READY, or PLAYING status. Triggers auto-finish check.
5. **Deathless elimination** (PLAYING): on a race with `deathless` set, the first positive death-count delta seen by the `status_update` handler transitions the participant to `ABANDONED` (`handle_deathless_death`). Triggers auto-finish check.
6. **IGT cutoff elimination** (PLAYING): on a race with `igt_cutoff_ms` set, a `status_update` or a finish whose recorded IGT passes it transitions the participant to `ABANDONED` (`handle_igt_cutoff`). Triggers auto-finish check.

**Any status → DISQUALIFIED**: `POST /races/{id}/participants/{pid}/disqualify` with a required reason, by the race organizer or an admin (on a daily, whose organizer is the system account, admins only), while the race is RUNNING or FINISHED. The participant's status is saved in `status_before_disqualification` and the run data is kept as it is. A ban does the same to the user's participations in running races, with the reason "Account banned". In a running race the auto-finish check runs; in a finished race the win rewards go to the new winner. See the "Sanctions" section of `CHEAT_DETECTION.md` for the effects on results.

**DISQUALIFIED → status before**: `DELETE` on the same path, by the same people. The saved status comes back with the run as it was. When the race was restarted after the disqualification (the race is in SETUP, or its `started_at` or `seeds_released_at` is later than `disqualified_at`: a reset moves the first on the next start, a daily reroll keeps the race running and moves the second), the saved status belongs to an attempt that no longer exists, so the participant starts over as REGISTERED with its progress cleared. When the race has finished in the meantime (the disqualification of the last runner still out may have finished it), a saved non-terminal status comes back as ABANDONED, as the finish would have recorded it.

A participant who is disqualified or has a cheat detection can neither leave the race nor be removed from it ("This participation is under review"), so the record stays for the staff.

### Terminal States

`FINISHED`, `ABANDONED` and `DISQUALIFIED` are terminal (`TERMINAL_PARTICIPANT_STATUSES`); only a cancelled disqualification leaves one. Once a participant reaches a terminal state:

- All incoming `status_update`, `event_flag`, `zone_query`, and `finished` messages are silently dropped.
- The server does not update `igt_ms` or `death_count`; data is frozen.

More broadly, `event_flag` and `zone_query` handlers require `status == PLAYING`. Messages from READY or REGISTERED participants are silently dropped, preventing zone_history mutations before the player has been validated (see READY to PLAYING transition above).

### Progress Tracking

**`current_layer`** is a **high watermark**: it tracks the furthest layer reached and never regresses, even if the player backtracks to an earlier zone. This ensures leaderboard stability.

**`zone_history`** is a JSON array of `{"node_id": str, "igt_ms": int, "deaths"?: int, "message_id"?: int}` entries. A new entry is appended on every zone transition, including backtracks (the same `node_id` may appear multiple times). The optional `message_id` is present on `fog` entries created from newer `event_flag` messages and is used for idempotent replay after reconnect. The `deaths` key is added/incremented by `status_update` when the death count increases. Deaths are attributed to the **most recent** entry matching the player's current zone. Frontend consumers (popup, highlights, replay) aggregate time and deaths across all visits to the same node.

**`last_igt_change_at`** is updated on every `status_update` where `igt_ms` differs from the stored value. Used by the inactivity monitor. A quit-out (IGT=0) does not reset it since IGT doesn't change, it just becomes 0.

---

## Seed Status

```
AVAILABLE ──→ CONSUMED          (drawn: race, Daily Seed, Speedrun-mode solo run)
CONSUMED  ──→ SEEN              (reroll or deletion of a race still in SETUP)
CONSUMED  ──→ REPORTED          (reroll with a report)
REPORTED  ──→ SEEN | DISCARDED  (admin restore | admin discard)
REPORTED  ──→ AVAILABLE         (admin restore, training pool)
CONSUMED  ──→ AVAILABLE         (reroll or deletion of a SETUP race, training pool)
SEEN      ──→ CONSUMED          (drawn again by a normal race)
any other ──→ DISCARDED         (pool discard)
```

| Status    | Description                                                                                                                                                                                                                                                                                                                                                                   |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AVAILABLE | In pool, never drawn: every draw can take it                                                                                                                                                                                                                                                                                                                                  |
| SEEN      | Drawn for a race that never started (rerolled or deleted in SETUP) or a restored report: its map may have been seen, so only normal races draw it again (see Draws)                                                                                                                                                                                                           |
| CONSUMED  | Assigned to a race, a Daily Seed or a Speedrun-mode solo run: never drawn again                                                                                                                                                                                                                                                                                               |
| REPORTED  | Reported as buggy on a reroll; an admin discards or restores it (`POST /api/admin/seeds/{id}/resolve`). Restoring makes it SEEN, never AVAILABLE (a training pool's seed goes back AVAILABLE): whoever reported it saw it. A restored seed may also have been played (a rerolled running daily, or a reset race reported on reroll): restore only seeds that were not played. |
| DISCARDED | Pool retired, seed no longer usable                                                                                                                                                                                                                                                                                                                                           |

### Rules

- **Assignment** (`assign_seed_to_race`): picks a random seed (AVAILABLE only, unless the caller allows SEEN ones: see Draws), marks it CONSUMED, sets `race.seed_id` and records whether the seed was SEEN (`race.seed_was_seen`; a reroll sets it the same way). A **normal race** allows SEEN seeds; a **Daily Seed** does not. A **speedrun race** draws through `draw_speedrun_seed` instead (AVAILABLE seeds only, refused at the pool's floor) and marks its seed CONSUMED; a **Set Seed race** takes a played seed and never changes its status (see Run mode).
- **Draws** (`get_available_seed`): AVAILABLE seeds only by default, so a caller that says nothing never gets a SEEN seed. With `allow_seen`, which only races that do not draw fresh seeds pass (the creation of a `normal` race, and the reroll of a race that `race_draws_fresh_seeds` leaves out: a `normal` race that is neither a Daily Seed nor an event race), SEEN seeds join the draw: while the pool has more AVAILABLE seeds than its speedrun floor (`Pool.speedrun_floor`, else `SPEEDRUN_DEFAULT_FLOOR`), one uniform draw over its SEEN and AVAILABLE seeds, so SEEN seeds leave the pool at their share of it instead of piling up for draws that never take them; at or under the floor, a random SEEN seed, else a random AVAILABLE seed from the reserve, so SEEN seeds spare the reserve that speedrun draws, Daily Seeds and event races need (a race whose rerolls already gave up every SEEN seed takes the reserve: its rerolls never come back to a seed it rejected). Speedrun races, Speedrun-mode solo runs, Daily Seeds and the rerolls of event races (`race_draws_fresh_seeds`) never draw a SEEN seed, and the floor counts AVAILABLE seeds only. A race that drew a SEEN seed (`Race.seed_was_seen`) counts on no board, even once attached to an event (`race_unranked_reason`), until a reroll gives it an AVAILABLE seed. Event races are created as normal races, so attaching one to its event (`POST /api/admin/races/{id}/event`) rerolls it when it is in SETUP on a SEEN seed whose seeds are not released yet (an event race's reroll draws AVAILABLE seeds only); a race whose seeds are out, or whose pool has no AVAILABLE seed left, keeps its seed, and the admin Races tab flags it. See "Ranked races" in `SPEEDRUN.md`.
- **Reroll** (`reroll_seed_for_race`): picks a new seed from the same pool, excluding the current seed ID and every seed the race's earlier rerolls gave up (`Race.rerolled_seed_ids`, which the old seed joins), as in Draws, so a race's rerolls never cycle back through the seeds it rejected and fail (400) once nothing else is left; a speedrun race draws through `draw_speedrun_seed`, so the floor applies to its rerolls too (409 "No fresh seed right now", the race keeps its seed). A Set Seed race is never rerolled (400 "A Set Seed race keeps its seed"). A reroll without a report (`reporter_id` None) that gives up a seed not SEEN when drawn (`seed_was_seen` false; a reset race's played seed included) sets `Race.rerolled_without_report`, which keeps a `normal` community race off the Speedrun boards; a speedrun race keeps counting, its reroll being a Random Seed reset (see "Which runs are counted" in `SPEEDRUN.md`).
- **Seen seeds** (every mode but Set Seed): the old seed of a reroll of a race still in SETUP becomes SEEN, its seeds released or not. Before the start, its organizer and registered runners (the race page shows them the map in SETUP) and anyone reading the race's live data (every `race_state` payload carries `graph_json`, whatever the status) may have seen its map, and a released pack may have been downloaded: such a seed must never reach a draw that counts on the boards. A report still makes it REPORTED; a DISCARDED seed stays DISCARDED. A played seed stays CONSUMED: a running Daily Seed's reroll keeps its old seed, and so does a reroll of a race reset back to SETUP (`Race.seed_played`, set by the reset, the only way back to SETUP after a start). The reroll clears `seed_played`, since the new seed was never played: that seed becomes SEEN on the next reroll. A **training pool**'s seed goes back AVAILABLE instead of SEEN: its seeds are shared practice seeds, which being seen does not spoil.
- **Deletion** (`DELETE /api/races/{id}`): the same rule: a SETUP race's unplayed seed becomes SEEN, released or not (AVAILABLE in a training pool; DISCARDED stays); a played seed stays CONSUMED, the seed of a RUNNING or FINISHED race and of a reset one (`seed_played`) alike. Deleting a Set Seed race never touches its seed (a played seed must not return to a pool for a future blind race).
- **Speedrun-mode solo** (`create_speedrun_session`): draws an AVAILABLE seed of the race pool above the pool's floor and marks it CONSUMED at creation; it is never released, even when the session is cancelled. **Set Seed solo** runs consume nothing and leave the seed's status alone. See `SPEEDRUN.md` ("Starting a ranked run").
- **Seed lookup**: a SEEN seed is a known seed (seed page, Set Seed) only once a race or a ranked session has played it, like any other seed; until then it answers "Unknown seed". See `SPEEDRUN.md`.
- **Pool discard** (`discard_pool`): marks every seed that is not DISCARDED yet (AVAILABLE, SEEN, CONSUMED, REPORTED) as DISCARDED in a single UPDATE. This prevents an in-progress race from putting a seed of a retired pool back in the draws via a reroll or a deletion.

---

## Training Session Status

```
ACTIVE ──→ FINISHED
  │
  └──→ ABANDONED
```

Simpler than race mode:

- `ACTIVE` on creation. `race_start` is sent immediately after `auth_ok` (no READY phase).
- `FINISHED` on `finish_event` flag detection.
- `ABANDONED` on explicit `POST /training/{id}/abandon` (`CANCELLED` without any progress), in one conditional update (`abandon_active_session`): a finish or an expiry committed after the request read the session stands, and the request answers 400 with that status.
- Seeds are **not** marked CONSUMED for training (practice) sessions; Speedrun-mode sessions do consume theirs (see Seed Status). A per-user exclusion list avoids replaying seeds; when all seeds have been used, the list resets.

---

## Leaderboard Sorting

Participants are sorted for display using a stable sort with composite key:

| Priority | Status         | Sort key                              |
| -------- | -------------- | ------------------------------------- |
| 0        | `finished`     | `igt_ms` ascending (fastest first)    |
| 1        | `playing`      | `-current_layer` then layer entry IGT |
| 2        | `ready`        | Arrival order preserved               |
| 3        | `registered`   | Arrival order preserved               |
| 4        | `abandoned`    | `-current_layer` then layer entry IGT |
| 5        | `disqualified` | Arrival order preserved               |

The layer entry IGT is the first arrival on `current_layer` (the deepest layer reached), so a DNF who played on there before abandoning keeps its place. See "Leaderboard Sorting" in `PROTOCOL.md`.

Arrival order is join order: the `Race.participants` relationship is ordered by `Participant.created_at`, then `color_index` (assigned max + 1 on join, the join order the cast overlays use) for rows sharing a timestamp, such as those backfilled when `created_at` was added. It also sets the order of the REST race detail's `participants`, which the race page's setup list renders as is.

---

## Broadcast Sequencing

### Race Start

1. `race_start` → mods
2. `zone_update` (start node) → each mod (unicast, localized)
3. `race_status_change(running)` → all (mods + spectators)
4. `race_state` → each spectator (unicast, per-connection graph gating)

### Race Finish (auto-finish, force-finish, abandon, or inactivity)

1. `race_state` → each spectator (with `status: finished` + full zone_history)
2. `race_status_change(finished)` → all
3. `leaderboard_update` → all
4. `fire_race_finished_notifications(race)`, fires on **all** finish paths:
   - Discord webhook (public normal races only, with podium; not for a Daily Seed, a speedrun or a Set Seed race)
   - speedrun record check (races that can count on the boards, see "Record announcements" in `SPEEDRUN.md`)
   - Discord scheduled event → COMPLETED (if event exists)
   - malenia calendar event → no transition (malenia has no active/completed status)

The ordering ensures spectators have full graph data before the status change UI update triggers.

### Race Reset

1. `close_room(code=1000)` → all WebSocket connections closed.
2. Status transition + ORM-loop reset of all participants.
3. Mods reconnect automatically and re-authenticate (receiving fresh `auth_ok`).
