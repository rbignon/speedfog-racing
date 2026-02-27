<!-- markdownlint-disable MD001 MD036 -->

# Slow Run (Exclude from Stats) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let players mark a training session as a "slow run" at creation time, excluding it from performance stats (avg_time, best_time, avg_deaths) while keeping it visible everywhere else.

**Architecture:** A boolean `exclude_from_stats` column on `TrainingSession`, passed via the creation API, filtered in the pool-stats query. Frontend adds a checkbox before the Start button and a muted "Slow" badge in history/detail views.

**Tech Stack:** SQLAlchemy (Alembic migration), FastAPI/Pydantic, SvelteKit 5 (runes), CSS badges

---

### Task 1: Add `exclude_from_stats` column to model + migration

**Files:**

- Modify: `server/speedfog_racing/models.py:250` (after `finished_at`)
- Create: `server/alembic/versions/<auto>_add_exclude_from_stats_to_training_sessions.py`

**Step 1: Add column to model**

In `server/speedfog_racing/models.py`, add after line 250 (`finished_at`):

```python
    exclude_from_stats: Mapped[bool] = mapped_column(default=False)
```

**Step 2: Generate Alembic migration**

Run:

```bash
cd server && uv run alembic revision --autogenerate -m "add exclude_from_stats to training_sessions"
```

Expected: New migration file created in `server/alembic/versions/`.

**Step 3: Apply migration (verify it works)**

Run:

```bash
cd server && uv run alembic upgrade head
```

Expected: SUCCESS, no errors.

**Step 4: Commit**

```bash
git add server/speedfog_racing/models.py server/alembic/versions/*exclude_from_stats*
git commit -m "feat(db): add exclude_from_stats column to training_sessions"
```

---

### Task 2: Update schemas and creation API

**Files:**

- Modify: `server/speedfog_racing/schemas.py:339-382` (training schemas)
- Modify: `server/speedfog_racing/api/training.py:132-171` (create endpoint)
- Modify: `server/speedfog_racing/services/training_service.py:92-125` (create service)

**Step 1: Add `exclude_from_stats` to schemas**

In `server/speedfog_racing/schemas.py`:

Add to `CreateTrainingRequest` (line 339):

```python
class CreateTrainingRequest(BaseModel):
    """Request to create a training session."""

    pool_name: str = "training_standard"
    exclude_from_stats: bool = False
```

Add `exclude_from_stats: bool` to `TrainingSessionResponse` (after `death_count`, line 355):

```python
    exclude_from_stats: bool
```

Add `exclude_from_stats: bool` to `TrainingSessionDetailResponse` (after `death_count`, line 374):

```python
    exclude_from_stats: bool
```

**Step 2: Pass `exclude_from_stats` through creation flow**

In `server/speedfog_racing/services/training_service.py`, update `create_training_session` signature (line 92):

```python
async def create_training_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    pool_name: str,
    *,
    exclude_from_stats: bool = False,
) -> TrainingSession:
```

And update the `TrainingSession(...)` constructor (line 106):

```python
    session = TrainingSession(
        user_id=user_id,
        seed_id=seed.id,
        exclude_from_stats=exclude_from_stats,
    )
```

In `server/speedfog_racing/api/training.py`, update the `create_session` endpoint (line 166):

```python
        session = await create_training_session(db, user.id, body.pool_name, exclude_from_stats=body.exclude_from_stats)
```

**Step 3: Expose in list response builder**

In `server/speedfog_racing/api/training.py`, add `exclude_from_stats` to `_build_list_response` (line 93):

```python
    return TrainingSessionResponse(
        ...
        exclude_from_stats=session.exclude_from_stats,
        ...
    )
```

And to `_build_detail_response` (line 113):

```python
    return TrainingSessionDetailResponse(
        ...
        exclude_from_stats=session.exclude_from_stats,
        ...
    )
```

**Step 4: Run linting**

Run:

```bash
cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/
```

Expected: No errors (or only pre-existing ones).

