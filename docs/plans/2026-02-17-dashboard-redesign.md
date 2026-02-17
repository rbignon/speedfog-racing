# Dashboard Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the personalized homepage with a dedicated `/dashboard` page (stats, active sessions, recent activity) and simplify the homepage to be identical for all users.

**Architecture:** New `/dashboard` SvelteKit route for logged-in users. Backend changes to enrich existing endpoints with contextual stats (podium rate, best placement) and progress data (current_layer). Homepage becomes a static public page.

**Tech Stack:** SvelteKit 5 (runes), Python/FastAPI, SQLAlchemy 2.0, Pydantic v2

---

## Task 1: Add `podium_rate` and `best_recent_placement` to user profile API

**Files:**

- Modify: `server/speedfog_racing/schemas.py` (lines 60-68, 71-82)
- Modify: `server/speedfog_racing/api/users.py` (lines 267-328)
- Test: `server/tests/test_user_profile.py`

### Step 1: Write failing tests

Add to `server/tests/test_user_profile.py`:

```python
@pytest.mark.asyncio
async def test_profile_stats_include_podium_rate(test_client, user_with_activity):
    """Profile stats include podium_rate computed from race results."""
    async with test_client as client:
        response = await client.get(f"/api/users/{user_with_activity.twitch_username}")
        assert response.status_code == 200
        stats = response.json()["stats"]
        # 2 podiums (1st + 2nd) out of 2 races = 1.0
        assert stats["podium_rate"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_profile_stats_podium_rate_zero_races(test_client, sample_user):
    """podium_rate is null when user has no finished races."""
    async with test_client as client:
        response = await client.get(f"/api/users/{sample_user.twitch_username}")
        stats = response.json()["stats"]
        assert stats["podium_rate"] is None


@pytest.mark.asyncio
async def test_profile_stats_include_best_recent_placement(test_client, user_with_activity):
    """Profile stats include best_recent_placement from recent finished races."""
    async with test_client as client:
        response = await client.get(f"/api/users/{user_with_activity.twitch_username}")
        stats = response.json()["stats"]
        brp = stats["best_recent_placement"]
        assert brp is not None
        assert brp["placement"] == 1
        assert brp["race_name"] == "Race 1"
        assert "race_id" in brp
        assert "finished_at" in brp


@pytest.mark.asyncio
async def test_profile_stats_best_recent_placement_none(test_client, sample_user):
    """best_recent_placement is null when user has no finished races."""
    async with test_client as client:
        response = await client.get(f"/api/users/{sample_user.twitch_username}")
        stats = response.json()["stats"]
        assert stats["best_recent_placement"] is None
```

### Step 2: Run tests to verify they fail

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_user_profile.py -v -k "podium_rate or best_recent_placement"`

Expected: FAIL — fields don't exist in response schema yet.

### Step 3: Add schemas

In `server/speedfog_racing/schemas.py`, add a new schema and update `UserStatsResponse`:

```python
class BestRecentPlacement(BaseModel):
    """Best placement among recent finished races."""
    placement: int
    race_name: str
    race_id: UUID
    finished_at: datetime | None
```

Update `UserStatsResponse` (line 60) to add two fields:

```python
class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""
    race_count: int
    training_count: int
    podium_count: int
    first_place_count: int
    organized_count: int
    casted_count: int
    podium_rate: float | None = None
    best_recent_placement: BestRecentPlacement | None = None
```

### Step 4: Compute stats in the API endpoint

In `server/speedfog_racing/api/users.py`, function `get_user_profile` (line 226), after the podium/first_place computation block (after line 309):

1. Compute `podium_rate`:

```python
podium_rate = podium_count / race_count if race_count > 0 else None
```

1. Compute `best_recent_placement`: find the best (lowest) placement across the user's finished races. Reuse the `user_finished` and `all_finished` data already computed. Build a list of `(placement, race_id)` tuples, sort by placement, pick the best.

You'll need to join with Race to get `race_name` and `started_at` (as `finished_at` proxy since races don't have a `finished_at` column — use `started_at` as the date, it's the closest timestamp). Import `BestRecentPlacement` from schemas.

Add both fields to the `UserStatsResponse(...)` constructor call at line 311.

### Step 5: Run tests to verify they pass

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_user_profile.py -v`

