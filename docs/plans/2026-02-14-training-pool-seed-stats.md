# Training Pool Seed Stats — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

Goal: Show users how many seeds they've already played in each training pool before starting a session.

Architecture: Add `get_played_seed_counts()` service function, enrich `GET /api/pools` with optional auth to include `played_by_user` per pool, update frontend to display seed progress.

Tech Stack: Python/FastAPI, SQLAlchemy async, SvelteKit 5, TypeScript

---

## Task 1: Add `get_played_seed_counts` service function

Files:

- Modify: `server/speedfog_racing/services/training_service.py`
- Modify: `server/speedfog_racing/services/__init__.py`
- Test: `server/tests/test_training.py`

Step 1 — Write the failing test.

Add to `server/tests/test_training.py` after the existing service tests section:

```python
@pytest.mark.asyncio
async def test_get_played_seed_counts_empty(async_session, training_user):
    """No sessions → empty counts."""
    from speedfog_racing.services.training_service import get_played_seed_counts

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {}


@pytest.mark.asyncio
async def test_get_played_seed_counts_one_pool(async_session, training_user, training_seed):
    """One session → count 1 for that pool."""
    from speedfog_racing.services.training_service import get_played_seed_counts

    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1}


@pytest.mark.asyncio
async def test_get_played_seed_counts_distinct(async_session, training_user, training_seed):
    """Two sessions on same seed → still count 1."""
    from speedfog_racing.services.training_service import get_played_seed_counts

    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with async_session() as db:
        counts = await get_played_seed_counts(db, training_user.id)
        assert counts == {"training_standard": 1}
```

Step 2 — Run tests to verify they fail.

Run: `cd server && uv run pytest tests/test_training.py::test_get_played_seed_counts_empty tests/test_training.py::test_get_played_seed_counts_one_pool tests/test_training.py::test_get_played_seed_counts_distinct -v`
Expected: FAIL with `ImportError: cannot import name 'get_played_seed_counts'`

Step 3 — Implement `get_played_seed_counts`.

Add to `server/speedfog_racing/services/training_service.py` after the existing imports (add `func` to sqlalchemy imports):

```python
from sqlalchemy import func, select
```

Add function after `get_training_seed`:

```python
async def get_played_seed_counts(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, int]:
    """Count distinct seeds played by a user, grouped by pool.

    Returns:
        Dict mapping pool_name → number of distinct seeds played.
    """
    result = await db.execute(
        select(Seed.pool_name, func.count(TrainingSession.seed_id.distinct()))
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(TrainingSession.user_id == user_id)
        .group_by(Seed.pool_name)
    )
    return dict(result.all())
```

Export from `server/speedfog_racing/services/__init__.py` — add `get_played_seed_counts` to the training_service import and `__all__`.

Step 4 — Run tests to verify they pass.

Run: `cd server && uv run pytest tests/test_training.py::test_get_played_seed_counts_empty tests/test_training.py::test_get_played_seed_counts_one_pool tests/test_training.py::test_get_played_seed_counts_distinct -v`
Expected: 3 PASSED

Step 5 — Commit.

```bash
git add server/speedfog_racing/services/training_service.py server/speedfog_racing/services/__init__.py server/tests/test_training.py
git commit -m "feat(server): add get_played_seed_counts service function"
```

---

## Task 2: Enrich `GET /api/pools` with `played_by_user`

Files:

- Modify: `server/speedfog_racing/api/pools.py`
- Test: `server/tests/test_training.py`

Step 1 — Write the failing test.

Add to `server/tests/test_training.py` after the API endpoint tests section. The `test_client` fixture already patches `get_pool_config`. We also need to monkeypatch the pools API's `get_pool_config`:

```python
@pytest.fixture
def pool_test_client(async_session, monkeypatch):
    """Test client with pool config patched for the pools API."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    monkeypatch.setattr(
        "speedfog_racing.api.pools.get_pool_config",
        lambda name: TRAINING_POOL_CONFIG if "training" in name else {"type": "race"},
    )

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pools_played_by_user_authenticated(pool_test_client, training_user, training_seed, async_session):
    """GET /api/pools?type=training returns played_by_user when authenticated."""
    # Create a training session for the user
    async with async_session() as db:
        db.add(TrainingSession(user_id=training_user.id, seed_id=training_seed.id))
        await db.commit()

    async with pool_test_client as client:
        resp = await client.get(
            "/api/pools?type=training",
            headers={"Authorization": f"Bearer {training_user.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "training_standard" in data
        assert data["training_standard"]["played_by_user"] == 1


@pytest.mark.asyncio
async def test_pools_played_by_user_unauthenticated(pool_test_client, training_seed):
    """GET /api/pools?type=training returns played_by_user=null when not authenticated."""
    async with pool_test_client as client:
        resp = await client.get("/api/pools?type=training")
        assert resp.status_code == 200
        data = resp.json()
        assert "training_standard" in data
        assert data["training_standard"]["played_by_user"] is None
```

Step 2 — Run tests to verify they fail.

