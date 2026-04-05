"""Tests for analytics-related endpoints (timezone collection via /auth/me)."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole, generate_token


@pytest.fixture
async def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def regular_user(async_session):
    """Create a regular user with an API token."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_regular",
            twitch_username="regularuser",
            twitch_display_name="Regular User",
            api_token=token,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, token


@pytest.fixture
async def admin_user(async_session):
    """Create an admin user with an API token."""
    async with async_session() as db:
        token = generate_token()
        user = User(
            twitch_id="twitch_admin",
            twitch_username="adminuser",
            twitch_display_name="Admin User",
            api_token=token,
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, token


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


@pytest.mark.asyncio
async def test_auth_me_updates_timezone(test_client, regular_user, async_session):
    """GET /api/auth/me?timezone=Europe/Paris updates the user's timezone."""
    _, token = regular_user
    async with test_client as client:
        response = await client.get(
            "/api/auth/me?timezone=Europe%2FParis",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200

    # Verify the timezone was persisted in the DB
    async with async_session() as db:
        result = await db.execute(select(User).where(User.api_token == token))
        user = result.scalar_one()
        assert user.timezone == "Europe/Paris"


@pytest.mark.asyncio
async def test_auth_me_without_timezone_leaves_null(test_client, regular_user, async_session):
    """GET /api/auth/me without timezone param leaves timezone as None."""
    _, token = regular_user
    async with test_client as client:
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200

    # Verify timezone was NOT set
    async with async_session() as db:
        result = await db.execute(select(User).where(User.api_token == token))
        user = result.scalar_one()
        assert user.timezone is None


# ---------------------------------------------------------------------------
# Analytics service tests
# ---------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from speedfog_racing.models import (  # noqa: E402
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
)
from speedfog_racing.services.analytics_service import compute_analytics  # noqa: E402


@pytest.fixture
async def analytics_data(async_session):
    """Create deterministic test data for analytics tests.

    - 3 users: user1 (Europe/Paris, active), user2 (America/New_York, active),
      user3 (Asia/Tokyo, last_seen > 30 days ago)
    - 1 consumed seed
    - 1 finished race with 2 participants (started_at = a few hours ago, this week)
    - 2 training sessions: 1 finished, 1 abandoned (created this week)
    """
    now = datetime.now(tz=UTC)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as db:
        # Users
        user1 = User(
            twitch_id="tz_user1",
            twitch_username="tzuser1",
            twitch_display_name="TZ User 1",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="Europe/Paris",
            created_at=this_month_start + timedelta(hours=1),
            last_seen=now - timedelta(days=5),
        )
        user2 = User(
            twitch_id="tz_user2",
            twitch_username="tzuser2",
            twitch_display_name="TZ User 2",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="America/New_York",
            created_at=this_month_start + timedelta(hours=2),
            last_seen=now - timedelta(days=10),
        )
        user3 = User(
            twitch_id="tz_user3",
            twitch_username="tzuser3",
            twitch_display_name="TZ User 3",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="Asia/Tokyo",
            created_at=this_month_start + timedelta(hours=3),
            last_seen=now - timedelta(days=35),
        )
        db.add_all([user1, user2, user3])
        await db.flush()

        # Seed
        seed = Seed(
            seed_number="999",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/seeds/999",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Race started a few hours ago (within current ISO week)
        race_started_at = now - timedelta(hours=3)
        race = Race(
            name="Analytics Test Race",
            organizer_id=user1.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=race_started_at,
            finished_at=now - timedelta(hours=1),
        )
        db.add(race)
        await db.flush()

        p1 = Participant(
            race_id=race.id,
            user_id=user1.id,
            mod_token=generate_token(),
            status=ParticipantStatus.FINISHED,
        )
        p2 = Participant(
            race_id=race.id,
            user_id=user2.id,
            mod_token=generate_token(),
            status=ParticipantStatus.FINISHED,
        )
        db.add_all([p1, p2])

        # Training sessions (both created this week)
        ts_finished = TrainingSession(
            user_id=user1.id,
            seed_id=seed.id,
            mod_token=generate_token(),
            status=TrainingSessionStatus.FINISHED,
            created_at=now - timedelta(hours=2),
        )
        ts_abandoned = TrainingSession(
            user_id=user2.id,
            seed_id=seed.id,
            mod_token=generate_token(),
            status=TrainingSessionStatus.ABANDONED,
            created_at=now - timedelta(hours=2),
        )
        db.add_all([ts_finished, ts_abandoned])
        await db.commit()

        return {
            "users": [user1, user2, user3],
            "seed": seed,
            "race": race,
            "training_sessions": [ts_finished, ts_abandoned],
        }


@pytest.mark.asyncio
async def test_compute_analytics_kpis(analytics_data, async_session):
    """KPI values must match fixture data."""
    async with async_session() as db:
        result = await compute_analytics(db)

    kpis = result["kpis"]
    # 3 users created by fixture (plus 2 from existing regular_user / admin_user fixtures
    # are NOT present here since analytics_data uses its own async_session)
    assert kpis["total_users"] == 3
    assert kpis["new_users_this_month"] == 3  # all created this month
    assert kpis["active_users_30d"] == 2  # user1 & user2; user3 last_seen > 30d
    assert kpis["active_users_pct"] == round(2 / 3 * 100, 1)
    assert kpis["total_races_finished"] == 1
    assert kpis["avg_participants"] == 2.0
    assert kpis["total_solo"] == 2
    assert kpis["solo_completion_pct"] == 50.0  # 1 finished / (1 finished + 1 abandoned)


@pytest.mark.asyncio
async def test_compute_analytics_timezones(analytics_data, async_session):
    """Timezone list must be sorted west (negative offset) to east (positive offset)."""
    async with async_session() as db:
        result = await compute_analytics(db)

    timezones = result["timezones"]
    # All 3 timezones present
    tz_names = [t["timezone"] for t in timezones]
    assert "Europe/Paris" in tz_names
    assert "America/New_York" in tz_names
    assert "Asia/Tokyo" in tz_names

    # Sorted west to east: New_York (negative) < Paris (positive low) < Tokyo (+540)
    offsets = [t["offset_minutes"] for t in timezones]
    assert offsets == sorted(offsets)

    # Each entry has the required fields
    for tz_entry in timezones:
        assert "timezone" in tz_entry
        assert "offset_minutes" in tz_entry
        assert "count" in tz_entry
        assert tz_entry["count"] == 1


@pytest.mark.asyncio
async def test_compute_analytics_weekly(analytics_data, async_session):
    """Weekly arrays must have 12 entries and current week must have correct counts."""
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

    # Current week (index -1, the last entry) should contain our fixture data
    assert weekly["new_users"][-1] == 3
    assert weekly["races"][-1] == 1
    assert weekly["solo"][-1] == 2
    assert weekly["solo_finished"][-1] == 1
    assert weekly["solo_abandoned"][-1] == 1
    assert weekly["avg_participants"][-1] == 2.0

    # Week label format must be "W<number>"
    for label in weekly["weeks"]:
        assert label.startswith("W")
        assert label[1:].isdigit()


@pytest.mark.asyncio
async def test_compute_analytics_heatmaps(analytics_data, async_session):
    """Heatmap grids must be 12 rows x 7 cols and contain fixture race/solo data."""
    async with async_session() as db:
        result = await compute_analytics(db)

    heatmaps = result["heatmaps"]
    race_grid = heatmaps["race_players"]
    solo_grid = heatmaps["solo"]

    assert len(race_grid) == 12
    assert len(solo_grid) == 12
    for row in race_grid:
        assert len(row) == 7
    for row in solo_grid:
        assert len(row) == 7

    # The fixture race started 3h ago and training sessions created 2h ago.
    # Total grid values should be non-zero (race has 2 participants, solo has 2 sessions).
    total_race = sum(cell for row in race_grid for cell in row)
    total_solo = sum(cell for row in solo_grid for cell in row)
    assert total_race == 2  # 2 participants in the one race
    assert total_solo == 2  # 2 training sessions


# ---------------------------------------------------------------------------
# Admin endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_200_for_admin(test_client, admin_user, analytics_data):
    """GET /api/admin/analytics returns 200 with expected keys for admin user."""
    _, token = admin_user
    async with test_client as client:
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "kpis" in data
    assert "weekly" in data
    assert "heatmaps" in data
    assert "timezones" in data


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_403_for_non_admin(test_client, regular_user):
    """GET /api/admin/analytics returns 403 for a non-admin user."""
    _, token = regular_user
    async with test_client as client:
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_analytics_endpoint_returns_401_without_auth(test_client):
    """GET /api/admin/analytics returns 401 when no auth header is provided."""
    async with test_client as client:
        response = await client.get("/api/admin/analytics")
    assert response.status_code == 401
