"""Seed pool management service."""

import json
import logging
import random
import tomllib
import uuid
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.models import Race, Seed, SeedStatus

logger = logging.getLogger(__name__)


def _read_graph_from_zip(zip_path: Path) -> dict[str, Any] | None:
    """Read graph.json from inside a seed zip file.

    Handles both root-level graph.json and nested */graph.json.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # Try root-level first
            if "graph.json" in names:
                result: dict[str, Any] = json.loads(zf.read("graph.json"))
                return result
            # Try nested (e.g., speedfog_abc123/graph.json)
            for name in names:
                parts = name.split("/")
                if len(parts) == 2 and parts[1] == "graph.json":
                    result = json.loads(zf.read(name))
                    return result
        logger.warning(f"No graph.json found in {zip_path}")
        return None
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to read graph.json from {zip_path}: {e}")
        return None


async def scan_pool(db: AsyncSession, pool_name: str = "standard") -> int:
    """Scan pool directory and sync with database.

    Looks for seed_*.zip files containing graph.json.
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

    for entry in sorted(pool_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.startswith("seed_") or not entry.name.endswith(".zip"):
            continue

        # Extract seed slug from filename (e.g., seed_a1b2c3d4.zip -> a1b2c3d4)
        seed_number = entry.name.removeprefix("seed_").removesuffix(".zip")
        if not seed_number:
            logger.warning(f"Invalid seed zip name: {entry.name}")
            continue

        # Check if already in database
        result = await db.execute(
            select(Seed).where(Seed.seed_number == seed_number, Seed.pool_name == pool_name)
        )
        if result.scalar_one_or_none():
            continue

        # Read graph.json from inside the zip
        graph_json = _read_graph_from_zip(entry)
        if graph_json is None:
            continue

        # Extract total_layers from graph
        total_layers = graph_json.get("total_layers", 0)
        if total_layers == 0:
            logger.warning(f"Missing total_layers in {entry}")

        # Create seed record
        seed = Seed(
            seed_number=seed_number,
            pool_name=pool_name,
            graph_json=graph_json,
            total_layers=total_layers,
            folder_path=str(entry),
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        added += 1
        logger.debug(f"Added seed {seed_number} from {pool_name}")

    await db.commit()
    logger.info(f"Pool '{pool_name}' scanned: {added} new seeds added")
    return added


async def get_available_seed(
    db: AsyncSession, pool_name: str = "standard", exclude_id: uuid.UUID | None = None
) -> Seed | None:
    """Get a random available seed from the pool.

    Args:
        db: Database session
        pool_name: Name of the pool
        exclude_id: Optional seed ID to exclude (e.g. current seed during re-roll)

    Returns:
        A random available Seed, or None if pool is exhausted
    """
    query = select(Seed).where(Seed.pool_name == pool_name, Seed.status == SeedStatus.AVAILABLE)
    if exclude_id is not None:
        query = query.where(Seed.id != exclude_id)
    result = await db.execute(query)
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


async def reroll_seed_for_race(db: AsyncSession, race: Race) -> Seed:
    """Re-roll the seed for a race, releasing the old one.

    Picks a new available seed from the same pool, excluding the current seed.

    Raises:
        ValueError: If no other seeds are available in the pool
    """
    old_seed = race.seed
    if old_seed is None:
        raise ValueError("Race has no seed assigned")

    pool_name = old_seed.pool_name

    new_seed = await get_available_seed(db, pool_name, exclude_id=old_seed.id)
    if new_seed is None:
        raise ValueError(f"No available seeds in pool '{pool_name}'")

    # Release old seed
    old_seed.status = SeedStatus.AVAILABLE

    # Assign new seed
    new_seed.status = SeedStatus.CONSUMED
    race.seed_id = new_seed.id
    race.seed = new_seed

    logger.info(
        f"Re-rolled seed for race {race.id}: {old_seed.seed_number} -> {new_seed.seed_number}"
    )
    return new_seed


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
            stats[pool_name] = {"available": 0, "consumed": 0, "discarded": 0}
        stats[pool_name][status.value] = count

    return stats


async def discard_pool(db: AsyncSession, pool_name: str) -> int:
    """Mark all AVAILABLE seeds in a pool as DISCARDED.

    Args:
        db: Database session
        pool_name: Name of the pool to discard

    Returns:
        Number of seeds discarded
    """
    result = await db.execute(
        update(Seed)
        .where(Seed.pool_name == pool_name, Seed.status == SeedStatus.AVAILABLE)
        .values(status=SeedStatus.DISCARDED)
    )
    await db.commit()
    count: int = result.rowcount  # type: ignore[attr-defined]
    logger.info(f"Discarded {count} seeds from pool '{pool_name}'")
    return count


def get_pool_config(pool_name: str) -> dict[str, Any] | None:
    """Read curated settings from a pool's config.toml."""
    config_file = Path(settings.seeds_pool_dir) / pool_name / "config.toml"
    if not config_file.exists():
        return None

    try:
        with open(config_file, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning(f"Failed to read {config_file}", exc_info=True)
        return None

    display = data.get("display", {})
    requirements = data.get("requirements", {})
    structure = data.get("structure", {})
    care_package = data.get("care_package", {})
    item_randomizer = data.get("item_randomizer", {})
    starting_items_raw = data.get("starting_items", {})

    # Build human-readable starting items list
    item_names = {
        "academy_key": "Academy Key",
        "pureblood_medal": "Pureblood Medal",
        "drawing_room_key": "Drawing Room Key",
        "lantern": "Lantern",
        "great_runes": "Great Runes",
        "whetblades": "Whetblades",
        "omother": "O, Mother",
        "welldepthskey": "Well Depths Key",
        "gaolupperlevelkey": "Gaol Upper Level Key",
        "gaollowerlevelkey": "Gaol Lower Level Key",
        "holeladennecklace": "Hole-Laden Necklace",
        "messmerskindling": "Messmer's Kindling",
    }
    starting_items: list[str] = []
    for key, label in item_names.items():
        if starting_items_raw.get(key):
            starting_items.append(label)
    if tp := starting_items_raw.get("talisman_pouches"):
        starting_items.append(f"{tp} Talisman Pouches" if tp > 1 else "1 Talisman Pouch")
    if gs := starting_items_raw.get("golden_seeds"):
        starting_items.append(f"{gs} Golden Seeds")
    if st := starting_items_raw.get("sacred_tears"):
        starting_items.append(f"{st} Sacred Tears")
    if sr := starting_items_raw.get("starting_runes"):
        starting_items.append(f"{sr // 1000}k Runes" if sr >= 1000 else f"{sr} Runes")
    if lt := starting_items_raw.get("larval_tears"):
        starting_items.append(f"{lt} Larval Tears" if lt > 1 else "1 Larval Tear")

    # Build care package items list
    care_package_items: list[str] = []
    if care_package.get("enabled"):
        cp_fields = [
            ("weapons", "Weapons"),
            ("shields", "Shields"),
            ("catalysts", "Catalysts"),
            ("talismans", "Talismans"),
            ("sorceries", "Sorceries"),
            ("incantations", "Incantations"),
            ("crystal_tears", "Crystal Tears"),
            ("ashes_of_war", "Ashes of War"),
        ]
        for key, label in cp_fields:
            if count := care_package.get(key):
                care_package_items.append(f"{count} {label}")
        armor_count = sum(
            care_package.get(k, 0) for k in ("head_armor", "body_armor", "arm_armor", "leg_armor")
        )
        if armor_count:
            care_package_items.append(f"{armor_count} Armor pieces")

    return {
        "type": display.get("type", "race"),
        "estimated_duration": display.get("estimated_duration"),
        "description": display.get("description") or None,
        "legacy_dungeons": requirements.get("legacy_dungeons"),
        "final_tier": structure.get("final_tier"),
        "min_layers": structure.get("min_layers"),
        "max_layers": structure.get("max_layers"),
        "starting_items": starting_items or None,
        "care_package": care_package.get("enabled"),
        "weapon_upgrade": care_package.get("weapon_upgrade"),
        "care_package_items": care_package_items or None,
        "items_randomized": item_randomizer.get("enabled"),
        "auto_upgrade_weapons": item_randomizer.get("auto_upgrade_weapons"),
        "remove_requirements": item_randomizer.get("remove_requirements"),
    }


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
