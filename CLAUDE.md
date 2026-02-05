# SpeedFog Racing

Competitive racing platform for SpeedFog (Elden Ring randomizer with fog gates).

## Architecture

```
speedfog-racing/
├── server/          # Python/FastAPI backend
├── web/             # SvelteKit frontend
├── mod/             # Rust mod injected into the game
├── tools/           # Seed pool generation scripts
└── docs/            # Specs and design documents
```

## Server (Python)

### Commands

```bash
cd server

# Install dependencies
uv sync --all-extras

# Run server
uv run speedfog-racing

# Tests
uv run pytest

# Linting
uv run ruff check .
uv run ruff format .
uv run mypy speedfog_racing/
```

### Structure

```
server/speedfog_racing/
├── main.py          # FastAPI app, CORS, lifespan
├── config.py        # Pydantic settings (env vars)
├── database.py      # SQLAlchemy async setup
├── models.py        # DB models (User, Race, Seed, Participant, Invite)
├── auth.py          # Twitch OAuth helpers + FastAPI dependencies
├── api/             # REST routes
│   ├── auth.py      # /api/auth/*
│   ├── races.py     # /api/races/*
│   └── users.py     # /api/users/*
├── websocket/       # WebSocket handlers
│   ├── manager.py   # Connection manager for race rooms
│   ├── mod.py       # Mod WebSocket handler
│   ├── spectator.py # Spectator WebSocket handler
│   └── schemas.py   # WebSocket message schemas
├── services/        # Business logic
│   ├── seed.py      # Seed pool management
│   └── zip_service.py # Zip generation for participants
└── schemas.py       # Pydantic schemas for API responses
```

### Conventions

- SQLAlchemy 2.0 style with `Mapped[]` and `mapped_column()`
- Async everywhere (`AsyncSession`, `async def`)
- Pydantic v2 for validation
- Tests with pytest-asyncio, in-memory SQLite fixtures

## Web (SvelteKit)

### Commands

```bash
cd web

# Install dependencies
npm install

# Run dev server (proxies /api to localhost:8000)
npm run dev

# Type checking
npm run check

# Linting
npm run lint

# Format
npm run format
```

### Structure

```
web/src/
├── lib/
│   ├── api.ts           # REST API client + types
│   ├── websocket.ts     # WebSocket client with reconnect
│   ├── stores/
│   │   ├── auth.ts      # Auth store (isLoggedIn, currentUser)
│   │   └── race.ts      # Race state store (live WebSocket data)
│   └── components/
│       ├── Leaderboard.svelte      # Live leaderboard
│       ├── RaceStatus.svelte       # Status badge + countdown
│       └── ConnectionStatus.svelte # WebSocket connection indicator
└── routes/
    ├── +layout.svelte   # Global layout with navbar
    ├── +page.svelte     # Home (race list)
    ├── auth/callback/   # Twitch OAuth callback
    └── race/
        ├── new/         # Create race form
        └── [id]/
            ├── +page    # Race detail (spectator view)
            └── manage/  # Admin page (participants, zips, start)
```

### Conventions

- SvelteKit 5 with runes (`$state`, `$derived`, `$props`)
- TypeScript strict mode
- Vite proxy for API calls during development

## Mod (Rust)

### Commands

```bash
cd mod

# Check (Linux - won't build DLL but checks syntax)
cargo check --lib

# Build (Windows only - requires MSVC toolchain)
cargo build --lib --release

# Tests (works on Linux)
cargo test
```

### Structure

```
mod/src/
├── lib.rs              # DLL entry point
├── core/               # Platform-independent types
│   ├── mod.rs
│   ├── race_protocol.rs  # WebSocket message types
│   ├── map_utils.rs      # Map ID formatting
│   └── types.rs          # PlayerPosition etc.
├── dll/                # Windows-only DLL code
│   ├── mod.rs
│   ├── race_config.rs    # TOML config loading
│   ├── race_tracker.rs   # Main orchestrator
│   ├── race_ui.rs        # ImGui overlay
│   └── race_websocket.rs # WebSocket client
└── eldenring/          # Game memory reading
    ├── mod.rs
    ├── game_state.rs
    ├── game_man.rs
    └── ...
```

### Protocol

The mod communicates with the server via WebSocket at `/ws/mod/{race_id}`:

**Client → Server:**

- `auth { mod_token }` - authenticate
- `ready` - player ready to race
- `status_update { igt_ms, current_zone, current_layer, death_count }` - periodic update
- `zone_entered { from_zone, to_zone, igt_ms }` - zone change
- `finished { igt_ms }` - race complete

**Server → Client:**

- `auth_ok { race, seed, participants }` - authentication success
- `auth_error { message }` - authentication failed
- `race_start` - race has begun
- `leaderboard_update { participants }` - updated standings
- `race_status_change { status }` - race state changed

## Documentation

- `docs/2026-02-04-speedfog-racing-design.md` - Overall design
- `docs/phase1-spec.md` - Phase 1 MVP detailed spec

## Current State

Phase 1 in progress. See `docs/phase1-spec.md` section 7 for step tracking.

**Completed:** Steps 1-10 (Server Foundation, Twitch Auth, Seed Pool Basic, Race CRUD, Zip Generation, Frontend Foundation, Race Management UI, WebSocket Server, WebSocket Frontend, Mod Fork)
**Next:** Step 11 (Integration Testing)

## Related Projects

- `../speedfog/` - SpeedFog seed generator
- `../../er-fog-vizu/` - Original tracking mod (upstream for fork)
