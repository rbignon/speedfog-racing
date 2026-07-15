"""Daily Seed background creation loop.

A single Daily Seed race rotates at 08:00 UTC every day. The loop polls
once a minute and creates the missing race for the current rotation day,
relying on the partial unique index ``uq_races_daily_date`` to prevent
duplicates if multiple workers tick concurrently.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.discord import notify_daily_seed_created
from speedfog_racing.models import (
    DailySeedSchedule,
    Participant,
    Race,
    RaceStatus,
    User,
)
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.services import assign_seed_to_race, get_pool
from speedfog_racing.services.hard_close_loop import close_expired_races

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
SYSTEM_TWITCH_ID = "system:daily"
DAILY_ROTATION_HOUR = 8  # UTC


def daily_date_for(now: datetime) -> date:
    """Return the rotation date for ``now``.

    The Daily Seed window starts at 08:00 UTC; instants before that hour
    still belong to the previous day's seed.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now.astimezone(UTC) - timedelta(hours=DAILY_ROTATION_HOUR)).date()


def daily_start_at(day: date) -> datetime:
    """Return the canonical 08:00 UTC start datetime for ``day``."""
    return datetime.combine(day, time(hour=DAILY_ROTATION_HOUR), tzinfo=UTC)


async def create_daily_seed_if_needed(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> Race | None:
    """Create today's Daily Seed if it does not exist yet.

    Returns the created Race, or None if the race already exists, the
    previous daily is still running (unexpected), the schedule is missing,
    the configured pool is disabled, or another worker won the race
    between our existence check and INSERT.
    """
    now_utc = now or datetime.now(UTC)
    today = daily_date_for(now_utc)

    # Give hard-close a chance to roll yesterday's daily before we look at it.
    await close_expired_races(session_maker)

    # Streak Update B: consume freezes / break streaks for users who did
    # not qualify on yesterday's daily. Idempotent within the rotation day
    # (the helper skips users with an existing freeze row for ``missed``).
    yesterday = today - timedelta(days=1)
    async with session_maker() as db:
        from speedfog_racing.services.daily_streak_service import (
            apply_close_day_for_all_users,
        )

        await apply_close_day_for_all_users(db, missed=yesterday)
        await db.commit()

    async with session_maker() as db:
        existing = (
            await db.execute(select(Race).where(Race.daily_date == today))
        ).scalar_one_or_none()
        if existing is not None:
            return None

        previous_running = (
            await db.execute(
                select(Race).where(
                    Race.daily_date.is_not(None),
                    Race.daily_date < today,
                    Race.status == RaceStatus.RUNNING,
                )
            )
        ).scalar_one_or_none()
        if previous_running is not None:
            logger.error(
                "Previous daily %s is still RUNNING; skipping creation for %s",
                previous_running.id,
                today,
            )
            return None

        schedule = await db.get(DailySeedSchedule, today.weekday())
        if schedule is None:
            logger.error("No daily seed schedule row for weekday=%s", today.weekday())
            return None

        pool = await get_pool(db, schedule.pool_name)
        if pool is None:
            logger.error("Daily seed pool %r is missing", schedule.pool_name)
            return None

        system_user = (
            await db.execute(select(User).where(User.twitch_id == SYSTEM_TWITCH_ID))
        ).scalar_one_or_none()
        if system_user is None:
            logger.error("System user %r is missing", SYSTEM_TWITCH_ID)
            return None

        start_at = daily_start_at(today)
        race = Race(
            name=f"Daily - {today.isoformat()} - {format_pool_display_name(pool)}",
            organizer_id=system_user.id,
            daily_date=today,
            exclude_from_elo=True,
            is_public=True,
            open_registration=True,
            max_participants=None,
            private_dag=False,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
            status=RaceStatus.RUNNING,
            started_at=start_at,
            seeds_released_at=start_at,
        )
        # Postgres enforces the partial unique index when the INSERT
        # statement executes (i.e. on flush), so wrap the whole
        # add/flush/assign/commit in the same IntegrityError guard.
        db.add(race)
        try:
            await db.flush()
            try:
                await assign_seed_to_race(db, race, schedule.pool_name)
            except ValueError:
                logger.exception(
                    "No available seeds in pool %r for daily %s",
                    schedule.pool_name,
                    today,
                )
                await db.rollback()
                return None
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info("Daily seed for %s was created concurrently", today)
            return None

        if today.weekday() == 0:  # Monday: roll up the previous week's daily wins.
            week_starting = today - timedelta(days=7)
            await RewardsService(db).refresh_weekly_daily_rewards(
                week_starting=week_starting,
                reason="weekly daily rollup",
            )
            await db.commit()

        # Re-fetch with the relationships finalize_race / Discord copy expects
        # so callers (and the notification) see a consistent eager-loaded row.
        full_race = (
            await db.execute(
                select(Race)
                .where(Race.id == race.id)
                .options(
                    selectinload(Race.organizer),
                    selectinload(Race.seed),
                    selectinload(Race.participants).selectinload(Participant.user),
                )
            )
        ).scalar_one()

        previous_race = (
            await db.execute(
                select(Race)
                .where(Race.daily_date == today - timedelta(days=1))
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.seed),
                )
            )
        ).scalar_one_or_none()

    await notify_daily_seed_created(full_race, previous_race)
    return full_race


async def daily_seed_loop(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Periodic loop that creates the daily seed race once per UTC day."""
    logger.info("Daily seed loop started (poll=%ds)", POLL_INTERVAL)
    while True:
        try:
            await create_daily_seed_if_needed(session_maker)
        except Exception:
            logger.exception("Daily seed loop error")
        await asyncio.sleep(POLL_INTERVAL)