Expected: ALL PASS

### Step 6: Update frontend types

In `web/src/lib/api.ts`, update `UserStats` interface (line 595):

```typescript
export interface BestRecentPlacement {
  placement: number;
  race_name: string;
  race_id: string;
  finished_at: string | null;
}

export interface UserStats {
  race_count: number;
  training_count: number;
  podium_count: number;
  first_place_count: number;
  organized_count: number;
  casted_count: number;
  podium_rate: number | null;
  best_recent_placement: BestRecentPlacement | null;
}
```

### Step 7: Commit

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/users.py server/tests/test_user_profile.py web/src/lib/api.ts
git commit -m "feat(api): add podium_rate and best_recent_placement to user profile stats"
```

---

## Task 2: Add `current_layer` to training list and `my_*` fields to my-races

**Files:**

- Modify: `server/speedfog_racing/schemas.py` (TrainingSessionResponse line 280, RaceResponse line 162)
- Modify: `server/speedfog_racing/api/training.py` (\_build_list_response line 87)
- Modify: `server/speedfog_racing/api/users.py` (get_my_races line 82)
- Modify: `server/speedfog_racing/api/helpers.py` (race_response line 43)
- Test: `server/tests/test_user_profile.py` (add new tests)

### Step 1: Write failing tests for training current_layer

Add to a new file `server/tests/test_dashboard_api.py`:

```python
"""Tests for dashboard-related API enhancements."""

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


SAMPLE_GRAPH = {
    "nodes": {
        "start": {"tier": 0, "display_name": "Start"},
        "limgrave_a": {"tier": 1, "display_name": "Limgrave A"},
        "liurnia_b": {"tier": 2, "display_name": "Liurnia B"},
        "boss": {"tier": 3, "display_name": "Final Boss"},
    },
    "edges": [],
    "total_nodes": 4,
}


