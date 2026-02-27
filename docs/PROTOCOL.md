# SpeedFog Racing - Protocol Reference

Reference document for API endpoints and WebSocket messages.

## REST API

### System

| Method | Endpoint  | Auth | Description                          |
| ------ | --------- | ---- | ------------------------------------ |
| GET    | `/health` | -    | Health check (`{ status, version }`) |

### Authentication

| Method | Endpoint             | Auth   | Description                                         |
| ------ | -------------------- | ------ | --------------------------------------------------- |
| GET    | `/api/auth/twitch`   | -      | Redirect to Twitch OAuth (`?redirect_url`)          |
| GET    | `/api/auth/callback` | -      | OAuth callback, redirects with `?code=` (ephemeral) |
| POST   | `/api/auth/exchange` | -      | Exchange auth code for API token                    |
| GET    | `/api/auth/me`       | Bearer | Get current user info (public, no `api_token`)      |
| POST   | `/api/auth/logout`   | Bearer | Regenerate API token (invalidates session)          |

### Races

| Method | Endpoint                               | Auth   | Description                                              |
| ------ | -------------------------------------- | ------ | -------------------------------------------------------- |
| GET    | `/api/races`                           | -      | List races (`?status=setup,running,...`)                 |
| POST   | `/api/races`                           | Bearer | Create race (status: SETUP)                              |
| GET    | `/api/races/{id}`                      | -      | Race details with participants and casters               |
| PATCH  | `/api/races/{id}`                      | Bearer | Update race settings (organizer, SETUP only)             |
| POST   | `/api/races/{id}/participants`         | Bearer | Add participant (organizer only)                         |
| DELETE | `/api/races/{id}/participants/{pid}`   | Bearer | Remove participant (organizer, SETUP only)               |
| POST   | `/api/races/{id}/casters`              | Bearer | Add caster (organizer only)                              |
| DELETE | `/api/races/{id}/casters/{cid}`        | Bearer | Remove caster (organizer only)                           |
| DELETE | `/api/races/{id}/invites/{invite_id}`  | Bearer | Revoke invite (organizer, SETUP only)                    |
| POST   | `/api/races/{id}/join`                 | Bearer | Self-join open-registration race (SETUP only)            |
| POST   | `/api/races/{id}/leave`                | Bearer | Leave race (SETUP only)                                  |
| POST   | `/api/races/{id}/release-seeds`        | Bearer | Release seeds for download (organizer, SETUP)            |
| POST   | `/api/races/{id}/reroll-seed`          | Bearer | Reroll the seed (organizer, SETUP, seeds not released)   |
| POST   | `/api/races/{id}/start`                | Bearer | Start race: SETUP → RUNNING (organizer)                  |
| POST   | `/api/races/{id}/reset`                | Bearer | Reset race: RUNNING → SETUP (organizer)                  |
| POST   | `/api/races/{id}/finish`               | Bearer | Force-finish race: RUNNING → FINISHED (organizer)        |
| DELETE | `/api/races/{id}`                      | Bearer | Delete race (organizer, SETUP only)                      |
| GET    | `/api/races/{id}/my-seed-pack`         | Bearer | Download own seed pack (requires seeds released)         |
| GET    | `/api/races/{id}/download/{mod_token}` | Bearer | Download participant seed pack (requires seeds released) |

### Pools

| Method | Endpoint              | Auth | Description                                                                                              |
| ------ | --------------------- | ---- | -------------------------------------------------------------------------------------------------------- |
| GET    | `/api/pools`          | -    | Pool stats with TOML metadata (`{ [name]: { available, consumed, estimated_duration?, description? } }`) |
| GET    | `/api/pools?type=...` | -    | Filter pools by type (e.g. `?type=training`)                                                             |

### Users

