# Race State Gating — Design

**Date:** 2026-02-15
**Status:** Approved

## Problem

1. The mod overlay shows race status as `[OPEN]`/`[RUNNING]` in the header — subtle and easy to miss.
2. The mod sends `status_update`, `event_flag`, and `finished` messages regardless of race state.
3. The server accepts and persists all gameplay messages even when the race is not RUNNING.
4. A player who starts playing before `race_start` has their data silently accepted — a bug.

## Design

### 1. Mod Overlay — State Banner (ui.rs)

Remove `[status]` from the header. Add a colored banner above the player status line:

| Race State          | Banner Text         | Color                     |
| ------------------- | ------------------- | ------------------------- |
| DRAFT / OPEN        | `WAITING FOR START` | Orange `[1.0, 0.75, 0.0]` |
| RUNNING (first ~3s) | `GO!`               | Green `[0.5, 1.0, 0.5]`   |
| RUNNING (after 3s)  | _(none)_            | —                         |
| FINISHED            | `RACE FINISHED`     | Green `[0.5, 1.0, 0.5]`   |

Implementation:

- Store `race_started_at: Option<Instant>` — set when `RaceStart` is received.
- In `render()`, before `render_player_status()`, check race status and elapsed time since start.
- Remove `format!("{} [{}]", display_name, race.status)` → just `display_name`.

### 2. Mod Gating — Skip Sends Pre-Race (tracker.rs)

Add `is_race_running()` helper that checks `race_state.race.status == "running"`.

Gate the following on `is_race_running()`:

- `send_status_update` — skip entirely if not running.
- `send_event_flag` — buffer into `pending_event_flags` instead of sending (flags are ephemeral in game memory, must still be detected immediately).
- Drain of `pending_event_flags` on reconnect — wait until race is running.
- Rescan of flags on reconnect — same condition.
- `send_ready` — unchanged, normal during OPEN.

No IGT/death reset at race start: the player who starts early penalizes themselves naturally (IGT ticking, deaths counting). This is fair and avoids complexity of game memory writes or offset tracking.

### 3. Server Guard — Reject Pre-Race Messages (mod.py)

Defense in depth: even with mod-side gating, the server validates.

Add a guard at the top of each handler:

- `handle_status_update()` — if `race.status != RUNNING`: log warning, send `{"type": "error", "message": "race not running"}`, return.
- `handle_event_flag()` — same.
- `handle_finished()` — same.
- `handle_ready()` — no guard (ready is expected during OPEN).

Reuses existing `error` message type — no protocol changes needed.

### 4. Web Frontend — Ephemeral "GO!" Banner (+page.svelte)

Add a green "GO!" banner that appears for 3 seconds when the race transitions to RUNNING:

- Detect `raceStatus` transition to `running` via `$effect`.
- Show `<div class="go-banner">GO!</div>` above the DAG block, centered.
- Fade out after 3 seconds via CSS opacity transition + `setTimeout`.
- No changes for OPEN state (layout change is already dramatic).
- No changes for FINISHED state (podium appearance is sufficient feedback).

### 5. Tests

Add integration test: connect a mod WS client, send `status_update` while race is OPEN, verify server responds with error and does not persist the data.

## Non-Changes

- **Protocol**: No new message types. Reuse existing `error` type.
- **Database schema**: No changes.
- **Data reset on start**: Not needed — server rejects pre-race messages, and early starters penalize themselves.
