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

from datetime import UTC, date, datetime, timedelta  # noqa: E402

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

    async with async_session() as db:
        # Users — created_at must be in the current ISO week so that the
        # weekly test assertions hold regardless of which day of the month
        # or week the test runs on.
        user1 = User(
            twitch_id="tz_user1",
            twitch_username="tzuser1",
            twitch_display_name="TZ User 1",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="Europe/Paris",
            created_at=now - timedelta(hours=6),
            last_seen=now - timedelta(days=5),
        )
        user2 = User(
            twitch_id="tz_user2",
            twitch_username="tzuser2",
            twitch_display_name="TZ User 2",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="America/New_York",
            created_at=now - timedelta(hours=5),
            last_seen=now - timedelta(days=10),
        )
        user3 = User(
            twitch_id="tz_user3",
            twitch_username="tzuser3",
            twitch_display_name="TZ User 3",
            api_token=generate_token(),
            role=UserRole.USER,
            timezone="Asia/Tokyo",
            created_at=now - timedelta(hours=4),
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
    assert kpis["total_daily_participants"] == 0
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
    assert "pool_usage" in data
    assert "top_organizers" in data


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


# ---------------------------------------------------------------------------
# Pool usage / top organizers tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_analytics_pool_usage_from_fixture(analytics_data, async_session):
    """pool_usage should aggregate race participations and eligible training sessions."""
    async with async_session() as db:
        result = await compute_analytics(db)

    pool_usage = result["pool_usage"]
    assert len(pool_usage) == 1
    entry = pool_usage[0]
    assert entry["pool_name"] == "standard"
    # One race in the pool (participant count does not inflate the value)
    assert entry["race_runs"] == 1
    # 1 FINISHED training; the ABANDONED one has igt_ms=0 so is excluded
    assert entry["training_runs"] == 1
    assert entry["total_runs"] == 2


@pytest.mark.asyncio
async def test_compute_analytics_pool_usage_merges_training_prefix(async_session):
    """A seed pool named "training_<x>" must merge into "<x>" on the pool_usage row."""
    now = datetime.now(tz=UTC)
    async with async_session() as db:
        user = User(
            twitch_id="pool_u",
            twitch_username="pooluser",
            api_token=generate_token(),
        )
        db.add(user)
        await db.flush()

        race_seed = Seed(
            seed_number="100",
            pool_name="boss_rush",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/100",
            status=SeedStatus.CONSUMED,
        )
        training_seed = Seed(
            seed_number="101",
            pool_name="training_boss_rush",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/101",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([race_seed, training_seed])
        await db.flush()

        race = Race(
            name="r",
            organizer_id=user.id,
            seed_id=race_seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(hours=1),
            finished_at=now,
        )
        db.add(race)
        await db.flush()
        db.add(
            Participant(
                race_id=race.id,
                user_id=user.id,
                mod_token=generate_token(),
                status=ParticipantStatus.FINISHED,
            )
        )
        db.add(
            TrainingSession(
                user_id=user.id,
                seed_id=training_seed.id,
                mod_token=generate_token(),
                status=TrainingSessionStatus.FINISHED,
                igt_ms=1000,
            )
        )
        await db.commit()

    async with async_session() as db:
        result = await compute_analytics(db)

    pools = {p["pool_name"]: p for p in result["pool_usage"]}
    assert "boss_rush" in pools
    # training_boss_rush must merge into boss_rush, not appear as its own row
    assert "training_boss_rush" not in pools
    entry = pools["boss_rush"]
    assert entry["race_runs"] == 1
    assert entry["training_runs"] == 1


@pytest.mark.asyncio
async def test_compute_analytics_top_organizers_from_fixture(analytics_data, async_session):
    """Top organizers should list user1 (1 finished race, avg 2.0 participants)."""
    async with async_session() as db:
        result = await compute_analytics(db)

    top = result["top_organizers"]
    assert len(top) == 1
    entry = top[0]
    assert entry["twitch_username"] == "tzuser1"
    assert entry["race_count"] == 1
    assert entry["avg_participants"] == 2.0


@pytest.mark.asyncio
async def test_compute_analytics_pool_usage_sorted_by_total_runs(async_session):
    """pool_usage entries must be sorted by total_runs desc, then pool_name asc."""
    now = datetime.now(tz=UTC)
    async with async_session() as db:
        user = User(twitch_id="su", twitch_username="suser", api_token=generate_token())
        db.add(user)
        await db.flush()

        seed_big = Seed(
            seed_number="400",
            pool_name="alpha",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/400",
            status=SeedStatus.CONSUMED,
        )
        seed_small = Seed(
            seed_number="401",
            pool_name="beta",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/401",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([seed_big, seed_small])
        await db.flush()

        # alpha: 2 races ; beta: 1 race
        for seed, count in ((seed_big, 2), (seed_small, 1)):
            for _ in range(count):
                db.add(
                    Race(
                        name="r",
                        organizer_id=user.id,
                        seed_id=seed.id,
                        status=RaceStatus.FINISHED,
                        started_at=now - timedelta(hours=1),
                        finished_at=now,
                    )
                )
        await db.commit()

    async with async_session() as db:
        result = await compute_analytics(db)

    names = [p["pool_name"] for p in result["pool_usage"]]
    assert names == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_compute_analytics_top_organizers_zero_participants(async_session):
    """A finished race with zero participants must still count in the organizer's tally."""
    now = datetime.now(tz=UTC)
    async with async_session() as db:
        user = User(twitch_id="zp", twitch_username="zporg", api_token=generate_token())
        db.add(user)
        await db.flush()
        seed = Seed(
            seed_number="500",
            pool_name="solo_pool",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/500",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        db.add(
            Race(
                name="r",
                organizer_id=user.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=now - timedelta(hours=1),
                finished_at=now,
            )
        )
        await db.commit()

    async with async_session() as db:
        result = await compute_analytics(db)

    top = result["top_organizers"]
    assert len(top) == 1
    assert top[0]["twitch_username"] == "zporg"
    assert top[0]["race_count"] == 1
    assert top[0]["avg_participants"] == 0.0


@pytest.mark.asyncio
async def test_compute_analytics_top_organizers_ranking(async_session):
    """Organizers must be ranked by race count (desc), ignoring non-finished races."""
    now = datetime.now(tz=UTC)
    async with async_session() as db:
        organizers = [
            User(
                twitch_id=f"o{i}",
                twitch_username=f"org{i}",
                api_token=generate_token(),
            )
            for i in range(3)
        ]
        # Pool of distinct players to satisfy participants.UNIQUE(race_id, user_id)
        players = [
            User(
                twitch_id=f"p{i}",
                twitch_username=f"player{i}",
                api_token=generate_token(),
            )
            for i in range(4)
        ]
        db.add_all(organizers + players)
        await db.flush()

        seed = Seed(
            seed_number="300",
            pool_name="std",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/300",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # org0: 3 finished races, 2 participants each
        # org1: 2 finished races, 4 participants each
        # org2: 1 SETUP race (must be ignored)
        race_specs = [
            (organizers[0], RaceStatus.FINISHED, 2),
            (organizers[0], RaceStatus.FINISHED, 2),
            (organizers[0], RaceStatus.FINISHED, 2),
            (organizers[1], RaceStatus.FINISHED, 4),
            (organizers[1], RaceStatus.FINISHED, 4),
            (organizers[2], RaceStatus.SETUP, 3),
        ]
        for organizer, status, participant_count in race_specs:
            race = Race(
                name="r",
                organizer_id=organizer.id,
                seed_id=seed.id,
                status=status,
                started_at=now - timedelta(hours=1) if status != RaceStatus.SETUP else None,
                finished_at=now if status == RaceStatus.FINISHED else None,
            )
            db.add(race)
            await db.flush()
            for idx in range(participant_count):
                db.add(
                    Participant(
                        race_id=race.id,
                        user_id=players[idx].id,
                        mod_token=generate_token(),
                        status=ParticipantStatus.FINISHED,
                    )
                )
        await db.commit()

    async with async_session() as db:
        result = await compute_analytics(db)

    top = result["top_organizers"]
    assert [e["twitch_username"] for e in top] == ["org0", "org1"]
    assert top[0]["race_count"] == 3
    assert top[0]["avg_participants"] == 2.0
    assert top[1]["race_count"] == 2
    assert top[1]["avg_participants"] == 4.0


@pytest.mark.asyncio
async def test_compute_analytics_daily_qualified_participants(async_session):
    """Daily races stay out of race-side aggregates, but qualified Daily
    participations (``len(zone_history) >= 2``) feed both the
    ``total_daily_participants`` KPI and the ``weekly.daily`` series."""
    now = datetime.now(tz=UTC)
    async with async_session() as db:
        organizer = User(twitch_id="o_d", twitch_username="orgd", api_token=generate_token())
        player = User(twitch_id="p_d", twitch_username="playerd", api_token=generate_token())
        other_player = User(
            twitch_id="p_d2", twitch_username="playerd2", api_token=generate_token()
        )
        db.add_all([organizer, player, other_player])
        await db.flush()

        regular_seed = Seed(
            seed_number="700",
            pool_name="standard",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/700",
            status=SeedStatus.CONSUMED,
        )
        daily_seed = Seed(
            seed_number="701",
            pool_name="daily_pool",
            graph_json={},
            total_layers=1,
            folder_path="/seeds/701",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([regular_seed, daily_seed])
        await db.flush()

        regular_race = Race(
            name="regular",
            organizer_id=organizer.id,
            seed_id=regular_seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
        )
        # Today's daily: RUNNING, to pin that no race-status filter applies.
        daily_race_today = Race(
            name="daily-today",
            organizer_id=organizer.id,
            seed_id=daily_seed.id,
            status=RaceStatus.RUNNING,
            started_at=now - timedelta(hours=2),
            daily_date=date.today(),
        )
        # Yesterday's daily: FINISHED, two participants with varied
        # zone_history lengths to exercise the qualification predicate.
        daily_race_yesterday = Race(
            name="daily-yesterday",
            organizer_id=organizer.id,
            seed_id=daily_seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(days=1, hours=2),
            finished_at=now - timedelta(days=1, hours=1),
            daily_date=date.today() - timedelta(days=1),
        )
        db.add_all([regular_race, daily_race_today, daily_race_yesterday])
        await db.flush()

        zh_qualified = [{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}]
        zh_unqualified_one = [{"node_id": "a"}]
        zh_empty: list[dict[str, str]] = []

        db.add_all(
            [
                Participant(
                    race_id=regular_race.id,
                    user_id=player.id,
                    mod_token=generate_token(),
                    status=ParticipantStatus.FINISHED,
                ),
                # Today's daily: one qualified runner (counts), one not yet (excluded).
                Participant(
                    race_id=daily_race_today.id,
                    user_id=player.id,
                    mod_token=generate_token(),
                    status=ParticipantStatus.PLAYING,
                    zone_history=zh_qualified,
                ),
                Participant(
                    race_id=daily_race_today.id,
                    user_id=other_player.id,
                    mod_token=generate_token(),
                    status=ParticipantStatus.REGISTERED,
                    zone_history=zh_empty,
                ),
                # Yesterday's daily: one qualified (counts), one with a single
                # entry (excluded), so the per-race qualified count is 1.
                Participant(
                    race_id=daily_race_yesterday.id,
                    user_id=player.id,
                    mod_token=generate_token(),
                    status=ParticipantStatus.FINISHED,
                    zone_history=zh_qualified,
                ),
                Participant(
                    race_id=daily_race_yesterday.id,
                    user_id=other_player.id,
                    mod_token=generate_token(),
                    status=ParticipantStatus.ABANDONED,
                    zone_history=zh_unqualified_one,
                ),
            ]
        )
        await db.commit()

    async with async_session() as db:
        result = await compute_analytics(db)

    # KPI: 1 qualified today + 1 qualified yesterday = 2.
    assert result["kpis"]["total_races_finished"] == 1
    assert result["kpis"]["total_daily_participants"] == 2
    assert result["kpis"]["avg_participants"] == 1.0

    # Weekly: regular race contributes to weekly.races (current week); the
    # two qualified daily participations split across the current week and
    # the previous-week bucket (yesterday's daily lives there when the
    # current weekday is Monday, otherwise the same week as today).
    weeks = result["weekly"]["weeks"]
    assert len(weeks) == 12
    today_iso = now.isocalendar()
    yesterday_iso = (now - timedelta(days=1)).isocalendar()
    today_idx = next(i for i, w in enumerate(weeks) if w == f"W{today_iso.week}")
    yesterday_idx = next(i for i, w in enumerate(weeks) if w == f"W{yesterday_iso.week}")
    daily_series = result["weekly"]["daily"]
    if today_idx == yesterday_idx:
        assert daily_series[today_idx] == 2
    else:
        assert daily_series[today_idx] == 1
        assert daily_series[yesterday_idx] == 1
    assert result["weekly"]["races"][-1] == 1

    # Heatmap stays race-only.
    total_race = sum(cell for row in result["heatmaps"]["race_players"] for cell in row)
    assert total_race == 1

    # pool_usage: daily_pool must not appear (no other activity in it).
    pool_names = {p["pool_name"] for p in result["pool_usage"]}
    assert "daily_pool" not in pool_names
    assert "standard" in pool_names

    # top_organizers: organizer's count is 1 (regular race only; dailies excluded)
    top = result["top_organizers"]
    assert len(top) == 1
    assert top[0]["twitch_username"] == "orgd"
    assert top[0]["race_count"] == 1
