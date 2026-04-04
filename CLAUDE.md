# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SpeedFog Racing is a competitive Elden Ring speedrunning platform with three components:

- **server/**: Python 3.11+ FastAPI backend (PostgreSQL, SQLAlchemy async, Alembic migrations)
- **web/**: SvelteKit 2 frontend (Svelte 5, TypeScript, static adapter with SPA fallback)
- **mod/**: Rust DLL injected into Elden Ring (Windows MSVC only; hudhook/ImGui overlay, libeldenring memory reading)

## Common Commands

### Backend (server/)

```bash
cd server
uv sync --all-extras              # Install all deps including dev/test
uv run speedfog-racing            # Start dev server on :8000 (API docs at /docs)
uv run pytest                     # Run all tests (uses SQLite, no Postgres needed)
uv run pytest tests/test_races.py # Run single test file
uv run pytest tests/test_races.py::test_create_race -v  # Single test
uv run ruff check .               # Lint
uv run ruff format .              # Format
uv run mypy speedfog_racing/      # Type check (strict mode)
uv run alembic revision --autogenerate -m "description"  # Create migration
uv run alembic upgrade head       # Apply migrations
```

### Frontend (web/)

```bash
cd web
npm install                       # Install deps
npm run dev                       # Dev server on :5173 (proxies /api and /ws to :8000)
npm run check                     # svelte-check + TypeScript
npm run lint                      # Prettier + ESLint
npm run format                    # Prettier write
npm run test                      # Vitest
npm run build                     # Production build (static adapter)
```

### Mod (mod/)

```bash
cd mod
cargo check --lib                 # Syntax check (works on Linux)
cargo test                        # Run tests
cargo build --lib --release       # Build DLL (Windows MSVC only)
```

### Deploy

```bash
./deploy/deploy.sh                # Builds frontend, uploads to VPS, runs migrations, restarts service
```

## Architecture

### Backend layers

REST routes (`api/`) and WebSocket handlers (`websocket/`) call into a services layer (`services/`). Models are in `models.py`, Pydantic schemas in `schemas.py`, config in `config.py` (Pydantic settings from `.env`).

### WebSocket protocol

Two connection types: **mod connections** (`/ws/mod/{race_id}`) for the in-game overlay sending game state (zones, event flags, IGT), and **spectator connections** (`/ws/race/{race_id}/spectate`) for the web UI receiving live updates. `websocket/manager.py` manages rooms and broadcast. See `docs/PROTOCOL.md` and `docs/WEBSOCKET_LIFECYCLE.md`.

### Race lifecycle

`RaceStatus`: setup -> running -> finished. `ParticipantStatus`: registered -> ready -> playing -> finished/abandoned. The organizer controls transitions. ELO is computed on finish using OpenSkill (see `docs/STATS.md`).

### Dual chat

Two channels per race: "participants" (private during race, no spoilers) and "public" (spoilers, unlocked after finishing). Messages are persistent in the database.

### Zone tracking

Game event flags map to map zones. The frontend renders a DAG (directed acyclic graph) of possible paths. Zone history is stored per participant.

### Frontend routing

SvelteKit file-based routing under `web/src/routes/`. Key paths: `/race/[id]` (race page), `/overlay/race/[id]/leaderboard` and `/overlay/race/[id]/dag` (OBS overlays), `/stats` (leaderboards), `/training/[id]` (solo sessions), `/admin` (admin panel). API client in `lib/api.ts`, WebSocket client in `lib/websocket.ts`.

### Mod architecture

Rust DLL entry point in `lib.rs`. `dll/` has the main loop (`mod.rs`), ImGui overlay (`ui.rs`), WebSocket client (`websocket.rs`), game event tracker (`tracker.rs`). `eldenring/` has game-specific logic: memory reading (`game_state.rs`), event flags (`event_flags.rs`), warp detection (`warp_hook.rs`). Cross-platform core in `core/` (protocol, types, constants).

## Code Style

- **Python**: ruff (line-length 100, rules E/F/I/UP), mypy strict, async/await for all I/O
- **Frontend**: Prettier + ESLint, strict TypeScript, Svelte 5 runes (`$state`, `$derived`)
- **Rust**: Edition 2021, stable toolchain, MSVC only for builds

## Testing Notes

- Backend tests use SQLite via aiosqlite (no PostgreSQL setup needed). Fixtures in `server/tests/conftest.py`.
- Frontend tests use Vitest, located in `web/src/lib/__tests__/`.
- pytest is configured with `asyncio_mode = "auto"` and 30s timeout per test.
