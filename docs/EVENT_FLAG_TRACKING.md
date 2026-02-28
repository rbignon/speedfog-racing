# Event Flag Tracking & Zone Progression

How the mod detects fog gate traversals and boss kills via EMEVD event flags, and how the server resolves them into zone progression.

## Overview

The mod reads event flags from Elden Ring's memory at 10Hz. When a flag is detected:

- **Fog gate flags** are deferred until the loading screen exits.
- **Boss kill (finish_event)** is sent immediately (no loading screen on boss kill).

The server maps `flag_id` → `node_id` via the seed's `event_map`, updates progression, and broadcasts leaderboard/zone updates.

## Mod-Side: Event Flag Polling

### VirtualMemoryFlag Memory Layout

The game stores EMEVD event flags in a sparse `std::map<category, page>` (MSVC red-black tree). Each category covers `divisor` flags (typically 1000).

**Tree node layout** (each 0x38+ bytes):

| Offset | Type   | Field                                             |
| ------ | ------ | ------------------------------------------------- |
| +0x00  | usize  | Left child pointer                                |
| +0x08  | usize  | Parent/first-child pointer (used from root)       |
| +0x10  | usize  | Right child pointer                               |
| +0x19  | u8     | Sentinel byte (0=real node, non-0=sentinel/null)  |
| +0x20  | i32    | Category key (flag_id / divisor)                  |
| +0x28  | i32    | Address mode (1=formula, 2=absent, >2=direct ptr) |
| +0x30  | varies | Multiplier (mode 1) or data pointer (mode >2)     |

**`find_category_page()`**: Traverses from `manager + 0x38` (root), starting at `root[+0x08]`. Standard BST search with max 64 iterations and sentinel detection. Tracks the last candidate node where traversal went left. After traversal, verifies the candidate key matches. Resolves the data address by mode:

- Mode 1: formula `(manager[0x20] * node[0x30]) + manager[0x28]`
- Mode 2: flag doesn't exist → `None`
- Mode >2: direct pointer at `node[0x30]`

**`is_flag_set()`**: Calls `find_category_page()`, then reads bit `7 - (remainder & 7)` of byte `remainder >> 3` in the category page. Returns `Option<bool>`: `None` on memory read failure (loading screens), `Some(false)` or `Some(true)`.

### Category 1040292

FogRando pre-allocates category 1040292 at runtime. SpeedFog Racing uses offsets 800-999 within this category; FogRando uses ~100-299. Category 9000 (originally planned) does NOT exist in a typical game — `SetEventFlag` to category 9000 is a silent no-op.

The `EVENT_FLAG_BASE` in `../speedfog/speedfog/output.py` is `1040292800`, giving flag IDs `1040292800` through `1040292999`.

### Polling Loop

Every 100ms (`POLL_INTERVAL = 100ms`), the tracker iterates all `event_ids` received from `auth_ok`:

```
for each flag_id in event_ids:
    if flag_id in triggered_flags: skip
    if is_flag_set(flag_id) == Some(true):
        triggered_flags.insert(flag_id)
        if flag_id == finish_event:
            → send immediately (or buffer if disconnected)
        else:
            → push to deferred_event_flags
```

**`triggered_flags` (HashSet)**: Ensures each flag is detected and sent exactly once per session. Never cleared — even on reconnect. Pending retransmission uses `pending_event_flags` instead.

**Polling runs always**: Even when disconnected or race not running. Flags are transient in game memory (~seconds), so detection must be immediate.

### Deferred vs Immediate Flags

| Flag type      | Sent when                | Why                              |
| -------------- | ------------------------ | -------------------------------- |
| Fog gate flags | Loading screen exit      | Loading screen = zone transition |
| `finish_event` | Immediately on detection | No loading screen on boss kills  |

Fog gate traversal triggers a loading screen. The flag is detected during polling but stored in `deferred_event_flags`. At loading screen exit, all deferred flags are sent.

### Loading Screen Detection

The mod reads `game_state.read_position()` every frame:

- `Some(pos)` → position readable → not loading
- `None` → position unreadable → loading screen

The loading screen exit is detected by `position_readable && !was_position_readable`.

### Loading Screen Exit Actions

At the `position_readable` rising edge:

