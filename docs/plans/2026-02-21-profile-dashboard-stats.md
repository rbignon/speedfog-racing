# Profile & Dashboard Stats Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Simplify dashboard and profile pages by removing misleading podium stats, adding per-pool performance table, and showing Twitch links on profiles.

**Architecture:** New backend endpoint `GET /api/users/{username}/pool-stats` aggregates race and training stats per pool via SQL. Frontend stat cards reduced from 6/3 to 4 on both pages. New `PoolStatsTable` Svelte component shared by dashboard and profile. Twitch icon added to profile header.

**Tech Stack:** Python/FastAPI + SQLAlchemy (backend), SvelteKit 5 with runes (frontend), pytest-asyncio (tests)

---

## Task 1: Backend — Clean up UserStatsResponse schema

**Files:**

- Modify: `server/speedfog_racing/schemas.py:77-96`
- Modify: `server/speedfog_racing/api/users.py:290-420`
- Modify: `server/tests/test_user_profile.py`

### Step 1: Update the schema

Remove `BestRecentPlacement`, `podium_count`, `first_place_count`, `podium_rate`, `best_recent_placement` from `schemas.py`:

```python
class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""

    race_count: int
    training_count: int
    organized_count: int
    casted_count: int
```

Delete the `BestRecentPlacement` class entirely.

### Step 2: Simplify the `get_user_profile` endpoint

In `api/users.py`, remove the entire podium/first-place/best-placement computation (lines 334-409). The endpoint becomes:

```python
@router.get("/{username}", response_model=UserProfileDetailResponse)
async def get_user_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserProfileDetailResponse:
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id

    race_count_q = await db.execute(
        select(func.count())
        .select_from(Participant)
        .join(Race, Participant.race_id == Race.id)
        .where(
            Participant.user_id == user_id,
            Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]),
        )
    )
    race_count = race_count_q.scalar_one()

    training_count_q = await db.execute(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user_id)
    )
    training_count = training_count_q.scalar_one()

    organized_count_q = await db.execute(
        select(func.count()).select_from(Race).where(Race.organizer_id == user_id)
    )
    organized_count = organized_count_q.scalar_one()

    casted_count_q = await db.execute(
        select(func.count()).select_from(Caster).where(Caster.user_id == user_id)
    )
    casted_count = casted_count_q.scalar_one()

    stats = UserStatsResponse(
        race_count=race_count,
        training_count=training_count,
        organized_count=organized_count,
        casted_count=casted_count,
    )

    return UserProfileDetailResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        created_at=user.created_at,
        stats=stats,
    )
```

Clean up unused imports: remove `BestRecentPlacement` from the import list, and remove `groupby`/`itemgetter` if no longer used.

### Step 3: Update tests

In `test_user_profile.py`:

- `test_get_profile_by_username`: Remove assertions for `podium_count`, `first_place_count`. Keep `race_count`, `training_count`, `organized_count`, `casted_count`.
- `test_profile_stats_counts`: Remove assertions for `podium_count`, `first_place_count`.
- Delete entirely: `test_profile_stats_include_podium_rate`, `test_profile_stats_podium_rate_zero_races`, `test_profile_stats_include_best_recent_placement`, `test_profile_stats_best_recent_placement_none`.

### Step 4: Run tests

Run: `cd server && uv run pytest tests/test_user_profile.py -v`
Expected: All remaining tests pass.

### Step 5: Lint

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Expected: Clean.