**Step 5: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/training.py server/speedfog_racing/services/training_service.py
git commit -m "feat(api): accept and expose exclude_from_stats on training sessions"
```

---

### Task 3: Filter pool stats query

**Files:**

- Modify: `server/speedfog_racing/api/users.py:211-227`

**Step 1: Add filter to training stats query**

In `server/speedfog_racing/api/users.py`, update the training stats query (line 212-227). Add `TrainingSession.exclude_from_stats == False` to the `.where()`:

```python
    training_stats_q = await db.execute(
        select(
            Seed.pool_name,
            func.count().label("runs"),
            func.avg(TrainingSession.igt_ms).label("avg_time_ms"),
            func.avg(TrainingSession.death_count).label("avg_deaths"),
            func.min(TrainingSession.igt_ms).label("best_time_ms"),
        )
        .select_from(TrainingSession)
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.status == TrainingSessionStatus.FINISHED,
            TrainingSession.exclude_from_stats == False,  # noqa: E712
        )
        .group_by(Seed.pool_name)
    )
```

Note: `== False` (not `is False`) is correct for SQLAlchemy column comparison. The `# noqa: E712` suppresses the ruff linting warning.

**Step 2: Run linting**

Run:

```bash
cd server && uv run ruff check . && uv run ruff format .
```

**Step 3: Commit**

```bash
git add server/speedfog_racing/api/users.py
git commit -m "feat(stats): exclude slow runs from training performance stats"
```

---

### Task 4: Write tests

**Files:**

- Modify: `server/tests/test_pool_stats.py`
- Modify: `server/tests/test_training.py`

**Step 1: Add pool stats test for exclude_from_stats**

In `server/tests/test_pool_stats.py`, add a slow-run training session to the `user_with_pool_data` fixture (after the active training session, around line 183):

```python
        # 1 finished "slow" training on training_standard (should NOT count in stats)
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seed_training_std.id,
                status=TrainingSessionStatus.FINISHED,
                igt_ms=500000,
                death_count=20,
                exclude_from_stats=True,
            )
        )
```

The existing test assertions should still pass because the slow run is excluded. This validates the filter works: only the original `igt_ms=100000, death_count=3` session counts.

**Step 2: Add a dedicated test for slow run exclusion**

In `server/tests/test_pool_stats.py`, add a new test:

```python
@pytest.mark.asyncio
async def test_pool_stats_excludes_slow_runs(test_client, user_with_pool_data):
    """Slow runs (exclude_from_stats=True) are excluded from training stats."""
    async with test_client as client:
        response = await client.get("/api/users/pool_player/pool-stats")
        assert response.status_code == 200
        data = response.json()
        pools = data["pools"]

        std = next(p for p in pools if p["pool_name"] == "standard")
        # Only the non-slow training session counts (igt_ms=100000, deaths=3)
        assert std["training"]["runs"] == 1
        assert std["training"]["avg_time_ms"] == 100000
        assert std["training"]["best_time_ms"] == 100000
        assert std["training"]["avg_deaths"] == pytest.approx(3.0)
```

**Step 3: Add training API test for exclude_from_stats**

In `server/tests/test_training.py`, add a test verifying that `exclude_from_stats` is accepted and returned. Find the section where session creation is tested and add:

```python
async def test_create_session_with_exclude_from_stats(test_client, user_token, ...):
    """Creating a session with exclude_from_stats=True persists the flag."""
    async with test_client as client:
        response = await client.post(
            "/api/training",
            json={"pool_name": "training_standard", "exclude_from_stats": True},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["exclude_from_stats"] is True
```

Note: Adapt the fixture names to match what's used in `test_training.py`. Read the existing test patterns carefully to match fixture setup.

**Step 4: Run tests**

Run:

```bash
cd server && uv run pytest tests/test_pool_stats.py tests/test_training.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add server/tests/test_pool_stats.py server/tests/test_training.py
git commit -m "test: add tests for exclude_from_stats on training sessions"
```

---

### Task 5: Frontend — API types and createTrainingSession

**Files:**

- Modify: `web/src/lib/api.ts:940-981`

**Step 1: Add `exclude_from_stats` to TypeScript types**

In `web/src/lib/api.ts`, add to `TrainingSession` interface (line 940):

```typescript
export interface TrainingSession {
  id: string;
  user: User;
  status: "active" | "finished" | "abandoned";
  pool_name: string;
  igt_ms: number;
  death_count: number;
  exclude_from_stats: boolean;
  created_at: string;
  finished_at: string | null;
  seed_total_layers: number | null;
  seed_total_nodes: number | null;
  current_layer: number;
}
```

**Step 2: Update `createTrainingSession` to accept the flag**

In `web/src/lib/api.ts`, update `createTrainingSession` (line 969):

```typescript
export async function createTrainingSession(
  poolName: string,
  excludeFromStats: boolean = false,
): Promise<TrainingSessionDetail> {
  const response = await fetch(`${API_BASE}/training`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      pool_name: poolName,
      exclude_from_stats: excludeFromStats,
    }),
  });
  return handleResponse<TrainingSessionDetail>(response);
}
```

