# Step 3: Seed Pool (Basic) - Design

**Date:** 2026-02-04
**Status:** Approved

## Overview

Implement basic seed pool management: scanning seed directories and assigning seeds to races.

## Pool Structure

```
$SEEDS_POOL_DIR/
└── standard/
    ├── config.toml          # Pool config (ignored by scanner for now)
    ├── seed_123456/
    │   ├── graph.json       # DAG structure, contains total_layers
    │   ├── mod/
    │   ├── ModEngine/
    │   └── launch_speedfog.bat
    └── seed_789012/
        └── ...
```

- Path configured via `SEEDS_POOL_DIR` environment variable
- Scanner looks for `seed_*` directories
- Each seed must have a `graph.json` file
- DB is source of truth for availability (no file moving)

## Service: `seed_service.py`

```python
async def scan_pool(db: AsyncSession, pool_name: str = "standard") -> int:
    """Scan pool directory and sync with database.

    - Iterates over seed_* directories in pool
    - Reads graph.json for metadata (total_layers)
    - Creates Seed records for new seeds (skips existing)
    - Returns count of newly added seeds
    """

async def get_available_seed(db: AsyncSession, pool_name: str = "standard") -> Seed | None:
    """Get a random available seed from the pool.

    - Queries seeds with status=AVAILABLE and matching pool_name
    - Returns random one, or None if pool exhausted
    """

async def assign_seed_to_race(db: AsyncSession, race: Race, pool_name: str) -> Seed:
    """Assign an available seed to a race.

    - Calls get_available_seed
    - Raises ValueError if no seeds available
    - Sets seed.status = CONSUMED
    - Sets race.seed_id = seed.id
    - Returns the assigned seed
    """

async def get_pool_stats(db: AsyncSession) -> dict[str, dict[str, int]]:
    """Get availability stats for all pools.

    Returns: {"standard": {"available": 45, "consumed": 12}, ...}
    """
```

## API: Admin Endpoints

```
POST /api/admin/seeds/scan
    Auth: Admin only
    Body: { "pool_name": "standard" }  (optional)
    Response: { "added": 5, "total": 47 }

GET /api/admin/seeds/stats
    Auth: Admin only
    Response: {
        "pools": {
            "standard": { "available": 45, "consumed": 12 }
        }
    }
```

## Startup Integration

In `main.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Scan seed pool on startup
    async with get_db_context() as db:
        try:
            added = await scan_pool(db, "standard")
            logger.info(f"Seed pool scanned: {added} new seeds added")
        except Exception as e:
            logger.warning(f"Seed pool scan failed: {e}")

    yield
```

Scan failure is non-fatal (warning only) to allow server to start without seeds configured.

## Files to Create/Modify

**Create:**

- `server/speedfog_racing/services/seed_service.py`
- `server/speedfog_racing/api/admin.py`
- `server/tests/test_seed_service.py`

**Modify:**

- `server/speedfog_racing/api/__init__.py` - add admin router
- `server/speedfog_racing/main.py` - add scan on startup
- `server/speedfog_racing/database.py` - add `get_db_context()` for non-request usage

## Tests

1. **Scanner tests:**
   - Scan empty directory returns 0
   - Scan directory with seeds creates DB records
   - Re-scan skips existing seeds

2. **Assignment tests:**
   - `get_available_seed` returns seed when available
   - `get_available_seed` returns None when exhausted
   - `assign_seed_to_race` marks seed as consumed
   - `assign_seed_to_race` raises when no seeds

3. **Admin endpoint tests:**
   - Requires admin role (403 for regular users)
   - Returns correct stats
