# Training Mode Design

Solo practice mode with dedicated seed pools, full mod tracking, and session history.

## Data Model

### Table `training_sessions`

| Column           | Type              | Notes                                 |
| ---------------- | ----------------- | ------------------------------------- |
| `id`             | UUID              | PK                                    |
| `user_id`        | UUID              | FK → users                            |
| `seed_id`        | UUID              | FK → seeds                            |
| `mod_token`      | str               | Unique, for WS auth                   |
| `status`         | enum              | `ACTIVE` / `FINISHED` / `ABANDONED`   |
| `igt_ms`         | int \| null       | Last reported IGT                     |
| `death_count`    | int               | Default 0                             |
| `progress_nodes` | list[str] \| null | Traversed node IDs (from event flags) |
| `created_at`     | datetime          |                                       |
| `finished_at`    | datetime \| null  |                                       |

- Seed FK points to an existing seed but **seed stays `AVAILABLE`** (never consumed).
- No `pool_name` column — derived from `session.seed.pool_name`.
- No optimistic locking (`version`) — single writer (the player via WS).

### Anti-repetition

Seed selection: `WHERE seed_id NOT IN (SELECT seed_id FROM training_sessions WHERE user_id = ?)`.
When pool exhausted (all seeds played by this user), reset and select from all seeds.

### Pool type in config

Add `type` field to pool `config.toml`:

```toml
[display]
type = "training"  # or "race" (default if absent)
estimated_duration = "~1h"
description = "Standard training pool"
```

`GET /api/pools` accepts `?type=race` or `?type=training` query param to filter.
Existing pools default to `type = "race"` for backwards compatibility.

## API Endpoints

### REST

| Method | Route                        | Auth | Description                                                          |
| ------ | ---------------------------- | ---- | -------------------------------------------------------------------- |
| `POST` | `/api/training`              | User | Create session (body: `{ pool_name }`) → returns session + seed info |
| `GET`  | `/api/training`              | User | List current user's sessions (history)                               |
| `GET`  | `/api/training/{id}`         | User | Session detail (includes `graph_json`)                               |
| `GET`  | `/api/training/{id}/pack`    | User | Download seed pack (mod config points to training WS)                |
| `POST` | `/api/training/{id}/abandon` | User | `ACTIVE` → `ABANDONED`                                               |

- `POST /api/training`: selects random seed from requested pool, excluding seeds already played by user. Resets selection if pool exhausted.
- `GET /api/training/{id}`: `graph_json` always included; frontend controls DAG visibility.
- All endpoints scoped to session owner only. No public visibility.

### WebSocket

| Route                                | Auth        | Description                                          |
| ------------------------------------ | ----------- | ---------------------------------------------------- |
| `/ws/training/{session_id}`          | `mod_token` | Mod connection, same protocol as `/ws/mod/{race_id}` |
| `/ws/training/{session_id}/spectate` | User token  | Web client live updates                              |

**Mod endpoint** — same protocol, simplified behavior:

- Client sends: `auth`, `status_update`, `event_flag`, `pong` (no `ready`)
- Server sends: `auth_ok` (seed + single participant), `race_start` (immediate after auth), `zone_update`, `ping`
- No `leaderboard_update`, `player_update`, or `race_status_change`

**Spectator endpoint** — forwards updates from mod handler to web client:

- Sends `leaderboard_update` (single participant), `race_status_change` (for FINISHED/ABANDONED)
- Reuses existing race store pattern on the frontend

## Mod (Rust)

### Config

New field in seed pack TOML:

```toml
[server]
url = "wss://speedfog.example.com"
race_id = "session-uuid"
mod_token = "..."
training = true
```

### Changes (~20 lines)

1. **`config.rs`** — `training: bool` field (default `false`)
2. **`websocket.rs`** — URL construction: `/ws/training/{id}` when training, `/ws/mod/{id}` otherwise
3. **`ui.rs`** — When `training == true`: title shows "Training" instead of race name, leaderboard hidden
4. **`tracker.rs`** — Skip `ready` message in training mode

## UI (SvelteKit)

### Routes

| Route            | Description                        |
| ---------------- | ---------------------------------- |
| `/training`      | Pool selection + session history   |
| `/training/[id]` | Session detail (live or completed) |

### Page `/training`

- **Top:** Three pool cards (sprint/standard/marathon) with duration, description, "Start" button
- **Bottom:** History table (pool, date, IGT, deaths, status badge), sorted by date desc, clickable rows
- **Auth required.** Unauthenticated users see login prompt.

Pool cards populated from `GET /api/pools?type=training`.

### Page `/training/[id]`

Central layout (no sidebar):

- **Header:** "Training — {pool}" + status badge (Active / Finished / Abandoned)
- **Stats bar:** IGT, deaths, progression (X/Y nodes) — live via WS spectator
- **DAG:** Reuses `MetroDAG` component. Hidden by default when ACTIVE (spoiler toggle), shown by default when FINISHED. Player progression colors nodes in real-time.
- **Seed info:** Layer count, node count, pool type
- **Actions:**
  - "Download pack" — while ACTIVE (allows re-download)
  - "Abandon" — ACTIVE only, with confirmation

**Live updates** via `/ws/training/{id}/spectate` feeding a training store (same pattern as race store).
