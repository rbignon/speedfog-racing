# Slow Run — Exclude from Stats

**Date:** 2026-02-27
**Status:** Approved

## Summary

Add an `exclude_from_stats` boolean flag to training sessions, allowing players to mark a solo run as a "slow run" at creation time. Slow runs are excluded from performance stats (avg_time, best_time, avg_deaths) but remain visible everywhere else.

## Data Model

- New column: `TrainingSession.exclude_from_stats: Mapped[bool] = mapped_column(default=False)`
- Alembic migration: `ALTER TABLE training_sessions ADD COLUMN exclude_from_stats BOOLEAN NOT NULL DEFAULT FALSE`

## API Changes

### `POST /api/training`

- Add `exclude_from_stats: bool = False` to request body (`TrainingSessionCreateRequest`)

### `TrainingSessionResponse` / `TrainingSessionDetailResponse`

- Expose `exclude_from_stats: bool` for frontend display

### `GET /{username}/pool-stats`

- Add `.where(TrainingSession.exclude_from_stats == False)` to the training stats query
- Both aggregation metrics (avg/min) AND `runs` count are filtered

### No changes

- WebSocket protocol (flag is stats-only, no real-time impact)
- `training_count` in user stats (slow runs count)
- Activity timeline (slow runs appear)
- Ghost replays (slow runs included)
- Seed anti-repetition (slow runs count as "already played")

## Frontend

### Training page (`/training`)

- Checkbox "Slow run" after pool selection, before "Start" button
- Muted description: "This session won't count in your performance stats"
- Checkbox state sent as `exclude_from_stats` in `POST /api/training`

### History & detail

- "Slow" badge (muted gray style) displayed:
  - In history table on `/training` (next to status badge)
  - In header of `/training/[id]`

## Design Decisions

- **Boolean over enum**: YAGNI — the need is binary (exclude or not). An enum can be introduced later if needed.
- **Definitive at creation**: Cannot be changed after session start. Avoids retroactive stat manipulation.
- **Performance stats only**: Keeps slow runs visible in history, activity, ghosts, and training count. Only excludes from avg_time, best_time, avg_deaths aggregations.