| Method | Endpoint                         | Auth   | Description                                             |
| ------ | -------------------------------- | ------ | ------------------------------------------------------- |
| GET    | `/api/users/search`              | Bearer | Search users by username or display name prefix (`?q=`) |
| GET    | `/api/users/me`                  | Bearer | Get user profile                                        |
| PATCH  | `/api/users/me/locale`           | Bearer | Update locale preference                                |
| PATCH  | `/api/users/me/settings`         | Bearer | Update overlay settings (e.g. `font_size`)              |
| GET    | `/api/users/me/races`            | Bearer | Races where user is organizer or participant            |
| GET    | `/api/users/{username}`          | -      | Public user profile                                     |
| GET    | `/api/users/{username}/activity` | -      | User activity timeline                                  |

### Invites

| Method | Endpoint                     | Auth   | Description     |
| ------ | ---------------------------- | ------ | --------------- |
| GET    | `/api/invite/{token}`        | -      | Get invite info |
| POST   | `/api/invite/{token}/accept` | Bearer | Accept invite   |

### i18n

| Method | Endpoint            | Auth | Description            |
| ------ | ------------------- | ---- | ---------------------- |
| GET    | `/api/i18n/locales` | -    | List available locales |

### Admin

| Method | Endpoint                     | Auth           | Description                         |
| ------ | ---------------------------- | -------------- | ----------------------------------- |
| POST   | `/api/admin/seeds/scan`      | Bearer (admin) | Rescan seed pool (`{ pool_name? }`) |
| GET    | `/api/admin/seeds/stats`     | Bearer (admin) | Pool statistics                     |
| POST   | `/api/admin/seeds/discard`   | Bearer (admin) | Discard seeds from pool             |
| GET    | `/api/admin/users`           | Bearer (admin) | List all users                      |
| PATCH  | `/api/admin/users/{user_id}` | Bearer (admin) | Update user role                    |
| GET    | `/api/admin/activity`        | Bearer (admin) | Admin activity timeline             |

---

## WebSocket: Mod Connection

**Endpoint:** `WS /ws/mod/{race_id}`

### Connection Lifecycle

```
CONNECT
  ↓
[AUTH PHASE: 5s timeout for auth message]
  ↓ auth_ok
REGISTER in room → broadcast leaderboard_update
  ↓
[HEARTBEAT: server sends ping every 30s]
[MESSAGE LOOP: process incoming messages]
  ↓ disconnect
UNREGISTER → broadcast leaderboard_update
```

### Client → Server

#### `auth`

First message after connection. Authenticates the mod. Must arrive within 5 seconds or the connection is closed (code 4001).

```json
{
  "type": "auth",
  "mod_token": "player_specific_token"
}
```

#### `ready`

Player is in-game and ready to race. Transitions status from `registered` → `ready`.

```json
{
  "type": "ready"
}
```

#### `status_update`

