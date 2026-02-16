# User Profile Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a public user profile page at `/user/{username}` with stats and activity timeline, plus make usernames clickable everywhere.

**Architecture:** Two new API endpoints (`GET /api/users/{username}` for profile+stats, `GET /api/users/{username}/activity` for paginated timeline). New SvelteKit page at `/user/[username]`. Reusable `UserLink.svelte` component deployed across existing pages.

**Tech Stack:** Python/FastAPI, async SQLAlchemy 2.0, Pydantic v2, SvelteKit 5 with runes, TypeScript.

**Design doc:** `docs/plans/2026-02-16-user-profile-page-design.md`

---

### Task 1: Profile + Stats API Schema

**Files:**

- Modify: `server/speedfog_racing/schemas.py` (add after line 50)

**Step 1: Write the failing test**

Create `server/tests/test_user_profile.py`:

```python
"""Tests for user profile endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole


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
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def profile_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="profile1",
            twitch_username="speedrunner",
            twitch_display_name="SpeedRunner",
            twitch_avatar_url="https://example.com/avatar.png",
            api_token="profile_token_1",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_get_profile_by_username(test_client, profile_user):
    async with test_client as client:
        response = await client.get(f"/api/users/{profile_user.twitch_username}")
        assert response.status_code == 200
        data = response.json()
        assert data["twitch_username"] == "speedrunner"
        assert data["twitch_display_name"] == "SpeedRunner"
        assert data["role"] == "organizer"
        assert "created_at" in data
        assert "stats" in data
        stats = data["stats"]
        assert stats["race_count"] == 0
        assert stats["training_count"] == 0
        assert stats["podium_count"] == 0
        assert stats["first_place_count"] == 0
        assert stats["organized_count"] == 0
        assert stats["casted_count"] == 0


@pytest.mark.asyncio
async def test_get_profile_not_found(test_client):
    async with test_client as client:
        response = await client.get("/api/users/nonexistent_user")
        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_user_profile.py -v -x`
Expected: FAIL (endpoint doesn't exist yet, 404 or 405)

**Step 3: Add schemas to `server/speedfog_racing/schemas.py`**

Add after the `UserResponse` class (after line 50):

```python
class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""

    race_count: int
    training_count: int
    podium_count: int
    first_place_count: int
    organized_count: int
    casted_count: int


class UserProfileResponse(BaseModel):
    """Public user profile with stats."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str
    created_at: datetime
    stats: UserStatsResponse
```

Note: There's already a `UserProfileResponse` in `server/speedfog_racing/api/users.py` (line 41) used for `/me`. Rename it to `MyProfileResponse` to avoid conflict, and update the `/me` endpoint to use the new name.

**Step 4: Implement the profile endpoint in `server/speedfog_racing/api/users.py`**

Add imports and the new endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from speedfog_racing.models import (
    Caster, Participant, ParticipantStatus, Race, RaceStatus,
    TrainingSession, User,
)
from speedfog_racing.schemas import (
    RaceListResponse, UserProfileResponse, UserResponse, UserStatsResponse,
)

@router.get("/{username}", response_model=UserProfileResponse)
async def get_user_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    """Get a user's public profile with stats."""
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Race count (as participant)
    race_count_q = await db.execute(
        select(func.count()).select_from(Participant).where(Participant.user_id == user.id)
    )
    race_count = race_count_q.scalar() or 0

    # Training count
    training_count_q = await db.execute(
        select(func.count())
        .select_from(TrainingSession)
        .where(TrainingSession.user_id == user.id)
    )
    training_count = training_count_q.scalar() or 0

    # Organized count
    organized_count_q = await db.execute(
        select(func.count()).select_from(Race).where(Race.organizer_id == user.id)
    )
    organized_count = organized_count_q.scalar() or 0

    # Casted count
    casted_count_q = await db.execute(
        select(func.count()).select_from(Caster).where(Caster.user_id == user.id)
    )
    casted_count = casted_count_q.scalar() or 0

    # Podium + first place: for each race where user finished, compute their rank
    # Get all participations where user finished
    finished_participations = await db.execute(
        select(Participant.race_id, Participant.igt_ms).where(
            Participant.user_id == user.id,
            Participant.status == ParticipantStatus.FINISHED,
        )
    )
    podium_count = 0
    first_place_count = 0
    for race_id, user_igt in finished_participations:
        # Count how many finished participants in that race have a lower IGT
        rank_q = await db.execute(
            select(func.count())
            .select_from(Participant)
            .where(
                Participant.race_id == race_id,
                Participant.status == ParticipantStatus.FINISHED,
                Participant.igt_ms < user_igt,
            )
        )
        rank = (rank_q.scalar() or 0) + 1  # 1-indexed
        if rank <= 3:
            podium_count += 1
        if rank == 1:
            first_place_count += 1

    return UserProfileResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        role=user.role.value,
        created_at=user.created_at,
        stats=UserStatsResponse(
            race_count=race_count,
            training_count=training_count,
            podium_count=podium_count,
            first_place_count=first_place_count,
            organized_count=organized_count,
            casted_count=casted_count,
        ),
    )