### Step 6: Commit

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/users.py server/tests/test_user_profile.py
git commit -m "refactor(api): remove podium stats from user profile endpoint"
```

---

## Task 2: Backend — Add pool-stats endpoint

**Files:**

- Modify: `server/speedfog_racing/api/users.py`
- Modify: `server/speedfog_racing/schemas.py`
- Create: `server/tests/test_pool_stats.py`

### Step 1: Write the failing test

Create `server/tests/test_pool_stats.py`:

```python
"""Tests for user pool stats endpoint."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
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
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def user_with_pool_data(async_session):
    """Create a user with race and training data across multiple pools."""
    async with async_session() as db:
        player = User(
            twitch_id="pool_player_1",
            twitch_username="pool_player",
            twitch_display_name="PoolPlayer",
            api_token="pool_player_token",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="pool_org_1",
            twitch_username="pool_organizer",
            api_token="pool_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add_all([player, organizer])
        await db.flush()

        # Seeds for two pools
        seed_std = Seed(
            seed_number="std_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=5,
            folder_path="/fake/standard",
            status=SeedStatus.CONSUMED,
        )
        seed_sprint = Seed(
            seed_number="spr_001",
            pool_name="sprint",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=3,
            folder_path="/fake/sprint",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([seed_std, seed_sprint])
        await db.flush()

        # 2 finished races on standard pool
        for i, igt in enumerate([120000, 180000]):
            race = Race(
                name=f"Std Race {i + 1}",
                organizer_id=organizer.id,
                seed_id=seed_std.id,
                status=RaceStatus.FINISHED,
            )
            db.add(race)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=player.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=igt,
                    death_count=5 + i * 3,
                )
            )

        # 1 finished race on sprint pool
        race_spr = Race(
            name="Sprint Race 1",
            organizer_id=organizer.id,
            seed_id=seed_sprint.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race_spr)
        await db.flush()
        db.add(
            Participant(
                race_id=race_spr.id,
                user_id=player.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=60000,
                death_count=2,
            )
        )

        # 1 DNF race on standard (should NOT count)
        race_dnf = Race(
            name="Std DNF",
            organizer_id=organizer.id,
            seed_id=seed_std.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race_dnf)
        await db.flush()
        db.add(
            Participant(
                race_id=race_dnf.id,
                user_id=player.id,
                status=ParticipantStatus.REGISTERED,
                igt_ms=50000,
                death_count=10,
            )
        )

        # 1 finished training on standard
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seed_std.id,
                status=TrainingSessionStatus.FINISHED,
                igt_ms=100000,
                death_count=3,
            )
        )

        # 1 active training on standard (should NOT count)
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seed_std.id,
                status=TrainingSessionStatus.ACTIVE,
                igt_ms=30000,
                death_count=1,
            )
        )

        await db.commit()
        await db.refresh(player)
        return player


@pytest.mark.asyncio
async def test_pool_stats_returns_aggregated_data(test_client, user_with_pool_data):
    """Pool stats endpoint returns correct aggregated data per pool."""
    async with test_client as client:
        response = await client.get("/api/users/pool_player/pool-stats")
        assert response.status_code == 200
        data = response.json()
        assert "pools" in data
        pools = data["pools"]

        # Standard has more total runs (2 race + 1 training = 3) than Sprint (1 race)
        assert pools[0]["pool_name"] == "standard"
        assert pools[1]["pool_name"] == "sprint"

        # Standard race stats
        std_race = pools[0]["race"]
        assert std_race["runs"] == 2
        assert std_race["avg_time_ms"] == 150000  # (120000 + 180000) / 2
        assert std_race["avg_deaths"] == pytest.approx(6.5)  # (5 + 8) / 2
        assert std_race["best_time_ms"] == 120000

        # Standard training stats
        std_training = pools[0]["training"]
        assert std_training["runs"] == 1
        assert std_training["avg_time_ms"] == 100000
        assert std_training["avg_deaths"] == pytest.approx(3.0)
        assert std_training["best_time_ms"] == 100000

        assert pools[0]["total_runs"] == 3

        # Sprint race stats
        spr_race = pools[1]["race"]
        assert spr_race["runs"] == 1
        assert spr_race["avg_time_ms"] == 60000
        assert spr_race["best_time_ms"] == 60000

        # Sprint has no training
        assert pools[1]["training"] is None
        assert pools[1]["total_runs"] == 1


@pytest.mark.asyncio
async def test_pool_stats_not_found(test_client):
    """Pool stats returns 404 for nonexistent user."""
    async with test_client as client:
        response = await client.get("/api/users/nonexistent/pool-stats")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_pool_stats_empty_user(test_client, async_session):
    """Pool stats returns empty list for user with no activity."""
    async with async_session() as db:
        user = User(
            twitch_id="empty_user_1",
            twitch_username="empty_user",
            api_token="empty_token",
        )
        db.add(user)
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/empty_user/pool-stats")
        assert response.status_code == 200
        data = response.json()
        assert data["pools"] == []
```

### Step 2: Run test to verify it fails

Run: `cd server && uv run pytest tests/test_pool_stats.py -v`
Expected: FAIL — endpoint does not exist (404 or similar).

### Step 3: Add schemas

In `server/speedfog_racing/schemas.py`, add after `UserStatsResponse`:

```python
class PoolTypeStatsResponse(BaseModel):
    """Stats for one type (race or training) in a pool."""

    runs: int
    avg_time_ms: int
    avg_deaths: float
    best_time_ms: int


class UserPoolStatsEntry(BaseModel):
    """Per-pool stats for a user."""

    pool_name: str
    race: PoolTypeStatsResponse | None = None
    training: PoolTypeStatsResponse | None = None
    total_runs: int


class UserPoolStatsResponse(BaseModel):
    """Aggregated pool stats for a user."""

    pools: list[UserPoolStatsEntry]
```

### Step 4: Add the endpoint

In `server/speedfog_racing/api/users.py`, add a new route before the `/{username}` route (to avoid shadowing):

```python
@router.get("/{username}/pool-stats", response_model=UserPoolStatsResponse)
async def get_user_pool_stats(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserPoolStatsResponse:
    """Get per-pool aggregated stats for a user."""
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id

    # Race stats: aggregate finished participations grouped by pool_name
    race_stats_q = await db.execute(
        select(
            Seed.pool_name,
            func.count().label("runs"),
            func.avg(Participant.igt_ms).label("avg_time_ms"),
            func.avg(Participant.death_count).label("avg_deaths"),
            func.min(Participant.igt_ms).label("best_time_ms"),
        )
        .select_from(Participant)
        .join(Race, Participant.race_id == Race.id)
        .join(Seed, Race.seed_id == Seed.id)
        .where(
            Participant.user_id == user_id,
            Participant.status == ParticipantStatus.FINISHED,
        )
        .group_by(Seed.pool_name)
    )
    race_stats = {
        row.pool_name: PoolTypeStatsResponse(
            runs=row.runs,
            avg_time_ms=int(row.avg_time_ms),
            avg_deaths=round(float(row.avg_deaths), 1),
            best_time_ms=row.best_time_ms,
        )
        for row in race_stats_q.all()
    }

    # Training stats: aggregate finished sessions grouped by pool_name
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
        )
        .group_by(Seed.pool_name)
    )
    training_stats = {
        row.pool_name: PoolTypeStatsResponse(
            runs=row.runs,
            avg_time_ms=int(row.avg_time_ms),
            avg_deaths=round(float(row.avg_deaths), 1),
            best_time_ms=row.best_time_ms,
        )
        for row in training_stats_q.all()
    }

    # Merge all pool names
    all_pools = set(race_stats.keys()) | set(training_stats.keys())
    entries = []
    for pool_name in all_pools:
        race = race_stats.get(pool_name)
        training = training_stats.get(pool_name)
        total_runs = (race.runs if race else 0) + (training.runs if training else 0)
        entries.append(
            UserPoolStatsEntry(
                pool_name=pool_name,
                race=race,
                training=training,
                total_runs=total_runs,
            )
        )

    entries.sort(key=lambda e: e.total_runs, reverse=True)

    return UserPoolStatsResponse(pools=entries)
```

Add the new schema imports to the import block and add `TrainingSessionStatus` to the model imports.

### Step 5: Run tests

Run: `cd server && uv run pytest tests/test_pool_stats.py tests/test_user_profile.py -v`
Expected: All pass.

### Step 6: Lint

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

### Step 7: Commit

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/users.py server/tests/test_pool_stats.py
git commit -m "feat(api): add per-pool stats endpoint for user profiles"
```

---

## Task 3: Frontend — Update API types and add fetchPoolStats

**Files:**

- Modify: `web/src/lib/api.ts`

### Step 1: Update UserStats interface

Remove `podium_count`, `first_place_count`, `podium_rate`, `best_recent_placement` from `UserStats`. Remove the `BestRecentPlacement` interface.

```typescript
export interface UserStats {
  race_count: number;
  training_count: number;
  organized_count: number;
  casted_count: number;
}
```

### Step 2: Add pool stats types and fetch function

```typescript
export interface PoolTypeStats {
  runs: number;
  avg_time_ms: number;
  avg_deaths: number;
  best_time_ms: number;
}

export interface UserPoolStatsEntry {
  pool_name: string;
  race: PoolTypeStats | null;
  training: PoolTypeStats | null;
  total_runs: number;
}

export interface UserPoolStats {
  pools: UserPoolStatsEntry[];
}

export async function fetchUserPoolStats(
  username: string,
): Promise<UserPoolStats> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}/pool-stats`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch pool stats: ${response.status}`);
  return response.json();
}
```

### Step 3: Commit

```bash
git add web/src/lib/api.ts
git commit -m "feat(web): add pool stats API types and fetch function"
```

---

## Task 4: Frontend — Create PoolStatsTable component

**Files:**

- Create: `web/src/lib/components/PoolStatsTable.svelte`

### Step 1: Create the component

Create `web/src/lib/components/PoolStatsTable.svelte` using Svelte 5 runes. The component receives `pools: UserPoolStatsEntry[]` as a prop.

Key details:

- Compute `maxRuns` across all rows (race + training) for bar width proportion
- Format times with `formatIgt` from `$lib/utils/training`
- Format pool names with `formatPoolName` from `$lib/utils/format`
- Bar width: `(runs / maxRuns) * 100%`, min-width so zero doesn't collapse
- Gold bar for race, purple bar for training
- Null type stats shown as dashes `—`
- Pool name on first row only (race row), second row (training) has empty pool cell
- Light separator (border-bottom) between pool groups
- Mobile: `overflow-x: auto` wrapper for horizontal scroll

### Step 2: Commit

```bash
git add web/src/lib/components/PoolStatsTable.svelte
git commit -m "feat(web): add PoolStatsTable component"
```

---

## Task 5: Frontend — Update dashboard page

**Files:**

- Modify: `web/src/routes/dashboard/+page.svelte`

### Step 1: Update imports and data fetching

- Add `fetchUserPoolStats` and `type UserPoolStats` to imports from `$lib/api`
- Add `import PoolStatsTable from '$lib/components/PoolStatsTable.svelte'`
- Add `let poolStats: UserPoolStats | null = $state(null)` state
- Add `fetchUserPoolStats(username)` to the `Promise.all` call
- Assign result to `poolStats`

### Step 2: Replace stats section

Remove the entire `stats-section` (stat cards + context cards). Replace with:

```svelte
<section class="stats-section">
    <div class="stats-grid">
        <div class="stat-card">
            <span class="stat-value">{profile.stats.race_count}</span>
            <span class="stat-label">Races</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">{profile.stats.training_count}</span>
            <span class="stat-label">Training</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">{profile.stats.organized_count}</span>
            <span class="stat-label">Organized</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">{profile.stats.casted_count}</span>
            <span class="stat-label">Casted</span>
        </div>
    </div>
</section>
```

### Step 3: Add pool stats section

After stats section, before Active Now:

```svelte
{#if poolStats && poolStats.pools.length > 0}
    <section class="pool-stats-section">
        <h2>Pool Stats</h2>
        <PoolStatsTable pools={poolStats.pools} />
    </section>
{/if}
```

### Step 4: Update CSS

- Change `.stats-grid` to `grid-template-columns: repeat(4, 1fr)`
- Remove all `.stats-context`, `.stat-context-card`, `.context-*` styles
- Add `.pool-stats-section { margin-bottom: 2rem; }`
- Mobile: `.stats-grid` stays `repeat(2, 1fr)`

### Step 5: Remove dead code

Remove `podiumRateDisplay`, `placementMedal` functions (only if not used elsewhere in this file — check the `activityBadge` function still uses `placementMedal` for the Recent Activity section, so keep it).

### Step 6: Commit

```bash
git add web/src/routes/dashboard/+page.svelte
git commit -m "feat(web): update dashboard with 4 stat cards and pool stats table"
```

---

## Task 6: Frontend — Update profile page

**Files:**

- Modify: `web/src/routes/user/[username]/+page.svelte`

### Step 1: Update imports and data fetching

- Add `fetchUserPoolStats` and `type UserPoolStats` to imports
- Add `import PoolStatsTable from '$lib/components/PoolStatsTable.svelte'`
- Add `let poolStats = $state<UserPoolStats | null>(null)` state
- Add `fetchUserPoolStats(username)` to the `Promise.all` in `loadProfile()`
- Assign result to `poolStats`

### Step 2: Replace stats grid

Change from 6 stat cards to 4:

```svelte
<div class="stats-grid">
    <div class="stat-card">
        <span class="stat-number">{profile.stats.race_count}</span>
        <span class="stat-label">Races</span>
    </div>
    <div class="stat-card">
        <span class="stat-number">{profile.stats.training_count}</span>
        <span class="stat-label">Training</span>
    </div>
    <div class="stat-card">
        <span class="stat-number">{profile.stats.organized_count}</span>
        <span class="stat-label">Organized</span>
    </div>
    <div class="stat-card">
        <span class="stat-number">{profile.stats.casted_count}</span>
        <span class="stat-label">Casted</span>
    </div>
</div>
```

### Step 3: Add pool stats section

Between stats grid and activity section:

```svelte
{#if poolStats && poolStats.pools.length > 0}
    <section class="pool-stats-section">
        <h2>Pool Stats</h2>
        <PoolStatsTable pools={poolStats.pools} />
    </section>
{/if}
```

### Step 4: Add Twitch link

In the profile header, between the `<h1>` and the role badge:

```svelte
<div class="profile-name-row">
    <h1>{profile.twitch_display_name || profile.twitch_username}</h1>
    <a
        href="https://twitch.tv/{profile.twitch_username}"
        target="_blank"
        rel="noopener noreferrer"
        class="twitch-link"
        title="Twitch channel"
    >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
            <path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z"/>
        </svg>
    </a>
    {#if profile.role !== 'user'}
        <span class="role-badge {profile.role}">{profile.role}</span>
    {/if}
</div>
```

### Step 5: Update CSS

- Change `.stats-grid` to `grid-template-columns: repeat(4, 1fr)`
- Add `.pool-stats-section h2` style (gold, same as activity section heading)
- Add `.twitch-link` styles:

```css
.twitch-link {
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  transition: color var(--transition);
}

.twitch-link:hover {
  color: var(--color-purple);
}
```

- Add `.pool-stats-section { margin-bottom: 2.5rem; }`

### Step 6: Commit

```bash
git add web/src/routes/user/[username]/+page.svelte
git commit -m "feat(web): update profile with 4 stat cards, pool stats table, and Twitch link"
```

---

## Task 7: Frontend type check + final verification

### Step 1: Run svelte-check

Run: `cd web && npm run check`
Expected: No type errors.

### Step 2: Run lint

Run: `cd web && npm run lint`

### Step 3: Run all backend tests

Run: `cd server && uv run pytest -v`
Expected: All pass.

### Step 4: Commit any fixes

If lint/check required changes, commit them.
