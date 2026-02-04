# SpeedFog Racing - Design Document

**Date:** 2026-02-04
**Status:** Draft

## 1. Overview and Objectives

**SpeedFog Racing** is a competitive racing platform for SpeedFog, allowing multiple players to race on the same seed with real-time tracking.

### Objectives

1. **Players**: In-game overlay displaying their progression, live leaderboard, and zone info
2. **Organizers**: Web interface to create races, manage participants, distribute personalized .zip files
3. **Spectators/Casters**: DAG visualization with real-time player positions (Twitch overlay)

### MVP Scope

- Twitch authentication
- Race creation (synchronous mode with countdown)
- Pre-generated seed pool (multi-pools with different settings)
- Personalized .zip distribution (token per player)
- Rust mod with in-game overlay (zone, IGT, leaderboard)
- Real-time WebSocket (mod <-> server <-> frontend)
- Spectator page with horizontal DAG
- OBS overlays (transparent background)

### Out of MVP Scope (future)

- Asynchronous races
- On-demand seed generation (requires Wine on server)
- Brackets/tournaments
- Historical player statistics
- Custom EMEVD events for precise tracking
- Progressive path display for players

---

## 2. Technical Architecture

### Repositories

```
speedfog/                    # Existing - Seed generator
├── speedfog/                # Python package (DAG generation)
├── writer/                  # C# wrappers (FogMod, ItemRandomizer)
└── output/                  # Generated seeds

speedfog-racing/             # New - Racing platform
├── server/                  # Python/FastAPI
├── web/                     # Svelte/SvelteKit
├── mod/                     # Rust (fork er-fog-vizu)
└── tools/                   # Scripts (generate_pool.py)
```

### speedfog-racing -> speedfog Dependency

Decoupled via CLI. The `generate_pool.py` script calls speedfog as a subprocess:

```python
subprocess.run(
    ["uv", "run", "speedfog", str(config_file), "-o", str(output_dir)],
    cwd=SPEEDFOG_PATH,  # Env var or config
    check=True,
)
```

Each project maintains its own venv. The only link is the `SPEEDFOG_PATH` path.

### Tech Stack

| Component     | Technology                 | Justification                                      |
| ------------- | -------------------------- | -------------------------------------------------- |
| Server        | FastAPI + SQLAlchemy async | Reuses er-fog-vizu patterns, native WebSocket      |
| Database      | PostgreSQL                 | Robust, JSON support for configs                   |
| Frontend      | SvelteKit                  | Native reactivity, lightweight, good for real-time |
| Mod           | Rust + ImGui               | Fork er-fog-vizu, DLL injection                    |
| Communication | WebSocket                  | Bidirectional real-time                            |
| Auth          | Twitch OAuth               | Targets streaming community                        |

### Main Data Flow

```
Rust Mod <--WebSocket--> FastAPI Server <--WebSocket--> Svelte Frontend
   |                           |                              |
   | Sends:                    | Stores:                      | Displays:
   | - IGT                     | - Race state                 | - DAG + positions
   | - Current zone            | - Player progression         | - Leaderboard
   | - Fog traversals          | - IGT                        | - Live stats
   | - Death count             |                              |
   |                           | Broadcasts:                  |
   | Receives:                 | - Updates to all             |
   | - Leaderboard             |   clients                    |
   | - Other players' state    |                              |
```

---

## 3. Data Model

### Main Entities

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│    User     │       │    Race     │       │    Seed     │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id          │       │ id          │       │ id          │
│ twitch_id   │       │ name        │       │ seed_number │
│ twitch_name │<──────│ organizer_id│       │ pool_name   │
│ avatar_url  │       │ seed_id     │──────>│ graph_json  │
│ api_token   │       │ status      │       │ total_layers│
│ is_admin    │       │ mode        │       │ zip_path    │
│ created_at  │       │ config      │       │ status      │
└─────────────┘       │ scheduled_  │       │ created_at  │
      ^               │   start     │       └─────────────┘
      │               │ created_at  │
      │               └─────────────┘
      │                     │
      │                     │ 1:N
      │                     v
      │               ┌─────────────┐
      │               │ Participant │
      └───────────────├─────────────┤
                      │ id          │
                      │ race_id     │
                      │ user_id     │
                      │ mod_token   │
                      │ current_zone│
                      │ current_layer│
                      │ igt_ms      │
                      │ death_count │
                      │ finished_at │
                      │ status      │
                      └─────────────┘
