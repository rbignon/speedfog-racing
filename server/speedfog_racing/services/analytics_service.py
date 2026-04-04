"""Analytics service: compute dashboard KPIs, weekly trends, heatmaps, and timezone data."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Participant,
    Race,
    RaceStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
)

logger = logging.getLogger(__name__)


def _hour_to_bucket(hour: int) -> int | None:
    """Map an hour (0-23) to a heatmap row index (0-7), or None if outside tracked hours.

    Buckets:
      row 0: 10-11
      row 1: 12-13
      row 2: 14-15
      row 3: 16-17
      row 4: 18-19
      row 5: 20-21
      row 6: 22-23
      row 7: 00-01
    Hours 2-9 are not tracked (return None).
    """
    if 10 <= hour <= 23:
        return (hour - 10) // 2
    if hour <= 1:
        return 7
    return None


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

    # ------------------------------------------------------------------
    # Load raw data
    # ------------------------------------------------------------------
    users: list[User] = list((await db.execute(select(User))).scalars().all())
    races: list[Race] = list((await db.execute(select(Race))).scalars().all())
    participants: list[Participant] = list((await db.execute(select(Participant))).scalars().all())
    training_sessions: list[TrainingSession] = list(
        (await db.execute(select(TrainingSession))).scalars().all()
    )

    # ------------------------------------------------------------------
    # Shared derived data (used by KPIs, weekly, and heatmaps)
    # ------------------------------------------------------------------
    # Participant count per race_id (str key for UUID compatibility)
    race_participant_counts: dict[str, int] = {}
    for p in participants:
        key = str(p.race_id)
        race_participant_counts[key] = race_participant_counts.get(key, 0) + 1

    finished_races = [r for r in races if r.status == RaceStatus.FINISHED]

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    total_users = len(users)

    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_users_this_month = sum(
        1 for u in users if u.created_at is not None and _ensure_utc(u.created_at) >= first_of_month
    )

    cutoff_30d = now - timedelta(days=30)
    active_users_30d = sum(
        1 for u in users if u.last_seen is not None and _ensure_utc(u.last_seen) >= cutoff_30d
    )
    active_users_pct = round(active_users_30d / total_users * 100, 1) if total_users > 0 else 0.0

    total_races_finished = len(finished_races)

    if finished_races:
        finished_ids = {str(r.id) for r in finished_races}
        counts_for_finished = [race_participant_counts.get(rid, 0) for rid in finished_ids]
        avg_participants = (
            round(sum(counts_for_finished) / len(counts_for_finished), 1)
            if counts_for_finished
            else 0.0
        )
    else:
        avg_participants = 0.0

    total_solo = len(training_sessions)
    solo_finished = sum(
        1 for ts in training_sessions if ts.status == TrainingSessionStatus.FINISHED
    )
    solo_abandoned = sum(
        1 for ts in training_sessions if ts.status == TrainingSessionStatus.ABANDONED
    )
    denom = solo_finished + solo_abandoned
    solo_completion_pct = round(solo_finished / denom * 100, 1) if denom > 0 else 0.0

    kpis = {
        "total_users": total_users,
        "new_users_this_month": new_users_this_month,
        "active_users_30d": active_users_30d,
        "active_users_pct": active_users_pct,
        "total_races_finished": total_races_finished,
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

    weekly = {
        "weeks": [f"W{wk[1]}" for wk in week_keys],
        "new_users": [week_new_users[wk] for wk in week_keys],
        "races": [week_races[wk] for wk in week_keys],
        "solo": [week_solo[wk] for wk in week_keys],
        "solo_finished": [week_solo_finished[wk] for wk in week_keys],
        "solo_abandoned": [week_solo_abandoned[wk] for wk in week_keys],
        "avg_participants": [
            round(week_race_participant_sum[wk] / week_race_count[wk], 1)
            if week_race_count[wk] > 0
            else 0.0
            for wk in week_keys
        ],
    }

    # ------------------------------------------------------------------
    # Heatmaps (8 rows x 7 cols)
    # ------------------------------------------------------------------
    # row = hour bucket, col = weekday (0=Mon, 6=Sun)
    race_grid = [[0] * 7 for _ in range(8)]
    solo_grid = [[0] * 7 for _ in range(8)]

    for r in races:
        if r.started_at is None or r.status not in (RaceStatus.RUNNING, RaceStatus.FINISHED):
            continue
        started = _ensure_utc(r.started_at)
        bucket = _hour_to_bucket(started.hour)
        if bucket is None:
            continue
        col = started.weekday()
        race_grid[bucket][col] += race_participant_counts.get(str(r.id), 0)

    for ts in training_sessions:
        if ts.created_at is None:
            continue
        created = _ensure_utc(ts.created_at)
        bucket = _hour_to_bucket(created.hour)
        if bucket is None:
            continue
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

    return {
        "kpis": kpis,
        "weekly": weekly,
        "heatmaps": heatmaps,
        "timezones": tz_list,
    }


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware. Treat naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
