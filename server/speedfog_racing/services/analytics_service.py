"""Analytics service: compute dashboard KPIs, weekly trends, heatmaps, and timezone data."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    Race,
    RaceStatus,
    Seed,
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.services.daily_streak_service import qualifies_for_streak_sql

logger = logging.getLogger(__name__)


def _hour_to_bucket(hour: int) -> int:
    """Map an hour (0-23, UTC) to a heatmap row index (0-11).

    Buckets cover the full 24h day in 2-hour slices:
      row 0: 00-01   row 4: 08-09   row 8:  16-17
      row 1: 02-03   row 5: 10-11   row 9:  18-19
      row 2: 04-05   row 6: 12-13   row 10: 20-21
      row 3: 06-07   row 7: 14-15   row 11: 22-23
    """
    return hour // 2


def _iso_week_key(dt: datetime) -> tuple[int, int]:
    """Return (iso_year, iso_week) for the given datetime."""
    iso = dt.isocalendar()
    return (iso.year, iso.week)


def _build_week_list(now: datetime, count: int = 12) -> list[tuple[int, int]]:
    """Build a list of the last `count` ISO week keys, oldest first."""
    weeks: list[tuple[int, int]] = []
    current = now
    for _ in range(count):
        weeks.append(_iso_week_key(current))
        current -= timedelta(weeks=1)
    return list(reversed(weeks))


async def compute_analytics(db: AsyncSession) -> dict[str, Any]:
    """Compute all dashboard analytics data from the database.

    Returns a dict with keys: kpis, weekly, heatmaps, timezones.
    Uses Python-side aggregation to stay compatible with SQLite (test) and PostgreSQL (prod).
    """
    now = datetime.now(tz=UTC)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cutoff_30d = now - timedelta(days=30)
    # Weekly and heatmap sections look back 12 ISO weeks; use 13 weeks as
    # the load cutoff so week boundary rounding never excludes data.
    window_cutoff = now - timedelta(weeks=13)

    # ------------------------------------------------------------------
    # KPIs via aggregate queries (all-time counts, O(1) via index)
    # ------------------------------------------------------------------
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    new_users_this_month = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= first_of_month))
    ).scalar_one()
    active_users_30d = (
        await db.execute(select(func.count(User.id)).where(User.last_seen >= cutoff_30d))
    ).scalar_one()
    active_users_pct = round(active_users_30d / total_users * 100, 1) if total_users > 0 else 0.0

    # Daily races (daily_date IS NOT NULL) are excluded from admin analytics:
    # they are system-organized and would inflate counts and skew per-race
    # averages relative to community-organized racing activity. The audience
    # they reach is surfaced separately via ``total_daily_participants``,
    # the cumulative participant count summed across all daily races.
    total_races_finished = (
        await db.execute(
            select(func.count(Race.id)).where(
                Race.status == RaceStatus.FINISHED,
                Race.daily_date.is_(None),
            )
        )
    ).scalar_one()
    # SQL counterpart of qualifies_for_streak (see daily_streak_service).
    # Race status is not filtered: a still-running daily contributes its
    # already-qualified runners immediately.
    daily_qualified_filter = qualifies_for_streak_sql()
    total_daily_participants = (
        await db.execute(
            select(func.count(Participant.id))
            .join(Race, Race.id == Participant.race_id)
            .where(
                Race.daily_date.is_not(None),
                daily_qualified_filter,
            )
        )
    ).scalar_one()

    # Average participants across all finished races: GROUP BY in SQL,
    # average in Python (avoids dialect differences for AVG over counts).
    per_race_counts = (
        (
            await db.execute(
                select(func.count(Participant.id))
                .join(Race, Participant.race_id == Race.id)
                .where(Race.status == RaceStatus.FINISHED, Race.daily_date.is_(None))
                .group_by(Participant.race_id)
            )
        )
        .scalars()
        .all()
    )
    avg_participants = (
        round(sum(per_race_counts) / len(per_race_counts), 1) if per_race_counts else 0.0
    )

    total_solo = (await db.execute(select(func.count(TrainingSession.id)))).scalar_one()
    solo_finished = (
        await db.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.status == TrainingSessionStatus.FINISHED
            )
        )
    ).scalar_one()
    solo_abandoned = (
        await db.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.status == TrainingSessionStatus.ABANDONED
            )
        )
    ).scalar_one()
    denom = solo_finished + solo_abandoned
    solo_completion_pct = round(solo_finished / denom * 100, 1) if denom > 0 else 0.0

    # ------------------------------------------------------------------
    # Load windowed raw data for weekly / heatmap / timezone sections
    # ------------------------------------------------------------------
    users: list[User] = list(
        (
            await db.execute(
                select(User).where((User.created_at >= window_cutoff) | (User.timezone.isnot(None)))
            )
        )
        .scalars()
        .all()
    )
    races: list[Race] = list(
        (
            await db.execute(
                select(Race).where(
                    Race.started_at >= window_cutoff,
                    Race.daily_date.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    training_sessions: list[TrainingSession] = list(
        (
            await db.execute(
                select(TrainingSession).where(TrainingSession.created_at >= window_cutoff)
            )
        )
        .scalars()
        .all()
    )

    # Per-daily-race qualified participant counts, restricted to the 13-week
    # window so the weekly bucketing has the rows it needs. Kept separate
    # from the ``races`` load above because that load filters out dailies
    # for the heatmap / ``avg_participants`` / pool_usage paths.
    daily_qualified_rows = (
        await db.execute(
            select(Race.started_at, func.count(Participant.id))
            .join(Participant, Participant.race_id == Race.id)
            .where(
                Race.daily_date.is_not(None),
                Race.started_at >= window_cutoff,
                daily_qualified_filter,
            )
            .group_by(Race.id, Race.started_at)
        )
    ).all()

    # Participant counts for the windowed races only
    race_ids_window = [r.id for r in races]
    race_participant_counts: dict[str, int] = {}
    if race_ids_window:
        windowed_counts = (
            await db.execute(
                select(Participant.race_id, func.count(Participant.id))
                .where(Participant.race_id.in_(race_ids_window))
                .group_by(Participant.race_id)
            )
        ).all()
        for race_id, count in windowed_counts:
            race_participant_counts[str(race_id)] = count

    kpis = {
        "total_users": total_users,
        "new_users_this_month": new_users_this_month,
        "active_users_30d": active_users_30d,
        "active_users_pct": active_users_pct,
        "total_races_finished": total_races_finished,
        "total_daily_participants": total_daily_participants,
        "avg_participants": avg_participants,
        "total_solo": total_solo,
        "solo_completion_pct": solo_completion_pct,
    }

    # ------------------------------------------------------------------
    # Weekly trends (last 12 ISO weeks)
    # ------------------------------------------------------------------
    week_keys = _build_week_list(now, 12)
    week_set = set(week_keys)

    # Build per-week counts
    week_new_users: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_races: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_race_participant_sum: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_race_count: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_solo: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_solo_finished: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_solo_abandoned: dict[tuple[int, int], int] = {k: 0 for k in week_keys}
    week_daily: dict[tuple[int, int], int] = {k: 0 for k in week_keys}

    for u in users:
        if u.created_at is not None:
            wk = _iso_week_key(_ensure_utc(u.created_at))
            if wk in week_set:
                week_new_users[wk] += 1

    for r in races:
        if r.started_at is not None and r.status in (RaceStatus.RUNNING, RaceStatus.FINISHED):
            wk = _iso_week_key(_ensure_utc(r.started_at))
            if wk in week_set:
                week_races[wk] += 1
                week_race_participant_sum[wk] += race_participant_counts.get(str(r.id), 0)
                week_race_count[wk] += 1

    for ts in training_sessions:
        if ts.created_at is not None:
            wk = _iso_week_key(_ensure_utc(ts.created_at))
            if wk in week_set:
                week_solo[wk] += 1
                if ts.status == TrainingSessionStatus.FINISHED:
                    week_solo_finished[wk] += 1
                elif ts.status == TrainingSessionStatus.ABANDONED:
                    week_solo_abandoned[wk] += 1

    for started_at, qualified_count in daily_qualified_rows:
        if started_at is None:
            continue
        wk = _iso_week_key(_ensure_utc(started_at))
        if wk in week_set:
            week_daily[wk] += qualified_count

    weekly = {
        "weeks": [f"W{wk[1]}" for wk in week_keys],
        "new_users": [week_new_users[wk] for wk in week_keys],
        "races": [week_races[wk] for wk in week_keys],
        "solo": [week_solo[wk] for wk in week_keys],
        "solo_finished": [week_solo_finished[wk] for wk in week_keys],
        "solo_abandoned": [week_solo_abandoned[wk] for wk in week_keys],
        "daily": [week_daily[wk] for wk in week_keys],
        "avg_participants": [
            round(week_race_participant_sum[wk] / week_race_count[wk], 1)
            if week_race_count[wk] > 0
            else 0.0
            for wk in week_keys
        ],
    }

    # ------------------------------------------------------------------
    # Heatmaps (12 rows x 7 cols, UTC)
    # ------------------------------------------------------------------
    # row = 2-hour bucket (00-01 ... 22-23), col = weekday (0=Mon, 6=Sun)
    race_grid = [[0] * 7 for _ in range(12)]
    solo_grid = [[0] * 7 for _ in range(12)]

    for r in races:
        if r.started_at is None or r.status not in (RaceStatus.RUNNING, RaceStatus.FINISHED):
            continue
        started = _ensure_utc(r.started_at)
        bucket = _hour_to_bucket(started.hour)
        col = started.weekday()
        race_grid[bucket][col] += race_participant_counts.get(str(r.id), 0)

    for ts in training_sessions:
        if ts.created_at is None:
            continue
        created = _ensure_utc(ts.created_at)
        bucket = _hour_to_bucket(created.hour)
        col = created.weekday()
        solo_grid[bucket][col] += 1

    heatmaps = {
        "race_players": race_grid,
        "solo": solo_grid,
    }

    # ------------------------------------------------------------------
    # Timezones
    # ------------------------------------------------------------------
    tz_counts: dict[str, int] = {}
    for u in users:
        if u.timezone:
            tz_counts[u.timezone] = tz_counts.get(u.timezone, 0) + 1

    tz_list: list[dict[str, int | str]] = []
    for tz_name, count in tz_counts.items():
        try:
            tz = ZoneInfo(tz_name)
            offset = datetime.now(tz).utcoffset()
            offset_minutes = int(offset.total_seconds() // 60) if offset is not None else 0
        except Exception:
            offset_minutes = 0
        tz_list.append({"timezone": tz_name, "offset_minutes": offset_minutes, "count": count})

    tz_list.sort(key=lambda x: int(x["offset_minutes"]))

    pool_usage = await _compute_pool_usage(db)
    top_organizers = await _compute_top_organizers(db)

    return {
        "kpis": kpis,
        "weekly": weekly,
        "heatmaps": heatmaps,
        "timezones": tz_list,
        "pool_usage": pool_usage,
        "top_organizers": top_organizers,
    }


async def _compute_pool_usage(db: AsyncSession) -> list[dict[str, Any]]:
    """Aggregate runs per pool, site-wide.

    Races: one count per race (any status), so that each race weighs the same
    regardless of its number of participants. Training: sessions with status
    FINISHED or (ABANDONED and igt_ms > 0), matching the per-user pool-stats
    semantics. Training pool names are normalized by stripping the "training_"
    prefix so they merge with their race pool.
    """
    race_counts_q = await db.execute(
        select(Seed.pool_name, func.count(Race.id))
        .select_from(Race)
        .join(Seed, Race.seed_id == Seed.id)
        .where(Race.daily_date.is_(None))
        .group_by(Seed.pool_name)
    )
    race_counts: dict[str, int] = {row[0]: row[1] for row in race_counts_q.all()}

    training_counts_q = await db.execute(
        select(Seed.pool_name, func.count(TrainingSession.id))
        .select_from(TrainingSession)
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            or_(
                TrainingSession.status == TrainingSessionStatus.FINISHED,
                (TrainingSession.status == TrainingSessionStatus.ABANDONED)
                & (TrainingSession.igt_ms > 0),
            ),
            TrainingSession.exclude_from_stats == False,  # noqa: E712
        )
        .group_by(Seed.pool_name)
    )
    training_counts: dict[str, int] = {}
    for raw_pool, count in training_counts_q.all():
        pool = raw_pool.removeprefix("training_")
        training_counts[pool] = training_counts.get(pool, 0) + count

    all_pools = set(race_counts) | set(training_counts)
    entries: list[dict[str, Any]] = [
        {
            "pool_name": pool,
            "race_runs": race_counts.get(pool, 0),
            "training_runs": training_counts.get(pool, 0),
            "total_runs": race_counts.get(pool, 0) + training_counts.get(pool, 0),
        }
        for pool in all_pools
    ]
    entries.sort(key=lambda e: (-int(e["total_runs"]), str(e["pool_name"])))
    return entries


async def _compute_top_organizers(db: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    """Top organizers by count of finished races, with average participants.

    Participant count per race is computed in SQL, then averaged in Python to
    stay dialect-agnostic (SQLite test DB does not support AVG of subquery
    aggregates in a single statement the same way as PostgreSQL).
    """
    # race_id -> participant count, restricted to finished races
    per_race_q = await db.execute(
        select(Race.id, Race.organizer_id, func.count(Participant.id))
        .select_from(Race)
        .outerjoin(Participant, Participant.race_id == Race.id)
        .where(Race.status == RaceStatus.FINISHED, Race.daily_date.is_(None))
        .group_by(Race.id, Race.organizer_id)
    )
    per_organizer_counts: dict[uuid.UUID, list[int]] = {}
    for _race_id, organizer_id, participant_count in per_race_q.all():
        per_organizer_counts.setdefault(organizer_id, []).append(participant_count)

    if not per_organizer_counts:
        return []

    users_q = await db.execute(select(User).where(User.id.in_(list(per_organizer_counts.keys()))))
    users_by_id = {u.id: u for u in users_q.scalars().all()}

    entries: list[dict[str, Any]] = []
    for organizer_id, counts in per_organizer_counts.items():
        user = users_by_id.get(organizer_id)
        if user is None:
            logger.warning("Finished race organizer %s not found in users table", organizer_id)
            continue
        race_count = len(counts)
        avg_participants = round(sum(counts) / race_count, 1) if race_count > 0 else 0.0
        entries.append(
            {
                "user_id": str(user.id),
                "twitch_username": user.twitch_username,
                "twitch_display_name": user.twitch_display_name,
                "twitch_avatar_url": user.twitch_avatar_url,
                "race_count": race_count,
                "avg_participants": avg_participants,
            }
        )

    entries.sort(key=lambda e: (-e["race_count"], e["twitch_username"]))
    return entries[:limit]


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware. Treat naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