```

Important: This new route must be placed **after** the `/me` and `/search` routes to avoid `/{username}` capturing `me` or `search` as a username. Add it at the end of the file.

**Step 5: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_user_profile.py -v -x`
Expected: PASS

**Step 6: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/users.py server/tests/test_user_profile.py
git commit -m "feat(server): add user profile endpoint with stats"
```

---

### Task 2: Profile Stats with Real Data

**Files:**

- Modify: `server/tests/test_user_profile.py`

**Step 1: Add test with real race/training data**

Append to `test_user_profile.py`:

```python
from speedfog_racing.models import (
    Caster, Participant, ParticipantStatus, Race, RaceStatus,
    Seed, SeedStatus, TrainingSession, TrainingSessionStatus,
    User, UserRole,
)


@pytest.fixture
async def user_with_activity(async_session, sample_graph_json):
    """Create a user with races, trainings, organizing, and casting activity."""
    async with async_session() as db:
        user = User(
            twitch_id="active1",
            twitch_username="active_player",
            twitch_display_name="Active Player",
            api_token="active_token_1",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org1",
            twitch_username="the_organizer",
            twitch_display_name="The Organizer",
            api_token="org_token_1",
            role=UserRole.ORGANIZER,
        )
        other = User(
            twitch_id="other1",
            twitch_username="other_player",
            twitch_display_name="Other Player",
            api_token="other_token_1",
        )
        db.add_all([user, organizer, other])
        await db.flush()

        seed = Seed(
            seed_number="test_seed_1",
            pool_name="standard",
            graph_json=sample_graph_json,
            total_layers=5,
            folder_path="/tmp/test_seed",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Race 1: user finished 1st (lowest IGT)
        race1 = Race(
            name="Race 1", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race1)
        await db.flush()
        p1 = Participant(
            race_id=race1.id, user_id=user.id,
            status=ParticipantStatus.FINISHED, igt_ms=100000,
        )
        p2 = Participant(
            race_id=race1.id, user_id=other.id,
            status=ParticipantStatus.FINISHED, igt_ms=200000,
        )
        db.add_all([p1, p2])

        # Race 2: user finished 2nd (higher IGT)
        race2 = Race(
            name="Race 2", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race2)
        await db.flush()
        p3 = Participant(
            race_id=race2.id, user_id=user.id,
            status=ParticipantStatus.FINISHED, igt_ms=300000,
        )
        p4 = Participant(
            race_id=race2.id, user_id=other.id,
            status=ParticipantStatus.FINISHED, igt_ms=150000,
        )
        db.add_all([p3, p4])

        # Race 3: user organized
        race3 = Race(
            name="Race 3", organizer_id=user.id, seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race3)
        await db.flush()

        # Race 4: user is caster
        race4 = Race(
            name="Race 4", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race4)
        await db.flush()
        caster = Caster(race_id=race4.id, user_id=user.id)
        db.add(caster)

        # Training session
        training = TrainingSession(
            user_id=user.id, seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED, igt_ms=500000,
        )
        db.add(training)

        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_profile_stats_counts(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player")
        assert response.status_code == 200
        stats = response.json()["stats"]
        assert stats["race_count"] == 2      # participated in 2 races
        assert stats["training_count"] == 1   # 1 training session
        assert stats["organized_count"] == 1  # organized 1 race
        assert stats["casted_count"] == 1     # casted 1 race
        assert stats["podium_count"] == 2     # 1st + 2nd place
        assert stats["first_place_count"] == 1  # only race 1
```

Also add the `sample_graph_json` fixture import — copy from conftest or inline a minimal graph:

```python
@pytest.fixture
def sample_graph_json():
    return {"nodes": [], "edges": [], "layers": []}
```

**Step 2: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_user_profile.py::test_profile_stats_counts -v -x`
Expected: PASS (the endpoint from Task 1 already handles this)

**Step 3: Commit**

```bash
git add server/tests/test_user_profile.py
git commit -m "test(server): add profile stats with real activity data"
```

---

### Task 3: Activity Timeline API

**Files:**

- Modify: `server/speedfog_racing/schemas.py` (add activity schemas)
- Modify: `server/speedfog_racing/api/users.py` (add activity endpoint)
- Modify: `server/tests/test_user_profile.py` (add tests)

**Step 1: Write the failing test**

Append to `test_user_profile.py`:

```python
@pytest.mark.asyncio
async def test_activity_timeline(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player/activity")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "has_more" in data
        items = data["items"]
        # Should have: 2 race_participant + 1 race_organizer + 1 race_caster + 1 training = 5
        assert data["total"] == 5
        types = [i["type"] for i in items]
        assert "race_participant" in types
        assert "race_organizer" in types
        assert "race_caster" in types
        assert "training" in types


@pytest.mark.asyncio
async def test_activity_timeline_pagination(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player/activity?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True

        response2 = await client.get("/api/users/active_player/activity?limit=2&offset=4")
        data2 = response2.json()
        assert len(data2["items"]) == 1
        assert data2["has_more"] is False


@pytest.mark.asyncio
async def test_activity_timeline_not_found(test_client):
    async with test_client as client:
        response = await client.get("/api/users/nonexistent/activity")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_activity_race_participant_has_placement(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player/activity")
        data = response.json()
        participant_items = [i for i in data["items"] if i["type"] == "race_participant"]
        for item in participant_items:
            assert "placement" in item
            assert "total_participants" in item
            assert "igt_ms" in item
            assert "death_count" in item
            assert "race_name" in item
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_user_profile.py::test_activity_timeline -v -x`
Expected: FAIL (endpoint doesn't exist yet)

**Step 3: Add activity schemas to `server/speedfog_racing/schemas.py`**

Add after `UserProfileResponse`:

```python
class ActivityItemBase(BaseModel):
    """Base for activity timeline items."""
    type: str
    date: datetime


class RaceParticipantActivity(ActivityItemBase):
    type: str = "race_participant"
    race_id: UUID
    race_name: str
    status: str
    placement: int | None = None
    total_participants: int
    igt_ms: int
    death_count: int


class RaceOrganizerActivity(ActivityItemBase):
    type: str = "race_organizer"
    race_id: UUID
    race_name: str
    status: str
    participant_count: int


class RaceCasterActivity(ActivityItemBase):
    type: str = "race_caster"
    race_id: UUID
    race_name: str
    date: datetime


class TrainingActivity(ActivityItemBase):
    type: str = "training"
    session_id: UUID
    pool_name: str
    status: str
    igt_ms: int
    death_count: int


ActivityItem = RaceParticipantActivity | RaceOrganizerActivity | RaceCasterActivity | TrainingActivity


class ActivityTimelineResponse(BaseModel):
    items: list[ActivityItem]
    total: int
    has_more: bool
```

**Step 4: Implement activity endpoint in `server/speedfog_racing/api/users.py`**

```python
from speedfog_racing.schemas import (
    ActivityTimelineResponse, RaceCasterActivity,
    RaceOrganizerActivity, RaceParticipantActivity, TrainingActivity,
    ...,
)

@router.get("/{username}/activity", response_model=ActivityTimelineResponse)
async def get_user_activity(
    username: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ActivityTimelineResponse:
    """Get a user's activity timeline."""
    result = await db.execute(select(User).where(User.twitch_username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    items: list = []

    # 1. Race participations
    parts = await db.execute(
        select(Participant)
        .join(Race)
        .options(selectinload(Participant.race).selectinload(Race.participants))
        .where(Participant.user_id == user.id)
    )
    for p in parts.scalars():
        race = p.race
        finished_participants = sorted(
            [pp for pp in race.participants if pp.status == ParticipantStatus.FINISHED],
            key=lambda pp: pp.igt_ms,
        )
        placement = None
        if p.status == ParticipantStatus.FINISHED:
            for i, pp in enumerate(finished_participants):
                if pp.id == p.id:
                    placement = i + 1
                    break
        items.append(RaceParticipantActivity(
            race_id=race.id,
            race_name=race.name,
            date=race.created_at,
            status=p.status.value,
            placement=placement,
            total_participants=len(race.participants),
            igt_ms=p.igt_ms,
            death_count=p.death_count,
        ))

    # 2. Organized races
    organized = await db.execute(
        select(Race)
        .options(selectinload(Race.participants))
        .where(Race.organizer_id == user.id)
    )
    for race in organized.scalars():
        items.append(RaceOrganizerActivity(
            race_id=race.id,
            race_name=race.name,
            date=race.created_at,
            status=race.status.value,
            participant_count=len(race.participants),
        ))

    # 3. Caster roles
    casted = await db.execute(
        select(Caster)
        .join(Race)
        .options(selectinload(Caster.race))
        .where(Caster.user_id == user.id)
    )
    for c in casted.scalars():
        items.append(RaceCasterActivity(
            race_id=c.race.id,
            race_name=c.race.name,
            date=c.race.created_at,
        ))

    # 4. Training sessions
    trainings = await db.execute(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
    )
    for t in trainings.scalars():
        items.append(TrainingActivity(
            session_id=t.id,
            pool_name=t.seed.pool_name if hasattr(t, 'seed') and t.seed else "unknown",
            date=t.created_at,
            status=t.status.value,
            igt_ms=t.igt_ms,
            death_count=t.death_count,
        ))

    # Sort by date descending
    items.sort(key=lambda x: x.date, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]

    return ActivityTimelineResponse(
        items=page,
        total=total,
        has_more=(offset + limit) < total,
    )
```

Note on training `pool_name`: The `TrainingSession` model doesn't have `pool_name` directly — it's accessed via the `seed` relationship. Add `selectinload(TrainingSession.seed)` to the training query.

**Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_user_profile.py -v -x`
Expected: ALL PASS

**Step 6: Run linters**

Run: `cd server && uv run ruff check speedfog_racing/api/users.py speedfog_racing/schemas.py && uv run ruff format speedfog_racing/api/users.py speedfog_racing/schemas.py`

**Step 7: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/users.py server/tests/test_user_profile.py
git commit -m "feat(server): add user activity timeline endpoint"
```

---

### Task 4: UserLink Component

**Files:**

- Create: `web/src/lib/components/UserLink.svelte`

**Step 1: Create the component**

```svelte
<script lang="ts">
 import type { User } from '$lib/api';

 interface Props {
  user: User;
  showAvatar?: boolean;
 }

 let { user, showAvatar = false }: Props = $props();

 let displayName = $derived(user.twitch_display_name || user.twitch_username);
</script>

<a href="/user/{user.twitch_username}" class="user-link">
 {#if showAvatar && user.twitch_avatar_url}
  <img src={user.twitch_avatar_url} alt="" class="user-link-avatar" />
 {/if}
 {displayName}
</a>

<style>
 .user-link {
  color: inherit;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
 }

 .user-link:hover {
  color: var(--color-purple);
  text-decoration: underline;
 }

 .user-link-avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  object-fit: cover;
 }
</style>
```

**Step 2: Commit**

```bash
git add web/src/lib/components/UserLink.svelte
git commit -m "feat(web): add reusable UserLink component"
```

---

### Task 5: API Client Types + Fetch Functions

**Files:**

- Modify: `web/src/lib/api.ts`

**Step 1: Add types and fetch functions**

Add after the `AdminUser` interface (around line 530):

```typescript
// User profile
export interface UserStats {
  race_count: number;
  training_count: number;
  podium_count: number;
  first_place_count: number;
  organized_count: number;
  casted_count: number;
}

export interface UserProfile {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  role: string;
  created_at: string;
  stats: UserStats;
}

export type ActivityType =
  | "race_participant"
  | "race_organizer"
  | "race_caster"
  | "training";

export interface ActivityItemBase {
  type: ActivityType;
  date: string;
}

export interface RaceParticipantActivity extends ActivityItemBase {
  type: "race_participant";
  race_id: string;
  race_name: string;
  status: string;
  placement: number | null;
  total_participants: number;
  igt_ms: number;
  death_count: number;
}

export interface RaceOrganizerActivity extends ActivityItemBase {
  type: "race_organizer";
  race_id: string;
  race_name: string;
  status: string;
  participant_count: number;
}

export interface RaceCasterActivity extends ActivityItemBase {
  type: "race_caster";
  race_id: string;
  race_name: string;
}

export interface TrainingActivityItem extends ActivityItemBase {
  type: "training";
  session_id: string;
  pool_name: string;
  status: string;
  igt_ms: number;
  death_count: number;
}

export type ActivityItem =
  | RaceParticipantActivity
  | RaceOrganizerActivity
  | RaceCasterActivity
  | TrainingActivityItem;

export interface ActivityTimeline {
  items: ActivityItem[];
  total: number;
  has_more: boolean;
}
```

Add fetch functions near the other user functions:

```typescript
export async function fetchUserProfile(username: string): Promise<UserProfile> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch profile: ${response.status}`);
  return response.json();
}

export async function fetchUserActivity(
  username: string,
  offset = 0,
  limit = 20,
): Promise<ActivityTimeline> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}/activity?offset=${offset}&limit=${limit}`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch activity: ${response.status}`);
  return response.json();
}
```

**Step 2: Run type check**

Run: `cd web && npm run check`
Expected: No new errors

**Step 3: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat(web): add user profile and activity API types and fetchers"
```

