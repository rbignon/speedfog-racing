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

| Method | Endpoint             | Auth   | Description                                          |
| ------ | -------------------- | ------ | ---------------------------------------------------- |
| GET    | `/api/auth/twitch`   | -      | Redirect to Twitch OAuth (`?redirect_url`)           |
| GET    | `/api/auth/callback` | -      | OAuth callback, redirects with `?token=`             |
| GET    | `/api/auth/me`       | Bearer | Get current user info (includes `api_token`, `role`) |
| POST   | `/api/auth/logout`   | Bearer | Regenerate API token (invalidates session)           |

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
| POST   | `/api/races/{id}/generate-seed-packs`  | Bearer | Generate personalized seed packs                |
| GET    | `/api/races/{id}/my-seed-pack`         | Bearer | Download own seed pack (ZIP)                    |
| GET    | `/api/races/{id}/download/{mod_token}` | -      | Download participant seed pack (ZIP)            |

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

Periodic update (every ~1 second). Also auto-transitions `ready` → `playing` if race is running.

```json
{
  "type": "status_update",
  "igt_ms": 123456,
  "death_count": 5
}
```

#### `event_flag`

Sent when the mod detects an event flag transition (0 → 1). The server resolves it to a DAG node via the seed's `event_map`. If the flag matches `finish_event`, the player is auto-finished.

```json
{
  "type": "event_flag",
  "flag_id": 1040292842,
  "igt_ms": 4532100
}
```

#### `finished`

Player finished the race. Server-side schema only — the mod does not send this directly. Instead, finishing is handled automatically when the server receives an `event_flag` matching the seed's `finish_event`.

```json
{
  "type": "finished",
  "igt_ms": 7654321
}
```

### Server → Client

#### `auth_ok`

Authentication successful. Contains initial race state.

```json
{
  "type": "auth_ok",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "open"
  },
  "seed": {
    "total_layers": 12,
    "event_ids": [1040292801, 1040292802, 1040292847]
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

`event_ids`: sorted list of event flag IDs the mod should monitor. Opaque to the mod — no mapping to zones or nodes is provided. `graph_json` is always `null` for mods.

#### `auth_error`

Authentication failed.

```json
{
  "type": "auth_error",
  "message": "Invalid mod token"
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

### Zone Tracking

Zone tracking uses EMEVD event flags. The mod monitors a list of event flag IDs (received via `auth_ok`) and reports transitions via `event_flag` messages. The server resolves flag IDs to DAG nodes using the seed's `event_map`. See `docs/specs/emevd-zone-tracking.md` for the full specification.
