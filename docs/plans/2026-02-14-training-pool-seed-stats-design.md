# Training Pool Seed Stats — Design

**Date:** 2026-02-14
**Goal:** Show users how many seeds they've already played in each training pool, so they know before starting a session whether they'll replay a seed.

## Context

`get_training_seed()` excludes seeds already played by the user, then resets when the pool is exhausted (picks randomly from all seeds). Currently there's no indication to the user that they've played all seeds and will get repeats.

## Approach

Enrich the existing `GET /api/pools?type=training` response with a `played_by_user` count per pool. No new endpoints.

## Backend Changes

### `server/speedfog_racing/api/pools.py`

- Add `played_by_user: int | None = None` to `PoolStats`
- Make auth optional: accept `get_optional_user` dependency
- If user is authenticated, query `training_sessions` to count distinct `seed_id` per pool for that user
- Add helper in `training_service.py`: `get_played_seed_counts(db, user_id) -> dict[str, int]` mapping pool_name → count of distinct seeds played

### `server/speedfog_racing/services/training_service.py`

New function:

```python
async def get_played_seed_counts(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Count distinct seeds played by user per pool."""
    # JOIN training_sessions with seeds ON seed_id
    # GROUP BY seeds.pool_name
    # SELECT pool_name, COUNT(DISTINCT seed_id)
```

## Frontend Changes

### `web/src/lib/api.ts`

- Add `played_by_user: number | null` to `PoolInfo` interface

### `web/src/routes/training/+page.svelte`

Pool card `.pool-seeds` and `.pool-detail-footer .seed-count`:

- `played_by_user === null` or `played_by_user === 0`: show `"{available} seeds available"` (unchanged)
- `0 < played_by_user < available`: show `"{played_by_user}/{available} seeds played"`
- `played_by_user >= available`: show `"{played_by_user}/{available} seeds played — seeds will repeat"` with warning color

Start button remains always enabled.

## Not In Scope

- Rotation tracking (cycle-aware exclusion)
- Blocking replay when pool exhausted