```

### Statuses

**Race.status**: `draft` -> `open` -> `countdown` -> `running` -> `finished`

**Participant.status**: `registered` -> `ready` -> `playing` -> `finished` | `abandoned`

**Seed.status**: `available` -> `consumed`

### Race Config (JSON)

```json
{
  "show_finished_names": true,
  "countdown_seconds": 10,
  "max_participants": 8
}
```

---

## 4. User Workflows

### Creating a Race (Organizer)

1. **Twitch Login**: OAuth redirect -> callback -> session created
2. **New Race**:
   - Name, config (show_finished_names, max_participants)
   - Pool selection (Sprint/Standard/Marathon) with settings display
   - Seed randomly assigned from chosen pool
   - Race created with "draft" status
3. **Participant Management**:
   - Add players by Twitch username
   - If account exists -> added directly
   - If no account -> generates invitation link `/invite/{token}`
4. **Launch**:
   - Set scheduled_start (datetime picker with timezone)
   - Click "Generate .zips" -> server generates personalized zip per player
   - Each player downloads their .zip
   - Click "Start" when everyone is ready -> synchronized countdown

### Participating in a Race (Player)

1. **Join**: Twitch login -> registration via link or added by organizer
2. **Preparation**:
   - Download personalized .zip
   - Unzip, run `launch_speedfog.bat`
   - Mod connects to server (token in config)
   - Status changes to "ready" when connected
3. **Race**:
   - Countdown displayed in overlay (calculated from scheduled_start)
   - GO! -> New character, IGT starts
   - Progression tracked via fog gate traversals
   - Leaderboard updated in real-time
4. **Finish**: Final boss defeated -> status "finished", IGT recorded

---

## 5. WebSocket Protocol

### Connections

```
/ws/mod/{race_id}      # Rust Mod -> Server (auth via mod_token)
/ws/race/{race_id}     # Frontend -> Server (spectators, organizer)
```

### Mod -> Server Messages

```typescript
// Authentication
{ type: "auth", mod_token: "abc123" }

// Player ready (connected, in game)
{ type: "ready" }

// Periodic update (every ~2-5 sec)
{ type: "status_update",
  igt_ms: 123456,
  current_zone: "altus_sagescave",
  current_layer: 3,
  death_count: 7 }

// Fog gate traversal
{ type: "zone_entered",
  from_zone: "caelid_gaolcave_boss",
  to_zone: "altus_sagescave",
  igt_ms: 98765 }

// Race finished (final boss defeated)
{ type: "finished", igt_ms: 6543210 }
```

### Server -> Mod Messages

```typescript
// Auth OK + initial state
{ type: "auth_ok",
  race: { name, status, scheduled_start },
  seed: { total_layers },
  participants: [...] }

// GO!
{ type: "race_start" }

// Leaderboard update (broadcast to all mods)
{ type: "leaderboard_update",
  participants: [
    { name: "Player1", layer: 8, igt_ms: null, death_count: 3, finished: false },
    { name: "Player2", layer: 6, igt_ms: 654321, death_count: 5, finished: true }
  ]}
```

### Server -> Frontend Messages (spectators)

```typescript
// Complete race state
{ type: "race_state",
  race: { name, status, scheduled_start },
  seed: { graph_json },  // For displaying the DAG
  participants: [
    { name, zone_id, layer, igt_ms, death_count, status }
  ]}

// Player position update
{ type: "player_update",
  player: { name, zone_id, layer, igt_ms, death_count, status }}
