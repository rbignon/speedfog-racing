# Admin Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add analytics visualizations (KPIs, weekly charts, heatmaps, timezone distribution) to the admin Stats tab.

**Architecture:** Single new API endpoint (`GET /api/admin/analytics`) returns all dashboard data pre-aggregated by a new `analytics_service.py`. Frontend renders KPI cards (HTML), weekly charts + timezone bar chart (Chart.js), and heatmaps (CSS grid). User timezone is collected via `/auth/me` and stored on the User model.

**Tech Stack:** Python/SQLAlchemy (service), FastAPI (endpoint), Chart.js (charts), SvelteKit 5 (UI)

**Spec:** `docs/plans/2026-04-04-admin-analytics-dashboard.md`

---

## File Structure

| Action | File                                                   | Responsibility                                                             |
| ------ | ------------------------------------------------------ | -------------------------------------------------------------------------- |
| Create | `server/speedfog_racing/services/analytics_service.py` | `compute_analytics()` function with all SQL queries and Python aggregation |
| Create | `server/tests/test_analytics.py`                       | Tests for analytics service and API endpoint                               |
| Modify | `server/speedfog_racing/models.py`                     | Add `timezone` field to `User`                                             |
| Modify | `server/speedfog_racing/api/auth.py`                   | Accept `timezone` query param on `/auth/me`                                |
| Modify | `server/speedfog_racing/api/admin.py`                  | Add `GET /analytics` endpoint                                              |
| Modify | `web/src/lib/api.ts`                                   | Add `AdminAnalytics` type and `fetchAdminAnalytics()`                      |
| Modify | `web/src/routes/admin/+page.svelte`                    | Render analytics dashboard in Stats tab                                    |

---

### Task 1: Add `timezone` field to User model

**Files:**

- Modify: `server/speedfog_racing/models.py:83-108`

- [ ] **Step 1: Add timezone field to User model**

In `server/speedfog_racing/models.py`, add after the `overlay_settings` field (line 98):

```python
timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 2: Commit**

```bash
git add server/speedfog_racing/models.py
git commit -m "feat: add timezone field to User model"
```

---

### Task 2: Collect timezone via `/auth/me`

**Files:**

- Modify: `server/speedfog_racing/api/auth.py:213-218`
- Modify: `web/src/lib/api.ts` (fetchCurrentUser function)
- Test: `server/tests/test_analytics.py`

- [ ] **Step 1: Write the test for timezone collection**

Create `server/tests/test_analytics.py`:

```python
"""Tests for admin analytics dashboard."""

from datetime import UTC, datetime, timedelta

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
    return async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )


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
async def admin_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="admin123",
            twitch_username="admin_user",
            api_token="admin_test_token",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def regular_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="user456",
            twitch_username="regular_user",
            api_token="user_test_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


# =============================================================================
# Timezone Collection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_auth_me_updates_timezone(test_client, admin_user, async_session):
    """GET /auth/me with timezone param updates user timezone."""
    async with test_client as client:
        response = await client.get(
            "/api/auth/me?timezone=Europe/Paris",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == admin_user.id))
        user = result.scalar_one()
        assert user.timezone == "Europe/Paris"


@pytest.mark.asyncio
async def test_auth_me_without_timezone_leaves_null(
    test_client, admin_user, async_session
):
    """GET /auth/me without timezone param does not set timezone."""
    async with test_client as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == admin_user.id))
        user = result.scalar_one()
        assert user.timezone is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_analytics.py::test_auth_me_updates_timezone -v`
Expected: FAIL (timezone param not handled yet)

- [ ] **Step 3: Modify `/auth/me` to accept timezone**

In `server/speedfog_racing/api/auth.py`, replace the `get_me` function (lines 213-218):

```python
@router.get("/me", response_model=UserPublicResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
    timezone: str | None = Query(None, max_length=50),
) -> User:
    """Get current authenticated user info."""
    if timezone is not None:
        user.timezone = timezone
    return user
