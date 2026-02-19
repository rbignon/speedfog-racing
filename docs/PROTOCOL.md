# SpeedFog Racing - Protocol Reference

Reference document for API endpoints and WebSocket messages.

## REST API

### System

| Method | Endpoint  | Auth | Description                          |
| ------ | --------- | ---- | ------------------------------------ |
| GET    | `/health` | -    | Health check (`{ status, version }`) |

### Site

| Method | Endpoint           | Auth | Description                                         |
| ------ | ------------------ | ---- | --------------------------------------------------- |
| GET    | `/api/site-config` | -    | Public site configuration (`{ coming_soon: bool }`) |

### Authentication

| Method | Endpoint             | Auth   | Description                                         |
| ------ | -------------------- | ------ | --------------------------------------------------- |
| GET    | `/api/auth/twitch`   | -      | Redirect to Twitch OAuth (`?redirect_url`)          |
| GET    | `/api/auth/callback` | -      | OAuth callback, redirects with `?code=` (ephemeral) |
| POST   | `/api/auth/exchange` | -      | Exchange auth code for API token                    |
| GET    | `/api/auth/me`       | Bearer | Get current user info (public, no `api_token`)      |
| POST   | `/api/auth/logout`   | Bearer | Regenerate API token (invalidates session)          |

### Races

| Method | Endpoint                               | Auth   | Description                                     |
| ------ | -------------------------------------- | ------ | ----------------------------------------------- |
| GET    | `/api/races`                           | -      | List races (`?status=draft,running,...`)        |
| POST   | `/api/races`                           | Bearer | Create race (DRAFT)                             |
| GET    | `/api/races/{id}`                      | -      | Race details with participants and casters      |
| POST   | `/api/races/{id}/participants`         | Bearer | Add participant (organizer only)                |
| DELETE | `/api/races/{id}/participants/{pid}`   | Bearer | Remove participant (organizer, DRAFT/OPEN only) |
| POST   | `/api/races/{id}/casters`              | Bearer | Add caster (organizer only)                     |
| DELETE | `/api/races/{id}/casters/{cid}`        | Bearer | Remove caster (organizer only)                  |
| POST   | `/api/races/{id}/open`                 | Bearer | Transition DRAFT → OPEN (organizer)             |
| POST   | `/api/races/{id}/start`                | Bearer | Start race: DRAFT/OPEN → RUNNING (organizer)    |
| GET    | `/api/races/{id}/my-seed-pack`         | Bearer | Download own seed pack (generated on-demand)    |
| GET    | `/api/races/{id}/download/{mod_token}` | Bearer | Download participant seed pack (ZIP)            |

### Pools

| Method | Endpoint     | Auth | Description                                                                                              |
| ------ | ------------ | ---- | -------------------------------------------------------------------------------------------------------- |
| GET    | `/api/pools` | -    | Pool stats with TOML metadata (`{ [name]: { available, consumed, estimated_duration?, description? } }`) |

### Users

| Method | Endpoint              | Auth   | Description                                             |
| ------ | --------------------- | ------ | ------------------------------------------------------- |
| GET    | `/api/users/search`   | Bearer | Search users by username or display name prefix (`?q=`) |
| GET    | `/api/users/me`       | Bearer | Get user profile                                        |
| GET    | `/api/users/me/races` | Bearer | Races where user is organizer or participant            |

### Invites

| Method | Endpoint                     | Auth   | Description     |
| ------ | ---------------------------- | ------ | --------------- |
| GET    | `/api/invite/{token}`        | -      | Get invite info |
| POST   | `/api/invite/{token}/accept` | Bearer | Accept invite   |

### Admin

| Method | Endpoint                 | Auth           | Description                         |
| ------ | ------------------------ | -------------- | ----------------------------------- |
| POST   | `/api/admin/seeds/scan`  | Bearer (admin) | Rescan seed pool (`{ pool_name? }`) |
| GET    | `/api/admin/seeds/stats` | Bearer (admin) | Pool statistics                     |

---

## WebSocket: Mod Connection

**Endpoint:** `WS /ws/mod/{race_id}`

### Client → Server

#### `auth`

First message after connection. Authenticates the mod.

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