---

### Task 6: User Profile Page

**Files:**

- Create: `web/src/routes/user/[username]/+page.svelte`

**Step 1: Create the page**

```svelte
<script lang="ts">
 import { page } from '$app/state';
 import {
  fetchUserProfile,
  fetchUserActivity,
  type UserProfile,
  type ActivityTimeline,
  type ActivityItem,
 } from '$lib/api';

 let username = $derived(page.params.username!);
 let profile = $state<UserProfile | null>(null);
 let activity = $state<ActivityTimeline | null>(null);
 let loading = $state(true);
 let loadingMore = $state(false);
 let error = $state<string | null>(null);

 $effect(() => {
  loadProfile();
 });

 async function loadProfile() {
  loading = true;
  error = null;
  try {
   const [p, a] = await Promise.all([
    fetchUserProfile(username),
    fetchUserActivity(username),
   ]);
   profile = p;
   activity = a;
  } catch (e) {
   error = e instanceof Error ? e.message : 'Failed to load profile.';
  } finally {
   loading = false;
  }
 }

 async function loadMore() {
  if (!activity || !activity.has_more) return;
  loadingMore = true;
  try {
   const more = await fetchUserActivity(username, activity.items.length);
   activity = {
    items: [...activity.items, ...more.items],
    total: more.total,
    has_more: more.has_more,
   };
  } catch (e) {
   error = e instanceof Error ? e.message : 'Failed to load more activity.';
  } finally {
   loadingMore = false;
  }
 }

 function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
   month: 'short',
   year: 'numeric',
  });
 }

 function formatFullDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
   month: 'short',
   day: 'numeric',
   year: 'numeric',
  });
 }

 function formatIgt(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
 }

 function placementLabel(p: number): string {
  if (p === 1) return '1st';
  if (p === 2) return '2nd';
  if (p === 3) return '3rd';
  return `${p}th`;
 }

 function placementClass(p: number | null): string {
  if (p === 1) return 'gold';
  if (p === 2) return 'silver';
  if (p === 3) return 'bronze';
  return '';
 }
</script>

<svelte:head>
 <title>
  {profile ? (profile.twitch_display_name || profile.twitch_username) : 'Profile'} - SpeedFog
  Racing
 </title>
</svelte:head>

<main class="profile-page">
 {#if loading}
  <p class="loading">Loading profile...</p>
 {:else if error && !profile}
  <div class="error-state">
   <p>{error}</p>
   <a href="/" class="btn btn-secondary">Home</a>
  </div>
 {:else if profile}
  <!-- Profile Header -->
  <div class="profile-header">
   {#if profile.twitch_avatar_url}
    <img src={profile.twitch_avatar_url} alt="" class="profile-avatar" />
   {:else}
    <div class="profile-avatar-placeholder"></div>
   {/if}
   <div class="profile-info">
    <div class="profile-name-row">
     <h1>{profile.twitch_display_name || profile.twitch_username}</h1>
     {#if profile.role !== 'user'}
      <span class="role-badge {profile.role}">{profile.role}</span>
     {/if}
    </div>
    <p class="profile-joined">Joined {formatDate(profile.created_at)}</p>
   </div>
  </div>

  <!-- Stats Grid -->
  <div class="stats-grid">
   <div class="stat-card">
    <span class="stat-number">{profile.stats.race_count}</span>
    <span class="stat-label">Races</span>
   </div>
   <div class="stat-card">
    <span class="stat-number">{profile.stats.training_count}</span>
    <span class="stat-label">Trainings</span>
   </div>
   <div class="stat-card">
    <span class="stat-number">{profile.stats.podium_count}</span>
    <span class="stat-label">Podiums</span>
   </div>
   <div class="stat-card">
    <span class="stat-number">{profile.stats.first_place_count}</span>
    <span class="stat-label">1st Places</span>
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

  <!-- Activity Timeline -->
  {#if activity}
   <section class="activity-section">
    <h2>Activity</h2>
    {#if activity.items.length === 0}
     <p class="empty">No activity yet.</p>
    {:else}
     <div class="timeline">
      {#each activity.items as item (item.type + '-' + ('race_id' in item ? item.race_id : 'session_id' in item ? item.session_id : '') + '-' + item.date)}
       <div class="activity-card">
        <span class="activity-date">{formatFullDate(item.date)}</span>
        {#if item.type === 'race_participant'}
         <div class="activity-body">
          <span class="activity-badge participant">Race</span>
          <a href="/race/{item.race_id}" class="activity-title">
           {item.race_name}
          </a>
          <div class="activity-details">
           {#if item.placement}
            <span class="placement {placementClass(item.placement)}">
             {placementLabel(item.placement)} / {item.total_participants}
            </span>
           {:else}
            <span class="status">{item.status}</span>
           {/if}
           <span class="mono">{formatIgt(item.igt_ms)}</span>
           <span>{item.death_count} deaths</span>
          </div>
         </div>
        {:else if item.type === 'race_organizer'}
         <div class="activity-body">
          <span class="activity-badge organizer">Organized</span>
          <a href="/race/{item.race_id}" class="activity-title">
           {item.race_name}
          </a>
          <div class="activity-details">
           <span>{item.participant_count} players</span>
           <span class="status">{item.status}</span>
          </div>
         </div>
        {:else if item.type === 'race_caster'}
         <div class="activity-body">
          <span class="activity-badge caster">Casted</span>
          <a href="/race/{item.race_id}" class="activity-title">
           {item.race_name}
          </a>
         </div>
        {:else if item.type === 'training'}
         <div class="activity-body">
          <span class="activity-badge training">Training</span>
          <a href="/training/{item.session_id}" class="activity-title">
           {item.pool_name}
          </a>
          <div class="activity-details">
           <span class="status">{item.status}</span>
           <span class="mono">{formatIgt(item.igt_ms)}</span>
           <span>{item.death_count} deaths</span>
          </div>
         </div>
        {/if}
       </div>
      {/each}
     </div>

     {#if activity.has_more}
      <button class="btn btn-secondary load-more" disabled={loadingMore} onclick={loadMore}>
       {loadingMore ? 'Loading...' : 'Load more'}
      </button>
     {/if}
    {/if}
   </section>
  {/if}
 {/if}
</main>

<style>
 .profile-page {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
  box-sizing: border-box;
 }

 .loading {
  color: var(--color-text-disabled);
  font-style: italic;
 }

 .error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 3rem;
  color: var(--color-text-secondary);
 }

 /* Profile Header */
 .profile-header {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-bottom: 2rem;
 }

 .profile-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--color-border);
 }

 .profile-avatar-placeholder {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: var(--color-surface);
  border: 2px solid var(--color-border);
 }

 .profile-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
 }

 .profile-name-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
 }

 .profile-name-row h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
  font-weight: 700;
  color: var(--color-gold);
 }

 .role-badge {
  font-size: var(--font-size-xs);
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
 }

 .role-badge.organizer {
  background: rgba(168, 85, 247, 0.15);
  color: var(--color-purple);
 }

 .role-badge.admin {
  background: rgba(239, 68, 68, 0.15);
  color: var(--color-danger);
 }

 .profile-joined {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
 }

 /* Stats Grid */
 .stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 2.5rem;
 }

 .stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
 }

 .stat-number {
  font-size: var(--font-size-xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
 }

 .stat-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
 }

 /* Activity Section */
 .activity-section h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
  margin: 0 0 1rem 0;
  color: var(--color-text-primary);
 }

 .empty {
  color: var(--color-text-disabled);
  font-style: italic;
 }

 .timeline {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
 }

 .activity-card {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
 }

 .activity-date {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  white-space: nowrap;
  min-width: 6rem;
  padding-top: 0.15rem;
 }

 .activity-body {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
 }

 .activity-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.1rem 0.4rem;
  border-radius: var(--radius-sm);
  width: fit-content;
 }

 .activity-badge.participant {
  background: rgba(59, 130, 246, 0.15);
  color: var(--color-blue, #3b82f6);
 }

 .activity-badge.organizer {
  background: rgba(168, 85, 247, 0.15);
  color: var(--color-purple);
 }

 .activity-badge.caster {
  background: rgba(236, 72, 153, 0.15);
  color: #ec4899;
 }

 .activity-badge.training {
  background: rgba(34, 197, 94, 0.15);
  color: var(--color-success);
 }

 .activity-title {
  color: var(--color-text-primary);
  text-decoration: none;
  font-weight: 600;
 }

 .activity-title:hover {
  color: var(--color-purple);
  text-decoration: underline;
 }

 .activity-details {
  display: flex;
  gap: 0.75rem;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
 }

 .placement {
  font-weight: 600;
 }

 .placement.gold {
  color: var(--color-gold);
 }

 .placement.silver {
  color: #c0c0c0;
 }

 .placement.bronze {
  color: #cd7f32;
 }

 .mono {
  font-variant-numeric: tabular-nums;
 }

 .status {
  text-transform: capitalize;
 }

 .load-more {
  margin-top: 1rem;
  width: 100%;
 }

 @media (max-width: 640px) {
  .profile-page {
   padding: 1rem;
  }

  .stats-grid {
   grid-template-columns: repeat(2, 1fr);
  }

  .activity-card {
   flex-direction: column;
   gap: 0.25rem;
  }

  .activity-date {
   min-width: auto;
  }
 }
</style>
```

