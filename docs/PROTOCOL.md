# SpeedFog Racing - Protocol Reference

Reference document for API endpoints and WebSocket messages.

## REST API

### System

| Method | Endpoint  | Auth | Description                          |
| ------ | --------- | ---- | ------------------------------------ |
| GET    | `/health` | -    | Health check (`{ status, version }`) |

### Authentication

| Method | Endpoint             | Auth   | Description                                                                                                   |
| ------ | -------------------- | ------ | ------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/auth/twitch`   | -      | Redirect to Twitch OAuth (`?redirect_url`, must match an allowed origin, else the configured default is used) |
| GET    | `/api/auth/callback` | -      | OAuth callback, redirects with `?code=` (ephemeral)                                                           |
| POST   | `/api/auth/exchange` | -      | Exchange auth code for API token                                                                              |
| GET    | `/api/auth/me`       | Bearer | Get current user info (public, no `api_token`)                                                                |
| POST   | `/api/auth/logout`   | Bearer | Regenerate API token (invalidates session)                                                                    |

### Races

| Method | Endpoint                              | Auth             | Description                                                                                                            |
| ------ | ------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/races`                          | -                | List races (`?status=setup,running,...`). Excludes Daily Seeds (`daily_date IS NULL`).                                 |
| POST   | `/api/races`                          | Bearer           | Create race (status: SETUP)                                                                                            |
| GET    | `/api/races/{id}`                     | -                | Race details with participants and casters                                                                             |
| PATCH  | `/api/races/{id}`                     | Bearer           | Update race settings (organizer, SETUP only)                                                                           |
| POST   | `/api/races/{id}/participants`        | Bearer           | Add participant (organizer only)                                                                                       |
| DELETE | `/api/races/{id}/participants/{pid}`  | Bearer           | Remove participant (organizer, SETUP only)                                                                             |
| POST   | `/api/races/{id}/casters`             | Bearer           | Add caster (organizer only)                                                                                            |
| DELETE | `/api/races/{id}/casters/{cid}`       | Bearer           | Remove caster (organizer only)                                                                                         |
| DELETE | `/api/races/{id}/invites/{invite_id}` | Bearer           | Revoke invite (organizer, SETUP only)                                                                                  |
| POST   | `/api/races/{id}/join`                | Bearer           | Self-join open-registration race (SETUP only)                                                                          |
| POST   | `/api/races/{id}/leave`               | Bearer           | Leave race (SETUP only)                                                                                                |
| POST   | `/api/races/{id}/release-seeds`       | Bearer           | Release seeds for download (organizer, SETUP)                                                                          |
| POST   | `/api/races/{id}/reroll-seed`         | Bearer           | Reroll the seed (organizer, SETUP, seeds not released). For Daily Seeds, accepts RUNNING and resets every participant. |
| POST   | `/api/races/{id}/start`               | Bearer           | Start race: SETUP → RUNNING (organizer)                                                                                |
| POST   | `/api/races/{id}/reset`               | Bearer           | Reset race: RUNNING → SETUP (organizer)                                                                                |
| POST   | `/api/races/{id}/finish`              | Bearer           | Force-finish race: RUNNING → FINISHED (organizer)                                                                      |
| DELETE | `/api/races/{id}`                     | Bearer           | Delete race (organizer, SETUP only)                                                                                    |
| GET    | `/api/races/{id}/seed-pack-ticket`    | Bearer           | Mint a short-lived download ticket for own seed pack (same gating as the download)                                     |
| GET    | `/api/races/{id}/my-seed-pack`        | Bearer or ticket | Download own seed pack (requires seeds released)                                                                       |

### Daily Seeds

| Method | Endpoint                             | Auth | Description                                                                                                                                                                                                                                                                                                 |
| ------ | ------------------------------------ | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/daily/today`                   | -    | Current rotation day's Daily Seed as `RaceResponse`, or 404 if none yet.                                                                                                                                                                                                                                    |
| GET    | `/api/daily/{yyyy-mm-dd}`            | -    | Look up a Daily Seed by rotation date. Returns `RaceDetailResponse` or 404.                                                                                                                                                                                                                                 |
| GET    | `/api/daily/recent?limit=N`          | -    | Past Daily Seeds (`daily_date < today`), most recent first. `limit` in `[1, 30]`, default 7.                                                                                                                                                                                                                |
| GET    | `/api/daily/week`                    | -    | Returns `DailyWeekResponse` (seven calendar-week cells + `my_streak` + `winners`). `winners`: `null` for the current/future week, `[]` for a past week with no qualified, otherwise list of `WinnerSummary {user, total_points}` tied at max points. Optional `?date=YYYY-MM-DD` anchors the returned week. |
| GET    | `/api/daily/week/leaderboard?date=X` | -    | `WeeklyLeaderboardResponse`: ranking for the week containing `X`. Public, no auth. Fields `week_starting`, `week_ending`, `dailies_total` (closed dailies in displayed week), `entries[]` with `rank`, `user`, `total_points`, `dailies_played`, `total_deaths`, `weapon_combos`.                           |

Daily Seeds are regular `Race` rows with `daily_date IS NOT NULL`; the underlying race / participant lifecycle (start, finish, abandon, reroll) and WebSocket protocol are unchanged. See [DAILY_SEED.md](DAILY_SEED.md) for the rotation, reroll-while-running, stats-skip, and Discord rules.

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

| Method | Endpoint                     | Auth           | Description                                  |
| ------ | ---------------------------- | -------------- | -------------------------------------------- |
| POST   | `/api/admin/seeds/scan`      | Bearer (admin) | Rescan seed pool (`{ pool_name? }`)          |
| GET    | `/api/admin/seeds/stats`     | Bearer (admin) | Pool statistics                              |
| POST   | `/api/admin/seeds/discard`   | Bearer (admin) | Discard seeds from pool                      |
| GET    | `/api/admin/pools`           | Bearer (admin) | List pools (incl. disabled) with seed counts |
| PATCH  | `/api/admin/pools/{name}`    | Bearer (admin) | Toggle `enabled` flag (`{ enabled: bool }`)  |
| GET    | `/api/admin/users`           | Bearer (admin) | List all users                               |
| PATCH  | `/api/admin/users/{user_id}` | Bearer (admin) | Update user role                             |
| GET    | `/api/admin/activity`        | Bearer (admin) | Admin activity timeline                      |

---

## Protocol Version

The mod-server wire protocol carries its own version, independent from
release numbers. Current: **1.0**. It is defined in
`server/speedfog_racing/websocket/schemas.py` (`PROTOCOL_VERSION`) and
`mod/src/core/protocol.rs` (`PROTOCOL_VERSION`), which must stay identical.

Bump rules:

- Breaking change to the wire protocol: major + 1 (minor resets to 0).
- Backward-compatible addition worth signalling: minor + 1 (optional).
- No wire change: unchanged.

At auth, the mod sends `protocol_version`; a different major (either
direction) is rejected with `auth_error` and close code 4003. A mod that
omits the field is assumed to speak protocol 1.0. Same major with an older
minor is accepted and gets `latest_mod_version` in `auth_ok` (soft update
notice). The `MIN_MOD_VERSION` server setting can additionally reject old
_release_ versions for non-protocol emergencies.

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
  "mod_token": "player_specific_token",
  "protocol_version": "1.0",
  "mod_version": "1.17.0"
}
```