```

Add `Query` to the existing imports from `fastapi` at the top of the file:

```python
from fastapi import Depends, HTTPException, Query, status
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_analytics.py -k timezone -v`
Expected: both timezone tests PASS

- [ ] **Step 5: Modify frontend to send timezone**

In `web/src/lib/api.ts`, find the `fetchCurrentUser` function (around line 277) and change the fetch URL:

```typescript
export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getStoredToken();
  if (!token) return null;

  let url = `${API_BASE}/auth/me`;
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (tz) {
      url += `?timezone=${encodeURIComponent(tz)}`;
    }
  } catch {
    // Ignore if Intl API is not available
  }

  const response = await fetch(url, {
    headers: getAuthHeaders(),
  });

  if (response.status === 401) {
    clearStoredToken();
    return null;
```

Keep the rest of the function unchanged.

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/api/auth.py server/tests/test_analytics.py web/src/lib/api.ts
git commit -m "feat: collect user timezone via /auth/me"
```

---

### Task 3: Analytics service

**Files:**

- Create: `server/speedfog_racing/services/analytics_service.py`
- Modify: `server/tests/test_analytics.py`

- [ ] **Step 1: Write the test for compute_analytics**

Append to `server/tests/test_analytics.py`:

```python
# =============================================================================
# Analytics Service Tests
# =============================================================================


@pytest.fixture
async def analytics_data(async_session):
    """Create test data for analytics: users, races, training sessions."""
    now = datetime.now(UTC)
    async with async_session() as db:
        # Users with different timezones and creation dates
        user1 = User(
            twitch_id="u1",
            twitch_username="user1",
            api_token="tok1",
            role=UserRole.ORGANIZER,
            timezone="Europe/Paris",
            last_seen=now - timedelta(days=1),
        )
        user2 = User(
            twitch_id="u2",
            twitch_username="user2",
            api_token="tok2",
            role=UserRole.USER,
            timezone="America/New_York",
            last_seen=now - timedelta(days=5),
        )
        user3 = User(
            twitch_id="u3",
            twitch_username="user3",
            api_token="tok3",
            role=UserRole.USER,
            timezone="Europe/Paris",
            last_seen=now - timedelta(days=60),
        )
        db.add_all([user1, user2, user3])
        await db.flush()

        # Seed
        seed = Seed(
            seed_number="seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "total_layers": 5},
            total_layers=5,
            folder_path="/tmp/seeds/standard/seed_001",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Finished race with 2 participants, started this week
        race1 = Race(
            name="Race 1",
            organizer_id=user1.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=1),
        )
        db.add(race1)
        await db.flush()

        p1 = Participant(
            race_id=race1.id,
            user_id=user1.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=3600000,
            death_count=5,
        )
        p2 = Participant(
            race_id=race1.id,
            user_id=user2.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=4200000,
            death_count=8,
        )
        db.add_all([p1, p2])

        # Training sessions
        t1 = TrainingSession(
            user_id=user1.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=1800000,
            death_count=3,
            created_at=now - timedelta(hours=2),
        )
        t2 = TrainingSession(
            user_id=user2.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.ABANDONED,
            igt_ms=600000,
            death_count=10,
            created_at=now - timedelta(hours=1),
        )
        db.add_all([t1, t2])
        await db.commit()

        return {
            "users": [user1, user2, user3],
            "races": [race1],
            "participants": [p1, p2],
            "training": [t1, t2],
        }


@pytest.mark.asyncio
async def test_compute_analytics_kpis(async_session, analytics_data):
    """compute_analytics returns correct KPI values."""
    from speedfog_racing.services.analytics_service import compute_analytics

    async with async_session() as db:
        result = await compute_analytics(db)

    kpis = result["kpis"]
    assert kpis["total_users"] == 3
    assert kpis["total_races_finished"] == 1
    assert kpis["avg_participants"] == 2.0
    assert kpis["total_solo"] == 2
    assert kpis["solo_completion_pct"] == 50.0
    # user3 last_seen > 30 days ago, so 2 active
    assert kpis["active_users_30d"] == 2


@pytest.mark.asyncio
async def test_compute_analytics_timezones(async_session, analytics_data):
    """compute_analytics returns timezone distribution sorted west to east."""
    from speedfog_racing.services.analytics_service import compute_analytics

    async with async_session() as db:
        result = await compute_analytics(db)

    tzs = result["timezones"]
    assert len(tzs) == 2
    # America/New_York (UTC-5/-4) should come before Europe/Paris (UTC+1/+2)
    assert tzs[0]["timezone"] == "America/New_York"
    assert tzs[0]["count"] == 1
    assert tzs[1]["timezone"] == "Europe/Paris"
    assert tzs[1]["count"] == 2


@pytest.mark.asyncio
async def test_compute_analytics_weekly(async_session, analytics_data):
    """compute_analytics returns weekly arrays with 12 entries."""
    from speedfog_racing.services.analytics_service import compute_analytics

    async with async_session() as db:
        result = await compute_analytics(db)

    weekly = result["weekly"]
    assert len(weekly["weeks"]) == 12
    assert len(weekly["new_users"]) == 12
    assert len(weekly["races"]) == 12
    assert len(weekly["solo"]) == 12
    assert len(weekly["solo_finished"]) == 12
    assert len(weekly["solo_abandoned"]) == 12
    assert len(weekly["avg_participants"]) == 12
    # Current week (last entry) should have our test data
    assert weekly["races"][-1] == 1
    assert weekly["solo"][-1] == 2
    assert weekly["solo_finished"][-1] == 1
    assert weekly["solo_abandoned"][-1] == 1
    assert weekly["avg_participants"][-1] == 2.0


@pytest.mark.asyncio
async def test_compute_analytics_heatmaps(async_session, analytics_data):
    """compute_analytics returns 8x7 heatmap grids."""
    from speedfog_racing.services.analytics_service import compute_analytics

    async with async_session() as db:
        result = await compute_analytics(db)

    for key in ("race_players", "solo"):
        grid = result["heatmaps"][key]
        assert len(grid) == 8, f"{key} should have 8 rows"
        for row in grid:
            assert len(row) == 7, f"{key} rows should have 7 columns"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_analytics.py -k "compute_analytics" -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement analytics service**

Create `server/speedfog_racing/services/analytics_service.py`:

```python
"""Analytics service for admin dashboard."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    Race,
    RaceStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
)

NUM_WEEKS = 12
HOUR_BUCKETS = [10, 12, 14, 16, 18, 20, 22, 0]


def _iso_week_key(dt: datetime) -> tuple[int, int]:
    """Return (iso_year, iso_week) for a datetime."""
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def _week_label(iso_year: int, iso_week: int) -> str:
    """Format a week label like 'W14'."""
    return f"W{iso_week}"


def _hour_to_bucket_index(hour: int) -> int | None:
    """Map an hour (0-23) to a bucket index (0-7). Returns None if outside range."""
    if hour >= 10 and hour < 24:
        # 10->0, 12->1, 14->2, 16->3, 18->4, 20->5, 22->6
        idx = (hour - 10) // 2
        if idx < 7:
            return idx
        return None
    if hour >= 0 and hour < 2:
        return 7  # 00h bucket
    return None


def _day_of_week_index(dt: datetime) -> int:
    """Return 0=Monday, 6=Sunday."""
    return dt.weekday()


async def compute_analytics(db: AsyncSession) -> dict:
    """Compute all analytics data for the admin dashboard."""
    now = datetime.now(UTC)

    # =========================================================================
    # KPIs
    # =========================================================================
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_users_this_month = (
        await db.execute(
            select(func.count(User.id)).where(User.created_at >= month_start)
        )
    ).scalar() or 0

    thirty_days_ago = now - timedelta(days=30)
    active_users_30d = (
        await db.execute(
            select(func.count(User.id)).where(User.last_seen >= thirty_days_ago)
        )
    ).scalar() or 0

    active_users_pct = round(active_users_30d / total_users * 100, 1) if total_users > 0 else 0.0

    total_races_finished = (
        await db.execute(
            select(func.count(Race.id)).where(Race.status == RaceStatus.FINISHED)
        )
    ).scalar() or 0

    # Avg participants per finished race
    participant_counts_q = await db.execute(
        select(func.count(Participant.id))
        .join(Race, Participant.race_id == Race.id)
        .where(Race.status == RaceStatus.FINISHED)
        .group_by(Race.id)
    )
    participant_counts = [row[0] for row in participant_counts_q.all()]
    avg_participants = (
        round(sum(participant_counts) / len(participant_counts), 1)
        if participant_counts
        else 0.0
    )

    total_solo = (
        await db.execute(select(func.count(TrainingSession.id)))
    ).scalar() or 0

    solo_finished = (
        await db.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.status == TrainingSessionStatus.FINISHED
            )
        )
    ).scalar() or 0

    solo_abandoned = (
        await db.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.status == TrainingSessionStatus.ABANDONED
            )
        )
    ).scalar() or 0

    solo_terminal = solo_finished + solo_abandoned
    solo_completion_pct = (
        round(solo_finished / solo_terminal * 100, 1) if solo_terminal > 0 else 0.0
    )

    # =========================================================================
    # Weekly buckets (last 12 weeks)
    # =========================================================================
    # Build list of the last 12 ISO weeks
    week_keys: list[tuple[int, int]] = []
    for i in range(NUM_WEEKS - 1, -1, -1):
        dt = now - timedelta(weeks=i)
        wk = _iso_week_key(dt)
        if wk not in week_keys:
            week_keys.append(wk)
    # Ensure exactly 12
    week_keys = week_keys[-NUM_WEEKS:]

    week_labels = [_week_label(y, w) for y, w in week_keys]
    week_index = {wk: i for i, wk in enumerate(week_keys)}

    new_users_weekly = [0] * NUM_WEEKS
    races_weekly = [0] * NUM_WEEKS
    solo_weekly = [0] * NUM_WEEKS
    solo_finished_weekly = [0] * NUM_WEEKS
    solo_abandoned_weekly = [0] * NUM_WEEKS
    race_participant_sums: dict[int, list[int]] = {i: [] for i in range(NUM_WEEKS)}

    # Users
    users_q = await db.execute(select(User.created_at))
    for (created_at,) in users_q.all():
        if created_at is None:
            continue
        wk = _iso_week_key(created_at)
        if wk in week_index:
            new_users_weekly[week_index[wk]] += 1

    # Races with participant counts
    races_q = await db.execute(
        select(Race.started_at, func.count(Participant.id))
        .join(Participant, Participant.race_id == Race.id)
        .where(Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]))
        .where(Race.started_at.is_not(None))
        .group_by(Race.id, Race.started_at)
    )
    for started_at, p_count in races_q.all():
        if started_at is None:
            continue
        wk = _iso_week_key(started_at)
        if wk in week_index:
            idx = week_index[wk]
            races_weekly[idx] += 1
            race_participant_sums[idx].append(p_count)

    # Training sessions
    training_q = await db.execute(
        select(TrainingSession.created_at, TrainingSession.status)
    )
    for created_at, ts_status in training_q.all():
        if created_at is None:
            continue
        wk = _iso_week_key(created_at)
        if wk in week_index:
            idx = week_index[wk]
            solo_weekly[idx] += 1
            if ts_status == TrainingSessionStatus.FINISHED:
                solo_finished_weekly[idx] += 1
            elif ts_status == TrainingSessionStatus.ABANDONED:
                solo_abandoned_weekly[idx] += 1

    avg_participants_weekly = [
        round(sum(counts) / len(counts), 1) if counts else 0
        for counts in [race_participant_sums[i] for i in range(NUM_WEEKS)]
    ]

    # =========================================================================
    # Heatmaps (day of week x 2h buckets)
    # =========================================================================
    race_players_grid = [[0] * 7 for _ in range(8)]
    solo_grid = [[0] * 7 for _ in range(8)]

    # Race players heatmap: sum of participant counts per slot
    race_heatmap_q = await db.execute(
        select(Race.started_at, func.count(Participant.id))
        .join(Participant, Participant.race_id == Race.id)
        .where(Race.started_at.is_not(None))
        .where(Race.status.in_([RaceStatus.RUNNING, RaceStatus.FINISHED]))
        .group_by(Race.id, Race.started_at)
    )
    for started_at, p_count in race_heatmap_q.all():
        if started_at is None:
            continue
        day = _day_of_week_index(started_at)
        bucket = _hour_to_bucket_index(started_at.hour)
        if bucket is not None:
            race_players_grid[bucket][day] += p_count

    # Solo heatmap: count per slot
    solo_heatmap_q = await db.execute(
        select(TrainingSession.created_at).where(
            TrainingSession.created_at.is_not(None)
        )
    )
    for (created_at,) in solo_heatmap_q.all():
        if created_at is None:
            continue
        day = _day_of_week_index(created_at)
        bucket = _hour_to_bucket_index(created_at.hour)
        if bucket is not None:
            solo_grid[bucket][day] += 1

    # =========================================================================
    # Timezone distribution
    # =========================================================================
    tz_q = await db.execute(
        select(User.timezone, func.count(User.id))
        .where(User.timezone.is_not(None))
        .group_by(User.timezone)
    )
    timezones = []
    for tz_name, count in tz_q.all():
        try:
            tz = ZoneInfo(tz_name)
            offset = datetime.now(tz).utcoffset()
            offset_minutes = int(offset.total_seconds() // 60) if offset else 0
        except (KeyError, Exception):
            offset_minutes = 0
        timezones.append(
            {"timezone": tz_name, "offset_minutes": offset_minutes, "count": count}
        )
    timezones.sort(key=lambda t: t["offset_minutes"])

    return {
        "kpis": {
            "total_users": total_users,
            "new_users_this_month": new_users_this_month,
            "active_users_30d": active_users_30d,
            "active_users_pct": active_users_pct,
            "total_races_finished": total_races_finished,
            "avg_participants": avg_participants,
            "total_solo": total_solo,
            "solo_completion_pct": solo_completion_pct,
        },
        "weekly": {
            "weeks": week_labels,
            "new_users": new_users_weekly,
            "races": races_weekly,
            "solo": solo_weekly,
            "solo_finished": solo_finished_weekly,
            "solo_abandoned": solo_abandoned_weekly,
            "avg_participants": avg_participants_weekly,
        },
        "heatmaps": {
            "race_players": race_players_grid,
            "solo": solo_grid,
        },
        "timezones": timezones,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_analytics.py -k "compute_analytics" -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/services/analytics_service.py server/tests/test_analytics.py
git commit -m "feat: add analytics service with KPIs, weekly, heatmaps, timezones"
```

---

### Task 4: Admin analytics API endpoint

**Files:**

- Modify: `server/speedfog_racing/api/admin.py`
- Modify: `server/tests/test_analytics.py`

- [ ] **Step 1: Write the API endpoint tests**

Append to `server/tests/test_analytics.py`:

```python
# =============================================================================
# Admin Analytics Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_200_for_admin(
    test_client, admin_user, analytics_data
):
    """GET /api/admin/analytics returns 200 for admin."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "kpis" in data
    assert "weekly" in data
    assert "heatmaps" in data
    assert "timezones" in data


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_403_for_non_admin(
    test_client, regular_user
):
    """GET /api/admin/analytics returns 403 for non-admin."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_401_without_auth(test_client):
    """GET /api/admin/analytics returns 401 without auth."""
    async with test_client as client:
        response = await client.get("/api/admin/analytics")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_analytics.py -k "endpoint" -v`
Expected: FAIL (404, endpoint does not exist yet)

- [ ] **Step 3: Add the endpoint to admin.py**

In `server/speedfog_racing/api/admin.py`, add at the end of the "Stats Management" section (after the `recalculate_stats` endpoint):

```python
@router.get("/analytics")
async def get_analytics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Get analytics dashboard data. Requires admin role."""
    from speedfog_racing.services.analytics_service import compute_analytics

    return await compute_analytics(db)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_analytics.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd server && uv run pytest -x -q`
Expected: all tests PASS

- [ ] **Step 6: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Fix any issues.

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/api/admin.py server/tests/test_analytics.py
git commit -m "feat: add GET /api/admin/analytics endpoint"
```

---

### Task 5: Frontend API types and Chart.js

**Files:**

- Modify: `web/package.json` (install chart.js)
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Install Chart.js**

```bash
cd web && npm install chart.js
```

- [ ] **Step 2: Add TypeScript types and fetch function**

In `web/src/lib/api.ts`, add the following types near the other admin types (around line 966):

```typescript
export interface AnalyticsKpis {
  total_users: number;
  new_users_this_month: number;
  active_users_30d: number;
  active_users_pct: number;
  total_races_finished: number;
  avg_participants: number;
  total_solo: number;
  solo_completion_pct: number;
}

export interface AnalyticsWeekly {
  weeks: string[];
  new_users: number[];
  races: number[];
  solo: number[];
  solo_finished: number[];
  solo_abandoned: number[];
  avg_participants: number[];
}

export interface AnalyticsTimezone {
  timezone: string;
  offset_minutes: number;
  count: number;
}

export interface AdminAnalytics {
  kpis: AnalyticsKpis;
  weekly: AnalyticsWeekly;
  heatmaps: {
    race_players: number[][];
    solo: number[][];
  };
  timezones: AnalyticsTimezone[];
}
```

Add the fetch function near the other admin fetch functions:

```typescript
export async function fetchAdminAnalytics(): Promise<AdminAnalytics> {
  const response = await fetch(`${API_BASE}/admin/analytics`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminAnalytics>(response);
}
```

- [ ] **Step 3: Run type check**

```bash
cd web && npm run check
```

Expected: no new errors

- [ ] **Step 4: Commit**

```bash
git add web/package.json web/package-lock.json web/src/lib/api.ts
git commit -m "feat: add Chart.js dependency and admin analytics API types"
```

---

### Task 6: Stats tab UI

**Files:**

- Modify: `web/src/routes/admin/+page.svelte`

- [ ] **Step 1: Add imports, state, and load function**

At the top of the `<script>` block in `web/src/routes/admin/+page.svelte`, add to the existing imports from `$lib/api`:

```typescript
import {
  // ...existing imports...
  fetchAdminAnalytics,
  type AdminAnalytics,
} from "$lib/api";
```

Add a new import for Chart.js:

```typescript
import { Chart, registerables } from "chart.js";
Chart.register(...registerables);
```

Add state variables alongside the existing ones:

```typescript
let analytics: AdminAnalytics | null = $state(null);
let analyticsLoading = $state(false);
```

Add a load function:

```typescript
async function loadAnalytics() {
  analyticsLoading = true;
  try {
    analytics = await fetchAdminAnalytics();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load analytics.";
  } finally {
    analyticsLoading = false;
  }
}
```

Update the `switchTab` function to load analytics when the stats tab is selected. Replace the existing stats/seeds condition:

```typescript
function switchTab(tab: Tab) {
  activeTab = tab;
  if (tab === "seeds" && !seedStats) {
    loadSeedStats();
    loadReportedSeeds();
  }
  if (tab === "stats" && !analytics) {
    loadAnalytics();
  }
  if (tab === "activity" && !activity) {
    loadActivity();
  }
}
```

- [ ] **Step 2: Add Chart.js canvas refs and effect**

Add canvas refs and chart instances in the `<script>` block:

```typescript
let newUsersCanvas: HTMLCanvasElement;
let raceSoloCanvas: HTMLCanvasElement;
let soloCompletionCanvas: HTMLCanvasElement;
let avgParticipantsCanvas: HTMLCanvasElement;
let timezoneCanvas: HTMLCanvasElement;

let charts: Chart[] = [];

function destroyCharts() {
  charts.forEach((c) => c.destroy());
  charts = [];
}

function renderCharts(data: AdminAnalytics) {
  destroyCharts();
  const gridColor = "rgba(255,255,255,0.06)";
  const tickColor = "#888";
  const defaultScales = {
    x: {
      grid: { display: false },
      ticks: { color: tickColor, font: { size: 10 } },
    },
    y: {
      beginAtZero: true,
      grid: { color: gridColor },
      ticks: { color: tickColor, font: { size: 10 } },
    },
  };
  const defaultPlugins = { legend: { display: false } };

  // New Users per Week
  charts.push(
    new Chart(newUsersCanvas, {
      type: "bar",
      data: {
        labels: data.weekly.weeks,
        datasets: [
          {
            data: data.weekly.new_users,
            backgroundColor: "rgba(139,92,246,0.6)",
            borderColor: "#8b5cf6",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: defaultPlugins,
        scales: defaultScales,
      },
    }),
  );

  // Races & Solo per Week
  charts.push(
    new Chart(raceSoloCanvas, {
      type: "bar",
      data: {
        labels: data.weekly.weeks,
        datasets: [
          {
            label: "Races",
            data: data.weekly.races,
            backgroundColor: "rgba(200,164,78,0.6)",
            borderColor: "#c8a44e",
            borderWidth: 1,
          },
          {
            label: "Solo",
            data: data.weekly.solo,
            backgroundColor: "rgba(139,92,246,0.6)",
            borderColor: "#8b5cf6",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        scales: {
          ...defaultScales,
          x: { ...defaultScales.x, stacked: true },
          y: { ...defaultScales.y, stacked: true },
        },
        plugins: {
          legend: {
            display: true,
            labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 },
          },
        },
      },
    }),
  );

  // Solo Completion Rate per Week
  charts.push(
    new Chart(soloCompletionCanvas, {
      type: "bar",
      data: {
        labels: data.weekly.weeks,
        datasets: [
          {
            label: "Finished",
            data: data.weekly.solo_finished,
            backgroundColor: "rgba(34,197,94,0.5)",
            borderColor: "#22c55e",
            borderWidth: 1,
          },
          {
            label: "Abandoned",
            data: data.weekly.solo_abandoned,
            backgroundColor: "rgba(239,68,68,0.5)",
            borderColor: "#ef4444",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        scales: {
          ...defaultScales,
          x: { ...defaultScales.x, stacked: true },
          y: { ...defaultScales.y, stacked: true },
        },
        plugins: {
          legend: {
            display: true,
            labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 },
          },
        },
      },
    }),
  );

  // Avg Participants per Race per Week
  charts.push(
    new Chart(avgParticipantsCanvas, {
      type: "bar",
      data: {
        labels: data.weekly.weeks,
        datasets: [
          {
            data: data.weekly.avg_participants,
            backgroundColor: "rgba(200,164,78,0.6)",
            borderColor: "#c8a44e",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: defaultPlugins,
        scales: defaultScales,
      },
    }),
  );

  // Timezone Distribution
  charts.push(
    new Chart(timezoneCanvas, {
      type: "bar",
      data: {
        labels: data.timezones.map((t) => t.timezone.replace("_", " ")),
        datasets: [
          {
            data: data.timezones.map((t) => t.count),
            backgroundColor: "rgba(139,92,246,0.6)",
            borderColor: "#8b5cf6",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: defaultPlugins,
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: tickColor, font: { size: 9 }, maxRotation: 45 },
          },
          y: {
            beginAtZero: true,
            grid: { color: gridColor },
            ticks: { color: tickColor, font: { size: 10 }, stepSize: 1 },
          },
        },
      },
    }),
  );
}

$effect(() => {
  if (analytics && newUsersCanvas) {
    renderCharts(analytics);
  }
  return () => destroyCharts();
});
```

- [ ] **Step 3: Replace Stats tab markup**

Replace the stats tab content (the `{:else if activeTab === 'stats'}` block) with:

```svelte
{:else if activeTab === 'stats'}
  {#if analyticsLoading}
    <p class="loading">Loading analytics...</p>
  {:else if analytics}
    <!-- KPI Cards -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Users</div>
        <div class="kpi-value">{analytics.kpis.total_users}</div>
        <div class="kpi-sub">+{analytics.kpis.new_users_this_month} this month</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Active (30d)</div>
        <div class="kpi-value">{analytics.kpis.active_users_30d}</div>
        <div class="kpi-sub">{analytics.kpis.active_users_pct}% of total</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Races (finished)</div>
        <div class="kpi-value kpi-gold">{analytics.kpis.total_races_finished}</div>
        <div class="kpi-sub">avg {analytics.kpis.avg_participants} players</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Solo Sessions</div>
        <div class="kpi-value kpi-purple">{analytics.kpis.total_solo}</div>
        <div class="kpi-sub">{analytics.kpis.solo_completion_pct}% finished</div>
      </div>
    </div>

    <!-- Weekly Charts -->
    <div class="charts-grid">
      <div class="chart-box">
        <div class="chart-title">New Users per Week</div>
        <canvas bind:this={newUsersCanvas}></canvas>
      </div>
      <div class="chart-box">
        <div class="chart-title">Races & Solo per Week</div>
        <canvas bind:this={raceSoloCanvas}></canvas>
      </div>
      <div class="chart-box">
        <div class="chart-title">Solo Completion Rate</div>
        <canvas bind:this={soloCompletionCanvas}></canvas>
      </div>
      <div class="chart-box">
        <div class="chart-title">Avg Participants per Race</div>
        <canvas bind:this={avgParticipantsCanvas}></canvas>
      </div>
    </div>

    <!-- Heatmaps -->
    <div class="heatmaps-row">
      {@const raceMax = Math.max(1, ...analytics.heatmaps.race_players.flat())}
      {@const soloMax = Math.max(1, ...analytics.heatmaps.solo.flat())}
      {@const hours = ['10h', '12h', '14h', '16h', '18h', '20h', '22h', '00h']}
      {@const days = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']}

      <div class="heatmap-box">
        <div class="heatmap-title heatmap-gold">Race Players</div>
        <div class="heatmap-grid">
          <div class="heatmap-corner"></div>
          {#each days as day}
            <div class="heatmap-day">{day}</div>
          {/each}
          {#each hours as hour, rowIdx}
            <div class="heatmap-hour">{hour}</div>
            {#each analytics.heatmaps.race_players[rowIdx] as val}
              <div
                class="heatmap-cell"
                style="background: rgba(200,164,78,{val / raceMax * 0.9})"
                title="{val}"
              ></div>
            {/each}
          {/each}
        </div>
        <div class="heatmap-legend">
          <span>0</span>
          <div class="heatmap-legend-bar heatmap-legend-gold"></div>
          <span>{raceMax}</span>
        </div>
      </div>

      <div class="heatmap-box">
        <div class="heatmap-title heatmap-purple">Solo</div>
        <div class="heatmap-grid">
          <div class="heatmap-corner"></div>
          {#each days as day}
            <div class="heatmap-day">{day}</div>
          {/each}
          {#each hours as hour, rowIdx}
            <div class="heatmap-hour">{hour}</div>
            {#each analytics.heatmaps.solo[rowIdx] as val}
              <div
                class="heatmap-cell"
                style="background: rgba(139,92,246,{val / soloMax * 0.9})"
                title="{val}"
              ></div>
            {/each}
          {/each}
        </div>
        <div class="heatmap-legend">
          <span>0</span>
          <div class="heatmap-legend-bar heatmap-legend-purple"></div>
          <span>{soloMax}</span>
        </div>
      </div>
    </div>

    <!-- Timezone Distribution -->
    {#if analytics.timezones.length > 0}
      <div class="chart-box chart-full">
        <div class="chart-title">Players by Timezone</div>
        <canvas bind:this={timezoneCanvas}></canvas>
      </div>
    {/if}

    <!-- Recalculate Stats (existing) -->
    <div class="stats-section">
      <h2 class="section-title">Recalculate</h2>
      <p class="stats-description">
        Recompute cached statistics for all users and participants from raw race data.
      </p>
      <div class="stats-actions">
        <button class="action-btn recalc" disabled={recalcLoading} onclick={handleRecalculateStats}>
          {recalcLoading ? 'Recalculating...' : 'Recalculate Stats'}
        </button>
        {#if recalcMessage}
          <span class="recalc-message {recalcMessage.type}">{recalcMessage.text}</span>
        {/if}
      </div>
    </div>
  {/if}
```

- [ ] **Step 4: Add CSS styles**

Add these styles to the `<style>` block in the same file:

```css
/* KPI Cards */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.kpi-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 1rem;
  text-align: center;
}

.kpi-label {
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
}

.kpi-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--color-text);
  margin: 0.25rem 0;
  font-variant-numeric: tabular-nums;
}

.kpi-gold {
  color: var(--color-gold);
}

.kpi-purple {
  color: var(--color-purple);
}

.kpi-sub {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

/* Charts */
.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.chart-box {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 1rem;
}

.chart-full {
  margin-bottom: 1.5rem;
}

.chart-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 0.75rem;
}

/* Heatmaps */
.heatmaps-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.heatmap-box {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 1rem;
}

.heatmap-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.heatmap-gold {
  color: var(--color-gold);
}

.heatmap-purple {
  color: var(--color-purple);
}

.heatmap-grid {
  display: grid;
  grid-template-columns: 2.5rem repeat(7, 1fr);
  gap: 3px;
}

.heatmap-corner {
  /* empty top-left cell */
}

.heatmap-day {
  text-align: center;
  font-size: 0.6rem;
  color: var(--color-text-secondary);
  padding-bottom: 2px;
}

.heatmap-hour {
  text-align: right;
  padding-right: 4px;
  font-size: 0.6rem;
  color: var(--color-text-secondary);
  line-height: 1.5rem;
}

.heatmap-cell {
  height: 1.5rem;
  border-radius: 2px;
  background: var(--color-bg, #0d1117);
}

.heatmap-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 0.5rem;
  font-size: 0.6rem;
  color: var(--color-text-secondary);
}

.heatmap-legend-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  max-width: 120px;
}

.heatmap-legend-gold {
  background: linear-gradient(to right, #0d1117, rgba(200, 164, 78, 0.9));
}

.heatmap-legend-purple {
  background: linear-gradient(to right, #0d1117, rgba(139, 92, 246, 0.9));
}

@media (max-width: 640px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .charts-grid,
  .heatmaps-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run frontend checks**

```bash
cd web && npm run check && npm run lint
```

Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/admin/+page.svelte
git commit -m "feat: add analytics dashboard UI with charts and heatmaps"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full server test suite**

```bash
cd server && uv run pytest -x -q
```

Expected: all tests PASS

- [ ] **Step 2: Run full frontend checks**

```bash
cd web && npm run check && npm run lint
```

Expected: no errors

- [ ] **Step 3: Run server linters**

```bash
cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/
```

Expected: clean

- [ ] **Step 4: Manual smoke test**

Start the dev server and verify:

```bash
# Terminal 1
cd server && uv run speedfog-racing

# Terminal 2
cd web && npm run dev
```

1. Navigate to `/admin`, click "Stats" tab
2. Verify KPI cards render with real data
3. Verify 4 weekly charts render (may be empty if no data)
4. Verify heatmaps render
5. Verify timezone chart renders (or is hidden if no timezone data yet)
6. Verify "Recalculate Stats" button still works
7. Reload the page and check browser console for timezone being sent on `/auth/me`

- [ ] **Step 5: Launch code review agent**
