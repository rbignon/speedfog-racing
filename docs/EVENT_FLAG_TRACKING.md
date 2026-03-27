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

FogRando pre-allocates category 1040292 at runtime. SpeedFog Racing uses offsets 800-999 within this category; FogRando uses ~100-299. Category 9000 (originally planned) does NOT exist in a typical game. `SetEventFlag` to category 9000 is a silent no-op.

The `EVENT_FLAG_BASE` in `../speedfog/speedfog/output.py` is `1040292800`, giving flag IDs `1040292800` through `1040292999`.

### Polling Loop

Every 100ms (`POLL_INTERVAL = 100ms`), the tracker iterates all `event_ids` received from `auth_ok`:

```
for each flag_id in event_ids:
    if flag_id == finish_event:
        if flag_id in triggered_flags: skip
        if is_flag_set(flag_id) == Some(true):
            triggered_flags.insert(flag_id)
            → send immediately (or buffer if disconnected)
    else:
        if is_flag_set(flag_id) == Some(true):
            set_flag(flag_id, false)   // clear for re-traversal detection
            → push to deferred_event_flags
```

**`finish_event` is one-shot**: Uses `triggered_flags` (HashSet), so the player can only finish once. Never cleared, even on reconnect.

**Regular fog gate flags are repeatable**: After capture, the flag is cleared in game memory (`set_flag(false)`) so the EMEVD script can re-set it on the next fog gate traversal. This enables backtrack detection: re-traversing an already-visited fog gate produces a new `event_flag` message.

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