Player finished the race. Server-side schema only — the mod does not send this directly. Instead, finishing is handled automatically when the server receives an `event_flag` matching the seed's `finish_event`.

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
    "status": "open"
  },
  "seed": {
    "total_layers": 12,
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

`event_ids`: sorted list of event flag IDs the mod should monitor. Opaque to the mod — no mapping to zones or nodes is provided. `graph_json` is always `null` for mods.

`finish_event` _(int | null)_: Flag ID for the final boss kill. The mod sends this immediately (no loading screen on boss kill). All other event flags are deferred to loading screen exit.

`spawn_items`: list of items to spawn at runtime via `func_item_inject`. Used for item types not supported by EMEVD's `DirectlyGivePlayerItem` (e.g., Gem/Ash of War, type 4). Each entry has `id` (EquipParamGem row ID) and `qty` (default 1). The mod spawns these once after game load, using event flag `1040292900` to prevent re-giving on reconnect or game restart. `null` if no runtime-spawned items exist.

#### `auth_error`

Authentication failed.

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

Race has started.

```json
{
  "type": "race_start"
}
```

#### `leaderboard_update`

Broadcast when any player's state changes.

```json
{
  "type": "leaderboard_update",
  "participants": [...]
}
```

Participants are pre-sorted (see [Leaderboard Sorting](#leaderboard-sorting)).

When the race finishes, `zone_history` is included on each participant (otherwise `null`).

#### `race_status_change`

Race status changed.

```json
{
  "type": "race_status_change",
  "status": "running"
}
```

#### `zone_update`

Unicast to the originating mod after an `event_flag` is processed, after `zone_query` (fast travel), after `auth_ok` (reconnect during a running race), or after `race_start` (for the start node). Contains the entered zone's display name, tier, and exits with discovery status.

```json
{
  "type": "zone_update",
  "node_id": "graveyard_cave_e235",
  "display_name": "Cave of Knowledge",
  "tier": 5,
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

| Field                | Type     | Description                                                |
| -------------------- | -------- | ---------------------------------------------------------- |
| `node_id`            | `string` | DAG node ID                                                |
| `display_name`       | `string` | Human-readable zone name                                   |
| `tier`               | `int?`   | Node tier (null for start node)                            |
| `exits`              | `list`   | Fog gates leaving this zone                                |
| `exits[].text`       | `string` | Fog gate label text                                        |
| `exits[].to_name`    | `string` | Display name of the destination zone                       |
| `exits[].discovered` | `bool`   | Whether the destination has been visited (in zone_history) |

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

---

## WebSocket: Spectator Connection

**Endpoint:** `WS /ws/race/{race_id}`

No authentication required (public), but optional auth within a 2-second grace period enables role-based DAG access.

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

Sent immediately on connection (after optional auth). Full race state. Also re-sent on status transitions (DRAFT → OPEN, OPEN/DRAFT → RUNNING, race finish) with recomputed DAG access.

```json
{
  "type": "race_state",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "running"
  },
  "seed": {
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

`seed.graph_json` is `null` if the viewer lacks DAG access (see [DAG Access Rules](#dag-access-rules)). `total_nodes` and `total_paths` are always included.

`zone_history` is included (as a list) when race status is `finished`, otherwise `null`.

#### `player_update`

Player state changed (on `status_update` from mod).

```json
{
  "type": "player_update",
  "player": { ... }
}
```

#### `leaderboard_update`

Full leaderboard broadcast (on zone progress, ready, or finish events).

```json
{
  "type": "leaderboard_update",
  "participants": [...]
}
```

#### `race_status_change`

Race status changed.

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

---

## Training Mode

Solo practice mode. Uses the same protocol messages as competitive races but with simplified single-player behavior.

### REST API

| Method | Endpoint                     | Auth   | Description                                              |
| ------ | ---------------------------- | ------ | -------------------------------------------------------- |
| POST   | `/api/training`              | Bearer | Create training session (`{ pool_name }`)                |
| GET    | `/api/training`              | Bearer | List user's training sessions                            |
| GET    | `/api/training/{id}`         | Bearer | Training session detail (with `graph_json`)              |
| POST   | `/api/training/{id}/abandon` | Bearer | Abandon session (ACTIVE → ABANDONED)                     |
| GET    | `/api/training/{id}/pack`    | Bearer | Download training seed pack (ZIP with `training = true`) |
| GET    | `/api/pools?type=training`   | -      | List training pools only (filtered by `type` in TOML)    |

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

Client → Server messages: `auth`, `status_update`, `event_flag` (same format as mod WS).

Server → Client messages: `auth_ok`, `race_start`, `zone_update` (same format as mod WS).

### WebSocket: Training Spectator

**Endpoint:** `WS /ws/training/{session_id}/spectate`

Owner-only spectator for live web UI updates during training.

- **Auth required**: Only the session owner can connect (sends `auth` with API token)
- **`race_state`**: Sent on connect with full graph, seed info, and participant state
- **`leaderboard_update`**: Single-participant update on status/zone changes
- **`race_status_change`**: Sent when session finishes or is abandoned

---

## Data Types

### Race Status

`draft` → `open` → `running` → `finished`

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

`zone_history` entries: `{ "node_id": "m60_51_36_00", "igt_ms": 123456 }`

### Leaderboard Sorting

Participants in `leaderboard_update` are pre-sorted by priority:

1. **Finished** — by `igt_ms` ascending (fastest first)
2. **Playing** — by `current_layer` descending (furthest first), then `igt_ms` ascending
3. **Ready**
4. **Registered**
5. **Abandoned**

### DAG Access Rules

The `graph_json` field in spectator `seed` is conditionally included based on user role:

| Race Status  | Rule                                                         |
| ------------ | ------------------------------------------------------------ |
| `finished`   | Always visible (race is over)                                |
| `running`    | Visible unless viewer is a participant (to prevent cheating) |
| `draft/open` | Visible only to non-participating organizer or caster        |

Anonymous (unauthenticated) spectators: visible during `running` and `finished`, hidden during `draft` and `open`.

### Security Notes

**Spectator WebSocket authentication (M9):** Spectator connections (`/ws/race/{race_id}`) are intentionally unauthenticated by default. Race leaderboard data is public by design. Optional auth within a 2-second grace period enables role-based DAG visibility — this allows casters to see the graph during a running race while participants cannot. Anonymous spectators see the DAG during `running` and `finished` states. This is an accepted design trade-off.

**CSRF (M5):** Auth tokens are stored in `localStorage` and sent via `Authorization` header, not auto-attached cookies. This makes CSRF attacks infeasible since the token is never sent automatically. If token storage changes to cookies in the future, CSRF protection must be added.

**localStorage vs cookies (M10):** Tokens in `localStorage` are vulnerable to XSS but not to CSRF. The codebase has no `{@html}` usage (preventing XSS vectors), and CSP headers restrict script sources. This trade-off is accepted for the current threat model.

### Race State Gating

Gameplay messages (`status_update`, `event_flag`, `zone_query`, `finished`) are only accepted when the race status is `running`. This is enforced at three layers:

1. **Server:** Each handler checks `race.status == RUNNING` before processing. If the race is not running, the server responds with an `error` message and discards the payload.
2. **Mod (outgoing):** The mod gates `status_update` and `event_flag` sends behind `is_race_running()`. Event flags detected before the race starts are buffered and sent once the race transitions to running.
3. **Mod (overlay):** A colored banner shows the race state — orange "WAITING FOR START" (draft/open), green "GO!" for 3 seconds (running), and green "RACE FINISHED" (finished).

The `ready` and `pong` messages are not gated — they are valid in any state.

### Zone Tracking

Zone tracking uses EMEVD event flags. The mod monitors a list of event flag IDs (received via `auth_ok`) and reports transitions via `event_flag` messages. The server resolves flag IDs to DAG nodes using the seed's `event_map`. See `docs/specs/emevd-zone-tracking.md` for the full specification.

### Runtime Item Spawning

Care package items of type 4 (Gem/Ash of War) cannot be given via EMEVD's `DirectlyGivePlayerItem`. Instead, the server extracts them from `graph_json.care_package` and sends them in `auth_ok.seed.spawn_items`. The mod spawns them at runtime using `func_item_inject` after the game is fully loaded (MapItemMan initialized). Event flag `1040292900` prevents re-giving items on reconnect or game restart.
