"""Seed pool management service."""

import json
import logging
import tomllib
import uuid
import zipfile
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.config import settings
from speedfog_racing.models import Pool, Race, RaceStatus, RunMode, Seed, SeedStatus
from speedfog_racing.services.seed_difficulty import compute_seed_difficulty
from speedfog_racing.services.speedrun_service import (
    _is_training,
    _pool_config,
    race_draws_fresh_seeds,
)

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


def _normalize_archived_layers(value: Any) -> list[int]:
    """``[display] archived_layers`` as a list of ints. Racing-only (the seed
    generator never reads it). A malformed value drops the offending items:
    a non-list gives ``[]``, non-int items (bools included) are skipped."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


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
    # Lamenter's Gaol is cut in three by two locked doors; unlike the other
    # anti-softlock keys, being handed both changes how the dungeon plays.
    upper_gaol_key = starting_items_raw.get("gaolupperlevelkey")
    lower_gaol_key = starting_items_raw.get("gaollowerlevelkey")
    if upper_gaol_key and lower_gaol_key:
        starting_items.append("Lamenter's Gaol Keys")
    elif upper_gaol_key or lower_gaol_key:
        # In-game names are "Gaol Upper/Lower Level Key"; prefix the dungeon.
        level = "Upper" if upper_gaol_key else "Lower"
        starting_items.append(f"Lamenter's Gaol {level} Level Key")

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

    # Compute major boss density from fixed count + layer count.
    # Accept legacy min_layers/max_layers (pre-speedfog refactor) as a fallback,
    # using the upper bound to match the original "target depth" semantic.
    major_bosses = requirements.get("major_bosses")
    layers_count = structure.get("layers_count")
    if layers_count is None:
        layers_count = structure.get("max_layers")
    if major_bosses and layers_count:
        mbr = major_bosses / layers_count
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
        "archived_layers": _normalize_archived_layers(display.get("archived_layers")),
        "type": display.get("type", "race"),
        "sort_order": display.get("sort_order", 99),
        "estimated_duration": display.get("estimated_duration"),
        "description": display.get("description") or None,
        "rules": display.get("rules") or None,
        "final_tier": structure.get("final_tier"),
        "layers_count": layers_count,
        "starting_runes": starting_runes,
        "starting_upgrades": starting_upgrades or None,
        "starting_items": starting_items or None,
        "care_package": care_package.get("enabled"),
        "weapon_upgrade": care_package.get("weapon_upgrade"),
        "care_package_items": care_package_items or None,
        "items_randomized": item_randomizer.get("enabled"),
        "auto_upgrade_weapons": item_randomizer.get("auto_upgrade_weapons"),
        "auto_equip": item_randomizer.get("auto_equip"),
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


async def _random_seed(
    db: AsyncSession,
    pool_name: str,
    statuses: Collection[SeedStatus],
    excluded: Collection[uuid.UUID],
) -> Seed | None:
    """One seed picked uniformly among the pool's seeds in ``statuses``."""
    query = (
        select(Seed)
        .where(Seed.pool_name == pool_name, Seed.status.in_(statuses))
        .order_by(func.random())
        .limit(1)
        # Never take a row a concurrent speedrun draw holds (ignored on SQLite).
        .with_for_update(of=Seed, skip_locked=True)
    )
    if excluded:
        query = query.where(Seed.id.not_in(excluded))
    return (await db.execute(query)).scalar_one_or_none()


async def get_available_seed(
    db: AsyncSession,
    pool_name: str = "standard",
    exclude_id: uuid.UUID | None = None,
    *,
    allow_seen: bool = False,
    rerolled_seed_ids: Collection[uuid.UUID] = (),
) -> Seed | None:
    """Get a random seed to draw from the pool.

    By default only AVAILABLE seeds are drawn. With ``allow_seen`` (the races
    ``race_draws_fresh_seeds`` leaves out: community races in normal mode, which
    a SEEN seed keeps off the boards), SEEN seeds join the
    draw: while the pool has more AVAILABLE seeds than its speedrun floor,
    one uniform draw over its SEEN and AVAILABLE seeds, so SEEN seeds leave
    the pool at their share of it instead of piling up; at or under the
    floor, a SEEN seed, else an AVAILABLE one from the reserve the speedrun
    draws need.

    Args:
        db: Database session
        pool_name: Name of the pool
        exclude_id: Optional seed ID to exclude (e.g. current seed during re-roll),
            from the floor count too
        allow_seen: Whether SEEN seeds may be drawn (see above)
        rerolled_seed_ids: Seeds the race's rerolls already gave up
            (``Race.rerolled_seed_ids``), left out of every candidate set

    Returns:
        A random Seed, or None if the pool has none to draw
    """
    excluded = {*rerolled_seed_ids, *([exclude_id] if exclude_id is not None else [])}
    if not allow_seen:
        return await _random_seed(db, pool_name, (SeedStatus.AVAILABLE,), excluded)
    if await _available_count(db, pool_name, exclude_id) > await speedrun_floor(db, pool_name):
        return await _random_seed(db, pool_name, (SeedStatus.SEEN, SeedStatus.AVAILABLE), excluded)
    seen = await _random_seed(db, pool_name, (SeedStatus.SEEN,), excluded)
    if seen is not None:
        return seen
    return await _random_seed(db, pool_name, (SeedStatus.AVAILABLE,), excluded)