`protocol_version` (optional): wire-protocol version spoken by the mod (see [Protocol Version](#protocol-version)). Absent on pre-versioning builds, which are assumed to speak `1.0`. An incompatible major is rejected with `auth_error` + close 4003.

`mod_version` (optional): mod release version, used for server logs and the admin activity view only, never for decisions (except the emergency `MIN_MOD_VERSION` gate).

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
  "death_count": 5,
  "weapons": [null, 2000025]
}
```

`weapons` is `[left_hand, right_hand]` raw runtime `EquipParamWeapon` IDs (param row + upgrade level, e.g. `2000025` = Longsword +25). Each slot is `null` when the hand is empty, masked under two-handing, unreadable, or filled with the Unarmed sentinel (`110000`). The field is omitted by older mod builds. The server discards weapons whose `wep_type` is in the excluded set (staves, seals, shields, torches) and writes the surviving raw IDs onto the current `zone_history` entry as `weapons`. A tick that resolves to `[null, null]` after filtering (loading screen, unreadable memory, empty hands, or all-filtered types) is skipped: the last meaningful weapons captured for the current zone are preserved.

#### `event_flag`

Sent when the mod detects an event flag transition (0 → 1). The server resolves it to a DAG node via the seed's `event_map`. If the flag matches `finish_event`, the player is auto-finished. Rejected with `error` if race is not running (see [Race State Gating](#race-state-gating)).

`message_id` is optional for backward compatibility. Newer mods attach a monotonically increasing client-local ID so the server can acknowledge persistence and deduplicate replayed `event_flag` messages after reconnect.

**Revisited nodes:** Multiple flags can map to the same DAG node (e.g., shared entrance merges where several branches connect to a single cluster). When a player backtracks and re-enters a previously visited node, a new entry is appended to `zone_history` with the current `igt_ms`. This enables accurate per-visit time and death attribution. Only first visits trigger a `leaderboard_update` broadcast; revisits trigger a `player_update` instead. In both cases a `zone_history` snapshot is also emitted to spectators so they can update their local store.

**Timing:** Regular event flags (fog gate traversals) are detected immediately by polling but deferred until loading screen exit. This ensures spectators see progress updates in sync with the player's arrival, and prevents zone name spoilers during loading screens. The `finish_event` (boss kill) is an exception: it is sent immediately since boss kills don't trigger a loading screen.

**Acknowledgement:** On new protocol versions, the server sends `event_flag_ack` after the `event_flag` has been committed. The mod keeps the flag in an in-flight set until this ACK arrives. If the connection drops first, the mod replays the unacknowledged `event_flag` on reconnect. The server stores `message_id` in `zone_history` entries of type `"fog"` and treats replays with the same `message_id` as idempotent (ACK again, no second append). The server also ACKs messages that it deduplicates or rejects on its own (shared-entrance counterpart, unknown flag, history cap reached): without that ACK the mod would keep the message in-flight and replay it after a reconnect, and the dedup check against `history[-1]` would no longer match once the player has progressed, causing a stale duplicate with the original (older) `igt_ms` to be appended.

```json
{
  "type": "event_flag",
  "flag_id": 1040292842,
  "igt_ms": 4532100,
  "message_id": 17
}
```

| Field        | Type       | Description                                                       |
| ------------ | ---------- | ----------------------------------------------------------------- |
| `flag_id`    | `integer`  | Event flag ID set by the EMEVD script                             |
| `igt_ms`     | `integer`  | In-game time in milliseconds at the moment of the transition      |
| `message_id` | `integer?` | Optional client-generated idempotency key for ACK/replay handling |

#### `zone_query`

Sent at loading screen exit when no event_flag was detected (death, respawn, fast travel, quit-out). All fields are optional. The server tries grace lookup first, then falls back to map_id-based resolution.

```json
{
  "type": "zone_query",
  "igt_ms": 60000,
  "grace_entity_id": 10002950,
  "map_id": "m10_00_00_00",
  "position": [100.0, 50.0, 200.0],
  "play_region_id": 12345
}
```

| Field             | Type                        | Description                                                  |
| ----------------- | --------------------------- | ------------------------------------------------------------ |
| `igt_ms`          | `integer`                   | In-game time in milliseconds at the moment of the query      |
| `grace_entity_id` | `integer \| null`           | Grace entity ID captured by the warp hook during fast travel |
| `map_id`          | `string \| null`            | Map ID string (e.g. `m10_00_00_00`) for map-based fallback   |
| `position`        | `[number, number, number]?` | Player position `[x, y, z]` (reserved for future use)        |
| `play_region_id`  | `integer \| null`           | Play region ID (reserved for future use)                     |

**Response:** The server sends a `zone_update` (unicast) if the query resolves to a node in the current seed's graph. No response if unresolvable or ambiguous.

**Backtrack recording:** When the resolved node differs from `current_zone`, the server appends a new `zone_history` entry (recording the backtrack via death/teleport/quit-out) and emits a `zone_history` snapshot to spectators. First visits trigger `leaderboard_update`; revisits trigger `player_update`. If the resolved node matches `current_zone`, only `current_zone` is refreshed (no history append, no `zone_history` snapshot).

#### `finished`

Player finished the race. Server-side schema only; the mod does not send this directly. Instead, finishing is handled automatically when the server receives an `event_flag` matching the seed's `finish_event`. The server does accept `finished` if sent directly, but this path is not used by the mod in practice.

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
    "seeds_released_at": null,
    "race_ends_at": null
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
    ],
    "items_spawned_flag": 1050290000
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

`event_ids`: sorted list of event flag IDs the mod should monitor. Opaque to the mod, no mapping to zones or nodes is provided. `graph_json` is always `null` for mods.

`finish_event` _(int | null)_: Flag ID for the final boss kill. The mod sends this immediately (no loading screen on boss kill). All other event flags are deferred to loading screen exit.

`spawn_items`: list of items to spawn at runtime via `func_item_inject`. Used for item types not supported by EMEVD's `DirectlyGivePlayerItem` (e.g., Gem/Ash of War, type 4). Each entry has `id` (EquipParamGem row ID) and `qty` (default 1). The mod spawns these once after game load, using `items_spawned_flag` to prevent re-giving on reconnect or game restart. `null` if no runtime-spawned items exist.

`items_spawned_flag`: (int, optional) Event flag ID for runtime item spawn prevention. When present, the mod checks this flag before spawning items, and sets it after. Persists in save file (saved flag range). `null` if not provided by graph.json (backward compat: mod skips flag check).

`latest_mod_version`: (string, optional) server release version, present only when a newer compatible mod build exists (server protocol minor ahead of the client's). The mod shows it as a transient update notice. Absent (or `null`) otherwise; old mods ignore it.

**Note:** The `race` object includes `started_at`, `seeds_released_at`, and `race_ends_at`. `started_at` is the effective gameplay start: on race launch the server sets it to `now + countdown_seconds` so the countdown window doesn't eat into the configured duration. `race_ends_at` is `null` until the race transitions to `running` (it is computed from `started_at + race_duration_minutes`); when the race starts, the server pushes a [`race_info_update`](#race_info_update) so mods that authed in `setup` pick up the now-populated value.

#### `auth_error`

Authentication failed. Connection is closed with code 4003.

```json
{
  "type": "auth_error",
  "message": "Invalid mod token"
}
```

#### `error`

Generic error during the message loop (not auth phase). Sent when a gameplay message is rejected. Examples: race not running, stale save detected (IGT too high on first `status_update`).

```json
{
  "type": "error",
  "message": "Race not running"
}
```

```json
{
  "type": "error",
  "message": "Please start a New Game to race"
}
```

#### `race_start`

Race has started. Followed immediately by a `zone_update` unicast for the start node. Includes `countdown_seconds` for a cosmetic countdown before the race effectively begins. During the countdown period, the server rejects `event_flag` messages. Clients should display a countdown (N→1→GO!) and delay event flag / status update sending. When `countdown_seconds` is `0`, there is no countdown (backward compatible).

```json
{
  "type": "race_start",
  "countdown_seconds": 10
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

`zone_history` is always `null` in `leaderboard_update` broadcasts (and in `player_update`). Clients bootstrap the full history from `race_state` on the spectator endpoint, then apply `zone_history` snapshots to track new visits and death attribution. Mods don't consume `zone_history`, so they never need a fresh copy. See [zone_history updates](#zone_history-updates).

**Daily races (per-mod projection).** Daily races (those with `daily_date != null`) replay against asynchronous ghosts, so a finished or concurrent runner must appear as if racing in parallel with the local viewer. For these races, web spectators still receive the real-state payload, but each connected mod whose participant is currently `playing` receives a payload tailored to its own IGT: every other participant's `status`, `current_zone`, `current_layer`, `igt_ms`, `death_count` and `zone_history` are projected to the viewer's IGT. The wire format is identical to a regular `leaderboard_update`; the mod does not know it is consuming a projection. Non-playing mods (ready, registered, finished, abandoned) receive the same real payload as spectators, so projection is suspended outside the viewer's `playing` window. See `server/speedfog_racing/websocket/race/projection.py`.

#### `race_status_change`

Race status changed. Broadcast to all mods and spectators. Includes `started_at` and `countdown_seconds` when transitioning to `running`.

```json
{
  "type": "race_status_change",
  "status": "running",
  "started_at": "2026-02-19T14:00:00Z",
  "countdown_seconds": 10
}
```

| Field               | Type      | Description                                                                                                                |
| ------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `status`            | `string`  | New race status (`running`, `finished`)                                                                                    |
| `started_at`        | `string?` | ISO 8601 timestamp of effective gameplay start (already shifted by `countdown_seconds`); included when status is `running` |
| `countdown_seconds` | `int?`    | Cosmetic countdown duration in seconds, included for `running`                                                             |

**Note:** The mod does not currently consume `started_at` from this message; the field is silently ignored by serde. The mod refreshes the rest of its cached RaceInfo from a separate `race_info_update` broadcast (see below).

#### `race_info_update`

A refreshed [RaceInfo](#raceinfo) snapshot broadcast to all mods and spectators whenever a race-level field changes outside the normal lifecycle messages. Receivers replace their cached RaceInfo wholesale (no per-field merge). Emitted in three situations:

- The organizer issues a `PATCH /races/{id}` that mutates a tracked field (`name`, `is_public`, `open_registration`, `max_participants`, `scheduled_at`, `late_join_window_minutes`, `race_duration_minutes`, `private_dag`, `custom_rules`). No-op PATCHes do not broadcast.
- The race transitions from `setup` to `running` (`POST /races/{id}/start`). At that point `started_at` becomes non-null and `race_ends_at` becomes computable; the broadcast lets mods that authed in `setup` pick up the new deadlines without reconnecting.
- The seed is rerolled (`POST /races/{id}/reroll-seed`). `race_state` carries the new full seed to spectators, but mods are not on that channel, so the `race_info_update` is what delivers the new `seed_id` to a connected mod, letting it raise the "SEED OUTDATED" banner mid-session (not just at the next `auth_ok`).

```json
{
  "type": "race_info_update",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "running",
    "started_at": "2026-02-19T14:00:00Z",
    "seeds_released_at": "2026-02-19T13:55:00Z",
    "race_ends_at": "2026-02-19T18:00:00Z"
  }
}
```

| Field  | Type     | Description                       |
| ------ | -------- | --------------------------------- |
| `race` | `object` | Full [RaceInfo](#raceinfo) object |

#### `zone_update`

Unicast to the originating mod after an `event_flag` is processed, after `zone_query` (fast travel), after `auth_ok` (reconnect during a running race), or after `race_start` (for the start node). Contains the entered zone's display name, tier, layer, exits with discovery status, and whether this is the player's first visit to this zone.

```json
{
  "type": "zone_update",
  "node_id": "graveyard_cave_e235",
  "display_name": "Cave of Knowledge",
  "tier": 5,
  "original_tier": 8,
  "layer": 2,
  "is_first_visit": true,
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

| Field                | Type     | Description                                                                    |
| -------------------- | -------- | ------------------------------------------------------------------------------ |
| `node_id`            | `string` | DAG node ID                                                                    |
| `display_name`       | `string` | Human-readable zone name (localized)                                           |
| `tier`               | `int?`   | Node tier in the current graph layout (null for start node)                    |
| `original_tier`      | `int?`   | Original tier before graph rebalancing (null if same as `tier` or unknown)     |
| `layer`              | `int?`   | 0-indexed layer of this zone in the graph (used by mod to detect backtracking) |
| `is_first_visit`     | `bool`   | Whether this is the player's first visit to this zone (false on reconnect)     |
| `exits`              | `list`   | Fog gates leaving this zone                                                    |
| `exits[].text`       | `string` | Fog gate label text (may include `[Zone Name]` annotation after i18n)          |
| `exits[].to_name`    | `string` | Display name of the destination zone                                           |
| `exits[].discovered` | `bool`   | Whether the destination has been visited (in zone_history)                     |

#### `event_flag_ack`

Unicast ACK sent to the originating mod after an `event_flag` has been durably committed, or after a replay with the same `message_id` has been recognized as already committed.

```json
{
  "type": "event_flag_ack",
  "message_id": 17
}
```

| Field        | Type      | Description                                 |
| ------------ | --------- | ------------------------------------------- |
| `message_id` | `integer` | Echo of the client-supplied `event_flag` id |

#### `death_counts`

Aggregated death counts per DAG node across all race participants. Broadcast to all mods when a death is attributed (delta > 0). Also sent as a unicast on reconnect if any deaths have occurred.

The mod uses these counts with `death_flags` from `SeedInfo` to set EMEVD event flags that control in-game bloodstain visibility. Three thresholds: low (1+), med (3+), high (5+).

```json
{
  "type": "death_counts",
  "counts": {
    "node_a": 4,
    "node_b": 1
  }
}
```

`counts`: sparse dict of node_id to total deaths. Nodes with zero deaths are omitted. Deaths only increase during a race.

#### `player_update`

Single player update, broadcast to all connections (mods + spectators). See also the [Spectator Connection](#websocket-spectator-connection) section.

**Daily races (mods skipped).** On daily races (`daily_date != null`), `player_update` is routed to spectators only. Mods consume `player_update` by overwriting the matching row in their local participant list, which would desync that single row from the projected leaderboard until the next `leaderboard_update` tick (~1s). Mods receive their per-viewer projection through `leaderboard_update` instead.

#### `daily_streak_update`

Daily-streak progression for a user, unicast by the server to **every** connection of that user on the race room, including the mod connection, after a daily run resolves.

```json
{
  "type": "daily_streak_update",
  "current": 7,
  "best": 12,
  "freeze_count": 2,
  "freeze_consumed_for": "2026-06-06"
}
```

The mod has no use for this message and **intentionally ignores it**: it is modeled as a no-op `ServerMessage` variant so it deserializes cleanly instead of tripping a parse-failure warning on every broadcast. The payload (consumed by the web clients) is dropped by the mod's catch-all match arm.

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
- The server does not track pong responses; it relies on TCP-level `WebSocketDisconnect` for cleanup

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

Sent immediately after connecting. If the user is not logged in, send `no_auth` instead so the server can skip the grace period and deliver `race_state` without delay.

```json
{
  "type": "auth",
  "token": "user_api_token"
}
```

#### `no_auth`

Sent immediately after connecting when the user is not logged in. Signals the server to skip the auth grace period timeout (2s) and proceed to sending `race_state` right away. If neither `auth` nor `no_auth` is sent, the server waits the full grace period before proceeding.

```json
{
  "type": "no_auth"
}
```

#### `chat`

Send a chat message to a channel. Requires authentication. Rate-limited to 500 characters. Persisted to the database.

```json
{
  "type": "chat",
  "channel": "participants",
  "message": "glhf"
}
```

| Field     | Type     | Description                       |
| --------- | -------- | --------------------------------- |
| `channel` | `string` | `"participants"` or `"public"`    |
| `message` | `string` | Message text (max 500 characters) |

See [Chat System](#chat-system) for channel access rules. Sends that violate the matrix are silently dropped by the server.

#### `request_chat_history`

Ask the server to (re)send chat history for a channel. The frontend emits this when its locally-computed access transitions from locked to readable. The server revalidates against the [Chat System](#chat-system) matrix; on accept it replies with a `chat_history` message for the requested channel, otherwise the request is silently dropped.

```json
{
  "type": "request_chat_history",
  "channel": "public"
}
```

| Field     | Type     | Description                    |
| --------- | -------- | ------------------------------ |
| `channel` | `string` | `"participants"` or `"public"` |

For the `public` channel the server also refreshes the connection's cached participant status from the database before evaluating access, so a participant who finished mid-race no longer needs to reconnect to see the unlock.

### Server → Client

#### `race_state`

Sent immediately on connection (after optional auth). Full race state. Also re-sent on status transitions (SETUP → RUNNING, RUNNING → FINISHED) and when seeds are released, with recomputed DAG access. On the initial connection it is immediately followed by a unicast `leaderboard_update` so the client has the gap inputs (`leader_splits` + `layer_entry_igt`) that `race_state` omits; see [Gap Timing](#gap-timing).

```json
{
  "type": "race_state",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "running",
    "started_at": "2026-02-19T14:00:00Z",
    "seeds_released_at": "2026-02-19T13:55:00Z",
    "race_ends_at": "2026-02-19T15:30:00Z"
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

`zone_history` is always included (as a list, possibly empty) in `race_state` for every participant. It seeds the client's local history store, which is then kept in sync via `zone_history` snapshot messages. See [zone_history updates](#zone_history-updates).

Each participant carries `daily_points` (integer) only on a **finished daily**: it is the per-rank Daily Seed score `round(50 * (n - r + 1) / n)` for qualified participants, and `null` for non-qualified ones and for any non-daily or still-running race. It is computed server-side (single source: `daily_points_service.daily_points_for_race`) and feeds the `+XX` indicator in the web leaderboard. The high-frequency `player_update` and `leaderboard_update` messages do not carry it (a finished daily emits no such updates).

#### `player_update`

Single player update. **Broadcast to all connections** (mods + spectators). Triggered by periodic `status_update` from mod, revisited nodes, or `zone_query` resolution. Includes `layer_entry_igt` so mods can recompute gaps client-side. `zone_history` is always `null` in this message (see [zone_history updates](#zone_history-updates)).

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

Race status changed. Broadcast to all mods and spectators. On the `setup` -> `running` transition the server also emits a [`race_info_update`](#race_info_update) (and a `race_state` push) so receivers can refresh deadlines.

```json
{
  "type": "race_status_change",
  "status": "finished"
}
```

#### `race_info_update`

Same payload as the [mod variant](#race_info_update). Broadcast to spectators when a race-level field changes via `PATCH /races` or when the race starts. Spectators also receive the same data through `race_state` on transitions that already trigger a full state push (start, finish, seed release), so this message is mostly relevant for in-place edits while the race is live.

#### `spectator_count`

Broadcast to all spectators when spectator count changes (connect/disconnect).

```json
{
  "type": "spectator_count",
  "count": 5
}
```

#### `zone_history`

Full `zone_history` snapshot for a single participant. Broadcast to spectators only (mods don't consume `zone_history`). Emitted whenever the server's view of a participant's `zone_history` changes: new entry appended (spawn, fog gate, zone_query backtrack) or existing entry's `deaths` count updated via death attribution.

```json
{
  "type": "zone_history",
  "participant_id": "uuid",
  "history": [
    { "node_id": "start_node", "igt_ms": 0, "type": "spawn" },
    { "node_id": "m60_51_36_00", "igt_ms": 123456, "type": "fog", "deaths": 2 }
  ]
}
```

| Field            | Type     | Description                                                                      |
| ---------------- | -------- | -------------------------------------------------------------------------------- |
| `participant_id` | `string` | Participant UUID (or training session UUID)                                      |
| `history`        | `array`  | Full current `zone_history` for this participant (same shape as in `race_state`) |

Clients replace their local `zone_history[participant_id]` with the payload. Sending the full list is self-healing: a client that missed an earlier message still ends up with the correct state on the next emission (no per-entry upsert or sequence tracking needed).

#### `daily_streak_update`

Unicast to a single user on a daily race when their daily streak state changes. Emitted on the qualification crossing (the participant's `zone_history` length just reached 2) and on the explicit-abandon trigger (the player gave up on the current daily without having qualified, so the close-day branch fired immediately). Routed to **every** connection of `user_id` on the race room: their mod connection plus all open spectator tabs. Never broadcast to other spectators; never sent on non-daily races.

```json
{
  "type": "daily_streak_update",
  "current": 7,
  "best": 42,
  "freeze_count": 1,
  "freeze_consumed_for": null
}
```

| Field                 | Type           | Description                                                                                                                                                          |
| --------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `current`             | `int`          | Current consecutive-daily streak length after the update                                                                                                             |
| `best`                | `int`          | Best streak length ever achieved by this user                                                                                                                        |
| `freeze_count`        | `int`          | Number of freeze tokens available to protect a future missed day                                                                                                     |
| `freeze_consumed_for` | `date \| null` | The `daily_date` (YYYY-MM-DD) whose `freeze_protected` flag just flipped to true, when this message reports a freeze consumption. `null` on qualification crossings. |

The message is fire-and-forget: it is not retried, and the canonical state is always re-fetched from REST on the next page load. The mod ignores it (streak state is web-only); the field appears in the catalog because the dispatcher writes to every connection of the user, including the mod.

#### `chat_message`

A chat message broadcast to the connections that have read access to the channel (see [Chat System](#chat-system)). Sent when a user posts in a channel, or when the server generates a system notification (e.g., player finished or abandoned).

```json
{
  "type": "chat_message",
  "channel": "public",
  "username": "player1",
  "display_name": "Player1",
  "avatar_url": "https://...",
  "role": "participant",
  "dominant_trait": "rusher",
  "message": "gg",
  "timestamp": "2026-02-19T14:30:00Z"
}
```

| Field            | Type      | Description                                                                         |
| ---------------- | --------- | ----------------------------------------------------------------------------------- |
| `channel`        | `string`  | `"participants"` or `"public"`                                                      |
| `username`       | `string`  | Twitch username (empty string for system messages)                                  |
| `display_name`   | `string?` | Twitch display name (`null` for system messages)                                    |
| `avatar_url`     | `string?` | Twitch avatar URL (`null` for system messages)                                      |
| `role`           | `string`  | `"organizer"`, `"admin"`, `"caster"`, `"participant"`, `"spectator"`, or `"system"` |
| `dominant_trait` | `string?` | Player's dominant trait (e.g., `"rusher"`, `"explorer"`), `null` if none            |
| `message`        | `string`  | Message text                                                                        |
| `timestamp`      | `string`  | ISO 8601 timestamp                                                                  |

**System messages** (`role: "system"`): Notifications generated by the server for lifecycle events (race start/finish, player finish/abandon, seed reroll/release, join/leave, etc.). They are persisted to the database and replayed in `chat_history` on reconnect. Some events broadcast only to the public channel (e.g. player finish/abandon), others to both channels (race start/finish). The frontend treats them as ambient context: they are excluded from the chat sidebar's unread badge so only real user messages raise a notification.

#### `chat_history`

Sent on connection for each accessible channel. Contains all persisted messages for that channel. Also sent in response to a [`request_chat_history`](#request_chat_history) message when a viewer's local access for that channel has just unlocked.

```json
{
  "type": "chat_history",
  "channel": "public",
  "messages": [
    {
      "type": "chat_message",
      "channel": "public",
      "username": "player1",
      "...": "..."
    }
  ]
}
```

| Field      | Type     | Description                     |
| ---------- | -------- | ------------------------------- |
| `channel`  | `string` | `"participants"` or `"public"`  |
| `messages` | `list`   | Array of `chat_message` objects |

#### `ping`

Heartbeat ping. Sent every 30 seconds.

```json
{
  "type": "ping"
}
```

---

## Chat System

Chat operates on the spectator WebSocket (`/ws/race/{race_id}`). Two channels with different access rules. The server is authoritative for every send, history load, and broadcast; the frontend mirrors these rules locally to drive the UI but cannot grant access the server denies.

### Participants channel

Readable and writable by authenticated viewers with a race role: participant, organizer, admin, or caster. Anonymous viewers and authenticated viewers without a race role never receive history or broadcasts on this channel.

### Public channel

Readability follows the matrix below. Race role (organizer, admin, caster) does NOT unlock public chat by itself: privileged users follow the same rules as authenticated spectators. Writability adds two requirements on top of readability: the viewer must be authenticated and must not be an active participant.

| Race state                  | Viewer                         | Public chat |
| --------------------------- | ------------------------------ | ----------- |
| `SETUP`                     | anyone                         | locked      |
| `RUNNING`, late-join open   | active participant             | locked      |
| `RUNNING`, late-join open   | finished/abandoned participant | yes         |
| `RUNNING`, late-join open   | spectator (incl. priv. role)   | locked      |
| `RUNNING`, late-join closed | active participant             | locked      |
| `RUNNING`, late-join closed | finished/abandoned participant | yes         |
| `RUNNING`, late-join closed | spectator (incl. priv. role)   | yes         |
| `FINISHED`                  | anyone                         | yes         |

When a participant finishes or abandons mid-race the server flips the connection's cached status so subsequent broadcasts pass the filter. Past public messages are pulled by the client via [`request_chat_history`](#request_chat_history) once it detects the local transition. Late-join window unlocks for a connected spectator are also driven by the client: it ticks its own clock against the deadline and sends `request_chat_history` when the window closes.

### System Messages

The server broadcasts system notifications for the following events:

| Event                       | Channels              | Message                                                      |
| --------------------------- | --------------------- | ------------------------------------------------------------ |
| Race starts                 | participants + public | `"The race has started."`                                    |
| Race finishes               | public                | `"The race has finished."`                                   |
| Player joins                | participants          | `"{display_name} has joined the race"`                       |
| Player leaves               | participants          | `"{display_name} has left the race"`                         |
| Player removed by organizer | participants          | `"{display_name} has been removed from the race"`            |
| Player finishes             | public                | `"{display_name} has finished the race!"`                    |
| Player abandons             | public                | `"{display_name} has abandoned the race."`                   |
| Player inactive (abandoned) | public                | `"{display_name} has abandoned the race due to inactivity."` |

For daily seed races (`Race.daily_date` set), the wording is adjusted so the chat reads naturally for an asynchronous individual format. Events that cannot fire on a daily (start, leave, removed) or that are suppressed on a daily (inactivity-abandon, see `inactivity_monitor.py`) keep no daily variant.

| Event           | Channels     | Message                                      |
| --------------- | ------------ | -------------------------------------------- |
| Daily finishes  | public       | `"The daily seed is over."`                  |
| Player joins    | participants | `"{display_name} started the daily seed"`    |
| Player finishes | public       | `"{display_name} finished the daily seed!"`  |
| Player abandons | public       | `"{display_name} abandoned the daily seed."` |

System messages use `role: "system"` with empty `username`, `null` `display_name` and `avatar_url`.

The "Channels" column lists the channel a message is persisted to. Live delivery on `public` still goes through the per-connection access filter: viewers for whom the public channel is locked at broadcast time will only see the message after their access unlocks and they pull `chat_history`. This is why "Race starts" lands on `public` even though no public viewer is unlocked at that moment.

### Persistence

Both user-sent and system messages are persisted to the database (indexed by `race_id`, `channel`, `created_at`) and replayed as `chat_history` on connection or in response to a `request_chat_history`.

---

## Training Mode

Solo practice mode. Uses the same protocol messages as competitive races but with simplified single-player behavior.

### REST API

| Method | Endpoint                         | Auth             | Description                                                                            |
| ------ | -------------------------------- | ---------------- | -------------------------------------------------------------------------------------- |
| POST   | `/api/training`                  | Bearer           | Create training session (`{ pool_name }`)                                              |
| GET    | `/api/training`                  | Bearer           | List user's training sessions                                                          |
| GET    | `/api/training/{id}`             | -                | Training session detail (public read-only)                                             |
| POST   | `/api/training/{id}/abandon`     | Bearer           | Abandon session (ACTIVE → ABANDONED)                                                   |
| GET    | `/api/training/{id}/pack-ticket` | Bearer           | Mint a short-lived download ticket for the training pack (same gating as the download) |
| GET    | `/api/training/{id}/pack`        | Bearer or ticket | Download training seed pack (ZIP with `training = true`)                               |

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

Server → Client messages: `auth_ok`, `auth_error`, `error`, `race_start`, `zone_update`, `leaderboard_update`, `race_status_change`, `ping` (same format as mod WS). `death_counts` is **not** sent in training sessions (racing only, since there is only one participant in training).

### WebSocket: Training Spectator

**Endpoint:** `WS /ws/training/{session_id}/spectate`

Live web UI updates during training. Accepts both authenticated and anonymous spectators.

- **Auth handshake required**: An `auth` message must be sent within 5 seconds (connection closed with code 4001 otherwise), but the `token` field is optional (omit it for anonymous access)
- **`race_state`**: Sent on connect with full graph (always included for training), seed info, and participant state (including full `zone_history`)
- **`leaderboard_update`**: Single-participant update on status/zone changes (with `zone_history` omitted)
- **`zone_history`**: Full zone_history snapshots for the session (same shape as the race spectator endpoint)
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

| Field                       | Type      | Description                                                                                                                                                                       |
| --------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                        | `string`  | Participant UUID                                                                                                                                                                  |
| `twitch_username`           | `string`  | Twitch login name                                                                                                                                                                 |
| `twitch_display_name`       | `string?` | Twitch display name                                                                                                                                                               |
| `status`                    | `string`  | Participant status (see above)                                                                                                                                                    |
| `current_zone`              | `string?` | Current DAG node ID (e.g. `m60_51_36_00`)                                                                                                                                         |
| `current_layer`             | `int`     | Current layer in the DAG (0 = start)                                                                                                                                              |
| `current_layer_tier`        | `int?`    | Tier of the current node (computed from graph)                                                                                                                                    |
| `igt_ms`                    | `int`     | In-game time in milliseconds                                                                                                                                                      |
| `death_count`               | `int`     | Total deaths                                                                                                                                                                      |
| `color_index`               | `int`     | Player color assignment (0-indexed)                                                                                                                                               |
| `mod_connected`             | `bool`    | Whether the mod client is currently connected                                                                                                                                     |
| `zone_history`              | `list?`   | Zone visit history: included in `race_state` bootstrap, `null` in `leaderboard_update`/`player_update` broadcasts (see [zone_history updates](#zone_history-updates))             |
| `gap_ms`                    | `int?`    | Gap to the leader in milliseconds (see below)                                                                                                                                     |
| `layer_entry_igt`           | `int?`    | Player's IGT when entering their current layer                                                                                                                                    |
| `equipped_badge_id`         | `string?` | Logical id of the badge the user has equipped (web resolves the icon via `GET /api/rewards/catalog`). `null` when no badge is equipped.                                           |
| `equipped_name_template_id` | `string?` | Logical id of the active name template (web resolves `background_css` via the catalog). `null` or `"default"` means no override; render with the default style.                   |
| `name_template`             | `object?` | Pre-resolved render payload for the mod overlay: `{ color?: "#RRGGBB", gradient?: ["#RRGGBB","#RRGGBB"] }`. `null` for default users; backgrounds are not transmitted (web-only). |

`zone_history` entries: `{ "node_id": "m60_51_36_00", "igt_ms": 123456, "deaths"?: 3, "type"?: "spawn"|"fog"|"backtrack", "message_id"?: 17, "weapons"?: [int|null, int|null] }`. A node may appear multiple times if the player backtracks; each visit is a separate entry with its own `igt_ms` and optional `deaths` count. The `type` field indicates entry source: `"spawn"` (initial placement on first status_update), `"fog"` (fog gate traversal via event_flag), or `"backtrack"` (zone_query detection from death/teleport/quit-out). `message_id` is optional and only present on newer `"fog"` entries; it is used server-side to make replayed `event_flag` messages idempotent after reconnect. `weapons` is `[left_hand, right_hand]` runtime weapon IDs (last-write-wins per zone via `status_update`), filtered to the tracked melee/ranged set; absent on entries pre-dating the feature or when the mod didn't report a value. Entries without `type` are treated as `"fog"` for backward compatibility.

`name_template` example:

```json
{
  "name_template": { "color": null, "gradient": ["#FFFFFF", "#FFD700"] }
}
```

The mod parses the hex strings to RGBA on receipt and caches the resolved colors per participant; the per-frame leaderboard render reads from that cache. The `default` template is intentionally serialized as `null` (rather than a solid white payload) so the mod and web fall back to the surrounding status color, preserving the functional readability of the leaderboard.

**Note:** The mod's Rust `ParticipantInfo` struct only declares a subset of these fields (`id`, `twitch_username`, `twitch_display_name`, `status`, `current_zone`, `current_layer`, `current_layer_tier`, `igt_ms`, `death_count`, `gap_ms`, `layer_entry_igt`, `name_template`). Extra fields like `color_index`, `mod_connected`, `zone_history`, `equipped_badge_id`, and `equipped_name_template_id` are present on the wire but silently ignored by serde.

### RaceInfo

Included in `auth_ok`, `race_state`, and `race_info_update` messages. The full payload is rebroadcast on change rather than diffed, so receivers replace their cached copy wholesale.

| Field               | Type      | Description                                                                                                 |
| ------------------- | --------- | ----------------------------------------------------------------------------------------------------------- |
| `id`                | `string`  | Race UUID                                                                                                   |
| `name`              | `string`  | Race name                                                                                                   |
| `status`            | `string`  | Race status (see above)                                                                                     |
| `started_at`        | `string?` | ISO 8601 timestamp of effective gameplay start (server sets it to `now + countdown_seconds` at race launch) |
| `seeds_released_at` | `string?` | ISO 8601 timestamp when seeds were released                                                                 |
| `race_ends_at`      | `string?` | ISO 8601 timestamp when the race ends (late-join and time limit cutoff)                                     |
| `seed_id`           | `string?` | Current seed UUID; lets the mod detect a stale loaded seed pack (e.g. after a reroll)                       |

**Note:** The mod's overlay reads `id`, `name`, `status`, `race_ends_at` (countdown warning when less than 1h remains), and `seed_id` (compared against the configured pack to raise the "SEED OUTDATED" banner). Other fields are present on the wire but currently unused by the mod.

### SeedInfo

Included in `auth_ok` (mod) and `race_state` (spectator):

| Field                | Type      | Mod | Spectator | Description                                                  |
| -------------------- | --------- | --- | --------- | ------------------------------------------------------------ |
| `seed_id`            | `string?` | yes | yes       | Seed UUID                                                    |
| `total_layers`       | `int`     | yes | yes       | Number of layers in the DAG                                  |
| `graph_json`         | `object?` | no  | yes\*     | Full graph for DAG visualization (\* see DAG rules)          |
| `total_nodes`        | `int?`    | no  | yes       | Total number of nodes in the DAG                             |
| `total_paths`        | `int?`    | no  | yes       | Total number of paths in the DAG                             |
| `event_ids`          | `int[]`   | yes | no        | Event flag IDs to monitor                                    |
| `finish_event`       | `int?`    | yes | no        | Final boss kill flag ID                                      |
| `spawn_items`        | `list`    | yes | no        | Items for runtime spawning                                   |
| `items_spawned_flag` | `int?`    | yes | no        | Event flag ID for runtime item spawn prevention              |
| `death_flags`        | `object`  | yes | no        | Death marker flags per cluster `{node_id: [low, med, high]}` |

### Leaderboard Sorting

Participants in `leaderboard_update` are pre-sorted by priority:

1. **Finished**: by `igt_ms` ascending (fastest first)
2. **Playing**: by `current_layer` descending (furthest first), then layer entry IGT ascending
3. **Ready**
4. **Registered**
5. **Abandoned**

Both the in-game mod and the web frontend render participants in this server-provided order; neither re-sorts. The server is the single source of ranking truth, which keeps the two displays consistent and avoids the tie-break flicker a client-side re-sort on the ever-changing total `igt_ms` would cause for near-tied playing rows.

### zone_history updates

`zone_history` can grow to ~50 KB per participant (up to 1000 entries × ~50 bytes), which made full-state rebroadcast in every `leaderboard_update` / `player_update` a dominant bandwidth cost. The protocol carves `zone_history` out into its own dedicated snapshot message instead:

- **Bootstrap**: `race_state` (spectator) carries the full `zone_history` for every participant. Sent on initial connection, on race status transitions, on seed release, and on participant add/remove. Clients copy this into a local `zoneHistoryByParticipant` store.
- **Broadcasts**: `leaderboard_update` and `player_update` always carry `zone_history: null`. When a client receives one, it must preserve the locally-held `zone_history` rather than overwriting it with `null`.
- **Snapshots**: each server-side change to a participant's `zone_history` (append or death-attribution update) emits a `zone_history` message carrying the full current list. The client replaces its local copy. Because the payload is the full list each time, a client that missed an earlier message self-heals on the next emission.

Emission sites (server-side):

| Trigger                                              | Change                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------- |
| First `status_update` (READY → PLAYING, spawn node)  | Appends `{type: "spawn", igt_ms: 0, …}`                     |
| `status_update` with `delta > 0` (death attribution) | Bumps `deaths` on the most recent entry at `current_zone`   |
| `event_flag` (fog gate traversal)                    | Appends `{type: "fog", …}` (first visit and revisit alike)  |
| `zone_query` (backtrack via death/teleport/quit-out) | Appends `{type: "backtrack", …}` when resolved node differs |

Mods never receive `zone_history` snapshots (they don't consume `zone_history`). The training spectator endpoint (`/ws/training/{id}/spectate`) uses the same pattern with the training session UUID as `participant_id`.

**No-ops**: mod reconnects don't emit any `zone_history` event (the state is unchanged, the reconnecting mod gets a unicast `zone_update` and `death_counts`). Race/training finish also does not emit a snapshot: instead the server re-broadcasts a fresh `race_state` with the full `zone_history`.

**Rollout caveat**: old clients running against a new backend see `null` `zone_history` in high-frequency broadcasts and ignore unknown `zone_history` messages. Their local DAG view freezes at pre-deploy state, while the rest of the UI (IGT, deaths, layer, gaps) keeps updating. A page reload restores full behavior. Backend and frontend must ship together.

### Gap Timing

Gap timing uses a LiveSplit-style formula. The server computes `gap_ms` and sends `leader_splits` + `layer_entry_igt`; both the mod and the web frontend ignore the `gap_ms` snapshot and recompute the gap client-side from those inputs (the mod at frame rate, the web on each store update). The server `gap_ms` field is retained on the wire for contract compatibility.

#### Server-side (`gap_ms`)

Computed during `broadcast_leaderboard` for web spectators:

- **Leader:** `null`
- **Playing (within budget):** `player_layer_entry_igt - leader_splits[current_layer]`, fixed entry delta while the player's IGT is within the leader's time budget on the layer
- **Playing (exceeded budget):** `igt_ms - leader_splits[current_layer + 1]`, gap grows once the player exceeds the leader's exit IGT for that layer
- **Playing (leader on same layer):** entry delta only (no exit split available)
- **Finished:** `igt_ms - leader_igt_ms`, direct time delta
- **Ready / Registered / Abandoned:** `null`

#### Client-side (mod and web)

The mod ignores `gap_ms` and recomputes gaps locally each frame using `leader_splits` + `layer_entry_igt`. For the local player, the mod substitutes the real-time local IGT (read from game memory) instead of the server's snapshot `igt_ms`. For other players, the mod uses their server-provided `igt_ms` directly; gaps step in discrete increments aligned with the server's `player_update` cadence (~1s).

The web frontend recomputes the same gap in `web/src/lib/gap.ts` (a direct port of the mod/server formula), driven by the race store from the retained `leader_splits` + each participant's `layer_entry_igt` + live `igt_ms`. It has no local-memory IGT, so it uses the server snapshot `igt_ms` for every player including the viewer; gaps refresh on each `leaderboard_update` / `player_update` tick.

`race_state` carries no `leader_splits` / `layer_entry_igt`, so the spectator endpoint unicasts a `leaderboard_update` immediately after the initial `race_state` (`send_leaderboard_state`); a freshly connected web client therefore has the gap inputs at once instead of waiting for the next layer-crossing broadcast. This mirrors the mod, whose own connection triggers a room-wide leaderboard broadcast. Because `leader_splits` is rebuilt from the leader's `zone_history`, it is also populated for finished races, so the leaderboard shows each finisher's delta to the winner. Only a pre-race leaderboard (no leader yet) has no gap.

#### Color coding

- **Negative gap** (ahead of leader's pace): green (`-M:SS`)
- **Positive gap** (behind leader's pace): soft red (`+M:SS`)
- **Zero gap**: default text color

The web leaderboard page (`Leaderboard.svelte`) diverges: it formats the gap with `formatGapCompact` (degressive precision: `+M:SS` under 10 min, `+Mm` under 1 h, `+HhMM` from 1 h) and draws a positive gap in gold (`--color-gold`), keeping red for the death count alone and distinguishing the gap from the grey IGT of in-progress runs. Negative gaps stay green. The in-game mod and the OBS overlay keep the verbatim `formatGap` (`+H:MM:SS`) and the colors above.

#### Leader splits

`build_leader_splits(zone_history, graph_json)` walks the leader's `zone_history` and builds `{layer: first_igt_at_layer}`. Skips entries whose `node_id` is not in the graph. Deduplicates by taking the first IGT at each layer. Sent as `leader_splits` in `leaderboard_update`.

`broadcast_player_update()` omits `gap_ms` (computing it requires the full sorted participant list) but includes `layer_entry_igt` so mods can compute gaps client-side.

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
| `4000` | Replaced by a new connection (same participant)       | Mod, Training                 |
| `4001` | Auth timeout (no message received within deadline)    | Mod, Training, Training Spec  |
| `4003` | Auth error (invalid JSON/message, auth fail, version) | Mod, Training, Training Spec  |
| `4004` | Resource not found (race or session doesn't exist)    | Spectator, Training Spectator |

### Security Notes

**Spectator WebSocket authentication (M9):** Spectator connections (`/ws/race/{race_id}`) are intentionally unauthenticated by default. Race leaderboard data is public by design. Optional auth within a 2-second grace period enables role-based DAG visibility during SETUP, which prevents anonymous viewers from seeing the graph before the race starts. During `running` and `finished`, all spectators see the DAG. Clients should send `no_auth` when not logged in to skip the grace period. This is an accepted design trade-off.

**Private races are unlisted, not access-controlled (M11):** `is_public=False` only hides a race from the `/api/races` feed. Its detail (`GET /api/races/{id}`) and spectator WebSocket are still reachable by anyone holding the race ID, by design (share-by-direct-link). DAG and per-runner spoiler visibility follow the same status-based rules as public races (see above), independent of `is_public`. This is an accepted trade-off; there is no members-only enforcement for private races.

**CSRF (M5):** Auth tokens are stored in `localStorage` and sent via `Authorization` header, not auto-attached cookies. This makes CSRF attacks infeasible since the token is never sent automatically. If token storage changes to cookies in the future, CSRF protection must be added.

**localStorage vs cookies (M10):** Tokens in `localStorage` are vulnerable to XSS but not to CSRF. The codebase has no `{@html}` usage (preventing XSS vectors), and CSP headers restrict script sources. This trade-off is accepted for the current threat model.

### Race State Gating

Gameplay messages (`status_update`, `event_flag`, `zone_query`, `finished`) are only accepted when the race status is `running`. This is enforced at three layers:

1. **Server:** Each handler checks `race.status == RUNNING` before processing. If the race is not running, the server responds with an `error` message and discards the payload.
2. **Mod (outgoing):** The mod gates `status_update` and `event_flag` sends behind `is_race_running()`. Event flags detected before the race starts are buffered and sent once the race transitions to running.
3. **Mod (overlay):** A colored banner shows the race state: orange "WAITING FOR START" (setup), green "GO!" for 3 seconds (running), and green "RACE FINISHED" (finished).

The `ready` and `pong` messages are not gated; they are valid in any state.

**Participant status gating:** Beyond race status, `event_flag` and `zone_query` require `participant.status == PLAYING`. Messages from READY, REGISTERED, FINISHED, or ABANDONED participants are silently dropped.

**Fresh save validation:** On the READY to PLAYING transition (first `status_update`), the server checks `igt_ms <= 15000`. If the IGT is too high (player loaded a pre-existing save), the server sends an `error` message and the participant stays in READY. The mod displays the error on the overlay via `set_status()`. Self-healing: starting a New Game resets IGT. Training mode applies the same check on first `zone_history` initialization.

### Zone Tracking

Zone tracking uses EMEVD event flags. The mod monitors a list of event flag IDs (received via `auth_ok`) and reports transitions via `event_flag` messages. The server resolves flag IDs to DAG nodes using the seed's `event_map`.

**Per-connection flags:** Each connection in `graph.json` has a unique `flag_id`. The `event_map` is many-to-one: multiple flags can map to the same node (e.g., when a shared entrance merge has 3 branches entering the same cluster). The mod receives all flag IDs as an opaque list; the server performs the flag → node resolution. This ensures the mod detects each fog gate traversal independently, even when the destination cluster was previously visited via a different branch.

### Runtime Item Spawning

Care package items of type 4 (Gem/Ash of War) cannot be given via EMEVD's `DirectlyGivePlayerItem`. Instead, the server extracts them from `graph_json.care_package` and sends them in `auth_ok.seed.spawn_items`. The mod spawns them at runtime using `func_item_inject` after the game is fully loaded (MapItemMan initialized). The `items_spawned_flag` field (sent alongside `spawn_items`) is used to prevent re-giving items on reconnect or game restart: the mod checks the flag before spawning and sets it after. If `items_spawned_flag` is `null`, the flag check is skipped (backward compatibility).

### Broadcasting Strategy

| Event                          | Mods                                                                     | Spectators                                                           |
| ------------------------------ | ------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| Mod connects/disconnects       | `leaderboard_update`                                                     | `leaderboard_update`                                                 |
| `ready`                        | `leaderboard_update`                                                     | `leaderboard_update`                                                 |
| `status_update` (periodic)     | `player_update`                                                          | `player_update`                                                      |
| `status_update` (READY→PLAY)   | `leaderboard_update`                                                     | `leaderboard_update` + `zone_history` (spawn)                        |
| `status_update` (death delta)  | `player_update` + `death_counts`                                         | `player_update` + `zone_history` (deaths update)                     |
| `event_flag` (new node)        | `leaderboard_update`                                                     | `leaderboard_update` + `zone_history` (fog)                          |
| `event_flag` (revisit)         | `zone_update` (unicast) + `player_update`                                | `player_update` + `zone_history` (fog)                               |
| `event_flag` (finish)          | `leaderboard_update`                                                     | `race_state` + status change + `chat_message` (system)               |
| `zone_query` (same zone)       | `zone_update` (unicast) + `player_update`                                | `player_update`                                                      |
| `zone_query` (backtrack/new)   | `zone_update` (unicast) + `leaderboard_update` or `player_update`        | `leaderboard_update` or `player_update` + `zone_history` (backtrack) |
| Race starts                    | `race_start` + `zone_update` + `race_status_change` + `race_info_update` | `race_state` + `race_status_change` + `race_info_update`             |
| Race finishes                  | `race_status_change`                                                     | `race_state` + `race_status_change`                                  |
| Seeds released                 | (none)                                                                   | `race_state`                                                         |
| `PATCH /races` (field changes) | `race_info_update`                                                       | `race_info_update`                                                   |
| Spectator connects/disconnects | (none)                                                                   | `spectator_count` + `chat_history`                                   |
| Player abandons                | `leaderboard_update`                                                     | `leaderboard_update` + `chat_message` (system)                       |
| Player auto-abandoned          | `leaderboard_update`                                                     | `leaderboard_update` + `chat_message` (system)                       |
| Chat message sent              | (none)                                                                   | `chat_message` (filtered per [Chat System](#chat-system) matrix)     |

Note: `zone_history` snapshots are emitted only to spectators (mods don't consume `zone_history`). `leaderboard_update` and `player_update` carry `zone_history: null` in every broadcast; the full history is only seeded via `race_state` on connect, plus these snapshot messages. See [zone_history updates](#zone_history-updates).

Note on chat unlocks: when a participant finishes/abandons, when the late-join window closes, and when the race transitions to `FINISHED`, the public chat unlocks for some viewers without any dedicated server-initiated push. The client recomputes its local access from data it already receives (participant status updates, `race_info_update`, the registration deadline) and sends a `request_chat_history` to pull the prior messages. See [Chat System](#chat-system).
