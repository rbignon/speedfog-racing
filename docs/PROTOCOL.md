# SpeedFog Racing - Protocol Reference

Reference document for API endpoints and WebSocket messages.

## REST API

### Authentication

| Method | Endpoint             | Auth   | Description                     |
| ------ | -------------------- | ------ | ------------------------------- |
| GET    | `/api/auth/twitch`   | -      | Redirect to Twitch OAuth        |
| GET    | `/api/auth/callback` | -      | OAuth callback, creates session |
| GET    | `/api/auth/me`       | Bearer | Get current user info           |

### Races

| Method | Endpoint                               | Auth   | Description                       |
| ------ | -------------------------------------- | ------ | --------------------------------- |
| GET    | `/api/races`                           | -      | List races (filterable by status) |
| POST   | `/api/races`                           | Bearer | Create race                       |
| GET    | `/api/races/{id}`                      | -      | Race details with participants    |
| POST   | `/api/races/{id}/participants`         | Bearer | Add participant (organizer)       |
| DELETE | `/api/races/{id}/participants/{pid}`   | Bearer | Remove participant (organizer)    |
| POST   | `/api/races/{id}/generate-seed-packs`  | Bearer | Generate personalized seed packs  |
| GET    | `/api/races/{id}/my-seed-pack`         | Bearer | Download own seed pack            |
| GET    | `/api/races/{id}/download/{mod_token}` | -      | Download participant seed pack    |
| POST   | `/api/races/{id}/start`                | Bearer | Start race immediately            |

### Invites

| Method | Endpoint                     | Auth   | Description     |
| ------ | ---------------------------- | ------ | --------------- |
| GET    | `/api/invite/{token}`        | -      | Get invite info |
| POST   | `/api/invite/{token}/accept` | Bearer | Accept invite   |

### Admin

| Method | Endpoint                | Auth           | Description             |
| ------ | ----------------------- | -------------- | ----------------------- |
| GET    | `/api/admin/seeds`      | Bearer (admin) | Pool statistics         |
| POST   | `/api/admin/seeds/scan` | Bearer (admin) | Rescan seed directories |

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

Player is in-game and ready to race.

```json
{
  "type": "ready"
}
```

#### `status_update`

Periodic update (every ~1 second).

```json
{
  "type": "status_update",
  "igt_ms": 123456,
  "death_count": 5
}
```

Note: `current_zone` removed. Zone tracking is event-based via `event_flag`.

#### `event_flag`

Sent when the mod detects an event flag transition (0 → 1). Replaces `zone_entered`.

```json
{
  "type": "event_flag",
  "flag_id": 9000003,
  "igt_ms": 4532100
}
```

The `flag_id` is an opaque integer — the mod has no knowledge of what it represents. The server resolves it to a DAG node via the seed's `event_map`.

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
    "event_ids": [9000001, 9000002, 9000003, 9000047]
  },
  "participants": [
    {
      "name": "Player1",
      "layer": 0,
      "igt_ms": null,
      "death_count": 0,
      "status": "registered"
    }
  ]
}
```

`event_ids`: sorted list of event flag IDs the mod should monitor. Opaque to the mod — no mapping to zones or nodes is provided.

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
  "participants": [
    {
      "name": "Player1",
      "layer": 8,
      "igt_ms": null,
      "death_count": 3,
      "status": "playing"
    },
    {
      "name": "Player2",
      "layer": 6,
      "igt_ms": 654321,
      "death_count": 5,
      "status": "finished"
    }
  ]
}
```

Participants are pre-sorted:

1. Finished players first (by ascending IGT - fastest first)
2. In-progress players (by descending layer - furthest first)

#### `race_status_change`

Race status changed.

```json
{
  "type": "race_status_change",
  "status": "running"
}
```

#### `player_update`

Single player update (optimization, can be used instead of full leaderboard).

```json
{
  "type": "player_update",
  "player": {
    "name": "Player1",
    "layer": 8,
    "igt_ms": null,
    "death_count": 3,
    "status": "playing"
  }
}
```

---

## WebSocket: Spectator Connection

**Endpoint:** `WS /ws/race/{race_id}`

No authentication required (public).

### Server → Client

#### `race_state`

Sent immediately on connection. Full race state.

```json
{
  "type": "race_state",
  "race": {
    "id": "uuid",
    "name": "Sunday Showdown",
    "status": "running"
  },
  "seed": {
    "graph_json": { ... },
    "total_layers": 12
  },
  "participants": [
    {
      "name": "Player1",
      "zone_id": "m60_51_36_00",
      "layer": 8,
      "igt_ms": null,
      "death_count": 3,
      "status": "playing"
    }
  ]
}
```

#### `player_update`

Player state changed.

```json
{
  "type": "player_update",
  "player": {
    "name": "Player1",
    "zone_id": "m60_51_36_00",
    "layer": 8,
    "igt_ms": null,
    "death_count": 3,
    "status": "playing"
  }
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

---

## Data Types

### Race Status

`draft` → `open` → `running` → `finished`

### Participant Status

`registered` → `ready` → `playing` → `finished` | `abandoned`

### Zone Tracking

Zone tracking uses EMEVD event flags. The mod monitors a list of event flag IDs (received via `auth_ok`) and reports transitions via `event_flag` messages. The server resolves flag IDs to DAG nodes using the seed's `event_map`. See `docs/specs/emevd-zone-tracking.md` for the full specification.
