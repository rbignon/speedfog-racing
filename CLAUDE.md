# SpeedFog Racing

Competitive racing platform for SpeedFog (Elden Ring randomizer with fog gates).

## Architecture

```
speedfog-racing/
├── server/          # Python/FastAPI backend
├── web/             # SvelteKit frontend (not yet implemented)
├── mod/             # Rust mod injected into the game (not yet implemented)
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
├── websocket/       # WebSocket handlers (not yet implemented)
└── services/        # Business logic (not yet implemented)
```

### Conventions

- SQLAlchemy 2.0 style with `Mapped[]` and `mapped_column()`
- Async everywhere (`AsyncSession`, `async def`)
- Pydantic v2 for validation
- Tests with pytest-asyncio, in-memory SQLite fixtures

## Documentation

- `docs/2026-02-04-speedfog-racing-design.md` - Overall design
- `docs/phase1-spec.md` - Phase 1 MVP detailed spec

## Current State

Phase 1 in progress. See `docs/phase1-spec.md` section 7 for step tracking.

**Completed:** Steps 1-5 (Server Foundation, Twitch Auth, Seed Pool Basic, Race CRUD, Zip Generation)
**Next:** Step 6 (Frontend Foundation)

## Related Projects

- `../speedfog/` - SpeedFog seed generator
- `../../er-fog-vizu/` - Original tracking mod (upstream for fork)
