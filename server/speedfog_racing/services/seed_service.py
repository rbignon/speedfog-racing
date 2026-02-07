"""Seed pool management service."""

import json
import logging
import random
import tomllib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.models import Race, Seed, SeedStatus

logger = logging.getLogger(__name__)


async def scan_pool(db: AsyncSession, pool_name: str = "standard") -> int:
    """Scan pool directory and sync with database.

    Looks for seed_* directories containing graph.json files.
    Creates Seed records for new seeds, skips existing ones.

    Args:
        db: Database session
        pool_name: Name of the pool to scan (subdirectory of seeds_pool_dir)

    Returns:
        Number of newly added seeds
    """
    pool_dir = Path(settings.seeds_pool_dir) / pool_name

    if not pool_dir.exists():
        logger.warning(f"Pool directory does not exist: {pool_dir}")
        return 0

    added = 0

    for seed_dir in sorted(pool_dir.iterdir()):
        if not seed_dir.is_dir():
            continue
        if not seed_dir.name.startswith("seed_"):
            continue

        # Extract seed number from directory name (e.g., seed_123456 -> 123456)
        try:
            seed_number = int(seed_dir.name.split("_")[1])
        except (IndexError, ValueError):
            logger.warning(f"Invalid seed directory name: {seed_dir.name}")
            continue

        # Check if already in database
        result = await db.execute(
            select(Seed).where(Seed.seed_number == seed_number, Seed.pool_name == pool_name)
        )
        if result.scalar_one_or_none():
            continue

        # Load graph.json
        graph_file = seed_dir / "graph.json"
        if not graph_file.exists():
            logger.warning(f"Missing graph.json in {seed_dir}")
            continue

        try:
            with open(graph_file) as f:
                graph_json = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {graph_file}: {e}")
            continue

        # Extract total_layers from graph
        total_layers = graph_json.get("total_layers", 0)
        if total_layers == 0:
            logger.warning(f"Missing total_layers in {graph_file}")

        # Create seed record
        seed = Seed(
            seed_number=seed_number,
            pool_name=pool_name,
            graph_json=graph_json,
            total_layers=total_layers,
            folder_path=str(seed_dir),
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        added += 1
        logger.debug(f"Added seed {seed_number} from {pool_name}")

    await db.commit()
    logger.info(f"Pool '{pool_name}' scanned: {added} new seeds added")
    return added


async def get_available_seed(db: AsyncSession, pool_name: str = "standard") -> Seed | None:
    """Get a random available seed from the pool.

    Args:
        db: Database session
        pool_name: Name of the pool

    Returns:
        A random available Seed, or None if pool is exhausted
    """
    result = await db.execute(
        select(Seed).where(Seed.pool_name == pool_name, Seed.status == SeedStatus.AVAILABLE)
    )
    available_seeds = list(result.scalars().all())

    if not available_seeds:
        return None

    return random.choice(available_seeds)


async def assign_seed_to_race(db: AsyncSession, race: Race, pool_name: str = "standard") -> Seed:
    """Assign an available seed to a race.

    Marks the seed as consumed and sets race.seed_id.

    Args:
        db: Database session
        race: Race to assign seed to
        pool_name: Name of the pool to pick from

    Returns:
        The assigned Seed

    Raises:
        ValueError: If no seeds are available in the pool
    """
    seed = await get_available_seed(db, pool_name)

    if seed is None:
        raise ValueError(f"No available seeds in pool '{pool_name}'")

    seed.status = SeedStatus.CONSUMED
    race.seed_id = seed.id
    race.seed = seed

    logger.info(f"Assigned seed {seed.seed_number} to race {race.id}")
    return seed


async def get_pool_stats(db: AsyncSession) -> dict[str, dict[str, int]]:
    """Get availability statistics for all pools.

    Returns:
        Dict mapping pool names to {"available": N, "consumed": M}
    """
    result = await db.execute(
        select(Seed.pool_name, Seed.status, func.count(Seed.id)).group_by(
            Seed.pool_name, Seed.status
        )
    )

    stats: dict[str, dict[str, int]] = {}

    for pool_name, status, count in result:
        if pool_name not in stats:
            stats[pool_name] = {"available": 0, "consumed": 0}
        stats[pool_name][status.value] = count

    return stats


def get_pool_metadata(seeds_pool_dir: str) -> dict[str, dict[str, str | None]]:
    """Read display metadata from pool config.toml files.

    Scans subdirectories of seeds_pool_dir for config.toml files and extracts
    the [display] section from each.

    Returns:
        Dict mapping pool names to {"estimated_duration": ..., "description": ...}
    """
    pool_dir = Path(seeds_pool_dir)
    if not pool_dir.exists():
        return {}

    metadata: dict[str, dict[str, str | None]] = {}

    for subdir in pool_dir.iterdir():
        if not subdir.is_dir():
            continue
        config_file = subdir / "config.toml"
        if not config_file.exists():
            continue
        try:
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
            display = data.get("display", {})
            metadata[subdir.name] = {
                "estimated_duration": display.get("estimated_duration"),
                "description": display.get("description"),
            }
        except (OSError, tomllib.TOMLDecodeError):
            logger.warning(f"Failed to read config.toml from {subdir}", exc_info=True)

    return metadata