**Step 2: Run type check**

Run: `cd web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add web/src/routes/user/\[username\]/+page.svelte
git commit -m "feat(web): add user profile page with stats and activity timeline"
```

---

### Task 7: Deploy UserLink Across Existing Pages

**Files:**

- Modify: `web/src/routes/admin/+page.svelte` (make usernames clickable in table)
- Modify: `web/src/lib/components/RaceCard.svelte` (make organizer name clickable)
- Modify: `web/src/lib/components/ParticipantCard.svelte` (make participant name clickable)
- Modify: `web/src/routes/training/[id]/+page.svelte` (add player name in header)
- Modify: `web/src/lib/components/CasterList.svelte` (make caster names clickable)

**Step 1: Admin page — make usernames clickable**

In `web/src/routes/admin/+page.svelte`, replace lines 159-165:

```svelte
<!-- Before -->
<td class="user-cell">
 {#if user.twitch_avatar_url}
  <img src={user.twitch_avatar_url} alt="" class="avatar" />
 {/if}
 <span class="username">{user.twitch_display_name || user.twitch_username}</span>
</td>

<!-- After -->
<td class="user-cell">
 {#if user.twitch_avatar_url}
  <img src={user.twitch_avatar_url} alt="" class="avatar" />
 {/if}
 <a href="/user/{user.twitch_username}" class="username-link">
  {user.twitch_display_name || user.twitch_username}
 </a>
</td>
```