@pytest.fixture
async def dashboard_user(async_session):
    """Create a user with active training and active race for dashboard tests."""
    async with async_session() as db:
        user = User(
            twitch_id="dash_user_1",
            twitch_username="dash_player",
            twitch_display_name="DashPlayer",
            api_token="dash_test_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.flush()

        seed = Seed(
            seed_number="dash_seed_001",
            pool_name="standard",
            graph_json=SAMPLE_GRAPH,
            total_layers=3,
            folder_path="/fake/seed/dash",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Active training with progress at tier 2
        training = TrainingSession(
            user_id=user.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.ACTIVE,
            progress_nodes=[
                {"node_id": "start", "igt_ms": 0},
                {"node_id": "limgrave_a", "igt_ms": 60000},
                {"node_id": "liurnia_b", "igt_ms": 120000},
            ],
        )
        db.add(training)

        # Running race with participant
        race = Race(
            name="Dash Race",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            current_layer=2,
            igt_ms=90000,
            death_count=3,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(user)
        return user


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


@pytest.mark.asyncio
async def test_training_list_includes_current_layer(test_client, dashboard_user):
    """GET /training includes current_layer computed from progress_nodes."""
    async with test_client as client:
        response = await client.get(
            "/api/training",
            headers={"Authorization": f"Bearer {dashboard_user.api_token}"},
        )
        assert response.status_code == 200
        sessions = response.json()
        active = [s for s in sessions if s["status"] == "active"]
        assert len(active) == 1
        assert active[0]["current_layer"] == 2  # tier 2 = liurnia_b
        assert active[0]["seed_total_layers"] == 3


@pytest.mark.asyncio
async def test_my_races_includes_progress(test_client, dashboard_user):
    """GET /users/me/races includes my_current_layer, my_igt_ms, my_death_count."""
    async with test_client as client:
        response = await client.get(
            "/api/users/me/races",
            headers={"Authorization": f"Bearer {dashboard_user.api_token}"},
        )
        assert response.status_code == 200
        races = response.json()["races"]
        running = [r for r in races if r["status"] == "running"]
        assert len(running) == 1
        assert running[0]["my_current_layer"] == 2
        assert running[0]["my_igt_ms"] == 90000
        assert running[0]["my_death_count"] == 3
        assert running[0]["seed_total_layers"] == 3
```

### Step 2: Run tests to verify they fail

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_dashboard_api.py -v`

Expected: FAIL — fields don't exist.

### Step 3: Add `current_layer` to TrainingSessionResponse

In `server/speedfog_racing/schemas.py`, add to `TrainingSessionResponse` (after line 293):

```python
current_layer: int = 0
```

In `server/speedfog_racing/api/training.py`, update `_build_list_response` (line 87) to compute current_layer from progress_nodes + graph_json:

```python
def _build_list_response(session: TrainingSession) -> TrainingSessionResponse:
    current_layer = 0
    if session.progress_nodes and session.seed.graph_json:
        nodes = session.seed.graph_json.get("nodes", {})
        for entry in session.progress_nodes:
            node_data = nodes.get(entry.get("node_id"), {})
            tier = node_data.get("tier")
            if isinstance(tier, (int, float)) and int(tier) > current_layer:
                current_layer = int(tier)
        if session.status == TrainingSessionStatus.FINISHED:
            current_layer = session.seed.total_layers

    return TrainingSessionResponse(
        id=session.id,
        user=user_response(session.user),
        status=session.status,
        pool_name=session.seed.pool_name,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        created_at=session.created_at,
        finished_at=session.finished_at,
        seed_total_layers=session.seed.total_layers,
        seed_total_nodes=(
            session.seed.graph_json.get("total_nodes") if session.seed.graph_json else None
        ),
        current_layer=current_layer,
    )
```

### Step 4: Add `my_*` fields to RaceResponse and get_my_races

In `server/speedfog_racing/schemas.py`, add optional fields to `RaceResponse` (after line 176):

```python
seed_total_layers: int | None = None
my_current_layer: int | None = None
my_igt_ms: int | None = None
my_death_count: int | None = None
```

In `server/speedfog_racing/api/users.py`, update `get_my_races` (line 82) to find the current user's participant in each race and populate these fields:

```python
@router.get("/me/races", response_model=RaceListResponse)
async def get_my_races(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RaceListResponse:
    """Get races where the user is organizer or participant."""
    participant_race_ids = select(Participant.race_id).where(Participant.user_id == user.id)
    query = (
        select(Race)
        .where(or_(Race.organizer_id == user.id, Race.id.in_(participant_race_ids)))
        .options(
            selectinload(Race.organizer),
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
        .order_by(Race.created_at.desc())
    )
    result = await db.execute(query)
    races = list(result.scalars().all())

    race_responses = []
    for r in races:
        resp = race_response(r)
        # Add user-specific progress fields
        my_participant = next((p for p in r.participants if p.user_id == user.id), None)
        if my_participant:
            resp.my_current_layer = my_participant.current_layer
            resp.my_igt_ms = my_participant.igt_ms
            resp.my_death_count = my_participant.death_count
        if r.seed:
            resp.seed_total_layers = r.seed.total_layers
        race_responses.append(resp)

    return RaceListResponse(races=race_responses)
```

### Step 5: Run tests to verify they pass

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_dashboard_api.py tests/test_user_profile.py -v`

Expected: ALL PASS

### Step 6: Update frontend types

In `web/src/lib/api.ts`, update `Race` interface to add optional fields:

```typescript
// Add to Race interface (wherever it's defined)
seed_total_layers?: number | null;
my_current_layer?: number | null;
my_igt_ms?: number | null;
my_death_count?: number | null;
```

Update `TrainingSession` interface to add:

```typescript
current_layer: number;
```

### Step 7: Run all server tests

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest -v`

Expected: ALL PASS

### Step 8: Commit

```bash
git add server/ web/src/lib/api.ts
git commit -m "feat(api): add progress fields to training list and my-races endpoints"
```

---

## Task 3: Simplify homepage — remove logged-in conditional

**Files:**

- Modify: `web/src/routes/+page.svelte`

### Step 1: Rewrite homepage

Replace the entire content of `web/src/routes/+page.svelte` to remove the `{#if auth.isLoggedIn}` branch. The homepage should:

1. Keep the error banner (for auth errors on redirect)
2. Always show the hero section (DAG + CTA + Discord link)
3. Always show public races (live + upcoming)
4. Remove all `myRaces`, `fetchMyRaces`, `activeRace`, `myRaceIds` logic
5. Remove the dashboard styles (`.dashboard`, `.spotlight-*`, `.my-races-*`, `.empty-state`)
6. Remove the `auth` import since it's no longer needed for conditional rendering (but keep error handling)

The hero CTA should adapt: if logged in, "Try a seed" becomes "Start Training" (→ `/training`). If anonymous, keep "Try a seed" (→ Twitch login).

Keep imports: `onMount`, `page`, `site`, `fetchRaces`, `getTwitchLoginUrl`, `MetroDagAnimated`, `RaceCard`, `LiveIndicator`, `heroSeed`.

Remove imports: `auth`, `fetchMyRaces`.

Wait — actually, keep `auth` import for the CTA button logic (show different CTA if logged in). But remove `fetchMyRaces` and all my-races state.

### Step 2: Verify manually

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run dev`

Check that `/` shows hero + public races for all users (logged in or not). Check that the CTA adapts.

### Step 3: Run svelte-check

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`

Expected: PASS (no type errors from removed code)

### Step 4: Commit

```bash
git add web/src/routes/+page.svelte
git commit -m "refactor(web): simplify homepage to be identical for all users"
```

---

## Task 4: Update navbar and auth redirect

**Files:**

- Modify: `web/src/routes/+layout.svelte` (lines 24-52)
- Modify: `web/src/routes/auth/callback/+page.svelte` (line 17)

### Step 1: Update navbar

In `web/src/routes/+layout.svelte`:

1. Line 26: Make logo href conditional — `href={auth.isLoggedIn ? '/dashboard' : '/'}` (this requires the `<a>` tag to be reactive, so use a derived or inline expression)
2. Add a "Races" link in the nav for logged-in users, between the user info and Training link. This links to `/` so they can browse public races.

```svelte
{#if auth.isLoggedIn}
    <a href="/user/{auth.user?.twitch_username}" class="user-info">...</a>
    <a href="/" class="btn btn-secondary">Races</a>
    <a href="/training" class="btn btn-secondary">Training</a>
    ...
```

### Step 2: Update auth callback redirect

In `web/src/routes/auth/callback/+page.svelte`, line 17, change the fallback from `'/'` to `'/dashboard'`:

```typescript
goto(
  redirect?.startsWith("/") && !redirect.startsWith("//")
    ? redirect
    : "/dashboard",
);
```

### Step 3: Run svelte-check

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`

Expected: PASS

### Step 4: Commit

```bash
git add web/src/routes/+layout.svelte web/src/routes/auth/callback/+page.svelte
git commit -m "feat(web): update navbar logo link and auth redirect to /dashboard"
```

---

## Task 5: Create dashboard page

**Files:**

- Create: `web/src/routes/dashboard/+page.svelte`

### Step 1: Create the dashboard page

Create `web/src/routes/dashboard/+page.svelte` with:

**Script section:**

- Import: `onMount` from svelte, `goto` from `$app/navigation`, `auth` from stores, `fetchUserProfile`, `fetchUserActivity`, `fetchMyRaces`, `fetchTrainingSessions` and types from api
- State: `profile` (UserProfile | null), `activity` (ActivityItem[]), `myRaces` (Race[]), `trainingSessions` (TrainingSession[]), `loading` (boolean)
- Auth guard: `$effect` that redirects to `/` if `auth.initialized && !auth.isLoggedIn`
- On init: when `auth.initialized && auth.isLoggedIn && auth.user`, fetch all 4 data sources in parallel with `Promise.all`
- Derive: `activeRaces` = myRaces filtered to status running/open
- Derive: `activeTraining` = trainingSessions filtered to status active

**Template section — three main sections:**

1. **Stats section** — render from `profile.stats`:
   - Row 1: 3-column grid with `race_count`, `training_count`, `podium_count` as big numbers + labels
   - Row 2: 2-column grid with `best_recent_placement` (medal + name + relative time) and `podium_rate` (percentage display)

2. **Active Now section** — render from `activeRaces` and `activeTraining`:
   - Each active race: `<a>` card wrapping the whole thing, gold border, shows race name, status badge, participant count, IGT, deaths, progress bar (`my_current_layer / seed_total_layers`)
   - Each active training: `<a>` card, standard border, shows pool name, status badge, IGT, deaths, progress bar (`current_layer / seed_total_layers`)
   - Empty state with CTAs

3. **Recent Activity section** — render from `activity` (first 5 items):
   - Each item: type badge, event name as link, relative timestamp
   - Footer: "See all activity" → `/user/{auth.user.twitch_username}`

**Style section:** Use project CSS variables (`--color-gold`, `--color-surface`, `--radius-lg`, etc.). Follow patterns from existing pages. Key classes:

- `.dashboard` — max-width 1200px, centered
- `.stats-grid` — CSS grid, 3 columns
- `.stats-context` — CSS grid, 2 columns
- `.stat-card` — background surface, border radius, centered text
- `.active-card` — full width, clickable, gold border for races
- `.progress-bar` — background track + gold fill
- `.activity-list` — simple stacked rows

Use relative time formatting. Create a `timeAgo(dateStr: string): string` helper inline (or import if one exists). Check if the project has an existing time formatting utility.

### Step 2: Verify manually

Run dev server and test:

- Navigate to `/dashboard` when logged in → see all sections
- Navigate to `/dashboard` when not logged in → redirects to `/`
- Stats display correctly
- Active cards link to correct pages
- Progress bars render
- Activity links work
- "See all activity" goes to profile

### Step 3: Run checks

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`

Expected: PASS

### Step 4: Commit

```bash
git add web/src/routes/dashboard/+page.svelte
git commit -m "feat(web): create /dashboard page with stats, active sessions, and recent activity"
```

---

## Task 6: Polish and responsive design

**Files:**

- Modify: `web/src/routes/dashboard/+page.svelte`

### Step 1: Responsive breakpoints

Add `@media (max-width: 640px)` rules:

- Stats grid: 2 columns instead of 3
- Stats context: 1 column instead of 2
- Active cards: reduce padding
- Dashboard container: reduce padding to 1rem

### Step 2: Loading and error states

- Show skeleton/loading state while data loads
- Handle API errors gracefully (show error message, don't crash)
- Handle empty profile (new user with zero stats)

### Step 3: Test edge cases manually

- New user with no races, no training, no activity
- User with only training, no races
- User with running race but not a participant (organizer only)

### Step 4: Run final checks

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check && npm run lint`

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest -v`

Expected: ALL PASS

### Step 5: Commit

```bash
git add web/src/routes/dashboard/+page.svelte
git commit -m "feat(web): add responsive design and edge case handling to dashboard"
```
