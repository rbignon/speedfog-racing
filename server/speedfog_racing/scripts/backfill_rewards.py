"""Idempotent backfill: early_adopter for old accounts, current top1 ELO holder."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from speedfog_racing.database import async_session_maker as default_session_maker
from speedfog_racing.models import Participant, ParticipantStatus, User, UserRole
from speedfog_racing.rewards.catalog import (
    DAILY_STREAK_REWARD_THRESHOLD,
    VETERAN_RACE_THRESHOLD,
)
from speedfog_racing.rewards.service import RewardsService

logger = logging.getLogger(__name__)

DEFAULT_CUTOFF = date(2026, 4, 1)


async def backfill_rewards(
    session_maker: async_sessionmaker[AsyncSession],
    cutoff: date = DEFAULT_CUTOFF,
) -> None:
    """Idempotent: re-running produces no duplicates."""
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
            await svc.grant_name_template(
                u.id,
                "pioneer",
                reason=f"backfill: account < {cutoff.isoformat()}",
            )
            await svc.grant_phantom_skin(
                u.id,
                "emerald-aura",
                reason=f"backfill: account < {cutoff.isoformat()}",
            )
        await db.commit()
        logger.info("Granted early_adopter + pioneer + emerald-aura to %d account(s)", len(users))

    async with session_maker() as db:
        svc = RewardsService(db)
        admins = await db.execute(select(User).where(User.role == UserRole.ADMIN))
        admin_users = list(admins.scalars().all())
        for u in admin_users:
            await svc.grant_name_template(u.id, "archon", reason="backfill: admin role")
        await db.commit()
        logger.info("Granted archon to %d admin(s)", len(admin_users))

    async with session_maker() as db:
        svc = RewardsService(db)
        await svc.refresh_top1_elo_holders(reason="backfill: initial top 1 sync")
        await db.commit()
        logger.info("Refreshed top1_elo holders")

    async with session_maker() as db:
        svc = RewardsService(db)
        eligible = await db.execute(
            select(Participant.user_id, func.count(Participant.id).label("finished"))
            .where(Participant.status == ParticipantStatus.FINISHED)
            .group_by(Participant.user_id)
            .having(func.count(Participant.id) >= VETERAN_RACE_THRESHOLD)
        )
        veteran_users = list(eligible.all())
        for row in veteran_users:
            reason = f"backfill: finished {row.finished} races"
            await svc.grant_permanent_badge(row.user_id, "veteran", reason=reason)
            await svc.grant_name_template(row.user_id, "weathered", reason=reason)
            await svc.grant_phantom_skin(row.user_id, "crimson-aura", reason=reason)
        await db.commit()
        logger.info(
            "Granted veteran + weathered + crimson-aura to %d account(s)", len(veteran_users)
        )

    async with session_maker() as db:
        svc = RewardsService(db)
        streakers = await db.execute(
            select(User.id, User.daily_best_streak).where(
                User.daily_best_streak >= DAILY_STREAK_REWARD_THRESHOLD
            )
        )
        streaker_rows = list(streakers.all())
        for row in streaker_rows:
            await svc.grant_phantom_skin(
                row.id,
                "molten-aura",
                reason=f"backfill: reached {row.daily_best_streak}-day daily streak",
            )
        await db.commit()
        logger.info("Granted molten-aura to %d account(s)", len(streaker_rows))


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
    asyncio.run(backfill_rewards(default_session_maker, cutoff=args.cutoff))


if __name__ == "__main__":
    main()