class SpeedrunFloorError(ValueError):
    """A speedrun draw was refused: the pool is at or under its floor."""

    def __init__(self) -> None:
        super().__init__("No fresh seed right now")


def effective_speedrun_floor(pool: Pool) -> int:
    """A pool row's speedrun floor: its admin override, else the setting's default."""
    if pool.speedrun_floor is not None:
        return pool.speedrun_floor
    return settings.speedrun_default_floor


async def speedrun_floor(db: AsyncSession, pool_name: str) -> int:
    """The pool's speedrun floor: its admin override, else the setting's default."""
    override = (
        await db.execute(select(Pool.speedrun_floor).where(Pool.name == pool_name))
    ).scalar_one_or_none()
    return override if override is not None else settings.speedrun_default_floor


async def _available_count(
    db: AsyncSession, pool_name: str, exclude_id: uuid.UUID | None = None
) -> int:
    query = (
        select(func.count())
        .select_from(Seed)
        .where(Seed.pool_name == pool_name, Seed.status == SeedStatus.AVAILABLE)
    )
    if exclude_id is not None:
        query = query.where(Seed.id != exclude_id)
    return (await db.execute(query)).scalar_one()


async def has_fresh_speedrun_seed(db: AsyncSession, pool_name: str) -> bool:
    """Whether a speedrun draw from the pool would currently succeed."""
    return await _available_count(db, pool_name) > await speedrun_floor(db, pool_name)


async def draw_speedrun_seed(
    db: AsyncSession, pool_name: str, *, exclude_id: uuid.UUID | None = None
) -> Seed:
    """Pick a random AVAILABLE seed for a speedrun, refusing at or under the floor.

    The count and the pick both leave out ``exclude_id`` (a reroll's current
    seed). Does not change the seed's status: callers do.

    The picked row stays locked until the caller's commit (``FOR UPDATE SKIP
    LOCKED`` on PostgreSQL; SQLite ignores it), so two concurrent draws never
    get the same seed: the second one skips the locked row. The count cannot
    see a concurrent draw's uncommitted pick, so simultaneous draws can each
    pass the floor check and take the pool under its floor by the extra
    draws; the floor is a reserve, not an invariant.

    Raises:
        SpeedrunFloorError: If the pool has ``<= floor`` AVAILABLE seeds, or
            every remaining one is locked by a concurrent draw.
    """
    if await _available_count(db, pool_name, exclude_id) <= await speedrun_floor(db, pool_name):
        raise SpeedrunFloorError()
    query = (
        select(Seed)
        .where(Seed.pool_name == pool_name, Seed.status == SeedStatus.AVAILABLE)
        .order_by(func.random())
        .limit(1)
        # OF seeds: the eager-loaded pool is outer joined, and PostgreSQL
        # refuses FOR UPDATE on the nullable side of an outer join.
        .with_for_update(of=Seed, skip_locked=True)
    )
    if exclude_id is not None:
        query = query.where(Seed.id != exclude_id)
    seed = (await db.execute(query)).scalar_one_or_none()
    if seed is None:  # floor 0 and an empty pool, or every seed locked
        raise SpeedrunFloorError()
    return seed


