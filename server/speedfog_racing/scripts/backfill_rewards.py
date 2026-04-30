"""Idempotent backfill: early_adopter for old accounts, current top1 ELO holder."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from speedfog_racing.models import User

logger = logging.getLogger(__name__)

DEFAULT_CUTOFF = date(2026, 4, 1)


async def backfill_rewards(
    session_maker: async_sessionmaker[AsyncSession],
    cutoff: date = DEFAULT_CUTOFF,
) -> None:
    """Idempotent: re-running produces no duplicates."""
    # Lazy import: rewards.service <-> services.race_lifecycle is a circular dependency.
    # Importing here (rather than at module top) avoids the partial-initialization error
    # when this script is executed as a standalone __main__ before the services package
    # has been fully loaded.
    from speedfog_racing.rewards.service import RewardsService  # noqa: PLC0415

    cutoff_dt = datetime.combine(cutoff, time.min, tzinfo=UTC)

    async with session_maker() as db:
        svc = RewardsService(db)
        rows = await db.execute(select(User).where(User.created_at < cutoff_dt))
        users = list(rows.scalars().all())
        for u in users:
            await svc.grant_permanent_badge(
                u.id,
                "early_adopter",
                reason=f"backfill: account < {cutoff.isoformat()}",
            )
        await db.commit()
        logger.info("Granted early_adopter to %d account(s)", len(users))

    async with session_maker() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders(reason="backfill: initial top 1 sync")
        await db.commit()
        logger.info("Refreshed top1_elo holders")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backfill rewards.")
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=DEFAULT_CUTOFF,
        help="Early-adopter cutoff (YYYY-MM-DD).",
    )
    args = parser.parse_args()
    # Import lazily to avoid a circular-import chain triggered by the app's
    # services/__init__.py when this module is loaded as a standalone script.
    from speedfog_racing.database import (  # noqa: PLC0415
        async_session_maker as default_session_maker,
    )

    asyncio.run(backfill_rewards(default_session_maker, cutoff=args.cutoff))


if __name__ == "__main__":
    main()
