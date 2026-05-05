"""Tests for user profile endpoint."""

import os
from datetime import date

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
        assert stats["daily_count"] == 0
        assert stats["training_count"] == 0
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
async def test_activity_timeline(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player/activity")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "has_more" in data
        # 2 race_participant + 1 race_organizer + 1 race_caster + 1 training = 5
        assert data["total"] == 5
        types = [i["type"] for i in data["items"]]
        assert "race_participant" in types
        assert "race_organizer" in types
        assert "race_caster" in types
        assert "training" in types


@pytest.mark.asyncio
async def test_activity_pagination(test_client, user_with_activity):
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
async def test_activity_not_found(test_client):
    async with test_client as client:
        response = await client.get("/api/users/nonexistent/activity")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_activity_participant_has_placement(test_client, user_with_activity):
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


@pytest.mark.asyncio
async def test_activity_caster_has_status(test_client, user_with_activity):
    async with test_client as client:
        response = await client.get("/api/users/active_player/activity")
        data = response.json()
        caster_items = [i for i in data["items"] if i["type"] == "race_caster"]
        assert len(caster_items) >= 1
        for item in caster_items:
            assert "race_name" in item
            assert "status" in item


@pytest.mark.asyncio
async def test_activity_merges_self_organized_race(test_client, async_session):
    """When the user organizes a race they also play, only one row is emitted."""
    async with async_session() as db:
        user = User(
            twitch_id="self_host_1",
            twitch_username="self_host",
            twitch_display_name="Self Host",
            api_token="self_host_token",
        )
        db.add(user)
        await db.flush()

        seed = Seed(
            seed_number="self_host_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Self-Hosted",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race)
        await db.flush()

        db.add(
            Participant(
                race_id=race.id,
                user_id=user.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=120000,
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/self_host/activity")
        assert response.status_code == 200
        data = response.json()

    types = [i["type"] for i in data["items"]]
    assert types.count("race_participant") == 1
    assert "race_organizer" not in types
    participant_item = next(i for i in data["items"] if i["type"] == "race_participant")
    assert participant_item["is_organizer"] is True


@pytest.mark.asyncio
async def test_profile_stats_counts(test_client, user_with_activity):
    """Profile stats reflect real race/training/caster/organizer activity."""
    async with test_client as client:
        response = await client.get(f"/api/users/{user_with_activity.twitch_username}")
        assert response.status_code == 200
        data = response.json()
        stats = data["stats"]

        assert stats["race_count"] == 2  # participated in 2 races
        assert stats["daily_count"] == 0  # no daily participations
        assert stats["training_count"] == 1  # 1 training session
        assert stats["organized_count"] == 1  # organized 1 race
        assert stats["casted_count"] == 1  # casted 1 race


@pytest.mark.asyncio
async def test_profile_stats_split_daily_and_regular_races(test_client, async_session):
    """Daily Seed participations land in daily_count, not race_count."""
    async with async_session() as db:
        user = User(
            twitch_id="daily_split_uid",
            twitch_username="daily_splitter",
            twitch_display_name="DailySplitter",
            api_token="daily_splitter_token",
            role=UserRole.USER,
        )
        admin = User(
            twitch_id="daily_split_admin",
            twitch_username="daily_split_admin",
            twitch_display_name="Admin",
            api_token="daily_split_admin_token",
            role=UserRole.ADMIN,
        )
        db.add_all([user, admin])
        await db.flush()

        seed = Seed(
            seed_number="profile_daily_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/profile/daily",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        regular_race = Race(
            name="Regular",
            organizer_id=admin.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        daily_race = Race(
            name="Daily",
            organizer_id=admin.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 5, 5),
        )
        db.add_all([regular_race, daily_race])
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=regular_race.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=120000,
                ),
                Participant(
                    race_id=daily_race.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=130000,
                ),
            ]
        )
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/daily_splitter")
        assert response.status_code == 200
        stats = response.json()["stats"]
        assert stats["race_count"] == 1
        assert stats["daily_count"] == 1


@pytest.mark.asyncio
async def test_activity_emits_daily_participant_for_daily_seeds(test_client, async_session):
    """Daily Seed participations surface as ``daily_participant`` items so
    the frontend can deep-link to ``/daily/[date]`` and stop visually mixing
    them with regular race entries."""
    async with async_session() as db:
        player = User(
            twitch_id="daily_activity_user",
            twitch_username="daily_activity",
            api_token="daily_activity_token",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="daily_activity_org",
            twitch_username="system:daily",
            api_token="daily_activity_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add_all([player, organizer])
        await db.flush()

        # The conftest ``after_create`` listener auto-seeds a ``standard``
        # Pool row with ``config={"name": "Standard"}`` for every test DB,
        # so ``format_pool_display_name`` will return ``"Standard"`` here.
        seed = Seed(
            seed_number="daily_activity_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=3,
            folder_path="/fake/daily_activity",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        daily_race = Race(
            name="Daily 2026-04-29",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 4, 29),
        )
        db.add(daily_race)
        await db.flush()

        db.add(
            Participant(
                race_id=daily_race.id,
                user_id=player.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=180000,
                death_count=2,
            )
        )

        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/daily_activity/activity")
        assert response.status_code == 200
        data = response.json()

    types = [i["type"] for i in data["items"]]
    assert "daily_participant" in types
    # The same race must NOT also surface as a regular race_participant.
    assert "race_participant" not in types

    daily_item = next(i for i in data["items"] if i["type"] == "daily_participant")
    assert daily_item["daily_date"] == "2026-04-29"
    assert daily_item["pool_name"] == "standard"
    assert daily_item["pool_display_name"] == "Standard"
    assert daily_item["status"] == "finished"
    assert daily_item["placement"] == 1
    assert daily_item["total_participants"] == 1
    assert daily_item["igt_ms"] == 180000
    assert daily_item["death_count"] == 2


@pytest.mark.asyncio
async def test_traits_returns_progress_when_insufficient_races(test_client, async_session):
    """Traits endpoint returns scores=null with progress info when player has too few finishes."""
    async with async_session() as db:
        user = User(
            twitch_id="few_finishes",
            twitch_username="few_finishes",
            api_token="few_finishes_token",
            role=UserRole.USER,
            elo_races=4,
        )
        db.add(user)
        await db.flush()

        org = User(
            twitch_id="traits_org",
            twitch_username="traits_org",
            api_token="traits_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(org)
        await db.flush()

        seed = Seed(
            seed_number="traits_seed",
            pool_name="standard",
            graph_json={"nodes": {}, "total_layers": 1},
            total_layers=1,
            folder_path="/fake/traits",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # 2 finished races, 2 abandoned: below MIN_RACES_FOR_TRAITS (3) finishes
        for i, status in enumerate(
            [
                ParticipantStatus.FINISHED,
                ParticipantStatus.FINISHED,
                ParticipantStatus.ABANDONED,
                ParticipantStatus.ABANDONED,
            ]
        ):
            race = Race(
                name=f"Traits Race {i}",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
            )
            db.add(race)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    mod_token=f"traits_mod_{i}",
                    status=status,
                    igt_ms=1_000_000 + i * 100_000,
                    death_count=5 + i,
                )
            )

        # Add a PlayerTraitScores row with all zeros (as recompute would produce)
        from speedfog_racing.models import PlayerTraitScores

        db.add(
            PlayerTraitScores(
                user_id=user.id,
                rusher=0,
                cautious=0,
                resilient=0,
                rage_quitter=0,
                explorer=0,
                pathfinder=0,
                boss_slayer=0,
                dominant_trait=None,
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/few_finishes/traits")
        assert response.status_code == 200
        data = response.json()

        # scores should be null (all zeros hidden)
        assert data["scores"] is None
        assert data["dominant_trait"] is None
        assert data["dominant_description"] is None
        # Progress fields present
        assert data["finished_races"] == 2
        assert data["races_required"] == 3


async def test_user_profile_includes_weekly_block(test_client, sample_user):
    async with test_client as client:
        response = await client.get(f"/api/users/{sample_user.twitch_username}")
    assert response.status_code == 200
    data = response.json()

    assert "weekly" in data["stats"]
    weekly = data["stats"]["weekly"]
    assert isinstance(weekly["races"], list)
    assert isinstance(weekly["daily"], list)
    assert isinstance(weekly["solo"], list)
    assert isinstance(weekly["organized"], list)
    assert (
        len(weekly["races"])
        == len(weekly["daily"])
        == len(weekly["solo"])
        == len(weekly["organized"])
        == weekly["weeks_count"]
    )
    assert "capped" in weekly
