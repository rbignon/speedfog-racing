# SpeedFog Racing

Competitive racing platform for SpeedFog - race against other players on randomized Elden Ring seeds with real-time tracking.

## Features

- Real-time leaderboard and position tracking
- In-game overlay showing race status
- Spectator view with DAG visualization
- OBS overlays for streamers/casters
- Twitch authentication

## Architecture

```
speedfog-racing/
├── server/          # Python/FastAPI backend
├── web/             # SvelteKit frontend
├── mod/             # Rust mod (fork of er-fog-vizu)
├── tools/           # Seed pool generation scripts
└── docs/            # Design documents and specs
```

## Requirements

- Python 3.11+
- Node.js 20+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Rust toolchain (for mod, Windows MSVC required for DLL build)

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/rbignon/speedfog-racing.git
cd speedfog-racing
```

### 2. Set up PostgreSQL

Create a database for the application:

```bash
createdb speedfog_racing
```

### 3. Configure environment

Create a `.env` file in the `server/` directory:

```bash
cp server/.env.example server/.env  # If example exists, or create manually
```

Edit `server/.env` with your configuration:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/speedfog_racing

# Twitch OAuth (get credentials at https://dev.twitch.tv/console/apps)
TWITCH_CLIENT_ID=your_client_id
TWITCH_CLIENT_SECRET=your_client_secret
TWITCH_REDIRECT_URI=http://localhost:8000/api/auth/callback

# Application
SECRET_KEY=generate-a-secure-random-key
OAUTH_REDIRECT_URL=http://localhost:5173/auth/callback
WEBSOCKET_URL=ws://localhost:8000
CORS_ORIGINS=["http://localhost:5173", "http://localhost:8000"]

# Seeds (adjust paths as needed)
SEEDS_POOL_DIR=/data/seeds
SPEEDFOG_PATH=/path/to/speedfog

# Logging
LOG_LEVEL=INFO
LOG_JSON=false
```

### 4. Set up the server

```bash
cd server

# Install dependencies
uv sync --all-extras

# Run database migrations
uv run alembic upgrade head

# Start the server
uv run speedfog-racing
```

The API will be available at `http://localhost:8000`.

### 5. Set up the frontend

```bash
cd web

# Install dependencies
npm install

# Start dev server (proxies /api to localhost:8000)
npm run dev
```

The frontend will be available at `http://localhost:5173`.

### 6. Build the mod (Windows only)

The mod requires Windows with MSVC toolchain to build the DLL:

```bash
cd mod

# Build release DLL
cargo build --lib --release
```

The DLL will be at `target/release/speedfog_race_mod.dll`.

On Linux, you can check syntax but not build:

```bash
cargo check --lib
cargo test
```

## Development

### Server commands

```bash
cd server

# Run server
uv run speedfog-racing

# Run tests
uv run pytest

# Linting
uv run ruff check .
uv run ruff format .
uv run mypy speedfog_racing/
```

### Frontend commands

```bash
cd web

# Dev server with hot reload
npm run dev

# Type checking
npm run check

# Linting
npm run lint

# Format code
npm run format

# Build for production
npm run build
```

### Mod commands

```bash
cd mod

# Check syntax (Linux/Windows)
cargo check --lib

# Run tests
cargo test

# Build DLL (Windows only)
cargo build --lib --release
```

## API Documentation

Once the server is running, API documentation is available at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## WebSocket Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the complete WebSocket protocol reference.

## Related Projects

- [SpeedFog](https://github.com/rbignon/speedfog) - Seed generator for Elden Ring fog gate randomizer
- [er-fog-vizu](https://github.com/rbignon/er-fog-vizu) - Original tracking mod (upstream for fork)

## License

AGPL-3.0