**Step 3: Run type checking**

Run:

```bash
cd web && npm run check
```

Expected: No new errors.

**Step 4: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat(web): add exclude_from_stats to training session types and API"
```

---

### Task 6: Frontend — Checkbox in training creation UI

**Files:**

- Modify: `web/src/routes/training/+page.svelte`

**Step 1: Add state for the checkbox**

In the `<script>` section (around line 22), add:

```typescript
let slowRun = $state(false);
```

**Step 2: Add checkbox UI before the Start button**

In the template, inside the `{#if selectedPool && selectedConfig}` block (around line 153), add a checkbox between `<PoolSettingsCard>` and `<div class="pool-detail-footer">`:

```svelte
    <label class="slow-run-toggle">
     <input type="checkbox" bind:checked={slowRun} />
     <span class="slow-run-label">Slow run</span>
     <span class="slow-run-desc">This session won't count in your performance stats</span>
    </label>
```

**Step 3: Pass the flag to the API call**

Update the `startTraining` function (line 74):

```typescript
const session = await createTrainingSession(poolName, slowRun);
```

**Step 4: Reset checkbox when pool changes (optional but good UX)**

Not strictly needed — `slowRun` resets when the component remounts. Keep it simple.

**Step 5: Add CSS for the checkbox**

Add in the `<style>` section:

```css
.slow-run-toggle {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-top: 0.75rem;
  cursor: pointer;
}

.slow-run-toggle input[type="checkbox"] {
  accent-color: var(--color-gold);
}

.slow-run-label {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text);
}

.slow-run-desc {
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
}
```

**Step 6: Run dev server and verify visually**

Run:

```bash
cd web && npm run dev
```

Check: Navigate to `/training`, select a pool, verify checkbox appears.

**Step 7: Commit**

```bash
git add web/src/routes/training/+page.svelte
git commit -m "feat(web): add slow run checkbox to training session creation"
```

---

### Task 7: Frontend — "Slow" badge in history table and detail page

**Files:**

- Modify: `web/src/routes/training/+page.svelte` (history table)
- Modify: `web/src/routes/training/[id]/+page.svelte` (header)
- Modify: `web/src/app.css` (badge style)

**Step 1: Add badge CSS**

In `web/src/app.css`, after `.badge-active` (line 206), add:

```css
.badge-slow {
  background: rgba(107, 114, 128, 0.15);
  color: var(--color-text-disabled);
  font-weight: 500;
}
```

**Step 2: Add badge in history table**

In `web/src/routes/training/+page.svelte`, in the history table row (around line 213), add the Slow badge after the status badge:

```svelte
        <td>
         <span class="badge badge-{session.status}">{session.status}</span>
         {#if session.exclude_from_stats}
          <span class="badge badge-slow">Slow</span>
         {/if}
        </td>
```

**Step 3: Add badge in detail page header**

In `web/src/routes/training/[id]/+page.svelte`, in the header-right div (around line 195), add before the status badge:

```svelte
    {#if session.exclude_from_stats}
     <span class="badge badge-slow">Slow</span>
    {/if}
```

**Step 4: Run type checking**

Run:

```bash
cd web && npm run check
```

Expected: No errors.

**Step 5: Commit**

```bash
git add web/src/app.css web/src/routes/training/+page.svelte web/src/routes/training/[id]/+page.svelte
git commit -m "feat(web): add slow run badge to training history and detail pages"
```

---

### Task 8: Final verification

**Step 1: Run all server tests**

Run:

```bash
cd server && uv run pytest -v
```

Expected: All tests pass.

**Step 2: Run all linting**

Run:

```bash
cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/
```

Expected: Clean.

**Step 3: Run frontend checks**

Run:

```bash
cd web && npm run check && npm run lint
```

Expected: Clean.

**Step 4: Verify dev flow end-to-end**

Start both servers:

```bash
cd server && uv run speedfog-racing &
cd web && npm run dev &
```

Test flow:

1. Go to `/training`
2. Select a pool
3. Check "Slow run" checkbox
4. Click Start → verify session created with `exclude_from_stats: true`
5. Check history table → "Slow" badge visible
6. Click into session detail → "Slow" badge in header
7. Check user profile pool stats → slow session excluded from avg/best

**Step 5: Final commit if any fixes needed**