1. **Forced rescan**: Immediately re-reads all `event_ids` to catch flags set during loading (e.g., Erdtree burn, Maliketh warp cutscene). Newly detected regular flags go to `deferred_event_flags`. A `finish_event` caught here is sent **immediately** if connected (no deferral — boss kills have no loading screen, but edge cases like Maliketh's cutscene can trigger both a flag and a loading screen).

2. **Deferred flags exist** → send all deferred `event_flag` messages to server.

3. **No deferred flags** → this is a death/respawn/quit-out/fast-travel:
   - Capture grace entity ID from warp hook (fast travel only).
   - Send `zone_query { grace_entity_id, map_id, position, play_region_id }`.
   - Clear captured grace entity ID.

### Zone Reveal Delay

Separate from the loading exit event dispatch above, zone reveal has its own logic:

When the server sends a `zone_update`, the mod stores it in `pending_zone_update`. Each frame, if `pending_zone_update` is set:

- If position is **not** readable → reset `loading_exit_time` to None (still loading).
- If position **is** readable → set `loading_exit_time` if not already set, then check if `ZONE_REVEAL_DELAY = 2s` has elapsed.
- Once 2s have elapsed → move `pending_zone_update` to `current_zone` (displayed on overlay).

This covers the fade-in / spawn animation so the overlay doesn't update while the screen is still black. Last-writer-wins: if two flags fire in rapid succession, only the last `zone_update` is shown.

---

## Server-Side: Event Flag Resolution

### `handle_event_flag()` (`websocket/mod.py`)

```
receive event_flag { flag_id, igt_ms }
    │
    ├── flag_id == finish_event?
    │       ├── yes → update igt_ms + current_layer=total_layers, commit
    │       │         exit session, call handle_finished() in new session
    │       │
    │       └── no → look up event_map[str(flag_id)] → node_id
    │                  │
    │                  ├── not found → warn + return
    │                  │
    │                  ├── node_id in zone_history? (revisit)
    │                  │       → update current_zone + igt_ms only
    │                  │       → unicast zone_update to mod
    │                  │       → broadcast player_update to spectators
    │                  │
    │                  └── new discovery
    │                          → append to zone_history
    │                          → update current_layer (high watermark, never regress)
    │                          → broadcast leaderboard_update to all
    │                          → unicast zone_update to mod
```

### Zone Query Resolution (`grace_service.py`)

Three-strategy cascade for resolving where the player is after a death/fast-travel:

**Strategy 1 — Grace lookup** (highest confidence):
`grace_entity_id` → `graces.json` mapping → `zone_id` → find graph node with matching `zones` array.

**Strategy 2 — Map-based lookup** (fallback):

1. `map_id` → `fog.txt` (complete map→zone mapping) → candidate `zone_ids`.
2. If position available, `submaps.txt` narrows to one zone_id.
3. Find graph nodes whose `zones` array intersects candidates.
4. If still ambiguous, filter by `zone_history` (player can only be in an already-explored node — zone_query is never sent on fog gate traversal).

**Strategy 3 — None**: Ambiguous or no data. No `zone_update` sent — overlay stays on previous zone.

Zone queries do **not** modify `zone_history` (progression). They only update `current_zone` (overlay display pointer) and trigger `player_update` for spectators.

### Grace Entity ID Capture

A warp hook (inline detour on `lua_warp`) captures the grace entity ID when the player fast-travels. The entity ID is stored in a global atomic and consumed at loading exit. This is needed because the entity ID is only available at the moment of the warp call — by the time the loading screen exits, the game has already moved past the warp context.

---

## Gap Timing

LiveSplit-style gap computation. The gap is fixed (entry delta) while the player is within the leader's time budget on a layer, then grows in real-time once exceeded. Negative gaps (player ahead of leader's pace) are supported.

### Leader Splits

`build_leader_splits(zone_history, graph_json)` walks the leader's `zone_history` and builds `{layer: first_igt_at_layer}`. Skips entries whose `node_id` is not in the graph. Deduplicates by taking the first IGT at each layer.

### Layer Entry IGT

`get_layer_entry_igt(zone_history, current_layer, graph_json)` finds the player's IGT when they first entered their current layer. Sent as `layer_entry_igt` in `ParticipantInfo`.

### Server-Side Gap Computation

`compute_gap_ms(status, igt_ms, current_layer, player_layer_entry_igt, leader_splits, leader_igt_ms, is_leader)`:

| Condition                                         | Result                                          |
| ------------------------------------------------- | ----------------------------------------------- |
| Is leader                                         | `None`                                          |
| Status = `finished`                               | `igt_ms - leader_igt_ms` (direct delta)         |
| Status = `playing`, within leader's time budget   | `player_layer_entry_igt - leader_splits[layer]` |
| Status = `playing`, exceeded leader's time budget | `igt_ms - leader_splits[layer + 1]`             |
| Status = `playing`, leader still on same layer    | `player_layer_entry_igt - leader_splits[layer]` |
| Status = `playing`, no split for layer            | `None`                                          |
| Other statuses                                    | `None`                                          |

"Within budget" means `igt_ms <= leader_splits[current_layer + 1]` — the player hasn't used more time on this layer than the leader did.

### Client-Side Gap Computation (Mod)

The mod ignores `gap_ms` and recomputes gaps locally each frame using the same formula with `leader_splits` + `layer_entry_igt` from `leaderboard_update`. For the local player, the mod substitutes the real-time local IGT (read from game memory) instead of the server's `igt_ms`, producing frame-rate gap updates.

Gaps are color-coded: green for negative (ahead), soft red for positive (behind).

`broadcast_player_update()` intentionally omits `gap_ms` (computing it requires the full sorted participant list).

---

## Constants Summary

| Constant               | Value      | Location                | Purpose                                      |
| ---------------------- | ---------- | ----------------------- | -------------------------------------------- |
| Poll interval          | 100ms      | `tracker.rs`            | Event flag read frequency                    |
| `ZONE_REVEAL_DELAY`    | 2s         | `tracker.rs`            | Delay before showing zone after loading      |
| `EVENT_FLAG_BASE`      | 1040292800 | `output.py`             | First SpeedFog event flag ID                 |
| Flag range             | 800-999    | category 1040292        | Our offset range within FogRando's cat       |
| Divisor                | 1000       | game memory             | Flags per category page                      |
| Max tree iterations    | 64         | `event_flags.rs`        | Guard against infinite tree traversal        |
| Status update interval | 1s         | `tracker.rs`            | Throttle for IGT/death broadcasts            |
| Inactivity timeout     | 15min      | `inactivity_monitor.py` | Auto-abandon threshold (stale IGT + no-show) |
| Inactivity poll        | 60s        | `inactivity_monitor.py` | Monitor check frequency                      |
