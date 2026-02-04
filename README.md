# SpeedFog Racing

Competitive racing platform for SpeedFog - race against other players on randomized Elden Ring seeds with real-time tracking.

## Overview

SpeedFog Racing enables multiplayer races on SpeedFog seeds with:
- Real-time leaderboard and position tracking
- In-game overlay showing race status
- Spectator view with DAG visualization
- OBS overlays for streamers/casters

## Architecture

```
speedfog-racing/
├── server/          # Python/FastAPI backend
├── web/             # SvelteKit frontend
├── mod/             # Rust mod (fork of er-fog-vizu)
└── tools/           # Pool generation scripts
```

See [design document](../speedfog/docs/plans/2026-02-04-speedfog-racing-design.md) for full architecture.

## Development Status

**Phase 1 (MVP)** - In Progress

## Requirements

- Python 3.11+
- Node.js 20+
- Rust toolchain (for mod)
- PostgreSQL

## Setup

TODO: Setup instructions after Phase 1 implementation.

## Related Projects

- [SpeedFog](../speedfog) - Seed generator
- [er-fog-vizu](../../er-fog-vizu) - Original tracking mod (upstream for fork)
