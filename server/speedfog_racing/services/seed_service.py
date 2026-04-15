"""Seed pool management service."""

import json
import logging
import random
import tomllib
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.models import Pool, Race, Seed, SeedStatus
from speedfog_racing.services.seed_difficulty import compute_seed_difficulty

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


_VALID_BOSS_MODES = {"none", "minor", "all"}


def _normalize_randomize_bosses(value: Any) -> str | None:
    """Normalize randomize_bosses from bool (legacy) or str to enum string."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "all" if value else "none"
    result = str(value)
    if result not in _VALID_BOSS_MODES:
        logger.warning(f"Invalid randomize_bosses value: {result!r}, defaulting to 'none'")
        return "none"
    return result


def _normalize_pool_config(data: dict[str, Any]) -> dict[str, Any]:
    """Turn a parsed config.toml dict into the curated pool config payload.

    The returned dict is stored on ``Pool.config`` and consumed by the
    ``/api/pools`` endpoint + ``PoolConfig`` schema.
    """
    display = data.get("display", {})
    requirements = data.get("requirements", {})
    structure = data.get("structure", {})
    care_package = data.get("care_package", {})
    item_randomizer = data.get("item_randomizer", {})
    enemy = data.get("enemy", {})
    starting_items_raw = data.get("starting_items", {})

    # Build starting upgrades (quantified resources that affect progression)
    starting_upgrades: list[str] = []
    if tp := starting_items_raw.get("talisman_pouches"):
        starting_upgrades.append(f"{tp} Talisman Pouches" if tp > 1 else "1 Talisman Pouch")
    if gs := starting_items_raw.get("golden_seeds"):
        starting_upgrades.append(f"{gs} Golden Seeds")
    if st := starting_items_raw.get("sacred_tears"):
        starting_upgrades.append(f"{st} Sacred Tears")
    if lt := starting_items_raw.get("larval_tears"):
        starting_upgrades.append(f"{lt} Larval Tears" if lt > 1 else "1 Larval Tear")

    starting_runes = starting_items_raw.get("starting_runes")

    # Build starting items (utility items, excluding anti-softlock keys)
    utility_items = {
        "lantern": "Lantern",
        "spirit_calling_bell": "Spirit Calling Bell",
        "physick_flask": "Physick Flask",
        "great_runes": "Restored Great Runes",
        "whetblades": "Whetblades",
    }
    starting_items: list[str] = []
    for key, label in utility_items.items():
        if starting_items_raw.get(key):
            starting_items.append(label)
    if sk := starting_items_raw.get("stonesword_keys"):
        starting_items.append(f"{sk} Stonesword Keys" if sk > 1 else "1 Stonesword Key")

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

    # Compute major boss density from fixed count + layer range
    major_bosses = requirements.get("major_bosses")
    min_layers = structure.get("min_layers")
    max_layers = structure.get("max_layers")
    if major_bosses and min_layers and max_layers:
        mbr = major_bosses / ((min_layers + max_layers) / 2)
        major_boss_label = "High" if mbr >= 0.35 else ("Medium" if mbr >= 0.20 else "Low")
    else:
        major_boss_label = None

    # Derive difficulty curve label from tier_curve + tier_curve_exponent
    tier_curve = structure.get("tier_curve", "linear")
    tier_curve_exponent = structure.get("tier_curve_exponent", 1.0)
    if tier_curve == "power":
        if tier_curve_exponent > 1.0:
            difficulty_curve_label = "Late spike"
        elif tier_curve_exponent < 1.0:
            difficulty_curve_label = "Early spike"
        else:
            difficulty_curve_label = "Linear"
    else:
        difficulty_curve_label = "Linear"

    return {
        "name": display.get("name"),
        "type": display.get("type", "race"),
        "sort_order": display.get("sort_order", 99),
        "estimated_duration": display.get("estimated_duration"),
        "description": display.get("description") or None,
        "final_tier": structure.get("final_tier"),
        "min_layers": structure.get("min_layers"),
        "max_layers": structure.get("max_layers"),
        "starting_runes": starting_runes,
        "starting_upgrades": starting_upgrades or None,
        "starting_items": starting_items or None,
        "care_package": care_package.get("enabled"),
        "weapon_upgrade": care_package.get("weapon_upgrade"),
        "care_package_items": care_package_items or None,
        "items_randomized": item_randomizer.get("enabled"),
        "auto_upgrade_weapons": item_randomizer.get("auto_upgrade_weapons"),
        "remove_requirements": item_randomizer.get("remove_requirements"),
        "major_boss_ratio": major_boss_label,
        "randomize_bosses": _normalize_randomize_bosses(enemy.get("randomize_bosses")),
        "difficulty_curve": difficulty_curve_label,
        "nerf_gargoyles": item_randomizer.get("nerf_gargoyles"),
        "nerf_malenia": item_randomizer.get("nerf_malenia"),
        "allcraft": item_randomizer.get("allcraft"),
        "sentry_torch_shop": data.get("run", {}).get("sentry_torch_shop"),
    }


def _load_pool_config_from_disk(pool_name: str) -> dict[str, Any] | None:
    """Parse ``<seeds_pool_dir>/<pool_name>/config.toml`` and normalize it."""
    config_file = Path(settings.seeds_pool_dir) / pool_name / "config.toml"
    if not config_file.exists():
        return None
    try:
        with open(config_file, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning(f"Failed to read {config_file}", exc_info=True)
        return None
    return _normalize_pool_config(data)


async def scan_pool(db: AsyncSession, pool_name: str = "standard") -> int:
    """Scan pool directory and sync with database.

    Upserts the ``Pool`` row (refreshing ``config`` from the on-disk
    ``config.toml`` and bumping ``last_scanned_at``, never touching
    ``enabled``), then looks for ``seed_*.zip`` files containing
    ``graph.json`` and creates missing ``Seed`` records.

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

    pool_config = _load_pool_config_from_disk(pool_name) or {}

    # Upsert the Pool row. ``enabled`` is intentionally excluded from the
    # update clause so admin toggles survive rescans.
    #
    # We use the PostgreSQL ``insert`` construct; SQLite >= 3.24 understands
    # the same ``ON CONFLICT ... DO UPDATE`` syntax, so tests running against
    # aiosqlite work too. If the minimum SQLite version ever drops, swap this
    # for a portable select-then-insert-or-update pattern.
    stmt = pg_insert(Pool).values(
        name=pool_name,
        enabled=True,
        config=pool_config,
        last_scanned_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Pool.name],
        set_={
            "config": stmt.excluded.config,
            "last_scanned_at": stmt.excluded.last_scanned_at,
        },
    )
    await db.execute(stmt)

    # Pre-fetch all known seed numbers for this pool to avoid per-file queries
    # and, more importantly, skip zip I/O for seeds already in the database.
    result = await db.execute(select(Seed.seed_number).where(Seed.pool_name == pool_name))
    existing_numbers: set[str] = set(result.scalars().all())

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

        # Skip seeds already in database (no zip I/O needed)
        if seed_number in existing_numbers:
            continue

        # Read graph.json from inside the zip
        graph_json = _read_graph_from_zip(entry)
        if graph_json is None:
            continue

        # Extract total_layers from graph
        total_layers = graph_json.get("total_layers", 0)
        if total_layers == 0:
            logger.warning(f"Missing total_layers in {entry}")

        difficulty_score = compute_seed_difficulty(graph_json)

        # Create seed record
        seed = Seed(
            seed_number=seed_number,
            pool_name=pool_name,
            graph_json=graph_json,
            total_layers=total_layers,
            difficulty_score=difficulty_score,
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

    Marks the seed as consumed and sets race.seed_id. Callers are
    responsible for enforcing ``Pool.enabled`` (see
    ``api/races.py:create_race`` / ``api/training.py:create_session``);
    this function only cares about seed availability.

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
        raise ValueError(f"No available seeds in mode '{pool_name}'")

    seed.status = SeedStatus.CONSUMED
    race.seed_id = seed.id
    race.seed = seed

    logger.info(f"Assigned seed {seed.seed_number} to race {race.id}")
    return seed


async def reroll_seed_for_race(
    db: AsyncSession,
    race: Race,
    reporter_id: uuid.UUID | None = None,
    report_reason: str | None = None,
) -> Seed:
    """Re-roll the seed for a race, releasing the old one.

    Picks a new available seed from the same pool, excluding the current seed.

    When ``reporter_id`` is provided, the old seed is marked as REPORTED
    (instead of AVAILABLE) and the report fields are populated.

    Note: ``race.seed`` must be eager-loaded (selectinload) before calling.

    Raises:
        ValueError: If no other seeds are available in the pool
    """
    old_seed = race.seed
    if old_seed is None:
        raise ValueError("Race has no seed assigned")

    pool_name = old_seed.pool_name

    new_seed = await get_available_seed(db, pool_name, exclude_id=old_seed.id)
    if new_seed is None:
        raise ValueError(f"No available seeds in mode '{pool_name}'")

    # Release old seed (keep DISCARDED if pool was discarded)
    if old_seed.status != SeedStatus.DISCARDED:
        if reporter_id is not None:
            old_seed.status = SeedStatus.REPORTED
            old_seed.reported_by_id = reporter_id
            old_seed.reported_reason = report_reason
            old_seed.reported_at = datetime.now(UTC)
        else:
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
            stats[pool_name] = {"available": 0, "consumed": 0, "discarded": 0, "reported": 0}
        stats[pool_name][status.value] = count

    return stats


async def discard_pool(db: AsyncSession, pool_name: str) -> int:
    """Mark all AVAILABLE and CONSUMED seeds in a pool as DISCARDED.

    CONSUMED seeds are included so they cannot leak back to AVAILABLE
    when a race re-rolls or is deleted after the pool is discarded.

    Args:
        db: Database session
        pool_name: Name of the pool to discard

    Returns:
        Number of seeds discarded
    """
    result = await db.execute(
        update(Seed)
        .where(
            Seed.pool_name == pool_name,
            Seed.status.in_([SeedStatus.AVAILABLE, SeedStatus.CONSUMED, SeedStatus.REPORTED]),
        )
        .values(status=SeedStatus.DISCARDED)
    )
    await db.commit()
    count: int = result.rowcount  # type: ignore[attr-defined]
    logger.info(f"Discarded {count} seeds from pool '{pool_name}'")
    return count


async def get_pool_config(db: AsyncSession, pool_name: str) -> dict[str, Any] | None:
    """Return the normalized config dict for a pool, or ``None`` if unknown.

    Reads from the ``pools.config`` column (populated at scan time).
    """
    result = await db.execute(select(Pool.config).where(Pool.name == pool_name))
    row = result.first()
    if row is None:
        return None
    config = row[0]
    # Row stored as empty dict when backfilled but not yet rescanned.
    return config or None
