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
├── main.py              # FastAPI app, CORS, lifespan
├── config.py            # Pydantic settings (env vars)
├── database.py          # SQLAlchemy async setup
├── models.py            # DB models (User, Race, Seed, Participant, Caster, Invite, TrainingSession, EloHistory, PlayerTraitScores)
├── auth.py              # Twitch OAuth helpers + FastAPI dependencies
├── schemas.py           # Pydantic schemas for API responses
├── discord.py           # Discord bot integration
├── rate_limit.py        # slowapi rate limiting setup
├── api/                 # REST routes
│   ├── auth.py          # /api/auth/*
│   ├── races.py         # /api/races/*
│   ├── users.py         # /api/users/*
│   ├── admin.py         # /api/admin/*
│   ├── discord.py       # /api/discord/*
│   ├── invites.py       # /api/invites/*
│   ├── pools.py         # /api/pools/*
│   ├── stats.py         # /api/stats/*
│   ├── training.py      # /api/training/*
│   ├── helpers.py       # Shared API helpers (auth, pagination)
│   └── i18n.py          # Internationalization routes
├── websocket/           # WebSocket handlers
│   ├── manager.py       # Connection manager for race rooms
│   ├── mod.py           # Mod WebSocket handler
│   ├── spectator.py     # Spectator WebSocket handler
│   ├── schemas.py       # WebSocket message schemas
│   ├── common.py        # Shared WebSocket utilities
│   ├── training_manager.py  # Training mode connection manager
│   ├── training_mod.py      # Training mod WebSocket handler
│   └── training_spectator.py # Training spectator handler
├── services/            # Business logic
│   ├── seed_service.py      # Seed pool management
│   ├── seed_pack_service.py # Seed pack generation for participants
│   ├── seed_difficulty.py   # Seed difficulty scoring
│   ├── race_lifecycle.py    # Race state transitions
│   ├── layer_service.py     # Zone layer/tier computation
│   ├── zone_resolver.py     # Zone name resolution from event flags
│   ├── stats_service.py     # ELO ratings + behavioral traits
│   ├── training_service.py  # Training session management
│   ├── grace_service.py     # Grace period logic
│   ├── inactivity_monitor.py # AFK detection
│   ├── twitch_live.py       # Twitch live status polling
│   └── i18n.py              # Server-side i18n
└── ...
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
│   ├── api.ts               # REST API client + types
│   ├── websocket.ts         # WebSocket client with reconnect
│   ├── format.ts            # Display formatting helpers
│   ├── highlights.ts        # Race highlights computation
│   ├── personal-highlights.ts # Per-player highlights
│   ├── stores/
│   │   ├── auth.svelte.ts       # Auth store (isLoggedIn, currentUser)
│   │   ├── race.svelte.ts       # Race state store (live WebSocket data)
│   │   ├── locale.svelte.ts     # Locale/i18n store
│   │   └── training.svelte.ts   # Training session state
│   ├── dag/                 # Metro-style DAG (pure SVG, custom layout)
│   │   ├── MetroDag.svelte      # Main DAG component
│   │   ├── NodePopup.svelte     # Zone info popup
│   │   ├── layout.ts            # DAG layout algorithm
│   │   ├── popupData.ts         # Popup data aggregation
│   │   └── ...
│   ├── replay/              # Race replay system
│   │   ├── RaceReplay.svelte    # Replay player
│   │   ├── ReplayDag.svelte     # Replay DAG view
│   │   └── ...
│   ├── utils/               # Shared utilities
│   ├── data/                # Static data files
│   └── components/          # UI components (30+)
│       ├── Leaderboard.svelte       # Live leaderboard
│       ├── RaceStatus.svelte        # Status badge
│       ├── RaceCard.svelte          # Race list card
│       ├── RaceControls.svelte      # Organizer race actions
│       ├── RaceHighlights.svelte    # Post-race highlights
│       ├── RaceStats.svelte         # Race statistics
│       ├── ParticipantCard.svelte   # Player card with optional remove
│       ├── CasterList.svelte        # Caster management
│       ├── Podium.svelte            # Podium display
│       ├── PlayStyle.svelte         # Player trait visualization
│       ├── ChatPanel.svelte         # Race chat
│       ├── LeaderboardOverlay.svelte # OBS overlay leaderboard
│       ├── stats/                   # Stats page components
│       │   ├── LeaderboardTab.svelte
│       │   ├── PlayersTab.svelte
│       │   ├── ZonesTab.svelte
│       │   └── BossesTab.svelte
│       └── ...
└── routes/
    ├── +layout.svelte   # Global layout with navbar
    ├── +page.svelte     # Home (race list + hero DAG)
    ├── auth/            # Twitch OAuth callback
    ├── race/
    │   ├── new/         # Create race form
    │   └── [id]/        # Race detail (spectator + organizer view)
    ├── races/           # Race listing
    ├── training/        # Training mode
    ├── stats/           # Global statistics
    ├── dashboard/       # User dashboard
    ├── admin/           # Admin panel
    ├── overlay/         # OBS overlay
    ├── user/            # User profiles
    ├── settings/        # User settings
    ├── invite/          # Invite handling
    ├── about/           # About page
    ├── changelog/       # Changelog page
    └── help/            # Help page
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
│   ├── types.rs          # PlayerPosition etc.
│   ├── color.rs          # Color utilities
│   ├── constants.rs      # Shared constants
│   ├── flag_buffer.rs    # Event flag buffering
│   ├── format.rs         # Display formatting
│   └── traits.rs         # Shared traits
├── dll/                # Windows-only DLL code
│   ├── mod.rs
│   ├── config.rs         # TOML config loading
│   ├── tracker.rs        # Main orchestrator
│   ├── ui.rs             # ImGui overlay
│   ├── websocket.rs      # WebSocket client
│   ├── death_icon.rs     # Death icon overlay
│   └── hotkey.rs         # Hotkey handling
└── eldenring/          # Game memory reading
    ├── mod.rs
    ├── game_state.rs     # Game state detection
    ├── event_flags.rs    # EMEVD event flag reading (VirtualMemoryFlag tree)
    ├── item_spawner.rs   # Item spawn via game memory
    └── warp_hook.rs      # Warp/teleport hook
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

- `docs/GRAPHIC_CHARTER.md` - Visual identity and color palette
- `docs/PROTOCOL.md` - API and WebSocket protocol reference
- `docs/RACE_LIFECYCLE.md` - State machines (race, participant, seed) and transition rules
- `docs/WEBSOCKET_LIFECYCLE.md` - WebSocket connection management (mod reconnect, spectator auth, broadcast safety)
- `docs/EVENT_FLAG_TRACKING.md` - Event flag polling, zone progression, gap timing
- `docs/STATS.md` - ELO ratings, behavioral traits, zone/boss analytics
- `docs/SEED_PIPELINE.md` - Seed generation, ingestion, on-demand pack assembly
- `docs/DISCORD_BOT.md` - Discord bot setup and configuration

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
