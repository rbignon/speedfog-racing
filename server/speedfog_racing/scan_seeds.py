"""Standalone seed pool scanner.

Scans seed pool directories and inserts new seeds into the database.
Can be run independently of the server (e.g. from deploy scripts).

Usage:
    speedfog-scan-seeds                     # scan all pools
    speedfog-scan-seeds --pool sprint       # scan one pool
    speedfog-scan-seeds --pool sprint --pool standard  # scan specific pools
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from speedfog_racing.config import settings
from speedfog_racing.database import get_db_context
from speedfog_racing.services.seed_service import scan_pool

logger = logging.getLogger(__name__)


def _discover_pools() -> list[str]:
    """Discover all pool directories (subdirs with config.toml)."""
    pool_base = Path(settings.seeds_pool_dir)
    if not pool_base.exists():
        return []
    return sorted(
        subdir.name
        for subdir in pool_base.iterdir()
        if subdir.is_dir() and (subdir / "config.toml").exists()
    )


async def _scan(pools: list[str]) -> bool:
    """Scan the given pools and print results. Returns True if all succeeded."""
    ok = True
    async with get_db_context() as db:
        for pool_name in pools:
            try:
                added = await scan_pool(db, pool_name)
                print(f"  {pool_name}: {added} new seeds added")
            except Exception:
                logger.exception("Failed to scan pool '%s'", pool_name)
                print(f"  {pool_name}: ERROR")
                ok = False
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan seed pool directories into the database")
    parser.add_argument(
        "--pool",
        action="append",
        dest="pools",
        help="Pool name to scan (repeatable). Default: all pools.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    pools: list[str] = args.pools or _discover_pools()
    if not pools:
        print("No pools found.")
        sys.exit(1)

    print(f"Scanning {len(pools)} pool(s): {', '.join(pools)}")
    ok = asyncio.run(_scan(pools))
    if not ok:
        sys.exit(1)