```

---

## 6. In-Game Overlay (Rust Mod)

### Layout

```
┌────────────────────────────────────────┐
│ Altus Sagescave              01:23:45  │  <- Zone | IGT
│ Tier 8                          3/12   │  <- Scaling | Layer
├────────────────────────────────────────┤
│ 1. Player4 [FIN]   01:45:32         ✓  │  <- Finished at top (sorted by IGT)
│ 2. Player1         ██████████    8/12  │  <- In progress (sorted by layer)
│ 3. You             ███████       6/12  │  <- Color highlight
│ 4. Player3         █████         5/12  │
├────────────────────────────────────────┤
│ > Exits (F11 to collapse)              │  <- Optional/collapsible
│   <- Caelid Gaol Cave (origin)         │
│   -> ??? (undiscovered)                │
└────────────────────────────────────────┘
```

### Leaderboard Logic

1. **Finished players** at top, sorted by finish IGT (fastest first)
2. **In-progress players** below, sorted by progression (layer)

### Organizer Config

- `show_finished_names: true/false` - Display finished players' names

### er-fog-vizu Fork

**Kept:**

- `core/`: Types, map_utils, warp_tracker
- `eldenring/`: Memory reading, game_state, animations
- `dll/ui.rs`: ImGui overlay rendering
- `dll/websocket.rs`: WebSocket client (to adapt)

**Removed:**

- `launcher/`: No GUI launcher

**Config (speedfog_race.toml):**

```toml
[server]
url = "wss://speedfog-racing.example.com"
mod_token = "player_specific_token_here"
race_id = "uuid-of-race"

[overlay]
show_exits = true
font_size = 16

[keybindings]
toggle_ui = "f9"
toggle_exits = "f11"
```

### Injection

Via ModEngine2 (included in .zip):

```toml
# config_speedfog/config.toml (ModEngine2)
[modengine]
external_dlls = ["speedfog_race.dll"]
```

---

## 7. FastAPI Server

### Structure

```
speedfog-racing/server/
├── speedfog_racing/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, CORS
│   ├── config.py            # Settings (env vars, seeds_pool_dir)
│   ├── database.py          # SQLAlchemy async, models
│   ├── auth.py              # Twitch OAuth
│   │
│   ├── api/
│   │   ├── auth.py          # /api/auth/twitch, /api/auth/callback
│   │   ├── races.py         # CRUD races, participants
│   │   ├── seeds.py         # Admin stats
│   │   └── users.py         # Profile
│   │
│   ├── websocket/
│   │   ├── manager.py       # RaceRoom, connections per race
│   │   ├── mod.py           # Mod connections handler
│   │   └── spectator.py     # Spectator connections handler
│   │
│   └── services/
│       ├── race_service.py  # Race business logic
│       ├── seed_service.py  # Pool management, zip generation
│       └── leaderboard.py   # Real-time leaderboard calculation
│
├── alembic/                 # DB migrations
├── tests/
├── pyproject.toml
└── .env.example
```

### Main Endpoints

```
Auth:
  GET  /api/auth/twitch              -> Twitch OAuth redirect
  GET  /api/auth/callback            -> Callback, creates session
  GET  /api/auth/me                  -> Current user

Races:
  POST /api/races                    -> Create race (organizer)
  GET  /api/races/{id}               -> Race details
  POST /api/races/{id}/participants  -> Add player (by twitch name)
  POST /api/races/{id}/generate-zips -> Generate personalized .zips
  POST /api/races/{id}/start         -> Set scheduled_start, launch
  GET  /api/races/{id}/download/{token} -> Download personal .zip

Seeds (admin):
  GET  /api/admin/seeds              -> Pool stats (available/consumed)
  POST /api/admin/seeds/scan         -> Rescan directory

WebSocket:
  WS   /ws/mod/{race_id}             -> Mod connection
  WS   /ws/race/{race_id}            -> Spectator/organizer connection
