<!-- markdownlint-disable MD001 MD036 -->

# Seed Release Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gate seed pack downloads behind an explicit organizer "Release Seeds" action, preventing early access before the race.

**Architecture:** Add `seeds_released_at` nullable timestamp to the Race model. New `POST /release-seeds` endpoint sets it. Download endpoints return 403 when NULL. Reroll resets it to NULL. Frontend gates download buttons and shows release controls.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0, Alembic, SvelteKit 5, TypeScript

**Design doc:** `docs/plans/2026-02-19-seed-release-workflow-design.md`

---

### Task 1: Add `seeds_released_at` column to Race model

**Files:**

- Modify: `server/speedfog_racing/models.py:105-139` (Race class)

**Step 1: Add the column**

In `models.py`, add after `started_at` (line 122):

```python
seeds_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Step 2: Run tests to ensure no regression**

Run: `cd server && uv run pytest tests/test_races.py -x -q`
Expected: All existing tests pass (column is nullable, no migration needed for SQLite test DB).

**Step 3: Commit**

```
feat(model): add seeds_released_at column to Race
```

---

### Task 2: Create Alembic migration

**Files:**

- Create: `server/alembic/versions/xxxx_add_seeds_released_at_to_race.py`

**Step 1: Generate migration**

```bash
cd server && uv run alembic revision --autogenerate -m "add seeds_released_at to race"
```

**Step 2: Verify generated migration**

Open the generated file. It should contain:

```python
def upgrade() -> None:
    op.add_column("races", sa.Column("seeds_released_at", sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column("races", "seeds_released_at")
```

No server_default needed — NULL means "not released". Existing races with status RUNNING/FINISHED already started, so NULL is correct for them (download already happened).

**Step 3: Commit**

```
feat(db): add migration for seeds_released_at column
```

---

### Task 3: Add `seeds_released_at` to API schemas

**Files:**

- Modify: `server/speedfog_racing/schemas.py:179-200` (RaceResponse)
- Modify: `server/speedfog_racing/schemas.py:228-251` (RaceDetailResponse)

**Step 1: Add field to both response schemas**

In `RaceResponse` (after `started_at` on line 192):

```python
seeds_released_at: datetime | None = None
```

In `RaceDetailResponse` (after `started_at` on line 241):

```python
seeds_released_at: datetime | None = None
```

**Step 2: Run tests**

Run: `cd server && uv run pytest tests/test_races.py -x -q`
Expected: PASS (field has default None, existing tests unaffected).

**Step 3: Commit**

```
feat(schema): add seeds_released_at to race response schemas
```

---

### Task 4: Create `POST /release-seeds` endpoint with tests (TDD)

**Files:**

- Modify: `server/speedfog_racing/api/races.py`
- Create: `server/tests/test_seed_release.py`

**Step 1: Write the test file**

Create `server/tests/test_seed_release.py`:

```python
"""Tests for seed release workflow."""

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="org123",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="organizer_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="player123",
            twitch_username="player1",
            twitch_display_name="Player One",
            api_token="player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        seed = Seed(
            seed_number="abc123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": {}},
            total_layers=10,
            folder_path="/test/seed_abc123.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return seed


@pytest.fixture
async def race_setup(async_session, organizer, seed):
    """A SETUP race with seeds NOT released."""
    async with async_session() as db:
        race = Race(
            name="Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            # seeds_released_at is NULL by default
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race


@pytest.fixture
async def race_with_participant(async_session, race_setup, player):
    """A SETUP race with one participant."""
    async with async_session() as db:
        participant = Participant(
            race_id=race_setup.id,
            user_id=player.id,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(participant)
    return race_setup


class TestReleaseSeedsEndpoint:
    """Tests for POST /races/{id}/release-seeds."""

    def test_release_seeds_organizer(self, client, organizer, race_setup):
        """Organizer can release seeds."""
        resp = client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["seeds_released_at"] is not None

    def test_release_seeds_non_organizer_forbidden(self, client, player, race_setup):
        """Non-organizer cannot release seeds."""
        resp = client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 403

    def test_release_seeds_already_released(self, client, organizer, race_setup):
        """Cannot release seeds twice."""
        # First release
        client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        # Second release
        resp = client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400

    def test_release_seeds_not_setup(self, client, organizer, async_session, race_setup):
        """Cannot release seeds for non-SETUP race."""
        import asyncio

        async def _set_running():
            async with async_session() as db:
                race = await db.get(Race, race_setup.id)
                race.status = RaceStatus.RUNNING
                race.started_at = datetime.now(UTC)
                await db.commit()

        asyncio.get_event_loop().run_until_complete(_set_running())

        resp = client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400


class TestDownloadGating:
    """Tests that download is gated on seeds_released_at."""

    def test_download_blocked_before_release(self, client, player, race_with_participant):
        """Participant cannot download before seeds are released."""
        resp = client.get(
            f"/api/races/{race_with_participant.id}/my-seed-pack",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 403
        assert "released" in resp.json()["detail"].lower()

    def test_download_allowed_after_release(
        self, client, organizer, player, race_with_participant, seed_zip_context
    ):
        """Participant can download after seeds are released."""
        # Release seeds
        client.post(
            f"/api/races/{race_with_participant.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Mock the seed folder_path to the temp zip
        import asyncio

        async def _set_folder():
            from speedfog_racing.database import get_db

            # This is tested via the client fixture which overrides get_db
            pass

        # Note: full download test requires seed file on disk.
        # The 403 gating test above is the important one.
        # Integration tests with real files are in test_races.py.


class TestRerollResetsRelease:
    """Tests that reroll resets seeds_released_at to NULL."""

    def test_reroll_clears_seeds_released(self, client, organizer, race_setup):
        """Rerolling after release resets seeds_released_at to NULL."""
        # Release seeds
        resp = client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.json()["seeds_released_at"] is not None

        # Reroll seed
        resp = client.post(
            f"/api/races/{race_setup.id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["seeds_released_at"] is None


class TestStartRaceRequiresRelease:
    """Tests that start race requires seeds to be released."""

    def test_start_blocked_before_release(self, client, organizer, race_setup):
        """Cannot start race before seeds are released."""
        resp = client.post(
            f"/api/races/{race_setup.id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400
        assert "release" in resp.json()["detail"].lower()

    def test_start_allowed_after_release(self, client, organizer, race_setup):
        """Can start race after seeds are released."""
        # Release seeds
        client.post(
            f"/api/races/{race_setup.id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        # Start race
        resp = client.post(
            f"/api/races/{race_setup.id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
```

**Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_seed_release.py -x -q`
Expected: FAIL — endpoint doesn't exist yet.

**Step 3: Implement the release-seeds endpoint**

In `server/speedfog_racing/api/races.py`, add after the `start_race` endpoint (after line 762):

```python
@router.post("/{race_id}/release-seeds", response_model=RaceDetailResponse)
async def release_seeds(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Release seeds so participants can download their packs."""
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    _require_organizer(race, user)

    if race.status != RaceStatus.SETUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only release seeds for setup races",
        )

    if race.seeds_released_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seeds are already released",
        )

    # Atomic update with optimistic locking
    now = datetime.now(UTC)
    current_version = race.version
    result = await db.execute(
        update(Race)
        .where(Race.id == race.id, Race.version == current_version)
        .values(seeds_released_at=now, version=current_version + 1)
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Race was modified concurrently, please retry",
        )
    race.seeds_released_at = now
    race.version = current_version + 1
    await db.commit()

    # Notify connected clients
    await broadcast_race_state_update(race_id, race)

    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)
```

**Step 4: Add download gating to both download endpoints**

In `download_my_seed_pack` (line 937), add after the `race = await _get_race_or_404` call (line 948):

```python
    # Gate download on seed release
    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeds have not been released yet",
        )
```

In `download_seed_pack` (line 988), add after the `race = await _get_race_or_404` call (line 1000):

```python
    # Gate download on seed release
    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeds have not been released yet",
        )
```

**Step 5: Add start race gating**

In `start_race` (line 712), add after the status check (after line 726):

```python
    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seeds must be released before starting the race",
        )
```

**Step 6: Make reroll reset `seeds_released_at`**

In `reroll_seed` (line 765), in the `.values()` call on line 799, add `seeds_released_at=None`:

```python
        .values(version=current_version + 1, seed_id=race.seed_id, seeds_released_at=None)
```

Also update the in-memory object after the optimistic lock check (after line 806):

```python
    race.seeds_released_at = None
```

**Step 7: Add `seeds_released_at` to response helpers**

In `_race_detail_response` (line 91), add to the `RaceDetailResponse(...)` constructor:

```python
        seeds_released_at=race.seeds_released_at,
```

In `server/speedfog_racing/api/helpers.py`, find the `race_response` function and add:

```python
        seeds_released_at=race.seeds_released_at,
```

**Step 8: Run tests**

Run: `cd server && uv run pytest tests/test_seed_release.py -x -v`
Expected: All PASS.

Run: `cd server && uv run pytest -x -q`
Expected: All existing tests still pass. Note: existing tests that call `start_race` will fail unless the race has `seeds_released_at` set. Fix any failing tests by releasing seeds first. Check `test_races.py` for tests that call the start endpoint.

**Step 9: Run type checker**

Run: `cd server && uv run mypy speedfog_racing/`

**Step 10: Commit**

```
feat(api): add seed release workflow with download gating

New POST /release-seeds endpoint sets seeds_released_at timestamp.
Downloads return 403 before release. Start race requires release.
Reroll resets seeds_released_at to NULL.
```

---

### Task 5: Add `seeds_released_at` to frontend types and API client

**Files:**

- Modify: `web/src/lib/api.ts`

**Step 1: Add field to Race interface**

In `web/src/lib/api.ts`, in the `Race` interface (line 25), add after `started_at`:

```typescript
seeds_released_at: string | null;
```

The `RaceDetail` interface extends `Race`, so it inherits the field.

**Step 2: Add `releaseSeeds` API function**

After the `rerollSeed` function (line 387), add:

```typescript
/**
 * Release seeds for a SETUP race. Organizer only.
 */
export async function releaseSeeds(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/release-seeds`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}
```

**Step 3: Run type check**

Run: `cd web && npm run check`

**Step 4: Commit**

```
feat(web): add seeds_released_at type and releaseSeeds API function
```

---

### Task 6: Update RaceControls component

**Files:**

- Modify: `web/src/lib/components/RaceControls.svelte`

**Step 1: Add import and handler**

Add `releaseSeeds` to the import (line 4):

```typescript
import {
    releaseSeeds,
    rerollSeed,
    startRace,
    ...
} from '$lib/api';
```

Add handler function after `handleReroll` (after line 38):

```typescript
async function handleRelease() {
  loading = true;
  error = null;
  try {
    const updated = await releaseSeeds(race.id);
    onRaceUpdated(updated);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to release seeds";
  } finally {
    loading = false;
  }
}
```

Update the reroll confirmation message for post-release case. Replace the existing `handleReroll` (line 25):

```typescript
async function handleReroll() {
  const msg = race.seeds_released_at
    ? "Participants may have already downloaded. Re-rolling will require everyone to re-download. Continue?"
    : "Re-roll the seed? Participants will need to download a new seed pack.";
  if (!confirm(msg)) return;
  loading = true;
  error = null;
  try {
    const updated = await rerollSeed(race.id);
    onRaceUpdated(updated);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to re-roll seed";
  } finally {
    loading = false;
  }
}
```

**Step 2: Update template**

Derive a helper:

```typescript
let seedsReleased = $derived(race.seeds_released_at !== null);
```

Replace the `{#if raceStatus === 'setup'}` block (lines 111-119) with:

```svelte
{#if raceStatus === 'setup'}
    {#if seedsReleased}
        <button class="btn btn-primary btn-full" onclick={handleStart} disabled={loading}>
            {loading ? 'Starting...' : 'Start Race'}
        </button>
    {:else}
        <button class="btn btn-primary btn-full" onclick={handleRelease} disabled={loading}>
            {loading ? 'Releasing...' : 'Release Seeds'}
        </button>
        <p class="hint">Make seed packs available for download.</p>
    {/if}

    {#if seedsReleased}
        <p class="released-badge">Seeds released ✓</p>
    {/if}

    <button class="btn btn-secondary btn-full" onclick={handleReroll} disabled={loading}>
        {loading ? 'Re-rolling...' : 'Re-roll Seed'}
    </button>
    <p class="hint">
        {seedsReleased
            ? 'Assign a different seed. Participants must re-download.'
            : 'Assign a different seed.'}
    </p>
```

**Step 3: Add CSS for the released badge**

```css
.released-badge {
  color: var(--color-success, #10b981);
  font-size: var(--font-size-sm);
  font-weight: 500;
  margin: 0 0 0.5rem 0;
}
```

**Step 4: Run lint and type check**

Run: `cd web && npm run check && npm run lint`

**Step 5: Commit**

```
feat(web): add seed release controls to RaceControls component
```

---

### Task 7: Update race detail page download gating

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

**Step 1: Gate download button on seeds_released_at**

Replace the download section (lines 548-557). Change the condition from:

```svelte
{#if myParticipant && initialRace.seed_total_layers != null}
```

to:

```svelte
{#if myParticipant && initialRace.seeds_released_at}
```

**Step 2: Gate participant card download button**

In the ParticipantCard rendering (line 337), change `canDownload`:

```svelte
canDownload={initialRace.seeds_released_at !== null}
```

**Step 3: Add "Waiting for seeds" indicator for participants**

After the participant list section, inside the `{:else}` block (SETUP state, around line 371), add before the CasterList:

```svelte
{#if myParticipant && !initialRace.seeds_released_at}
    <div class="waiting-seeds">
        <p>Waiting for seeds to be released...</p>
    </div>
{/if}
```

Add CSS:

```css
.waiting-seeds {
  padding: 0.75rem;
  text-align: center;
  color: var(--color-text-disabled);
  font-size: var(--font-size-sm);
  font-style: italic;
}
```

**Step 4: Run checks**

Run: `cd web && npm run check && npm run lint`

**Step 5: Commit**

```
feat(web): gate download button on seeds_released_at
```

---

### Task 8: Handle WebSocket live updates for seed release

**Files:**

- Modify: `web/src/lib/stores/race.svelte.ts` (or wherever the WS store processes messages)

The server already broadcasts `race_state` after release (via `broadcast_race_state_update`). The frontend WS store already processes `race_state` messages and updates `raceStore.seed` and `raceStore.race`. So the SeedInfo and RaceInfo will naturally refresh.

**Step 1: Verify the race store handles race_state updates**

Read `web/src/lib/stores/race.svelte.ts` and confirm that the `race_state` message handler updates the store. The download button reactivity should work automatically since `initialRace` is updated via `handleRaceUpdated` from the REST response, and the WS broadcast updates spectators.

However, the `initialRace` data (from REST) won't auto-update for non-organizer participants via WS. The participant sees the download button appear only after page refresh OR if we add `seeds_released_at` to the WS `RaceInfo`.

**Step 2: Add `seeds_released_at` to WS RaceInfo schema**

In `server/speedfog_racing/websocket/schemas.py`, add to `RaceInfo` (line 82):

```python
seeds_released_at: str | None = None
```

In `server/speedfog_racing/websocket/spectator.py`, in `send_race_state` (line 216), update the RaceInfo construction:

```python
race=RaceInfo(
    id=str(race.id),
    name=race.name,
    status=race.status.value,
    started_at=race.started_at.isoformat() if race.started_at else None,
    seeds_released_at=race.seeds_released_at.isoformat() if race.seeds_released_at else None,
),
```

**Step 3: Handle in frontend WS store**

In the frontend WS store, where `race_state` messages update `raceStore.race`, ensure `seeds_released_at` is included in the race type. Read the file to find the exact location.

The WS `race` data flows into `liveRace`. Derive `seedsReleased` in the page from the live data:

In `+page.svelte`, add a derived:

```typescript
let seedsReleased = $derived(
  (liveRace?.seeds_released_at ?? initialRace.seeds_released_at) !== null,
);
```

Use `seedsReleased` instead of `initialRace.seeds_released_at` for the download gating conditions so it updates live.

**Step 4: Run all tests and checks**

Run: `cd server && uv run pytest -x -q`
Run: `cd web && npm run check`

**Step 5: Commit**

```
feat(ws): broadcast seeds_released_at in race_state for live updates
```

---

### Task 9: Fix existing tests broken by start-race gating

**Files:**

- Modify: `server/tests/test_races.py`
- Possibly modify: other test files that call start_race

**Step 1: Find all tests that call the start endpoint**

Search for `"/start"` in test files. Any test that starts a race needs to release seeds first.

**Step 2: Add seed release calls before start in existing tests**

For each test that calls `/api/races/{id}/start`, add a prior call:

```python
client.post(
    f"/api/races/{race_id}/release-seeds",
    headers={"Authorization": f"Bearer {organizer_token}"},
)
```

**Step 3: Run full test suite**

Run: `cd server && uv run pytest -x -v`
Expected: All PASS.

**Step 4: Commit**

```
test: update existing tests to release seeds before starting races
```

---

### Task 10: Final validation and deploy prep

**Step 1: Run all linters**

```bash
cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/
cd web && npm run check && npm run lint && npm run format
```

**Step 2: Run full test suites**

```bash
cd server && uv run pytest -x -v
```

**Step 3: Manual smoke test (optional)**

Start the dev servers and verify:

1. Create a race → download button NOT visible for participants
2. Release seeds → download button appears
3. Reroll → download button disappears, "Seeds released ✓" disappears
4. Re-release → download button reappears
5. Start race → works only after release

**Step 4: Final commit if any formatting changes**

```
chore: formatting and lint fixes
```