1. **Forced rescan**: Immediately re-reads all `event_ids` to catch flags set during loading (e.g., Erdtree burn, Maliketh warp cutscene). Newly detected regular flags are cleared in game memory and added to `deferred_event_flags`. A `finish_event` caught here is sent **immediately** if connected (no deferral, since boss kills have no loading screen, but edge cases like Maliketh's cutscene can trigger both a flag and a loading screen).

2. **Deferred flags exist** → send all deferred `event_flag` messages to server.

3. **No deferred flags** → this is a death/respawn/quit-out/fast-travel:
   - Capture grace entity ID from warp hook (fast travel only).
   - Send `zone_query { grace_entity_id, map_id, position, play_region_id }`.
   - Clear captured grace entity ID.

### Zone Reveal Timing

Separate from the loading exit event dispatch above, zone reveal has its own logic:

When the server sends a `zone_update`, the mod stores it in `pending_zone_update`. Each frame, if `pending_zone_update` is set:

- Read the loading screen flag at `[[EventFlagMan]+0x28]+0x113` (byte, non-zero = in loading/cutscene).
- If `Some(false)` (loading done) → move `pending_zone_update` to `current_zone` (displayed on overlay).
- If `Some(true)` (still loading) → wait.
- If `None` (pointer unreadable) → fall back to position readability (`read_position().is_some()`).
- If `ZONE_REVEAL_TIMEOUT = 15s` has elapsed since the zone_update was received → reveal anyway (defensive).

The overlay keeps showing the old zone until the reveal. A `pre_reveal_layer` snapshot freezes the X/Y counter and tier display so they don't leak the new layer before the zone name updates. Last-writer-wins: if two flags fire in rapid succession, only the last `zone_update` is shown.

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
    │                  │       → append to zone_history (with current igt_ms)
    │                  │       → update current_zone + igt_ms
    │                  │       → current_layer unchanged (high watermark)
    │                  │       → unicast zone_update to mod
    │                  │       → broadcast player_update to all
    │                  │
    │                  └── new discovery (first visit)
    │                          → append to zone_history
    │                          → update current_layer (high watermark, never regress)
    │                          → broadcast leaderboard_update to all
    │                          → unicast zone_update to mod
```

### Zone Query Resolution (`grace_service.py`)

Three-strategy cascade for resolving where the player is after a death/fast-travel:

**Strategy 1, Grace lookup** (highest confidence):
`grace_entity_id` → `graces.json` mapping → `zone_id` → find graph node with matching `zones` array.

**Strategy 2, Map-based lookup** (fallback):

1. `map_id` → `fog.txt` (complete map→zone mapping) → candidate `zone_ids`.
2. If position available **and** `grace_entity_id` is present (fast travel context), use `submaps.txt` to narrow to one zone_id. Position is skipped for death/respawn because it reflects the respawn point (grace/stake), not where the player was fighting.
3. Find graph nodes whose `zones` array intersects candidates.
4. If still ambiguous, filter by `zone_history` (player can only be in an already-explored node).
5. If still ambiguous and no `grace_entity_id` (death/remembrance context), pick the most recently visited node from `zone_history`.

**Strategy 3, None**: Ambiguous or no data (including fast travel with failed grace lookup, as guessing would pollute the MetroDag). No `zone_update` sent; overlay stays on previous zone.

Zone queries do **not** modify `zone_history` (progression). They only update `current_zone` (overlay display pointer) and trigger `player_update` for all connections (mods + spectators).

### Grace Entity ID Capture

A warp hook (inline detour on `lua_warp`) captures the grace entity ID when the player fast-travels. The entity ID is stored in a global atomic and consumed at loading exit. This is needed because the entity ID is only available at the moment of the warp call. By the time the loading screen exits, the game has already moved past the warp context.

---

## Gap Timing

LiveSplit-style gap computation. The gap is fixed (entry delta) while the player is within the leader's time budget on a layer, then grows in real-time once exceeded. Negative gaps (player ahead of leader's pace) are supported.

### Leader Splits

`build_leader_splits(zone_history, graph_json)` walks the leader's `zone_history` and builds `{layer: first_igt_at_layer}`. Skips entries whose `node_id` is not in the graph. Deduplicates by taking the first IGT at each layer.

### Layer Entry IGT

`get_layer_entry_igt(zone_history, current_layer, graph_json)` finds the player's IGT when they first entered their current layer. Sent as `layer_entry_igt` in `ParticipantInfo`.

### Server-Side Gap Computation

`compute_gap_ms(status, igt_ms, current_layer, player_layer_entry_igt, leader_splits, leader_igt_ms, is_leader, leader_finished)`:

| Condition                                                  | Result                                                 |
| ---------------------------------------------------------- | ------------------------------------------------------ |
| Is leader                                                  | `None`                                                 |
| Status = `finished`                                        | `igt_ms - leader_igt_ms` (direct delta)                |
| Status = `playing`, within leader's time budget            | `player_layer_entry_igt - leader_splits[layer]`        |
| Status = `playing`, exceeded leader's time budget          | `igt_ms - leader_splits[layer + 1]`                    |
| Status = `playing`, last layer, leader finished, in budget | `player_layer_entry_igt - leader_splits[layer]`        |
| Status = `playing`, last layer, leader finished, exceeded  | entry delta + overshoot (uses `leader_igt_ms` as exit) |
| Status = `playing`, leader still on same layer             | `player_layer_entry_igt - leader_splits[layer]`        |
| Status = `playing`, no split for layer                     | `None`                                                 |
| Other statuses                                             | `None`                                                 |

"Within budget" means the player's time in the layer hasn't exceeded the leader's time in the same layer. On the last layer, when the leader has finished, `leader_igt_ms` is used as the leader's exit time (since no `leader_splits[layer + 1]` exists).

### Leaderboard Sorting

Players on the same layer are sorted by layer entry IGT (who arrived first), not total IGT. This ensures the true leader on a layer is the one who reached it first, regardless of their current total IGT. When `graph_json` is not available, the sort falls back to total IGT.

### Client-Side Gap Computation (Mod)

For playing players during a running race, the mod recomputes gaps locally each frame using the same formula with `leader_splits` + `layer_entry_igt` from `leaderboard_update` and `player_update` messages. For the local player, the mod substitutes the real-time local IGT (read from game memory) instead of the server's `igt_ms`. For other players, the mod uses their server-provided `igt_ms` directly; gaps step in discrete increments aligned with the server's `player_update` cadence (~1s).

When a player finishes or the race ends, the mod uses the server-computed `gap_ms` (frozen at the time of the last leaderboard update) instead of recomputing client-side. This prevents gap drift from game memory IGT continuing to tick after finish.

Gaps are color-coded: green for negative (ahead), soft red for positive (behind).

`broadcast_player_update()` omits `gap_ms` (computing it requires the full sorted participant list) but includes `layer_entry_igt` so mods can compute gaps client-side.

---

## Constants Summary

| Constant               | Value      | Location                | Purpose                                      |
| ---------------------- | ---------- | ----------------------- | -------------------------------------------- |
| Poll interval          | 100ms      | `tracker.rs`            | Event flag read frequency                    |
| `ZONE_REVEAL_TIMEOUT`  | 15s        | `tracker.rs`            | Defensive timeout for zone reveal            |
| `EVENT_FLAG_BASE`      | 1040292800 | `output.py`             | First SpeedFog event flag ID                 |
| Flag range             | 800-999    | category 1040292        | Our offset range within FogRando's cat       |
| Divisor                | 1000       | game memory             | Flags per category page                      |
| Max tree iterations    | 64         | `event_flags.rs`        | Guard against infinite tree traversal        |
| Status update interval | 1s         | `tracker.rs`            | Throttle for IGT/death broadcasts            |
| Inactivity timeout     | 15min      | `inactivity_monitor.py` | Auto-abandon threshold (stale IGT + no-show) |
| Inactivity poll        | 60s        | `inactivity_monitor.py` | Monitor check frequency                      |