```

### Configuration

```bash
# .env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/speedfog_racing
TWITCH_CLIENT_ID=xxx
TWITCH_CLIENT_SECRET=xxx
TWITCH_REDIRECT_URI=https://speedfog-racing.example.com/api/auth/callback
SEEDS_POOL_DIR=/data/seeds
SECRET_KEY=xxx
WEBSOCKET_URL=wss://speedfog-racing.example.com
```

---

## 8. SvelteKit Frontend

### Structure

```
speedfog-racing/web/
├── src/
│   ├── lib/
│   │   ├── api.ts              # REST API client
│   │   ├── websocket.ts        # WebSocket client with reconnect
│   │   ├── stores/
│   │   │   ├── auth.ts         # User session
│   │   │   ├── race.ts         # Current race state
│   │   │   └── leaderboard.ts  # Real-time leaderboard
│   │   └── components/
│   │       ├── DagView.svelte       # Horizontal DAG visualization
│   │       ├── Leaderboard.svelte   # Player leaderboard
│   │       ├── Countdown.svelte     # Pre-start timer
│   │       └── PlayerMarker.svelte  # Player marker on DAG
│   │
│   ├── routes/
│   │   ├── +layout.svelte      # Global layout, auth check
│   │   ├── +page.svelte        # Home
│   │   ├── auth/callback/+page.svelte
│   │   ├── race/
│   │   │   ├── new/+page.svelte       # Create race
│   │   │   └── [id]/
│   │   │       ├── +page.svelte       # Race view
│   │   │       ├── join/+page.svelte  # Join race
│   │   │       └── manage/+page.svelte
│   │   ├── overlay/[id]/
│   │   │   ├── dag/+page.svelte       # DAG overlay
│   │   │   └── leaderboard/+page.svelte
│   │   ├── invite/[token]/+page.svelte
│   │   └── admin/+page.svelte
│   │
│   └── app.css
├── static/
├── svelte.config.js
└── package.json
```

### Race Page `/race/{id}`

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SPEEDFOG RACE - "Sunday Showdown"                              [Logout] │
├────────────────────┬────────────────────────────────────────────────────┤
│  SIDEBAR           │              CENTER AREA                           │
│                    │                                                    │
│  ┌──────────────┐  │   ┌────────────────────────────────────────────┐   │
│  │ Leaderboard  │  │   │                                            │   │
│  │ 1. P1   8/12 │  │   │         [DAG / METRO MAP]                  │   │
│  │ 2. P2   6/12 │  │   │                                            │   │
│  │ ...          │  │   │    (blurred before start)                  │   │
│  └──────────────┘  │   │    (visible for spectators during race)    │   │
│                    │   │    (blurred for players during race)       │   │
│  ┌──────────────┐  │   │                                            │   │
│  │ OVERLAYS     │  │   └────────────────────────────────────────────┘   │
│  │ > DAG (OBS)  │  │                                                    │
│  │ > Leaderboard│  │                                                    │
│  └──────────────┘  │                                                    │
│                    │                                                    │
│  [Role actions]    │                                                    │
└────────────────────┴────────────────────────────────────────────────────┘
```

### DAG Visibility by Role

| Phase           | Spectator/Organizer  | Player        |
| --------------- | -------------------- | ------------- |
| Before start    | Blurred              | Blurred       |
| During race     | Full DAG + positions | Blurred       |
| Player finishes | -                    | DAG revealed  |
| Race finished   | DAG + results        | DAG + results |

### OBS Overlays (transparent background)

**Horizontal DAG** `/overlay/{id}/dag`:

```
               ●───●───●───●───●───●───●───●───●───●───●───●───○
              /        ^            |                          \
●───●───●───●          |player1     |                           ●───○ END
              \        ^            |                          /
               ●───●───●───●───●───●───●───●───●───●───●───●───○
                       |player2
```

**Vertical Leaderboard** `/overlay/{id}/leaderboard`:

```
┌─────────────────────────┐
│  SPEEDFOG RACE          │
├─────────────────────────┤
│ 1. Player4 [FIN]    💀5 │
│    01:45:32             │
├─────────────────────────┤
│ 2. Player1    8/12  💀3 │
│ 3. Player2    6/12  💀7 │
│ 4. Player3    5/12  💀2 │
└─────────────────────────┘
```

---

## 9. Seed Pool Management

### Multi-Pool Structure

```
/data/seeds/
├── pools.toml                    # Pool definitions
│
├── sprint/                       # "Sprint" pool (~30min)
│   ├── config.toml               # Fixed settings for this pool
│   ├── available/
│   │   └── seed_XXXXX/
│   └── consumed/
│
├── standard/                     # "Standard" pool (~1h)
│   ├── config.toml
│   ├── available/
│   └── consumed/
│
└── marathon/                     # "Marathon" pool (~2h)
    ├── config.toml
    ├── available/
    └── consumed/
```

### Pool Definitions

```toml
# pools.toml
[sprint]
display_name = "Sprint (~30min)"
description = "Fast race, few zones, moderate scaling"

[standard]
display_name = "Standard (~1h)"
description = "Classic format, good balance"

[marathon]
display_name = "Marathon (~2h)"
description = "Long race, many zones"
```

