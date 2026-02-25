# SpeedFog Racing

Competitive racing platform for SpeedFog (Elden Ring randomizer with fog gates).

## Architecture

```
speedfog-racing/
├── server/          # Python/FastAPI backend
├── web/             # SvelteKit frontend
├── mod/             # Rust mod injected into the game
├── tools/           # Seed pool generation and release scripts
├── deploy/          # VPS deployment (systemd, nginx, deploy script)
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
│   └── seed_pack_service.py # Seed pack generation for participants
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
│       ├── RaceStatus.svelte       # Status badge
│       └── ConnectionStatus.svelte # WebSocket connection indicator
└── routes/
    ├── +layout.svelte   # Global layout with navbar
    ├── +page.svelte     # Home (race list)
    ├── auth/callback/   # Twitch OAuth callback
    └── race/
        ├── new/         # Create race form
        └── [id]/
            └── +page    # Race detail (spectator + organizer view)
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
│   ├── protocol.rs       # WebSocket message types
│   ├── map_utils.rs      # Map ID formatting
│   └── types.rs          # PlayerPosition etc.
├── dll/                # Windows-only DLL code
│   ├── mod.rs
│   ├── config.rs         # TOML config loading
│   ├── tracker.rs        # Main orchestrator
│   ├── ui.rs             # ImGui overlay
│   └── websocket.rs      # WebSocket client
└── eldenring/          # Game memory reading
    ├── mod.rs
    ├── game_state.rs
    ├── game_man.rs
    └── ...
```

### Protocol

The mod communicates with the server via WebSocket at `/ws/mod/{race_id}`.
See `docs/PROTOCOL.md` for complete reference.

**Client → Server:**

- `auth { mod_token }` - authenticate
- `ready` - player ready to race
- `status_update { igt_ms, death_count }` - periodic update
- `event_flag { flag_id, igt_ms }` - EMEVD event flag triggered (fog gate traversal or boss kill)
- `finished { igt_ms }` - race complete

**Server → Client:**

- `auth_ok { race, seed, participants }` - authentication success (seed includes `event_ids`)
- `auth_error { message }` - authentication failed
- `race_start` - race has begun
- `leaderboard_update { participants }` - updated standings (pre-sorted)
- `race_status_change { status }` - race state changed
- `player_update { player }` - single player update

## Documentation

- `docs/ROADMAP.md` - Project roadmap (v1.0, v1.1, v2.0, future)
- `docs/DESIGN.md` - Overall design
- `docs/GRAPHIC_CHARTER.md` - Visual identity and color palette
- `docs/PROTOCOL.md` - API and WebSocket protocol reference
- `docs/specs/phase1.md` - Phase 1 MVP detailed spec
- `docs/specs/phase2-ui-ux.md` - Phase 2 UI/UX specification
- `docs/specs/emevd-zone-tracking.md` - EMEVD zone tracking spec (v1.0 critical)
- `docs/DISCORD_BOT.md` - Discord bot setup and configuration

## Current State

Phase 1 and Phase 2 complete.

**Phase 1 completed:** Steps 1-12 (Server Foundation, Twitch Auth, Seed Pool Basic, Race CRUD, Seed Pack Generation, Frontend Foundation, Race Management UI, WebSocket Server, WebSocket Frontend, Mod Fork, Integration Testing, Protocol Coherence & Frontend Gaps)
**Phase 2 completed:** Steps 1-8 (Data Model & API, Metro DAG Core, Homepage Redesign, Race Detail Lobby/Running/Finished States, Race Creation & Management, Polish). See `docs/specs/phase2-ui-ux.md`.

## Deployment

VPS deployment with nginx reverse proxy + systemd service. See `deploy/README.md` for full setup.

- Frontend: SvelteKit with `adapter-static` (SPA), built locally and uploaded via scp
- Backend: uvicorn behind nginx, managed by systemd as `speedfog` user
- Deploy: `DEPLOY_HOST=user@host ./deploy/deploy.sh` (builds locally, rsync server code, scp frontend, run migrations, restart)
- Config: `.env` in `server/` read by pydantic-settings (not systemd EnvironmentFile)
- Permissions: deploy user in `speedfog` group, setgid on `server/` and `web-build/`, sudoers for `speedfog` user and `systemctl restart`

## Versioning

- `CHANGELOG.md` — user-facing release notes (player audience), follows [Keep a Changelog](https://keepachangelog.com/) format. Includes changes from both this repo and `../speedfog/`. Technical/infra changes stay in git history only.
- `tools/release.sh <version>` — bumps version in all components (server, web, mod), commits, and creates git tag. Move `[Unreleased]` entries to a new version section in `CHANGELOG.md` before running.
- Version is synchronized across `server/pyproject.toml`, `server/speedfog_racing/__init__.py`, `mod/Cargo.toml`, and `web/package.json`

## Related Projects

- `../speedfog/` - SpeedFog seed generator
- `../../er-fog-vizu/` - Original tracking mod (upstream for fork)