Add style for `.username-link`:

```css
.username-link {
  color: inherit;
  text-decoration: none;
}

.username-link:hover {
  color: var(--color-purple);
  text-decoration: underline;
}
```

**Step 2: RaceCard — make organizer clickable**

In `web/src/lib/components/RaceCard.svelte`, the organizer display (lines 115-121) is inside an `<a>` tag (the card itself links to the race). We can't nest `<a>` tags. Instead, use an `onclick` with `stopPropagation` + `goto`, or make the organizer name stand out with a different approach.

Simpler approach: since the whole card is already an `<a href="/race/{race.id}">`, we add a click handler on the organizer name that navigates to the profile using `event.preventDefault()` + `event.stopPropagation()`:

```svelte
<!-- In the script tag, add: -->
import { goto } from '$app/navigation';

<!-- Replace the organizer span -->
<span class="race-organizer">
 by
 {#if race.organizer.twitch_avatar_url}
  <img src={race.organizer.twitch_avatar_url} alt="" class="organizer-avatar" />
 {/if}
 <button
  class="organizer-link"
  onclick={(e) => { e.preventDefault(); e.stopPropagation(); goto(`/user/${race.organizer.twitch_username}`); }}
 >
  {displayName}
 </button>
</span>
```

Add style:

```css
.organizer-link {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.organizer-link:hover {
  color: var(--color-purple);
  text-decoration: underline;
}
```

