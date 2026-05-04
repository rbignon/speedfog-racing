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

**Per-frame perf is non-negotiable.** `RaceTracker::update` and `ImguiRenderLoop::render` run once per game frame (60+ FPS). Anything done in those paths, or in helpers they call (`render_*`, `write_*`), runs that often. Before adding work to a per-frame path:

- Parse, format, allocate, or compute on receipt (WS message handler, config load) and cache the result on the struct that owns the data. See `CachedColors` (parsed once from hex strings), `RaceInfo::race_ends_at_dt` (parsed in `reparse_dates` on AuthOk / RaceInfoUpdate), `FrameSnapshot` (memory reads cached for the current frame), `LeaderboardCache` (recomputed only when `leaderboard_version` bumps), pre-allocated `RenderBuffers`.
- Avoid per-frame heap allocations: reuse `String` buffers via `RenderBuffers` and `write!`, never `format!` into a fresh `String` if a buffer is already in scope. The exception is rare cosmetic UI text that only renders for a few seconds (e.g. countdown banners), where allocation cost is negligible.
- Memory reads from the game process are expensive: route them through `FrameSnapshot` so the same value is read at most once per frame.
- Use `profile_span!` around any new non-trivial block so Tracy can confirm the cost. If a change is plausibly a hotspot, validate with Tracy (see `docs/MOD_PROFILING.md`) before merging.

## Code Style

- **Python**: ruff (line-length 100, rules E/F/I/UP), mypy strict, async/await for all I/O
- **Frontend**: Prettier + ESLint, strict TypeScript, Svelte 5 runes (`$state`, `$derived`)
- **Rust**: Edition 2021, stable toolchain, MSVC only for builds

## Testing Notes

- Backend tests use SQLite via aiosqlite (no PostgreSQL setup needed). Fixtures in `server/tests/conftest.py`.
- Frontend tests use Vitest, located in `web/src/lib/__tests__/`.
- pytest is configured with `asyncio_mode = "auto"` and 30s timeout per test.

### What to test (and what not to)

A test should fail when a real bug is introduced, not when the code under test is edited in a way that's also reflected in the test. Before adding a test, ask: "if this assertion fails, did something break, or did someone just change a value?"

Avoid these tautological patterns:

- **Mirror tests on constants/catalogs.** Re-asserting that `BADGES["x"].color == "#FFFFFF"` when the catalog literally defines it that way only catches "the constant changed", which is exactly what we want when we edit the catalog. Test invariants instead (uniqueness, derivation rules, structural constraints).
- **Framework default tests.** Asserting that a Pydantic field with `default=0` returns `0`, that an SQLAlchemy nullable column defaults to `None`, or that serde `#[serde(default)]` produces the declared default. Those exercise the framework, not our code. Backward-compat deserialization tests with a specific old-shape JSON payload are fine: they pin a wire contract.
- **Pure getter tests.** A test that calls `pos.pos()` and asserts it returns the `(x, y, z)` it was just constructed with tests nothing.
- **Round-trip-through-nothing tests.** Constructing an object with field `x = "foo"` then asserting `obj.x == "foo"` two lines later. Real round-trips go through DB constraints, serializers with edge cases, or schema validation.
- **Asset snapshot tests.** Asserting an SVG path's `d=` substring or a hardcoded HTML fragment that mirrors the template. They break on any cosmetic edit.
- **Mount-and-read-prop tests in Svelte.** Rendering a component with `text="Alice"` and asserting "Alice" appears just tests Svelte's `{#if}`. Test derived values, branches, or interactions.

What to keep: tests of computed values with edge cases (empty, zero, overflow, locale boundaries), tests of business rules combining multiple inputs, tests of invariants that aren't a single source line (e.g. "all sort_orders are unique"), and tests of error/edge paths (timeouts, 404s, malformed inputs).
