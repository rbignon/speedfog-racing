"""Lists the DISCARDED seeds whose zip files may be deleted.

Used by ``deploy/cleanup-seeds.sh``: prints one ``folder_path`` per line on
stdout and nothing else (logs go to stderr). A DISCARDED seed's zip is kept
while it is a top seed of its category, protected by a player, in use or played
in the last ``SEED_PURGE_GRACE_DAYS`` days, unless it was added (scanned) before
``SET_SEED_MIN_SEED_DATE`` (see docs/SEED_PIPELINE.md).

Usage:
    speedfog-purgeable-seeds                       # every pool
    speedfog-purgeable-seeds --pool standard       # one pool
    speedfog-purgeable-seeds --older-than 30       # seeds created over 30 days ago
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from speedfog_racing.database import get_db_context
from speedfog_racing.services.set_seed_service import purgeable_seeds


async def _list(pool: str | None, older_than_days: int | None) -> list[str]:
    async with get_db_context() as db:
        seeds = await purgeable_seeds(
            db, now=datetime.now(UTC), pool=pool, older_than_days=older_than_days
        )
    return [seed.folder_path for seed in seeds if seed.folder_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="List the DISCARDED seed zips that may be purged")
    parser.add_argument("--pool", help="Only seeds of this pool.")
    parser.add_argument(
        "--older-than", type=int, dest="older_than", help="Only seeds this many days old."
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    for path in asyncio.run(_list(args.pool, args.older_than)):
        print(path)
