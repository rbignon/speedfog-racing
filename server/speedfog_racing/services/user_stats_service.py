"""Compute the per-category weekly series powering UserStatsCards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.schemas import UserStatsWeekly

MAX_WEEKS = 52


def _iso_week_floor(dt: datetime) -> datetime:
    """Monday 00:00 UTC of the ISO week containing ``dt``."""
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    monday = aware - timedelta(days=aware.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


async def compute_weekly_series(
    db: AsyncSession,
    user: User,
    now: datetime | None = None,
) -> UserStatsWeekly:
    """Build the four weekly count lists for ``user`` since their join week.

    The window starts at the user's join week and ends at the current ISO
    week, capped to the most recent ``MAX_WEEKS``. Days/weeks without
    activity are zero-filled.

    Date columns mirror Recent Activity:
    - Races / Daily / Organized: ``race_date`` = started_at ?? scheduled_at ?? created_at
    - Solo: ``TrainingSession.created_at``
    """
    now_dt = now or datetime.now(UTC)
    end_week = _iso_week_floor(now_dt)
    join_week = _iso_week_floor(user.created_at)

    total_weeks = ((end_week - join_week).days // 7) + 1
    capped = total_weeks > MAX_WEEKS
    weeks_count = min(total_weeks, MAX_WEEKS)
    start_week = end_week - timedelta(weeks=weeks_count - 1)

    races = [0] * weeks_count
    daily = [0] * weeks_count
    solo = [0] * weeks_count
    organized = [0] * weeks_count

    def bucket(dt: datetime | None) -> int | None:
        if dt is None:
            return None
        wf = _iso_week_floor(dt)
        if wf < start_week or wf > end_week:
            return None
        return (wf - start_week).days // 7

    played_status_filter = or_(
        Participant.status == ParticipantStatus.FINISHED,
        (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
    )

    race_rows = (
        await db.execute(
            select(
                Race.daily_date,
                Race.started_at,
                Race.scheduled_at,
                Race.created_at,
            )
            .join(Participant, Participant.race_id == Race.id)
            .where(
                Participant.user_id == user.id,
                played_status_filter,
            )
        )
    ).all()
    for daily_date, started_at, scheduled_at, created_at in race_rows:
        b = bucket(started_at or scheduled_at or created_at)
        if b is None:
            continue
        if daily_date is None:
            races[b] += 1
        else:
            daily[b] += 1

    solo_rows = (
        await db.execute(
            select(TrainingSession.created_at).where(
                TrainingSession.user_id == user.id,
                TrainingSession.status != TrainingSessionStatus.CANCELLED,
            )
        )
    ).all()
    for (created_at,) in solo_rows:
        b = bucket(created_at)
        if b is not None:
            solo[b] += 1

    org_rows = (
        await db.execute(
            select(Race.started_at, Race.scheduled_at, Race.created_at).where(
                Race.organizer_id == user.id
            )
        )
    ).all()
    for started_at, scheduled_at, created_at in org_rows:
        b = bucket(started_at or scheduled_at or created_at)
        if b is not None:
            organized[b] += 1

    return UserStatsWeekly(
        races=races,
        daily=daily,
        solo=solo,
        organized=organized,
        weeks_count=weeks_count,
        capped=capped,
    )