async def assign_seed_to_race(
    db: AsyncSession, race: Race, pool_name: str = "standard", *, allow_seen: bool = False
) -> Seed:
    """Assign an available seed to a race.

    Marks the seed as consumed, sets race.seed_id, and records in
    ``race.seed_was_seen`` whether the seed was SEEN. Callers are
    responsible for enforcing ``Pool.enabled`` (see
    ``api/races.py:create_race`` / ``api/training.py:create_session``);
    this function only cares about seed availability.

    Args:
        db: Database session
        race: Race to assign seed to
        pool_name: Name of the pool to pick from
        allow_seen: Whether a SEEN seed may be drawn (see ``get_available_seed``);
            only for a race that ``race_draws_fresh_seeds`` leaves out

    Returns:
        The assigned Seed

    Raises:
        ValueError: If no seeds are available in the pool
    """
    seed = await get_available_seed(db, pool_name, allow_seen=allow_seen)

    if seed is None:
        raise ValueError(f"No available seeds in mode '{pool_name}'")

    race.seed_was_seen = seed.status == SeedStatus.SEEN
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
    """Re-roll the seed for a race.

    Picks a new seed from the same pool, excluding the current seed; a
    speedrun race draws through ``draw_speedrun_seed``, so the pool's floor
    applies, and a race that does not draw fresh seeds only
    (``race_draws_fresh_seeds``) may draw a SEEN seed (see
    ``get_available_seed``): an event race on a SEEN seed gets an AVAILABLE
    one, which puts it back on the boards (``Race.seed_was_seen``). The draw
    leaves out every seed the race's earlier rerolls gave up, and the old seed
    joins them (``Race.rerolled_seed_ids``), so rerolls never cycle back
    through rejected seeds. Nothing changes when no seed can be drawn.

    The old seed of a race still in SETUP becomes SEEN, released or not: its
    map reached the race's spectators, so no draw that counts on the boards
    may take it again. A training pool's seed goes back AVAILABLE instead
    (shared practice seeds: being seen means nothing there). A played seed
    stays CONSUMED: a running Daily Seed's, or a reset race's
    (``race.seed_played``, cleared here since the new seed was never
    played). When ``reporter_id`` is provided, it is marked REPORTED instead
    and the report fields are populated. A DISCARDED seed stays DISCARDED.

    Without ``reporter_id``, giving up a seed the race could count on (neither
    SEEN when drawn nor played) sets ``Race.rerolled_without_report``, which
    keeps a community race off the Speedrun boards for good: its organizer
    may have looked at that seed first (``race_unranked_reason``).

    Note: ``race.seed`` must be eager-loaded (selectinload) before calling.

    Raises:
        SpeedrunFloorError: A speedrun race's pool is at or under its floor.
        ValueError: A Set Seed race (it keeps its seed), or no other seed
            available in the pool.
    """
    if race.mode == RunMode.SET_SEED:
        raise ValueError("A Set Seed race keeps its seed")
    old_seed = race.seed
    if old_seed is None:
        raise ValueError("Race has no seed assigned")

    pool_name = old_seed.pool_name

    rerolled = race.rerolled_seed_ids or []
    new_seed: Seed | None
    if race.mode == RunMode.SPEEDRUN:
        # AVAILABLE seeds only, and a seed this race gave up is never AVAILABLE
        # again (speedrun races never draw from a training pool).
        new_seed = await draw_speedrun_seed(db, pool_name, exclude_id=old_seed.id)
    else:
        new_seed = await get_available_seed(
            db,
            pool_name,
            exclude_id=old_seed.id,
            allow_seen=not race_draws_fresh_seeds(race),
            rerolled_seed_ids=[uuid.UUID(seed_id) for seed_id in rerolled],
        )
    if new_seed is None:
        if rerolled:
            # The pool may still hold the seeds this race rejected.
            raise ValueError(f"No other seed left in pool '{pool_name}' for this race")
        raise ValueError(f"No available seeds in mode '{pool_name}'")

    # Release old seed (keep DISCARDED if pool was discarded)
    if old_seed.status != SeedStatus.DISCARDED:
        if reporter_id is not None:
            old_seed.status = SeedStatus.REPORTED
            old_seed.reported_by_id = reporter_id
            old_seed.reported_reason = report_reason
            old_seed.reported_at = datetime.now(UTC)
        elif race.status == RaceStatus.SETUP and not race.seed_played:
            old_seed.status = (
                SeedStatus.AVAILABLE
                if _is_training(_pool_config(old_seed.pool))
                else SeedStatus.SEEN
            )

    # A new list, so the ORM sees the JSON column change.
    race.rerolled_seed_ids = [*rerolled, str(old_seed.id)]
    # Giving up a seed the race could have counted on, unreported: the
    # organizer may have looked at it first. A SEEN or played seed could not
    # count, so the reroll off it only gives the race its first countable seed.
    if reporter_id is None and not race.seed_was_seen and not race.seed_played:
        race.rerolled_without_report = True

    # Assign new seed
    race.seed_was_seen = new_seed.status == SeedStatus.SEEN
    new_seed.status = SeedStatus.CONSUMED
    race.seed_id = new_seed.id
    race.seed = new_seed
    race.seed_played = False

    logger.info(
        f"Re-rolled seed for race {race.id}: {old_seed.seed_number} -> {new_seed.seed_number}"
    )
    return new_seed


async def get_pool_stats(db: AsyncSession) -> dict[str, dict[str, int]]:
    """Get availability statistics for all pools.

    Returns:
        Dict mapping pool names to a count per seed status (``SeedStatus``
        values as keys, every status present)
    """
    result = await db.execute(
        select(Seed.pool_name, Seed.status, func.count(Seed.id)).group_by(
            Seed.pool_name, Seed.status
        )
    )

    stats: dict[str, dict[str, int]] = {}

    for pool_name, status, count in result:
        if pool_name not in stats:
            stats[pool_name] = {s.value: 0 for s in SeedStatus}
        stats[pool_name][status.value] = count

    return stats


async def discard_pool(db: AsyncSession, pool_name: str) -> int:
    """Mark every seed of a pool that is not DISCARDED yet as DISCARDED.

    CONSUMED seeds are included so they cannot leak back to SEEN when a race
    re-rolls or is deleted after the pool is discarded; SEEN seeds since
    normal races could still draw them.

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
            Seed.status != SeedStatus.DISCARDED,
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
