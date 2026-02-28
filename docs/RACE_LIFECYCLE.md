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
- Discord notification: `notify_race_started()` + event status set to ACTIVE.

**RUNNING → FINISHED** (three paths)

1. **Auto-finish**: when all participants reach `FINISHED` or `ABANDONED`, `check_race_auto_finish()` transitions the race. Uses optimistic locking (see below).
2. **Force-finish**: `POST /races/{id}/finish` (organizer). Same optimistic lock mechanism.
3. **Inactivity monitor**: when the last active participant is auto-abandoned (15 min stale IGT or no-show), the monitor calls `check_race_auto_finish()`.

**RUNNING or FINISHED → SETUP** (`POST /races/{id}/reset`, organizer only)

- Closes all WebSocket connections first (`manager.close_room(code=1000)`).
- Transitions status via `_transition_status()` with optimistic lock. Clears `started_at` (but NOT `seeds_released_at` — seed packs remain downloadable).
- Resets all participants via ORM loop: `status=REGISTERED, current_zone=None, current_layer=0, igt_ms=0, death_count=0, zone_history=None, finished_at=None`.
- Mod clients detect the close and reconnect automatically.

### Optimistic Locking

Every Race has a `version` column (integer, starts at 1). All status transitions use:

```sql
UPDATE races
SET status = :new, version = version + 1
WHERE id = :id AND status IN (:allowed) AND version = :v
```

If `rowcount == 0`, the transition was lost to a concurrent update → HTTP 409 or silent no-op (for auto-finish). This prevents duplicate finish broadcasts when two participants finish simultaneously.

---

## Participant Status

```
REGISTERED ──→ READY ──→ PLAYING ──→ FINISHED
     │           │          │
     └───────────┴──────────┴──→ ABANDONED
```

| Status     | Description                                               |
| ---------- | --------------------------------------------------------- |
| REGISTERED | Signed up for the race                                    |
| READY      | Mod connected and ready signal sent                       |
| PLAYING    | Currently racing (IGT ticking)                            |
| FINISHED   | Completed the race (boss kill)                            |
| ABANDONED  | Left the race (inactivity, no-show, or voluntary abandon) |

### Transitions

**REGISTERED → READY** — mod sends `ready` WS message. Broadcasts `leaderboard_update`.

**READY → PLAYING** — auto-triggered on the first `status_update` while the race is RUNNING. On transition:

- Sets `current_zone` to the start node.
- Appends start node to `zone_history` with `igt_ms=0`.
- `current_layer` remains 0 (start node is layer 0).
- Broadcasts full `leaderboard_update`.

**PLAYING → FINISHED** — `event_flag` message with `flag_id == finish_event`. On transition:

- Sets `current_layer = total_layers` (progress shows N/N).
- Sets `finished_at` to current time.
- Calls `check_race_auto_finish()` for the race.
- Implementation note: the finish handler uses two separate DB sessions to avoid nested-session deadlocks in SQLite tests. The `event_flag` handler commits progress, exits its session, then calls `handle_finished()` in a new session.

**REGISTERED / READY / PLAYING → ABANDONED** — three paths:

1. **Inactivity monitor** (PLAYING): background loop checks every 60s for participants with `last_igt_change_at < now - 15min`. Marks them `ABANDONED` and triggers auto-finish check.
2. **No-show monitor** (REGISTERED/READY): same loop also catches participants who never started playing when `race.started_at < now - 15min`. Marks them `ABANDONED`.
3. **Voluntary abandon**: `POST /races/{id}/abandon` (participant). Accepts REGISTERED, READY, or PLAYING status. Triggers auto-finish check.

### Terminal States

`FINISHED` and `ABANDONED` are terminal. Once a participant reaches either state:

- All incoming `status_update`, `event_flag`, `zone_query`, and `finished` messages are silently dropped.
- The server does not update `igt_ms` or `death_count` — data is frozen.

### Progress Tracking

**`current_layer`** is a **high watermark** — it tracks the furthest layer reached and never regresses, even if the player backtracks to an earlier zone. This ensures leaderboard stability.

**`zone_history`** is a JSON array of `{"node_id": str, "igt_ms": int, "deaths"?: int}` entries. A new entry is appended on every zone transition, including backtracks (the same `node_id` may appear multiple times). The `deaths` key is added/incremented by `status_update` when the death count increases — deaths are attributed to the **most recent** entry matching the player's current zone. Frontend consumers (popup, highlights, replay) aggregate time and deaths across all visits to the same node.

**`last_igt_change_at`** is updated on every `status_update` where `igt_ms` differs from the stored value. Used by the inactivity monitor. A quit-out (IGT=0) does not reset it since IGT doesn't change — it just becomes 0.

---

## Seed Status

```
AVAILABLE ──→ CONSUMED ──→ AVAILABLE  (reroll)
    │              │
    └──→ DISCARDED ←┘  (pool discard)
```

| Status    | Description                         |
| --------- | ----------------------------------- |
| AVAILABLE | In pool, ready for assignment       |
| CONSUMED  | Assigned to a race                  |
| DISCARDED | Pool retired, seed no longer usable |

### Rules

- **Assignment** (`assign_seed_to_race`): picks a random AVAILABLE seed, marks it CONSUMED, sets `race.seed_id`.
- **Reroll** (`reroll_seed_for_race`): releases old seed back to AVAILABLE (unless DISCARDED), picks a new one. Excludes the current seed ID.
- **Pool discard** (`discard_pool`): marks both AVAILABLE and CONSUMED seeds as DISCARDED in a single UPDATE. This prevents an in-progress race from releasing a seed back into a retired pool via reroll.

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
- `ABANDONED` on explicit `POST /training/{id}/abandon`.
- Seeds are **not** marked CONSUMED for training. A per-user exclusion list avoids replaying seeds; when all seeds have been used, the list resets.

---

## Leaderboard Sorting

Participants are sorted for display using a stable sort with composite key:

| Priority | Status       | Sort key                           |
| -------- | ------------ | ---------------------------------- |
| 0        | `finished`   | `igt_ms` ascending (fastest first) |
| 1        | `playing`    | `-current_layer` then `igt_ms`     |
| 2        | `ready`      | Arrival order preserved            |
| 3        | `registered` | Arrival order preserved            |
| 4        | `abandoned`  | `-current_layer` then `igt_ms`     |

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
4. `fire_race_finished_notifications(race)` — fires on **all** finish paths:
   - Discord webhook (public races only, with podium)
   - Discord scheduled event → COMPLETED (if event exists)

The ordering ensures spectators have full graph data before the status change UI update triggers.

### Race Reset

1. `close_room(code=1000)` → all WebSocket connections closed.
2. Status transition + ORM-loop reset of all participants.
3. Mods reconnect automatically and re-authenticate (receiving fresh `auth_ok`).