### Pool Generation

```bash
# Uses the specified pool's config.toml
python tools/generate_pool.py --pool standard --count 10

# Workflow:
# 1. Load /data/seeds/standard/config.toml
# 2. Call speedfog via CLI (cwd=SPEEDFOG_PATH)
# 3. Add speedfog_race.dll to output
# 4. Create speedfog_race.toml template
# 5. Place in standard/available/
```

### Per-Player .zip Generation

```python
async def generate_player_zips(race: Race) -> dict[UUID, Path]:
    seed_dir = Path(race.seed.zip_path)

    for participant in race.participants:
        # Copy the seed
        player_dir = temp_dir / f"{race.id}_{participant.user.twitch_name}"
        shutil.copytree(seed_dir, player_dir)

        # Modify config with player's token
        config = toml.load(player_dir / "speedfog_race.toml")
        config["server"]["mod_token"] = participant.mod_token
        config["server"]["race_id"] = str(race.id)
        config["server"]["url"] = settings.websocket_url
        toml.dump(config, player_dir / "speedfog_race.toml")

        # Create zip
        shutil.make_archive(...)
```

### Admin Dashboard

```
┌─────────────────────────────────────────────┐
│  SEED POOL STATUS                           │
├─────────────────────────────────────────────┤
│  Sprint:    12 available / 3 consumed       │
│  Standard:  47 available / 13 consumed      │
│  Marathon:   8 available / 2 consumed       │
├─────────────────────────────────────────────┤
│  [Rescan pools]                             │
└─────────────────────────────────────────────┘
```

---

## 10. Implementation Phases

### Phase 1: Foundations (Minimal MVP)

**Objective:** A functional race from end to end

| Component    | Tasks                                                       |
| ------------ | ----------------------------------------------------------- |
| **Server**   | Setup FastAPI, DB, Twitch OAuth, models                     |
| **Server**   | Basic REST endpoints (races CRUD, auth)                     |
| **Server**   | Basic WebSocket (mod + spectator)                           |
| **Server**   | Simple pool management (1 pool, assign seed, generate zips) |
| **Frontend** | Setup SvelteKit, Twitch auth, basic pages                   |
| **Frontend** | Race creation page, race page (simple leaderboard)          |
| **Mod**      | Fork er-fog-vizu, adapt protocol, minimal overlay           |

**Result:** Organizer creates race -> Players download zip -> Race with leaderboard

### Phase 2: Complete Experience

| Component    | Tasks                                        |
| ------------ | -------------------------------------------- |
| **Frontend** | Horizontal DAG visualization                 |
| **Frontend** | OBS overlays (dag + leaderboard)             |
| **Frontend** | Multi-pools with selection                   |
| **Mod**      | Full overlay (leaderboard, exits, countdown) |
| **Server**   | Admin dashboard (seed stats)                 |
| **Server**   | Synchronized countdown                       |

**Result:** Complete viewing experience for casters

### Phase 3: Polish and Advanced Features

| Component    | Tasks                                  |
| ------------ | -------------------------------------- |
| **Mod**      | Custom EMEVD events (precise tracking) |
| **Frontend** | Progressive path display for players   |
| **Server**   | Asynchronous races                     |
| **Server**   | Player history / statistics            |
| **Infra**    | On-demand seed generation (Wine)       |

### Suggested Development Order (Phase 1)

1. Server: setup + Twitch auth + DB
2. Frontend: setup + Twitch login
3. Server: models + race endpoints
4. Frontend: race creation/list
5. Mod: fork + basic WebSocket connection
6. Server: mod WebSocket + leaderboard
7. Server: pool management + zip generation
8. Frontend: race page + zip download
9. Mod: full overlay
10. End-to-end tests

---

## Appendices

### Timing and Leaderboard

- Always based on IGT (In-Game Time) for fairness
- Leaderboard:
  1. Finished players (sorted by ascending IGT)
  2. In-progress players (sorted by descending layer)

### Technical TODOs to Explore

- [ ] Custom EMEVD events in FogModWrapper for precise traversal tracking
- [ ] Race finish detection mechanism (final boss defeated)
- [ ] Mod disconnection/reconnection handling during a race