**Step 3: ParticipantCard — make participant name clickable**

In `web/src/lib/components/ParticipantCard.svelte`, replace the name `<span>` with a UserLink. Import UserLink and use it where the name is displayed. Check the existing template for the name display and wrap it.

**Step 4: Training detail — add player name in header**

In `web/src/routes/training/[id]/+page.svelte`, add the player's name under the pool name title (line 114). The `session.user` already contains the user data:

```svelte
<!-- After the h1 -->
<h1>{displayPoolName(session.pool_name)}</h1>
{#if session.user}
 <span class="player-name">
  by
  <a href="/user/{session.user.twitch_username}" class="player-link">
   {#if session.user.twitch_avatar_url}
    <img src={session.user.twitch_avatar_url} alt="" class="player-avatar" />
   {/if}
   {session.user.twitch_display_name || session.user.twitch_username}
  </a>
 </span>
{/if}
```

Add styles:

```css
.player-name {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.player-link {
  color: inherit;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.player-link:hover {
  color: var(--color-purple);
  text-decoration: underline;
}

.player-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
}
```

**Step 5: CasterList — check if names need linking**

Read `web/src/lib/components/CasterList.svelte` and add `UserLink` or direct `<a>` tags where caster names are displayed.

**Step 6: Run type check + lint**

