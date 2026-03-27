"""Tests for seed difficulty computation."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Seed, SeedStatus
from speedfog_racing.services.seed_difficulty import compute_seed_difficulty


class TestComputeSeedDifficulty:
    def test_empty_graph(self):
        """Empty nodes dict returns 0."""
        assert compute_seed_difficulty({"nodes": {}}) == 0.0

    def test_start_node_excluded(self):
        """Start nodes do not contribute to difficulty."""
        graph = {
            "nodes": {
                "chapel_start": {"type": "start", "tier": 3},
            }
        }
        assert compute_seed_difficulty(graph) == 0.0

    def test_single_legacy_dungeon(self):
        """Single legacy dungeon: weight 1.0 * tier^1.3."""
        graph = {
            "nodes": {
                "start": {"type": "start", "tier": 3},
                "stormveil": {"type": "legacy_dungeon", "tier": 5},
            }
        }
        expected = 1.0 * (5**1.3)
        assert compute_seed_difficulty(graph) == pytest.approx(expected, rel=1e-6)

    def test_boss_types_weighted_higher(self):
        """Boss nodes have higher weight than dungeons at the same tier."""
        graph_dungeon = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 10},
            }
        }
        graph_boss = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "major_boss", "tier": 10},
            }
        }
        assert compute_seed_difficulty(graph_boss) > compute_seed_difficulty(graph_dungeon)

    def test_higher_tier_increases_difficulty(self):
        """Higher tier nodes produce higher difficulty score."""
        graph_low = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 3},
            }
        }
        graph_high = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 15},
            }
        }
        assert compute_seed_difficulty(graph_high) > compute_seed_difficulty(graph_low)

    def test_more_nodes_increases_difficulty(self):
        """More non-start nodes produce higher total difficulty."""
        graph_small = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "mini_dungeon", "tier": 5},
            }
        }
        graph_large = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "mini_dungeon", "tier": 5},
                "b": {"type": "mini_dungeon", "tier": 5},
                "c": {"type": "mini_dungeon", "tier": 5},
            }
        }
        assert compute_seed_difficulty(graph_large) > compute_seed_difficulty(graph_small)

    def test_final_boss_highest_weight(self):
        """Final boss has the highest type weight."""
        graph = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "final_boss", "tier": 10},
            }
        }
        graph_major = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "major_boss", "tier": 10},
            }
        }
        assert compute_seed_difficulty(graph) > compute_seed_difficulty(graph_major)

    def test_realistic_seed(self):
        """Realistic seed with mixed types produces a positive score."""
        graph = {
            "nodes": {
                "start": {"type": "start", "tier": 3},
                "ld1": {"type": "legacy_dungeon", "tier": 5},
                "md1": {"type": "mini_dungeon", "tier": 4},
                "md2": {"type": "mini_dungeon", "tier": 7},
                "ba1": {"type": "boss_arena", "tier": 6},
                "mb1": {"type": "major_boss", "tier": 10},
                "mb2": {"type": "major_boss", "tier": 14},
                "fb": {"type": "final_boss", "tier": 18},
            }
        }
        score = compute_seed_difficulty(graph)
        assert score > 0
        # Sanity: a realistic seed should produce a score in the hundreds
        assert score > 50

    def test_non_dict_nodes_returns_zero(self):
        """Nodes as a list (legacy test fixtures) returns 0."""
        assert compute_seed_difficulty({"nodes": []}) == 0.0


@pytest.fixture
async def async_db():
    """Create async in-memory test database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class TestSeedDifficultyAtIngestion:
    """Verify seeds get difficulty_score populated during scan."""

    @pytest.mark.asyncio
    async def test_scanned_seed_has_difficulty_score(self, async_db: AsyncSession, tmp_path):
        """Seeds ingested via scan_pool should have difficulty_score > 0."""
        import json
        import zipfile

        from speedfog_racing.config import settings
        from speedfog_racing.services.seed_service import scan_pool

        # Create a fake seed zip
        graph = {
            "total_layers": 5,
            "nodes": {
                "start": {"type": "start", "tier": 3},
                "ld1": {"type": "legacy_dungeon", "tier": 8},
                "mb1": {"type": "major_boss", "tier": 12},
            },
        }
        pool_dir = tmp_path / "test_pool"
        pool_dir.mkdir()
        zip_path = pool_dir / "seed_abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("graph.json", json.dumps(graph))

        original_dir = settings.seeds_pool_dir
        settings.seeds_pool_dir = str(tmp_path)
        try:
            added = await scan_pool(async_db, "test_pool")
        finally:
            settings.seeds_pool_dir = original_dir

        assert added == 1

        seed = (
            await async_db.execute(select(Seed).where(Seed.seed_number == "abc123"))
        ).scalar_one()
        assert seed.difficulty_score > 0


class TestBackfillDifficultyScores:
    @pytest.mark.asyncio
    async def test_backfill_updates_zero_scores(self, async_db: AsyncSession):
        """Backfill should compute difficulty for seeds with score=0."""
        from speedfog_racing.services.seed_difficulty import backfill_difficulty_scores

        seed = Seed(
            seed_number="backfill1",
            pool_name="test",
            graph_json={
                "total_layers": 3,
                "nodes": {
                    "s": {"type": "start", "tier": 1},
                    "a": {"type": "legacy_dungeon", "tier": 10},
                },
            },
            total_layers=3,
            difficulty_score=0.0,
            folder_path="/fake/path.zip",
            status=SeedStatus.AVAILABLE,
        )
        async_db.add(seed)
        await async_db.commit()

        count = await backfill_difficulty_scores(async_db)
        assert count == 1

        await async_db.refresh(seed)
        assert seed.difficulty_score > 0

    @pytest.mark.asyncio
    async def test_backfill_skips_already_computed(self, async_db: AsyncSession):
        """Backfill should not recompute seeds that already have a score."""
        from speedfog_racing.services.seed_difficulty import backfill_difficulty_scores

        seed = Seed(
            seed_number="backfill2",
            pool_name="test",
            graph_json={
                "total_layers": 3,
                "nodes": {
                    "s": {"type": "start", "tier": 1},
                    "a": {"type": "legacy_dungeon", "tier": 10},
                },
            },
            total_layers=3,
            difficulty_score=99.9,
            folder_path="/fake/path.zip",
            status=SeedStatus.AVAILABLE,
        )
        async_db.add(seed)
        await async_db.commit()

        count = await backfill_difficulty_scores(async_db)
        assert count == 0

        await async_db.refresh(seed)
        assert seed.difficulty_score == pytest.approx(99.9)
