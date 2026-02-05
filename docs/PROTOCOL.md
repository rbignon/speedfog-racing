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
| POST   | `/api/races/{id}/generate-zips`        | Bearer | Generate personalized zips        |
| GET    | `/api/races/{id}/download/{mod_token}` | -      | Download participant zip          |
| POST   | `/api/races/{id}/start`                | Bearer | Start race with scheduled time    |

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
  "current_zone": "m60_51_36_00",
  "death_count": 5
}
```

Note: `current_layer` was removed from client messages. The server computes the layer from `zone_entered` events.

#### `zone_entered`

Sent when player traverses a fog gate.

```json
{
  "type": "zone_entered",
  "from_zone": "m60_51_36_00",
  "to_zone": "m60_35_50_00",
  "igt_ms": 98765
}
```

#### `finished`

Player completed the race (final boss defeated).

```json
{
  "type": "finished",
  "igt_ms": 6543210
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
    "status": "open",
    "scheduled_start": "2026-02-05T18:00:00Z"
  },
  "seed": {
    "total_layers": 12
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

#### `auth_error`

Authentication failed.

```json
{
  "type": "auth_error",
  "message": "Invalid mod token"
}
```

#### `race_start`

Race countdown reached zero.

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
    "status": "running",
    "scheduled_start": "2026-02-05T18:00:00Z"
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

`draft` → `open` → `countdown` → `running` → `finished`

### Participant Status

`registered` → `ready` → `playing` → `finished` | `abandoned`

### Zone ID Format

Map IDs in format `mXX_YY_ZZ_WW` (e.g., `m60_51_36_00` for Limgrave).

---

## Phase 2 Extensions (Planned)

### Server → Mod: `zone_info`

Server-computed exit information (anti-spoiler design).

```json
{
  "type": "zone_info",
  "current_zone": {
    "name": "Altus Sagescave",
    "display_name": "Altus Sagescave",
    "layer": 8
  },
  "exits": [
    {
      "name": "Caelid Gaol Cave",
      "direction": "origin",
      "discovered": true
    },
    {
      "name": "???",
      "direction": "forward",
      "discovered": false
    }
  ]
}
```

This allows removing `graph.json` from player zips to prevent spoilers.