Periodic update (every ~1 second). Also auto-transitions `ready` → `playing` if race is running. Rejected with `error` if race is not running (see [Race State Gating](#race-state-gating)).

```json
{
  "type": "status_update",
  "igt_ms": 123456,
  "death_count": 5
}
```

#### `event_flag`

Sent when the mod detects an event flag transition (0 → 1). The server resolves it to a DAG node via the seed's `event_map`. If the flag matches `finish_event`, the player is auto-finished. Rejected with `error` if race is not running (see [Race State Gating](#race-state-gating)).

**Revisited nodes:** Multiple flags can map to the same DAG node (e.g., shared entrance merges where several branches connect to a single cluster). If the resolved node is already in `zone_history`, the server updates `current_zone` and sends a `zone_update` (same as `zone_query`) but does **not** add a duplicate entry to `zone_history` or broadcast a `leaderboard_update`.

**Timing:** Regular event flags (fog gate traversals) are detected immediately by polling but deferred until loading screen exit. This ensures spectators see progress updates in sync with the player's arrival, and prevents zone name spoilers during loading screens. The `finish_event` (boss kill) is an exception — it is sent immediately since boss kills don't trigger a loading screen.

```json
{
  "type": "event_flag",
  "flag_id": 1040292842,
  "igt_ms": 4532100
}
```

#### `zone_query`

Sent at loading screen exit when no event_flag was detected (death, respawn, fast travel, quit-out). All fields are optional — the server tries grace lookup first, then falls back to map_id-based resolution.

```json
{
  "type": "zone_query",
  "grace_entity_id": 10002950,
  "map_id": "m10_00_00_00",
  "position": [100.0, 50.0, 200.0],
  "play_region_id": 12345
}
```

| Field             | Type                        | Description                                                  |
| ----------------- | --------------------------- | ------------------------------------------------------------ |
| `grace_entity_id` | `integer \| null`           | Grace entity ID captured by the warp hook during fast travel |
| `map_id`          | `string \| null`            | Map ID string (e.g. `m10_00_00_00`) for map-based fallback   |
| `position`        | `[number, number, number]?` | Player position `[x, y, z]` (reserved for future use)        |
| `play_region_id`  | `integer \| null`           | Play region ID (reserved for future use)                     |

**Response:** The server sends a `zone_update` (unicast) if the query resolves to a node in the current seed's graph. No response if unresolvable or ambiguous.

**Note:** This message does NOT modify `zone_history` (progression). It only updates `current_zone` (overlay pointer) and triggers a spectator `player_update`.

#### `finished`

Player finished the race. Server-side schema only — the mod does not send this directly. Instead, finishing is handled automatically when the server receives an `event_flag` matching the seed's `finish_event`. The server does accept `finished` if sent directly, but this path is not used by the mod in practice.

```json
{
  "type": "finished",
  "igt_ms": 7654321
}
```

#### `pong`

Heartbeat response. Sent by the mod in reply to a server `ping`.

```json
{
  "type": "pong"
}
```

### Server → Client

#### `auth_ok`

Authentication successful. Contains initial race state.

```json
{
  "type": "auth_ok",
  "participant_id": "uuid",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "setup",
    "started_at": null,
    "seeds_released_at": null
  },
  "seed": {
    "seed_id": "uuid",
    "total_layers": 12,
    "graph_json": null,
    "event_ids": [1040292801, 1040292802, 1040292847],
    "finish_event": 1040292847,
    "spawn_items": [
      { "id": 10500, "qty": 1 },
      { "id": 16300, "qty": 1 }
    ]
  },
  "participants": [
    {
      "id": "uuid",
      "twitch_username": "player1",
      "twitch_display_name": "Player1",
      "status": "registered",
      "current_zone": null,
      "current_layer": 0,
      "current_layer_tier": null,
      "igt_ms": 0,
      "death_count": 0,
      "color_index": 0,
      "mod_connected": false,
      "zone_history": null
    }
  ]
}
```

`participant_id`: the authenticated participant's UUID, used by the mod to identify itself in leaderboard updates.

`seed_id`: the seed's UUID, used by the mod to detect stale seed packs after a reroll (compared against the seed_id in the local config).

`event_ids`: sorted list of event flag IDs the mod should monitor. Opaque to the mod — no mapping to zones or nodes is provided. `graph_json` is always `null` for mods.

`finish_event` _(int | null)_: Flag ID for the final boss kill. The mod sends this immediately (no loading screen on boss kill). All other event flags are deferred to loading screen exit.

`spawn_items`: list of items to spawn at runtime via `func_item_inject`. Used for item types not supported by EMEVD's `DirectlyGivePlayerItem` (e.g., Gem/Ash of War, type 4). Each entry has `id` (EquipParamGem row ID) and `qty` (default 1). The mod spawns these once after game load, using event flag `1040292900` to prevent re-giving on reconnect or game restart. `null` if no runtime-spawned items exist.

**Note:** The `race` object includes `started_at` and `seeds_released_at`, but the mod only uses `id`, `name`, and `status` — the other fields are silently ignored.

#### `auth_error`

Authentication failed. Connection is closed with code 4003.

```json
{
  "type": "auth_error",
  "message": "Invalid mod token"
}
```

#### `error`

Generic error during the message loop (not auth phase). Sent when a gameplay message (`status_update`, `event_flag`, `finished`) is rejected — for example, because the race is not running.

```json
{
  "type": "error",
  "message": "Race not running"
}
```

#### `race_start`

Race has started. Followed immediately by a `zone_update` unicast for the start node.

```json
{
  "type": "race_start"
}
```

#### `leaderboard_update`

Broadcast to all mods and spectators when any player's state changes (ready, new zone discovery, finish).

```json
{
  "type": "leaderboard_update",
  "participants": [...],
  "leader_splits": { "0": 0, "1": 30000, "2": 75000 }
}
```

| Field           | Type             | Description                                                                   |
| --------------- | ---------------- | ----------------------------------------------------------------------------- |
| `participants`  | `list`           | Pre-sorted participant list (see [Leaderboard Sorting](#leaderboard-sorting)) |
| `leader_splits` | `dict<int,int>?` | Leader's entry IGT per layer (`null` if no leader yet)                        |

`leader_splits` maps layer index → IGT at which the leader first entered that layer. Used by the mod for client-side LiveSplit gap computation. Keys are serialized as strings in JSON.

When the race finishes, `zone_history` is included on each participant (otherwise `null`).

#### `race_status_change`

Race status changed. Broadcast to all mods and spectators. Includes `started_at` when transitioning to `running`.

```json
{
  "type": "race_status_change",
  "status": "running",
  "started_at": "2026-02-19T14:00:00Z"
}
```

| Field        | Type      | Description                                           |
| ------------ | --------- | ----------------------------------------------------- |
| `status`     | `string`  | New race status (`running`, `finished`)               |
| `started_at` | `string?` | ISO 8601 timestamp, included when status is `running` |

**Note:** The mod does not currently consume `started_at` from this message — the field is silently ignored by serde.

#### `zone_update`

Unicast to the originating mod after an `event_flag` is processed, after `zone_query` (fast travel), after `auth_ok` (reconnect during a running race), or after `race_start` (for the start node). Contains the entered zone's display name, tier, and exits with discovery status.

```json
{
  "type": "zone_update",
  "node_id": "graveyard_cave_e235",
  "display_name": "Cave of Knowledge",
  "tier": 5,
  "original_tier": 8,
  "exits": [
    {
      "text": "Soldier of Godrick front",
      "to_name": "Road's End Catacombs",
      "discovered": false
    },
    {
      "text": "Stranded Graveyard first door",
      "to_name": "Ruin-Strewn Precipice",
      "discovered": true
    }
  ]
}
```

| Field                | Type     | Description                                                                |
| -------------------- | -------- | -------------------------------------------------------------------------- |
| `node_id`            | `string` | DAG node ID                                                                |
| `display_name`       | `string` | Human-readable zone name (localized)                                       |
| `tier`               | `int?`   | Node tier in the current graph layout (null for start node)                |
| `original_tier`      | `int?`   | Original tier before graph rebalancing (null if same as `tier` or unknown) |
| `exits`              | `list`   | Fog gates leaving this zone                                                |
| `exits[].text`       | `string` | Fog gate label text (may include `[Zone Name]` annotation after i18n)      |
| `exits[].to_name`    | `string` | Display name of the destination zone                                       |
| `exits[].discovered` | `bool`   | Whether the destination has been visited (in zone_history)                 |

#### `player_update`

**Spectators only.** Single player update — not sent to mod connections. See the [Spectator Connection](#websocket-spectator-connection) section.

#### `ping`

Heartbeat ping. Sent by the server every 30 seconds. The mod must respond with `pong`.

```json
{
  "type": "ping"
}
```

### Heartbeat

The server sends `{"type": "ping"}` to each connected mod every **30 seconds**. The mod responds with `{"type": "pong"}`. This is an asymmetric design: only the mod detects server absence.

- **Server → Mod:** `ping` every 30s
- **Mod → Server:** `pong` in response
- **Mod timeout:** If no `ping` is received for **60 seconds**, the mod treats the connection as dead and triggers a reconnect
- The server does not track pong responses — it relies on TCP-level `WebSocketDisconnect` for cleanup

### Reconnection

The mod uses exponential backoff for reconnection: 1s → 2s → 4s → ... → 30s (capped).

On reconnect:

- Stale outgoing `EventFlag` messages are re-queued to `pending_event_flags` (not lost)
- Stale `StatusUpdate` messages are discarded
- Mod immediately sends `Ready` (unless training mode)
- Pending event flags are drained and re-sent
- Safety-net rescan: all `event_ids` are re-checked in case flags were set during downtime
- If race is already running, server sends a `zone_update` unicast for the current zone

---

## WebSocket: Spectator Connection

**Endpoint:** `WS /ws/race/{race_id}`

No authentication required (public), but optional auth within a 2-second grace period enables role-based DAG access during SETUP status.

### Client → Server

#### `auth` (optional)

Sent within 2 seconds of connecting. If not sent, connection proceeds as anonymous.

```json
{
  "type": "auth",
  "token": "user_api_token"
}
```

### Server → Client

#### `race_state`

Sent immediately on connection (after optional auth). Full race state. Also re-sent on status transitions (SETUP → RUNNING, RUNNING → FINISHED) and when seeds are released, with recomputed DAG access.

```json
{
  "type": "race_state",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "running",
    "started_at": "2026-02-19T14:00:00Z",
    "seeds_released_at": "2026-02-19T13:55:00Z"
  },
  "seed": {
    "seed_id": "uuid",
    "total_layers": 12,
    "graph_json": { "...": "..." },
    "total_nodes": 45,
    "total_paths": 3
  },
  "participants": [
    {
      "id": "uuid",
      "twitch_username": "player1",
      "twitch_display_name": "Player1",
      "current_zone": "m60_51_36_00",
      "current_layer": 8,
      "current_layer_tier": 3,
      "igt_ms": 123456,
      "death_count": 3,
      "status": "playing",
      "color_index": 0,
      "mod_connected": true,
      "zone_history": null
    }
  ]
}
```

`seed.graph_json` is `null` if the viewer lacks DAG access (see [DAG Access Rules](#dag-access-rules)). `total_nodes` and `total_paths` are always included. `event_ids`, `finish_event`, and `spawn_items` are **not** included for spectators (mod-only).

`zone_history` is included (as a list) when race status is `finished`, otherwise `null`.

#### `player_update`

Single player update. **Sent to spectators only** (mods receive `leaderboard_update` instead). Triggered by periodic `status_update` from mod, revisited nodes, or `zone_query` resolution.

```json
{
  "type": "player_update",
  "player": { ... }
}
```

#### `leaderboard_update`

Full leaderboard broadcast to all mods and spectators (on zone progress, ready, or finish events). Includes `leader_splits` for client-side gap computation (see [Gap Timing](#gap-timing)).

```json
{
  "type": "leaderboard_update",
  "participants": [...],
  "leader_splits": { "0": 0, "1": 30000 }
}
```

#### `race_status_change`

Race status changed. Broadcast to all mods and spectators.

```json
{
  "type": "race_status_change",
  "status": "finished"
}
```

#### `spectator_count`

Broadcast to all spectators when spectator count changes (connect/disconnect).

```json
{
  "type": "spectator_count",
  "count": 5
}
```

#### `ping`

Heartbeat ping. Sent every 30 seconds.

```json
{
  "type": "ping"
}
```

---

## Training Mode

Solo practice mode. Uses the same protocol messages as competitive races but with simplified single-player behavior.

### REST API

| Method | Endpoint                     | Auth   | Description                                              |
| ------ | ---------------------------- | ------ | -------------------------------------------------------- |
| POST   | `/api/training`              | Bearer | Create training session (`{ pool_name }`)                |
| GET    | `/api/training`              | Bearer | List user's training sessions                            |
| GET    | `/api/training/{id}`         | -      | Training session detail (public read-only)               |
| POST   | `/api/training/{id}/abandon` | Bearer | Abandon session (ACTIVE → ABANDONED)                     |
| GET    | `/api/training/{id}/pack`    | Bearer | Download training seed pack (ZIP with `training = true`) |

### Training Session Status

`active` → `finished` | `abandoned`

### WebSocket: Training Mod

**Endpoint:** `WS /ws/training/{session_id}`

Same protocol as `/ws/mod/{race_id}` with differences:

- **Auth**: Uses `mod_token` from the training session (not a race participant token)
- **No `ready` phase**: Race starts immediately after `auth_ok`
- **`race_start` sent immediately**: No waiting for other players
- **Single player**: Only one mod connection per session
- **Finish detection**: `finish_event` flag triggers session completion (ACTIVE → FINISHED)

Client → Server messages: `auth`, `status_update`, `event_flag`, `zone_query`, `pong` (same format as mod WS).

Server → Client messages: `auth_ok`, `auth_error`, `error`, `race_start`, `zone_update`, `leaderboard_update`, `race_status_change`, `ping` (same format as mod WS).

### WebSocket: Training Spectator

**Endpoint:** `WS /ws/training/{session_id}/spectate`

Live web UI updates during training. Accepts both authenticated and anonymous spectators.

- **Auth handshake required**: An `auth` message must be sent within 5 seconds (connection closed with code 4001 otherwise), but the `token` field is optional — omit it for anonymous access
- **`race_state`**: Sent on connect with full graph (always included for training), seed info, and participant state
- **`leaderboard_update`**: Single-participant update on status/zone changes
- **`race_status_change`**: Sent when session finishes or is abandoned
- **`ping`**: Heartbeat every 30 seconds

---

## Data Types

### Race Status

`setup` → `running` → `finished`

### Participant Status

`registered` → `ready` → `playing` → `finished` | `abandoned`

### ParticipantInfo

Shared schema across all WebSocket messages:

| Field                 | Type      | Description                                     |
| --------------------- | --------- | ----------------------------------------------- |
| `id`                  | `string`  | Participant UUID                                |
| `twitch_username`     | `string`  | Twitch login name                               |
| `twitch_display_name` | `string?` | Twitch display name                             |
| `status`              | `string`  | Participant status (see above)                  |
| `current_zone`        | `string?` | Current DAG node ID (e.g. `m60_51_36_00`)       |
| `current_layer`       | `int`     | Current layer in the DAG (0 = start)            |
| `current_layer_tier`  | `int?`    | Tier of the current node (computed from graph)  |
| `igt_ms`              | `int`     | In-game time in milliseconds                    |
| `death_count`         | `int`     | Total deaths                                    |
| `color_index`         | `int`     | Player color assignment (0-indexed)             |
| `mod_connected`       | `bool`    | Whether the mod client is currently connected   |
| `zone_history`        | `list?`   | Zone visit history (only when race is finished) |
| `gap_ms`              | `int?`    | Gap to the leader in milliseconds (see below)   |
| `layer_entry_igt`     | `int?`    | Player's IGT when entering their current layer  |

`zone_history` entries: `{ "node_id": "m60_51_36_00", "igt_ms": 123456 }`

**Note:** The mod's Rust `ParticipantInfo` struct only declares a subset of these fields (`id`, `twitch_username`, `twitch_display_name`, `status`, `current_zone`, `current_layer`, `current_layer_tier`, `igt_ms`, `death_count`, `gap_ms`, `layer_entry_igt`). Extra fields like `color_index`, `mod_connected`, and `zone_history` are present on the wire but silently ignored by serde.

### RaceInfo

Included in `auth_ok` and `race_state` messages:

| Field               | Type      | Description                                 |
| ------------------- | --------- | ------------------------------------------- |
| `id`                | `string`  | Race UUID                                   |
| `name`              | `string`  | Race name                                   |
| `status`            | `string`  | Race status (see above)                     |
| `started_at`        | `string?` | ISO 8601 timestamp when race started        |
| `seeds_released_at` | `string?` | ISO 8601 timestamp when seeds were released |

**Note:** The mod only uses `id`, `name`, and `status` from RaceInfo.

### SeedInfo

Included in `auth_ok` (mod) and `race_state` (spectator):

| Field          | Type      | Mod | Spectator | Description                                         |
| -------------- | --------- | --- | --------- | --------------------------------------------------- |
| `seed_id`      | `string?` | yes | yes       | Seed UUID                                           |
| `total_layers` | `int`     | yes | yes       | Number of layers in the DAG                         |
| `graph_json`   | `object?` | no  | yes\*     | Full graph for DAG visualization (\* see DAG rules) |
| `total_nodes`  | `int?`    | no  | yes       | Total number of nodes in the DAG                    |
| `total_paths`  | `int?`    | no  | yes       | Total number of paths in the DAG                    |
| `event_ids`    | `int[]`   | yes | no        | Event flag IDs to monitor                           |
| `finish_event` | `int?`    | yes | no        | Final boss kill flag ID                             |
| `spawn_items`  | `list`    | yes | no        | Items for runtime spawning                          |

### Leaderboard Sorting

Participants in `leaderboard_update` are pre-sorted by priority:

1. **Finished** — by `igt_ms` ascending (fastest first)
2. **Playing** — by `current_layer` descending (furthest first), then `igt_ms` ascending
3. **Ready**
4. **Registered**
5. **Abandoned**

### Gap Timing

Gap timing uses a LiveSplit-style formula. The server computes `gap_ms` for web spectators and sends `leader_splits` + `layer_entry_igt` so the mod can compute gaps client-side at frame rate.

#### Server-side (`gap_ms`)

Computed during `broadcast_leaderboard` for web spectators:

- **Leader:** `null`
- **Playing (within budget):** `player_layer_entry_igt - leader_splits[current_layer]` — fixed entry delta while the player's IGT is within the leader's time budget on the layer
- **Playing (exceeded budget):** `igt_ms - leader_splits[current_layer + 1]` — gap grows once the player exceeds the leader's exit IGT for that layer
- **Playing (leader on same layer):** entry delta only (no exit split available)
- **Finished:** `igt_ms - leader_igt_ms` — direct time delta
- **Ready / Registered / Abandoned:** `null`

#### Client-side (mod)

The mod ignores `gap_ms` and recomputes gaps locally each frame using `leader_splits` + `layer_entry_igt`. For the local player, the mod substitutes the real-time local IGT (read from game memory) instead of the server's snapshot `igt_ms`, enabling frame-rate gap updates.

#### Color coding

- **Negative gap** (ahead of leader's pace): green (`-M:SS`)
- **Positive gap** (behind leader's pace): soft red (`+M:SS`)
- **Zero gap**: default text color

#### Leader splits

`build_leader_splits(zone_history, graph_json)` walks the leader's `zone_history` and builds `{layer: first_igt_at_layer}`. Skips entries whose `node_id` is not in the graph. Deduplicates by taking the first IGT at each layer. Sent as `leader_splits` in `leaderboard_update`.

`broadcast_player_update()` intentionally omits `gap_ms` (computing it requires the full sorted participant list).

### DAG Access Rules

The `graph_json` field in spectator `seed` is conditionally included based on race status and user role:

| Race Status | Rule                                                             |
| ----------- | ---------------------------------------------------------------- |
| `finished`  | Always visible (race is over)                                    |
| `running`   | Always visible (progressive reveal via zone_history)             |
| `setup`     | Visible only to participants and the organizer; hidden otherwise |

Anonymous (unauthenticated) spectators: visible during `running` and `finished`, hidden during `setup`.

### WebSocket Close Codes

| Code   | Reason                                                | Endpoints                     |
| ------ | ----------------------------------------------------- | ----------------------------- |
| `1000` | Normal closure (room shutdown, race reset)            | All                           |
| `4001` | Auth timeout (no message received within deadline)    | Mod, Training, Training Spec  |
| `4003` | Auth error (invalid JSON, invalid message, auth fail) | Mod, Training, Training Spec  |
| `4004` | Resource not found (race or session doesn't exist)    | Spectator, Training Spectator |

### Security Notes

**Spectator WebSocket authentication (M9):** Spectator connections (`/ws/race/{race_id}`) are intentionally unauthenticated by default. Race leaderboard data is public by design. Optional auth within a 2-second grace period enables role-based DAG visibility during SETUP — this prevents anonymous viewers from seeing the graph before the race starts. During `running` and `finished`, all spectators see the DAG. This is an accepted design trade-off.

**CSRF (M5):** Auth tokens are stored in `localStorage` and sent via `Authorization` header, not auto-attached cookies. This makes CSRF attacks infeasible since the token is never sent automatically. If token storage changes to cookies in the future, CSRF protection must be added.

**localStorage vs cookies (M10):** Tokens in `localStorage` are vulnerable to XSS but not to CSRF. The codebase has no `{@html}` usage (preventing XSS vectors), and CSP headers restrict script sources. This trade-off is accepted for the current threat model.

### Race State Gating

Gameplay messages (`status_update`, `event_flag`, `zone_query`, `finished`) are only accepted when the race status is `running`. This is enforced at three layers:

1. **Server:** Each handler checks `race.status == RUNNING` before processing. If the race is not running, the server responds with an `error` message and discards the payload.
2. **Mod (outgoing):** The mod gates `status_update` and `event_flag` sends behind `is_race_running()`. Event flags detected before the race starts are buffered and sent once the race transitions to running.
3. **Mod (overlay):** A colored banner shows the race state — orange "WAITING FOR START" (setup), green "GO!" for 3 seconds (running), and green "RACE FINISHED" (finished).

The `ready` and `pong` messages are not gated — they are valid in any state.

### Zone Tracking

Zone tracking uses EMEVD event flags. The mod monitors a list of event flag IDs (received via `auth_ok`) and reports transitions via `event_flag` messages. The server resolves flag IDs to DAG nodes using the seed's `event_map`.

**Per-connection flags:** Each connection in `graph.json` has a unique `flag_id`. The `event_map` is many-to-one: multiple flags can map to the same node (e.g., when a shared entrance merge has 3 branches entering the same cluster). The mod receives all flag IDs as an opaque list; the server performs the flag → node resolution. This ensures the mod detects each fog gate traversal independently, even when the destination cluster was previously visited via a different branch.

See `docs/specs/emevd-zone-tracking.md` for the full specification.

### Runtime Item Spawning

Care package items of type 4 (Gem/Ash of War) cannot be given via EMEVD's `DirectlyGivePlayerItem`. Instead, the server extracts them from `graph_json.care_package` and sends them in `auth_ok.seed.spawn_items`. The mod spawns them at runtime using `func_item_inject` after the game is fully loaded (MapItemMan initialized). Event flag `1040292900` prevents re-giving items on reconnect or game restart.

### Broadcasting Strategy

| Event                          | Mods                                                | Spectators                          |
| ------------------------------ | --------------------------------------------------- | ----------------------------------- |
| Mod connects/disconnects       | `leaderboard_update`                                | `leaderboard_update`                |
| `ready`                        | `leaderboard_update`                                | `leaderboard_update`                |
| `status_update` (periodic)     | —                                                   | `player_update`                     |
| `status_update` (READY→PLAY)   | `leaderboard_update`                                | `leaderboard_update`                |
| `event_flag` (new node)        | `leaderboard_update`                                | `leaderboard_update`                |
| `event_flag` (revisit)         | `zone_update` (unicast)                             | `player_update`                     |
| `event_flag` (finish)          | `leaderboard_update`                                | `race_state` + status change        |
| `zone_query`                   | `zone_update` (unicast)                             | `player_update`                     |
| Race starts                    | `race_start` + `zone_update` + `race_status_change` | `race_state` + `race_status_change` |
| Race finishes                  | `race_status_change`                                | `race_state` + `race_status_change` |
| Seeds released                 | —                                                   | `race_state`                        |
| Spectator connects/disconnects | —                                                   | `spectator_count`                   |
