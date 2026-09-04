"""Per-user activity aggregates: played-run counts and the weekly series powering UserStatsCards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
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
from speedfog_racing.services.daily_streak_service import qualifies_for_streak_sql

MAX_WEEKS = 52


@dataclass(frozen=True)
class PlayedRunCounts:
    """How many runs a user actually played, per category.

    Shared by the public profile and ``/auth/me`` so every surface agrees on
    what counts as "played".
    """

    race_count: int
    daily_count: int
    training_count: int


async def count_played_runs(db: AsyncSession, user_id: UUID) -> PlayedRunCounts:
    """Count the runs ``user_id`` actually played.

    Races: terminal participations on regular races where the user played
    (FINISHED, or ABANDONED with igt > 0). Daily Seed races
    (``Race.daily_date IS NOT NULL``) are counted separately, and only when
    the participation qualifies for the streak (``qualifies_for_streak_sql``),
    so a profile can never display ``best_streak`` above ``daily_count``.
    Training sessions count unless cancelled (the player never started).
    """
    played = or_(
        Participant.status == ParticipantStatus.FINISHED,
        (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
    )
    race_count = (
        await db.execute(
            select(func.count())
            .select_from(Participant)
            .join(Race, Race.id == Participant.race_id)
            .where(Participant.user_id == user_id, played, Race.daily_date.is_(None))
        )
    ).scalar_one()
    daily_count = (
        await db.execute(
            select(func.count())
            .select_from(Participant)
            .join(Race, Race.id == Participant.race_id)
            .where(
                Participant.user_id == user_id,
                qualifies_for_streak_sql(),
                Race.daily_date.is_not(None),
            )
        )
    ).scalar_one()
    training_count = (
        await db.execute(
            select(func.count())
            .select_from(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.status != TrainingSessionStatus.CANCELLED,
            )
        )
    ).scalar_one()
    return PlayedRunCounts(race_count, daily_count, training_count)


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

    # Same predicates as ``api/users.py``: regular races count terminal-played
    # participations; dailies count qualifying ones (``len(zone_history) >= 2``,
    # mirroring ``qualifies_for_streak``). Without this split, the daily
    # sparkline rendered next to the headline ``daily_count`` in
    # ``UserStatsCards`` could disagree with the ``best_streak`` shown in
    # the same card.
    race_played_filter = or_(
        Participant.status == ParticipantStatus.FINISHED,
        (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
    )
    # SQL counterpart of qualifies_for_streak (see daily_streak_service).
    daily_qualified_filter = qualifies_for_streak_sql()
    counted_filter = or_(
        and_(Race.daily_date.is_(None), race_played_filter),
        and_(Race.daily_date.is_not(None), daily_qualified_filter),
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
                counted_filter,
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