Run: `cd web && npm run check && npm run lint`
Expected: PASS

**Step 7: Commit**

```bash
git add web/src/routes/admin/+page.svelte web/src/lib/components/RaceCard.svelte web/src/lib/components/ParticipantCard.svelte web/src/routes/training/\[id\]/+page.svelte web/src/lib/components/CasterList.svelte
git commit -m "feat(web): make usernames clickable with links to profile pages"
```

---

### Task 8: Run Full Test Suite + Final Checks

**Files:** None new

**Step 1: Run server tests**

Run: `cd server && uv run pytest -v`
Expected: ALL PASS

**Step 2: Run server linters**

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`

**Step 3: Run web checks**

Run: `cd web && npm run check && npm run lint`

**Step 4: Fix any issues found**

**Step 5: Final commit if needed**

---

### Task Summary

| #   | Task                    | Description                                            |
| --- | ----------------------- | ------------------------------------------------------ |
| 1   | Profile + Stats API     | Schema + endpoint + basic tests                        |
| 2   | Profile Stats with Data | Test with real race/training/caster/organizer data     |
| 3   | Activity Timeline API   | Schema + endpoint + pagination tests                   |
| 4   | UserLink Component      | Reusable `<a>` component for user names                |
| 5   | API Client Types        | TypeScript types + fetch functions                     |
| 6   | Profile Page            | SvelteKit page with header, stats grid, timeline       |
| 7   | Deploy UserLink         | Admin, RaceCard, ParticipantCard, Training, CasterList |
| 8   | Final Checks            | Full test suite + linters                              |