Run: `cd server && uv run pytest tests/test_training.py::test_pools_played_by_user_authenticated tests/test_training.py::test_pools_played_by_user_unauthenticated -v`
Expected: FAIL (either KeyError or assertion on `played_by_user`)

Step 3 — Implement the changes in `pools.py`.

Update `server/speedfog_racing/api/pools.py`:

```python
"""Seed pools API routes (public, with optional auth enrichment)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.models import User
from speedfog_racing.schemas import PoolConfig
from speedfog_racing.services import get_pool_config, get_pool_stats
from speedfog_racing.services.training_service import get_played_seed_counts

router = APIRouter()


class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    played_by_user: int | None = None
    pool_config: PoolConfig | None = None


@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
    pool_type: str | None = Query(None, alias="type"),
    user: User | None = Depends(get_current_user_optional),
) -> dict[str, PoolStats]:
    """Get availability statistics for seed pools.

    Optional filter: ?type=race or ?type=training
    If authenticated, includes played_by_user count for training pools.
    """
    stats = await get_pool_stats(db)

    played_counts: dict[str, int] = {}
    if user:
        played_counts = await get_played_seed_counts(db, user.id)

    result: dict[str, PoolStats] = {}
    for name, counts in stats.items():
        raw_config = get_pool_config(name)
        # Filter by type if requested
        if pool_type and raw_config:
            if raw_config.get("type", "race") != pool_type:
                continue
        elif pool_type and not raw_config:
            if pool_type != "race":
                continue

        is_training = raw_config and raw_config.get("type") == "training"
        result[name] = PoolStats(
            available=counts.get("available", 0),
            consumed=counts.get("consumed", 0),
            played_by_user=played_counts.get(name) if user and is_training else None,
            pool_config=PoolConfig(**raw_config) if raw_config else None,
        )

    return result
```

Step 4 — Run tests to verify they pass.

Run: `cd server && uv run pytest tests/test_training.py::test_pools_played_by_user_authenticated tests/test_training.py::test_pools_played_by_user_unauthenticated -v`
Expected: 2 PASSED

Step 5 — Run full test suite to check for regressions.

Run: `cd server && uv run pytest -v`
Expected: All tests PASSED

Step 6 — Commit.

```bash
git add server/speedfog_racing/api/pools.py server/tests/test_training.py
git commit -m "feat(server): add played_by_user to pool stats for training pools"
```

---

## Task 3: Update frontend to display seed progress

Files:

- Modify: `web/src/lib/api.ts`
- Modify: `web/src/routes/training/+page.svelte`

Step 1 — Add `played_by_user` to TypeScript interface.

In `web/src/lib/api.ts`, add to the `PoolInfo` interface:

```typescript
export interface PoolInfo {
  available: number;
  consumed: number;
  played_by_user: number | null;
  pool_config: PoolConfig | null;
}
```

Step 2 — Update pool card seed display.

In `web/src/routes/training/+page.svelte`, replace the pool card's `.pool-seeds` span (around line 146-148):

```svelte
<span class="pool-seeds" class:pool-exhausted={info.played_by_user != null && info.played_by_user >= info.available}>
    {#if info.played_by_user != null && info.played_by_user > 0}
        {info.played_by_user}/{info.available} seed{info.available !== 1 ? 's' : ''} played
        {#if info.played_by_user >= info.available}
            — seeds will repeat
        {/if}
    {:else}
        {info.available} seed{info.available !== 1 ? 's' : ''} available
    {/if}
</span>
```

Step 3 — Update pool detail footer seed count.

Replace the `.seed-count` span in the pool-detail-footer (around line 156-158):

```svelte
<span class="seed-count" class:pool-exhausted={selectedInfo?.played_by_user != null && selectedInfo.played_by_user >= (selectedInfo?.available ?? 0)}>
    {#if selectedInfo?.played_by_user != null && selectedInfo.played_by_user > 0}
        {selectedInfo.played_by_user}/{selectedInfo.available} seed{selectedInfo.available !== 1 ? 's' : ''} played
        {#if selectedInfo.played_by_user >= selectedInfo.available}
            — seeds will repeat
        {/if}
    {:else}
        {selectedInfo?.available ?? 0} seed{(selectedInfo?.available ?? 0) !== 1 ? 's' : ''} available
    {/if}
</span>
```

Step 4 — Add `.pool-exhausted` style.

Add to the `<style>` block:

```css
.pool-exhausted {
  color: var(--color-gold);
}
```

Step 5 — Run type checking.

Run: `cd web && npm run check`
Expected: No errors

Step 6 — Commit.

```bash
git add web/src/lib/api.ts web/src/routes/training/+page.svelte
git commit -m "feat(web): show seed progress per training pool"
```

---

## Task 4: Manual verification

Step 1 — Run full backend tests.

Run: `cd server && uv run pytest -v`
Expected: All PASSED

Step 2 — Run frontend checks.

Run: `cd web && npm run check`
Expected: No errors

Step 3 — Run linting.

Run: `cd server && uv run ruff check . && uv run ruff format --check .`
Run: `cd web && npm run lint`
Expected: Clean
