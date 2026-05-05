"""Tests for user pool stats endpoint."""

import os
from datetime import date

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
        # Training seed for standard pool (pool_name has "training_" prefix)
        seed_training_std = Seed(
            seed_number="tr_std_001",
            pool_name="training_standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=5,
            folder_path="/fake/training_standard",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([seed_std, seed_sprint, seed_training_std])
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

        # 1 finished training on training_standard (should merge with "standard")
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seed_training_std.id,
                status=TrainingSessionStatus.FINISHED,
                igt_ms=100000,
                death_count=3,
            )
        )

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

        # 1 active training on training_standard (should NOT count)
        db.add(
            TrainingSession(
                user_id=player.id,
                seed_id=seed_training_std.id,
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
        assert std_race["best_time_ms"] == 120000
        assert "avg_time_ms" not in std_race
        assert "avg_deaths" not in std_race

        # Standard training stats
        std_training = pools[0]["training"]
        assert std_training["runs"] == 1
        assert std_training["best_time_ms"] == 100000
        assert "avg_time_ms" not in std_training
        assert "avg_deaths" not in std_training

        assert pools[0]["total_runs"] == 3

        # Sprint race stats
        spr_race = pools[1]["race"]
        assert spr_race["runs"] == 1
        assert spr_race["best_time_ms"] == 60000
        assert "avg_time_ms" not in spr_race
        assert "avg_deaths" not in spr_race

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


@pytest.mark.asyncio
async def test_pool_stats_excludes_daily_seeds(test_client, async_session):
    """Finished Daily Seed participations don't show up in per-mode pool stats.

    Daily Seeds are a community challenge format (no ELO) and bucketing
    them under their underlying pool would silently inflate per-mode stats.
    """
    async with async_session() as db:
        player = User(
            twitch_id="daily_only_player",
            twitch_username="daily_only_player",
            api_token="daily_only_token",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="daily_only_org",
            twitch_username="system:daily",
            api_token="daily_only_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add_all([player, organizer])
        await db.flush()

        seed = Seed(
            seed_number="daily_only_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=5,
            folder_path="/fake/daily_only",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Finished Daily Seed participation, the user's only race activity.
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
                igt_ms=200000,
                death_count=4,
            )
        )

        await db.commit()

    async with test_client as client:
        response = await client.get("/api/users/daily_only_player/pool-stats")
        assert response.status_code == 200
        data = response.json()
        # The daily-only finish must not surface as a "standard" pool entry.
        assert data["pools"] == []


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
        assert std["training"]["best_time_ms"] == 100000
        assert "avg_time_ms" not in std["training"]
        assert "avg_deaths" not in std["training"]
