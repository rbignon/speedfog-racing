"""Test seed pool service."""

import json
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Pool, Race, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.seed_service import (
    _normalize_pool_config,
    assign_seed_to_race,
    discard_pool,
    get_available_seed,
    get_pool_config,
    get_pool_stats,
    reroll_seed_for_race,
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


def _create_seed_zip(pool_dir: Path, name: str, graph: dict) -> Path:
    """Create a seed zip file with graph.json inside a top-level directory."""
    zip_path = pool_dir / f"{name}.zip"
    slug = name.removeprefix("seed_")
    top_dir = f"speedfog_{slug}"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{top_dir}/graph.json", json.dumps(graph))
        zf.writestr(f"{top_dir}/lib/speedfog_racing.dll", "mock dll")
    return zip_path


@pytest.fixture
def seed_pool_dir():
    """Create a temporary seed pool directory with zip files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()

        _create_seed_zip(pool_dir, "seed_abc123", {"total_layers": 10, "nodes": []})
        _create_seed_zip(pool_dir, "seed_def456", {"total_layers": 12, "nodes": []})

        # Create a config so scan_pool picks up the normalized display metadata.
        (pool_dir / "config.toml").write_text('[display]\nname = "Standard"\ntype = "race"\n')

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
        assert seed_numbers == {"abc123", "def456"}

        for seed in seeds:
            assert seed.pool_name == "standard"
            assert seed.status == SeedStatus.AVAILABLE
            assert seed.total_layers in (10, 12)
            assert seed.folder_path.endswith(".zip")


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


@pytest.mark.asyncio
async def test_scan_pool_reads_graph_from_zip(async_db, seed_pool_dir):
    """Scanning reads graph.json from inside zip files."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        result = await async_db.execute(select(Seed).where(Seed.seed_number == "abc123"))
        seed = result.scalar_one()

        assert seed.graph_json["total_layers"] == 10
        assert seed.graph_json["nodes"] == []


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
        assert stats["standard"]["discarded"] == 0


@pytest.mark.asyncio
async def test_get_pool_stats_with_discarded(async_db):
    """get_pool_stats includes discarded count."""
    seed = Seed(
        seed_number="disc001",
        pool_name="standard",
        graph_json={"total_layers": 5},
        total_layers=5,
        folder_path="/test/seed_disc001.zip",
        status=SeedStatus.DISCARDED,
    )
    async_db.add(seed)
    await async_db.flush()

    stats = await get_pool_stats(async_db)
    assert "standard" in stats
    assert stats["standard"]["discarded"] == 1
    assert stats["standard"]["available"] == 0
    assert stats["standard"]["consumed"] == 0


@pytest.mark.asyncio
async def test_discard_pool(async_db, seed_pool_dir):
    """discard_pool marks AVAILABLE and CONSUMED seeds as DISCARDED."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        # Mark one seed as consumed first
        result = await async_db.execute(select(Seed).limit(1))
        seed = result.scalar_one()
        seed.status = SeedStatus.CONSUMED
        await async_db.flush()
        await async_db.commit()

        # Discard the pool (affects both AVAILABLE and CONSUMED)
        count = await discard_pool(async_db, "standard")
        assert count == 2

        stats = await get_pool_stats(async_db)
        assert stats["standard"]["available"] == 0
        assert stats["standard"]["consumed"] == 0
        assert stats["standard"]["discarded"] == 2


@pytest.mark.asyncio
async def test_discard_pool_empty(async_db):
    """discard_pool returns 0 when no available seeds."""
    count = await discard_pool(async_db, "nonexistent")
    assert count == 0


@pytest.mark.asyncio
async def test_reroll_after_discard_keeps_seed_discarded(async_db):
    """Re-rolling after pool discard keeps the old seed DISCARDED, not AVAILABLE."""
    # Old seed (consumed by a race, then pool discarded → DISCARDED)
    old_seed = Seed(
        seed_number="old001",
        pool_name="standard",
        graph_json={"total_layers": 5},
        total_layers=5,
        folder_path="/test/seed_old001.zip",
        status=SeedStatus.DISCARDED,
    )
    # New seed from regenerated pool
    new_seed = Seed(
        seed_number="new001",
        pool_name="standard",
        graph_json={"total_layers": 8},
        total_layers=8,
        folder_path="/test/seed_new001.zip",
        status=SeedStatus.AVAILABLE,
    )
    async_db.add_all([old_seed, new_seed])
    await async_db.flush()

    user = User(twitch_id="u1", twitch_username="user1", role=UserRole.USER)
    async_db.add(user)
    await async_db.flush()

    race = Race(name="Test", organizer_id=user.id, seed_id=old_seed.id)
    race.seed = old_seed
    async_db.add(race)
    await async_db.flush()

    # Re-roll: old seed should stay DISCARDED, new seed becomes CONSUMED
    result = await reroll_seed_for_race(async_db, race)

    assert result.id == new_seed.id
    assert result.status == SeedStatus.CONSUMED
    assert old_seed.status == SeedStatus.DISCARDED  # NOT AVAILABLE


# =============================================================================
# Reporting Tests
# =============================================================================

# These tests use isolated fixtures with NullPool to avoid async teardown issues.


@pytest.fixture
async def reporting_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def reporting_session(reporting_engine):
    return async_sessionmaker(reporting_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def reporter_user(reporting_session):
    async with reporting_session() as db:
        user = User(
            twitch_id="reporter1",
            twitch_username="reporter",
            api_token="reporter_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def _make_seed(
    pool_name: str = "standard",
    status: SeedStatus = SeedStatus.AVAILABLE,
    seed_number: str | None = None,
) -> Seed:
    return Seed(
        seed_number=seed_number or uuid.uuid4().hex[:8],
        pool_name=pool_name,
        graph_json={"nodes": [], "edges": [], "total_layers": 5},
        total_layers=5,
        difficulty_score=1.0,
        folder_path="/tmp/fake",
        status=status,
    )


@pytest.mark.asyncio
async def test_reported_seeds_excluded_from_available(reporting_session):
    """REPORTED seeds must not be returned by get_available_seed."""
    async with reporting_session() as db:
        seed = _make_seed(status=SeedStatus.REPORTED)
        db.add(seed)
        await db.commit()

    async with reporting_session() as db:
        result = await get_available_seed(db, pool_name="standard")

    assert result is None


@pytest.mark.asyncio
async def test_reroll_with_report(reporting_session, reporter_user):
    """Re-rolling with reporter_id sets old seed to REPORTED with correct fields."""
    async with reporting_session() as db:
        old_seed = _make_seed(seed_number="oldseed1", status=SeedStatus.CONSUMED)
        new_seed = _make_seed(seed_number="newseed1", status=SeedStatus.AVAILABLE)
        db.add(old_seed)
        db.add(new_seed)
        await db.commit()
        await db.refresh(old_seed)
        await db.refresh(new_seed)

        race = Race(name="Test Race", organizer_id=reporter_user.id, seed_id=old_seed.id)
        race.seed = old_seed
        db.add(race)
        await db.commit()
        await db.refresh(race)

        before = datetime.now(UTC)
        result = await reroll_seed_for_race(
            db,
            race,
            reporter_id=reporter_user.id,
            report_reason="Bad seed",
        )
        after = datetime.now(UTC)
        await db.commit()
        await db.refresh(old_seed)

        assert result.seed_number == "newseed1"
        assert old_seed.status == SeedStatus.REPORTED
        assert old_seed.reported_by_id == reporter_user.id
        assert old_seed.reported_reason == "Bad seed"
        assert old_seed.reported_at is not None
        reported_at = old_seed.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=UTC)
        assert before <= reported_at <= after


@pytest.mark.asyncio
async def test_reroll_without_report(reporting_session):
    """Re-rolling without reporter_id sets old seed back to AVAILABLE (backward compat)."""
    async with reporting_session() as db:
        organizer = User(twitch_id="org1", twitch_username="organizer", role=UserRole.ORGANIZER)
        db.add(organizer)
        old_seed = _make_seed(seed_number="oldseed2", status=SeedStatus.CONSUMED)
        new_seed = _make_seed(seed_number="newseed2", status=SeedStatus.AVAILABLE)
        db.add(old_seed)
        db.add(new_seed)
        await db.commit()
        await db.refresh(organizer)
        await db.refresh(old_seed)
        await db.refresh(new_seed)

        race = Race(name="Test Race 2", organizer_id=organizer.id, seed_id=old_seed.id)
        race.seed = old_seed
        db.add(race)
        await db.commit()
        await db.refresh(race)

        result = await reroll_seed_for_race(db, race)
        await db.commit()
        await db.refresh(old_seed)

        assert result.seed_number == "newseed2"
        assert old_seed.status == SeedStatus.AVAILABLE
        assert old_seed.reported_by_id is None
        assert old_seed.reported_reason is None
        assert old_seed.reported_at is None


@pytest.mark.asyncio
async def test_discard_pool_includes_reported(reporting_session):
    """discard_pool must mark REPORTED seeds as DISCARDED."""
    async with reporting_session() as db:
        reported_seed = _make_seed(seed_number="rep1", status=SeedStatus.REPORTED)
        available_seed = _make_seed(seed_number="avail1", status=SeedStatus.AVAILABLE)
        db.add(reported_seed)
        db.add(available_seed)
        await db.commit()
        reported_id = reported_seed.id
        available_id = available_seed.id

    async with reporting_session() as db:
        count = await discard_pool(db, "standard")

    assert count == 2

    async with reporting_session() as db:
        result = await db.execute(select(Seed).where(Seed.id.in_([reported_id, available_id])))
        seeds = {s.id: s for s in result.scalars().all()}

    assert seeds[reported_id].status == SeedStatus.DISCARDED
    assert seeds[available_id].status == SeedStatus.DISCARDED


@pytest.mark.asyncio
async def test_get_pool_stats_includes_reported(reporting_session):
    """get_pool_stats must include a 'reported' key in the stats dict."""
    async with reporting_session() as db:
        db.add(_make_seed(status=SeedStatus.AVAILABLE))
        db.add(_make_seed(status=SeedStatus.REPORTED))
        await db.commit()

    async with reporting_session() as db:
        stats = await get_pool_stats(db)

    assert "standard" in stats
    pool = stats["standard"]
    assert "reported" in pool
    assert pool["reported"] == 1
    assert pool["available"] == 1


# =============================================================================
# Pool table Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_pool_upserts_pool_row(async_db, seed_pool_dir):
    """scan_pool creates a Pool row and fills config from the TOML."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

    result = await async_db.execute(select(Pool).where(Pool.name == "standard"))
    pool = result.scalar_one()
    assert pool.enabled is True
    assert pool.config["name"] == "Standard"
    assert pool.config["type"] == "race"
    assert pool.last_scanned_at is not None


@pytest.mark.asyncio
async def test_scan_pool_preserves_enabled_flag(async_db, seed_pool_dir):
    """Re-scanning a pool refreshes config but leaves enabled untouched."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir
        await scan_pool(async_db, "standard")

        pool = (await async_db.execute(select(Pool).where(Pool.name == "standard"))).scalar_one()
        pool.enabled = False
        await async_db.commit()

        # Re-scan should not flip enabled back to True
        await scan_pool(async_db, "standard")
        await async_db.refresh(pool)
        assert pool.enabled is False


@pytest.mark.asyncio
async def test_get_pool_config_reads_from_db(async_db):
    """get_pool_config returns the cached config dict from pools.config."""
    async_db.add(Pool(name="demo", enabled=True, config={"name": "Demo", "type": "race"}))
    await async_db.commit()

    config = await get_pool_config(async_db, "demo")
    assert config == {"name": "Demo", "type": "race"}

    missing = await get_pool_config(async_db, "ghost")
    assert missing is None


# =============================================================================
# Normalize Tests (layers_count + legacy min/max_layers compat)
# =============================================================================


def test_normalize_pool_config_uses_layers_count():
    """New-style configs expose layers_count and drop the legacy range."""
    out = _normalize_pool_config(
        {
            "structure": {"layers_count": 30},
            "requirements": {"major_bosses": 10},
        }
    )
    assert out["layers_count"] == 30
    assert "min_layers" not in out
    assert "max_layers" not in out


def test_normalize_pool_config_falls_back_to_max_layers():
    """Legacy configs without layers_count derive it from max_layers."""
    out = _normalize_pool_config(
        {
            "structure": {"min_layers": 25, "max_layers": 30},
            "requirements": {"major_bosses": 10},
        }
    )
    assert out["layers_count"] == 30


def test_normalize_pool_config_layers_count_overrides_legacy():
    """When both are present, layers_count wins (legacy is ignored)."""
    out = _normalize_pool_config(
        {
            "structure": {"layers_count": 35, "min_layers": 25, "max_layers": 30},
            "requirements": {"major_bosses": 10},
        }
    )
    assert out["layers_count"] == 35


def test_normalize_pool_config_major_boss_ratio_uses_layers_count():
    """major_boss_ratio bucket is computed from major_bosses / layers_count."""
    high = _normalize_pool_config(
        {"structure": {"layers_count": 20}, "requirements": {"major_bosses": 8}}
    )
    medium = _normalize_pool_config(
        {"structure": {"layers_count": 30}, "requirements": {"major_bosses": 8}}
    )
    low = _normalize_pool_config(
        {"structure": {"layers_count": 100}, "requirements": {"major_bosses": 10}}
    )
    assert high["major_boss_ratio"] == "High"  # 0.40
    assert medium["major_boss_ratio"] == "Medium"  # 0.27
    assert low["major_boss_ratio"] == "Low"  # 0.10


def test_pool_config_schema_derives_layers_count_from_legacy_json():
    """Stored Pool.config rows from before the refactor still populate layers_count."""
    from speedfog_racing.schemas import PoolConfig

    cfg = PoolConfig.model_validate({"min_layers": 25, "max_layers": 30})
    assert cfg.layers_count == 30

    # New-style rows pass through unchanged.
    cfg2 = PoolConfig.model_validate({"layers_count": 35})
    assert cfg2.layers_count == 35
