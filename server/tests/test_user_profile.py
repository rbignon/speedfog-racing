"""Tests for user profile endpoint."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
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
async def sample_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="profile_user_1",
            twitch_username="speedrunner42",
            twitch_display_name="SpeedRunner42",
            twitch_avatar_url="https://static-cdn.jtvnw.net/avatar.png",
            api_token="profile_test_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
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
async def test_get_profile_by_username(test_client, sample_user):
    """GET /api/users/{username} returns 200 with correct data and zero stats."""
    async with test_client as client:
        response = await client.get(f"/api/users/{sample_user.twitch_username}")
        assert response.status_code == 200
        data = response.json()

        # Check user fields
        assert data["id"] == str(sample_user.id)
        assert data["twitch_username"] == "speedrunner42"
        assert data["twitch_display_name"] == "SpeedRunner42"
        assert data["twitch_avatar_url"] == "https://static-cdn.jtvnw.net/avatar.png"
        assert data["role"] == "organizer"
        assert "created_at" in data

        # Check stats - all should be zero for a fresh user
        stats = data["stats"]
        assert stats["race_count"] == 0
        assert stats["training_count"] == 0
        assert stats["podium_count"] == 0
        assert stats["first_place_count"] == 0
        assert stats["organized_count"] == 0
        assert stats["casted_count"] == 0


@pytest.mark.asyncio
async def test_get_profile_nonexistent_user(test_client):
    """GET /api/users/{username} returns 404 for nonexistent user."""
    async with test_client as client:
        response = await client.get("/api/users/nonexistent_user_xyz")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
async def test_get_profile_is_public(test_client, sample_user):
    """GET /api/users/{username} does not require authentication."""
    async with test_client as client:
        # No Authorization header
        response = await client.get(f"/api/users/{sample_user.twitch_username}")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_profile_does_not_shadow_me(test_client, sample_user):
    """GET /api/users/me should hit the /me endpoint, not /{username}."""
    async with test_client as client:
        # /me requires auth, so without auth we should get 401, not 404
        response = await client.get("/api/users/me")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_profile_does_not_shadow_search(test_client, sample_user):
    """GET /api/users/search should hit the /search endpoint, not /{username}."""
    async with test_client as client:
        # /search requires auth, so without auth we should get 401 (or 422 for missing q)
        response = await client.get("/api/users/search?q=test")
        assert response.status_code == 401


@pytest.fixture
async def user_with_activity(async_session):
    """Create a user with races, training, caster, and organizer activity."""
    async with async_session() as db:
        # -- Users --
        active_player = User(
            twitch_id="active_player_1",
            twitch_username="active_player",
            twitch_display_name="ActivePlayer",
            api_token="active_player_token",
            role=UserRole.USER,
        )
        organizer_user = User(
            twitch_id="organizer_1",
            twitch_username="organizer_user",
            twitch_display_name="OrganizerUser",
            api_token="organizer_token",
            role=UserRole.ORGANIZER,
        )
        other_player = User(
            twitch_id="other_player_1",
            twitch_username="other_player",
            twitch_display_name="OtherPlayer",
            api_token="other_player_token",
            role=UserRole.USER,
        )
        db.add_all([active_player, organizer_user, other_player])
        await db.flush()

        # -- Seed --
        seed = Seed(
            seed_number="test_seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # -- Race 1: active_player finishes 1st, other finishes 2nd --
        race1 = Race(
            name="Race 1",
            organizer_id=organizer_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race1)
        await db.flush()

        p1_r1 = Participant(
            race_id=race1.id,
            user_id=active_player.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=100000,
        )
        p2_r1 = Participant(
            race_id=race1.id,
            user_id=other_player.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=200000,
        )
        db.add_all([p1_r1, p2_r1])

        # -- Race 2: active_player finishes 2nd, other finishes 1st --
        race2 = Race(
            name="Race 2",
            organizer_id=organizer_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race2)
        await db.flush()

        p1_r2 = Participant(
            race_id=race2.id,
            user_id=active_player.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=300000,
        )
        p2_r2 = Participant(
            race_id=race2.id,
            user_id=other_player.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=150000,
        )
        db.add_all([p1_r2, p2_r2])

        # -- Race 3: active_player is organizer (not a participant) --
        race3 = Race(
            name="Race 3",
            organizer_id=active_player.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race3)
        await db.flush()

        # -- Race 4: active_player is caster (not a participant) --
        race4 = Race(
            name="Race 4",
            organizer_id=organizer_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race4)
        await db.flush()

        caster = Caster(
            race_id=race4.id,
            user_id=active_player.id,
        )
        db.add(caster)

        # -- Training session --
        training = TrainingSession(
            user_id=active_player.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED,
        )
        db.add(training)

        await db.commit()
        await db.refresh(active_player)
        return active_player


@pytest.mark.asyncio
async def test_profile_stats_counts(test_client, user_with_activity):
    """Profile stats reflect real race/training/caster/organizer activity."""
    async with test_client as client:
        response = await client.get(f"/api/users/{user_with_activity.twitch_username}")
        assert response.status_code == 200
        data = response.json()
        stats = data["stats"]

        assert stats["race_count"] == 2  # participated in 2 races
        assert stats["training_count"] == 1  # 1 training session
        assert stats["organized_count"] == 1  # organized 1 race
        assert stats["casted_count"] == 1  # casted 1 race
        assert stats["podium_count"] == 2  # 1st + 2nd place both count
        assert stats["first_place_count"] == 1  # only race 1
