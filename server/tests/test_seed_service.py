"""Test seed pool service."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Race, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.seed_service import (
    assign_seed_to_race,
    get_available_seed,
    get_pool_stats,
    scan_pool,
)


@pytest.fixture
async def async_db():
    """Create async test database session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def seed_pool_dir():
    """Create a temporary seed pool directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()

        # Create seed_123456
        seed1_dir = pool_dir / "seed_123456"
        seed1_dir.mkdir()
        (seed1_dir / "graph.json").write_text(json.dumps({"total_layers": 10, "nodes": []}))

        # Create seed_789012
        seed2_dir = pool_dir / "seed_789012"
        seed2_dir.mkdir()
        (seed2_dir / "graph.json").write_text(json.dumps({"total_layers": 12, "nodes": []}))

        # Create a non-seed directory (should be ignored)
        (pool_dir / "config.toml").write_text("[pool]\nname = 'standard'")

        yield tmpdir


@pytest.fixture
def empty_pool_dir():
    """Create an empty temporary seed pool directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()
        yield tmpdir


# =============================================================================
# Scanner Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_empty_pool(async_db, empty_pool_dir):
    """Scanning an empty pool returns 0."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = empty_pool_dir
        added = await scan_pool(async_db, "standard")
        assert added == 0


@pytest.mark.asyncio
async def test_scan_nonexistent_pool(async_db):
    """Scanning a nonexistent pool returns 0 without error."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = "/nonexistent/path"
        added = await scan_pool(async_db, "standard")
        assert added == 0


@pytest.mark.asyncio
async def test_scan_pool_creates_seeds(async_db, seed_pool_dir):
    """Scanning a pool creates Seed records in the database."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        added = await scan_pool(async_db, "standard")

        assert added == 2

        # Verify seeds in database
        result = await async_db.execute(select(Seed))
        seeds = list(result.scalars().all())

        assert len(seeds) == 2
        seed_numbers = {s.seed_number for s in seeds}
        assert seed_numbers == {123456, 789012}

        for seed in seeds:
            assert seed.pool_name == "standard"
            assert seed.status == SeedStatus.AVAILABLE
            assert seed.total_layers in (10, 12)


@pytest.mark.asyncio
async def test_scan_pool_skips_existing(async_db, seed_pool_dir):
    """Re-scanning a pool skips seeds already in database."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir

        # First scan
        added1 = await scan_pool(async_db, "standard")
        assert added1 == 2

        # Second scan - should skip existing
        added2 = await scan_pool(async_db, "standard")
        assert added2 == 0

        # Still only 2 seeds in database
        result = await async_db.execute(select(Seed))
        seeds = list(result.scalars().all())
        assert len(seeds) == 2


# =============================================================================
# Assignment Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_available_seed_returns_seed(async_db, seed_pool_dir):
    """get_available_seed returns an available seed."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        seed = await get_available_seed(async_db, "standard")
        assert seed is not None
        assert seed.status == SeedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_get_available_seed_returns_none_when_exhausted(async_db):
    """get_available_seed returns None when no seeds available."""
    seed = await get_available_seed(async_db, "standard")
    assert seed is None


@pytest.mark.asyncio
async def test_assign_seed_to_race(async_db, seed_pool_dir):
    """assign_seed_to_race marks seed as consumed and links to race."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        # Create a user and race
        user = User(
            twitch_id="123",
            twitch_username="testuser",
            role=UserRole.USER,
        )
        async_db.add(user)
        await async_db.flush()

        race = Race(name="Test Race", organizer_id=user.id)
        async_db.add(race)
        await async_db.flush()

        # Assign seed
        seed = await assign_seed_to_race(async_db, race, "standard")

        assert seed.status == SeedStatus.CONSUMED
        assert race.seed_id == seed.id


@pytest.mark.asyncio
async def test_assign_seed_raises_when_exhausted(async_db):
    """assign_seed_to_race raises ValueError when no seeds available."""
    # Create a user and race
    user = User(
        twitch_id="123",
        twitch_username="testuser",
        role=UserRole.USER,
    )
    async_db.add(user)
    await async_db.flush()

    race = Race(name="Test Race", organizer_id=user.id)
    async_db.add(race)
    await async_db.flush()

    with pytest.raises(ValueError, match="No available seeds"):
        await assign_seed_to_race(async_db, race, "standard")


# =============================================================================
# Stats Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_pool_stats_empty(async_db):
    """get_pool_stats returns empty dict when no seeds."""
    stats = await get_pool_stats(async_db)
    assert stats == {}


@pytest.mark.asyncio
async def test_get_pool_stats_with_seeds(async_db, seed_pool_dir):
    """get_pool_stats returns correct counts."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        # Mark one seed as consumed
        result = await async_db.execute(select(Seed).limit(1))
        seed = result.scalar_one()
        seed.status = SeedStatus.CONSUMED
        await async_db.flush()

        stats = await get_pool_stats(async_db)

        assert "standard" in stats
        assert stats["standard"]["available"] == 1
        assert stats["standard"]["consumed"] == 1
