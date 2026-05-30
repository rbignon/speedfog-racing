"""Daily Seed API routes.

Daily seeds live in the regular ``races`` table; these endpoints are the
discovery surface for them. Regular ``/api/races`` listings exclude rows
where ``daily_date IS NOT NULL`` so the two surfaces never compete for
the same audience.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from speedfog_racing.api.helpers import format_pool_display_name, race_response
from speedfog_racing.api.races import _race_detail_response
from speedfog_racing.auth import get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Caster,
    DailySeedSchedule,
    DailyStreakFreeze,
    Participant,
    ParticipantStatus,
    Race,
    User,
    compute_late_join_deadlines,
)
from speedfog_racing.schemas import (
    DailyMyResult,
    DailyPodiumEntry,
    DailyWeekDay,
    DailyWeekResponse,
    RaceDetailResponse,
    RaceListResponse,
    RaceResponse,
    UserDailyStreakStats,
    WeeklyLeaderboardEntry,
    WeeklyLeaderboardResponse,
    WeeklyLeaderboardUser,
)
from speedfog_racing.services.daily_points_service import compute_weekly_leaderboard
from speedfog_racing.services.daily_seed_loop import daily_date_for
from speedfog_racing.services.daily_streak_service import qualifies_for_streak

router = APIRouter()


def _detail_options() -> tuple[ExecutableOption, ...]:
    """Eager-load every relationship that ``_race_detail_response`` reads."""
    return (
        selectinload(Race.organizer),
        selectinload(Race.seed),
        selectinload(Race.participants).selectinload(Participant.user),
        selectinload(Race.casters).selectinload(Caster.user),
        selectinload(Race.invites),
    )


@router.get("/today", response_model=RaceResponse)
async def get_today_daily(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> RaceResponse:
    """Return the running Daily Seed for the current UTC rotation day.

    Returns a ``Race`` summary (not ``RaceDetail``) because the home / dashboard
    surfaces only need the preview shape, and the dedicated ``/daily/{date}``
    page already pulls the full detail when needed.
    """
    today = daily_date_for(datetime.now(UTC))
    race = (
        await db.execute(select(Race).where(Race.daily_date == today).options(*_detail_options()))
    ).scalar_one_or_none()
    if race is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No daily seed today")
    return race_response(race, user=user)


@router.get("/recent", response_model=RaceListResponse)
async def get_recent_dailies(
    limit: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> RaceListResponse:
    """Return the most recent past Daily Seeds (excluding today)."""
    today = daily_date_for(datetime.now(UTC))
    result = await db.execute(
        select(Race)
        .where(Race.daily_date.is_not(None), Race.daily_date < today)
        .options(
            selectinload(Race.organizer),
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.casters).selectinload(Caster.user),
        )
        .order_by(Race.daily_date.desc())
        .limit(limit)
    )
    races = result.scalars().all()
    return RaceListResponse(races=[race_response(r, user) for r in races])


def _start_at_utc(d: date_type) -> datetime:
    return datetime(d.year, d.month, d.day, 8, 0, tzinfo=UTC)


def _ranked_finishers(parts: Iterable[Participant]) -> list[Participant]:
    """Finished participants ordered by (igt_ms ASC, finished_at ASC)."""
    return sorted(
        (p for p in parts if p.status == ParticipantStatus.FINISHED and p.igt_ms is not None),
        key=lambda p: (p.igt_ms, p.finished_at or datetime.max.replace(tzinfo=UTC)),
    )


def _build_podium(ranked: list[Participant]) -> list[DailyPodiumEntry]:
    return [
        DailyPodiumEntry(
            placement=i + 1,
            twitch_username=p.user.twitch_username,
            twitch_display_name=p.user.twitch_display_name,
            twitch_avatar_url=p.user.twitch_avatar_url,
            igt_ms=p.igt_ms,
        )
        for i, p in enumerate(ranked[:3])
    ]


def _my_result(
    parts: list[Participant],
    ranked: list[Participant],
    user: User | None,
    starters_count: int,
) -> DailyMyResult | None:
    if user is None:
        return None
    me = next((p for p in parts if p.user_id == user.id), None)
    if me is None:
        return None
    placement: int | None = None
    if me.status == ParticipantStatus.FINISHED:
        for i, p in enumerate(ranked):
            if p.id == me.id:
                placement = i + 1
                break
    return DailyMyResult(
        status=me.status,
        placement=placement,
        total_starters=starters_count,
        igt_ms=me.igt_ms if me.status == ParticipantStatus.FINISHED else None,
        death_count=me.death_count,
        qualifies=qualifies_for_streak(me.zone_history),
    )


@router.get("/week", response_model=DailyWeekResponse)
async def get_daily_week(
    anchor_date: date_type | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> DailyWeekResponse:
    """Return the seven-cell weekly grid centered on ``date`` (defaults to today)."""
    today = daily_date_for(datetime.now(UTC))
    anchor = anchor_date if anchor_date is not None else today
    week_start = anchor - timedelta(days=anchor.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    races_result = await db.execute(
        select(Race)
        .where(Race.daily_date.in_(week_dates))
        .options(
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
    )
    races_by_date: dict[date_type, Race] = {
        r.daily_date: r for r in races_result.scalars().all() if r.daily_date is not None
    }

    schedule_result = await db.execute(select(DailySeedSchedule))
    schedule_by_weekday: dict[int, DailySeedSchedule] = {
        row.weekday: row for row in schedule_result.scalars().all()
    }

    freeze_dates: set[date_type] = set()
    if user is not None:
        freeze_rows = await db.execute(
            select(DailyStreakFreeze.daily_date)
            .where(DailyStreakFreeze.user_id == user.id)
            .where(DailyStreakFreeze.daily_date.in_(week_dates))
        )
        freeze_dates = {d for (d,) in freeze_rows.all()}

    days: list[DailyWeekDay] = []
    for d in week_dates:
        weekday = d.weekday()
        race = races_by_date.get(d)
        schedule_row = schedule_by_weekday.get(weekday)
        scheduled_pool_name = schedule_row.pool_name if schedule_row else None
        scheduled_display = format_pool_display_name(schedule_row.pool) if schedule_row else None

        if race is not None:
            ranked = _ranked_finishers(race.participants)
            starters_count = sum(1 for p in race.participants if p.igt_ms > 0)
            cell_pool_name: str | None
            cell_pool_display: str | None
            if race.seed is not None:
                cell_pool_name = race.seed.pool_name
                cell_pool_display = format_pool_display_name(race.seed.pool)
            else:
                cell_pool_name = scheduled_pool_name
                cell_pool_display = scheduled_display
            _, race_ends_at = compute_late_join_deadlines(race)
            cell_state: Literal["past", "today", "future", "missing_past"] = (
                "today" if d == today else "past"
            )
            days.append(
                DailyWeekDay(
                    weekday=weekday,
                    date=d,
                    state=cell_state,
                    pool_name=cell_pool_name,
                    pool_display_name=cell_pool_display,
                    race_id=str(race.id),
                    started_at=race.started_at,
                    ends_at=race_ends_at,
                    starters_count=starters_count,
                    participants_count=len(race.participants),
                    podium=_build_podium(ranked),
                    my_result=_my_result(race.participants, ranked, user, starters_count),
                    freeze_protected=d in freeze_dates,
                )
            )
            continue

        if d > today:
            cell_state = "future"
        elif d == today:
            cell_state = "today"
        else:
            cell_state = "missing_past"

        started_at = _start_at_utc(d) if cell_state in {"today", "future"} else None
        ends_at = (started_at + timedelta(days=1)) if started_at else None
        days.append(
            DailyWeekDay(
                weekday=weekday,
                date=d,
                state=cell_state,
                pool_name=scheduled_pool_name,
                pool_display_name=scheduled_display,
                race_id=None,
                started_at=started_at,
                ends_at=ends_at,
                starters_count=0,
                participants_count=0,
                podium=[],
                my_result=None,
                freeze_protected=d in freeze_dates,
            )
        )

    earlier_exists = await db.execute(
        select(Race.id)
        .where(Race.daily_date.is_not(None))
        .where(Race.daily_date < week_start)
        .limit(1)
    )
    has_earlier = earlier_exists.scalar() is not None

    my_streak = UserDailyStreakStats.from_user(user) if user is not None else None

    return DailyWeekResponse(
        week_start=week_start,
        today=today,
        days=days,
        has_earlier=has_earlier,
        my_streak=my_streak,
    )


@router.get("/week/leaderboard", response_model=WeeklyLeaderboardResponse)
async def get_weekly_leaderboard(
    anchor: date_type = Query(alias="date"),
    db: AsyncSession = Depends(get_db),
) -> WeeklyLeaderboardResponse:
    """Return the weekly points leaderboard for the week containing ``date``."""
    monday = anchor - timedelta(days=anchor.weekday())
    data = await compute_weekly_leaderboard(db, monday)
    return WeeklyLeaderboardResponse(
        week_starting=data.week_starting,
        week_ending=data.week_ending,
        dailies_total=data.dailies_total,
        entries=[
            WeeklyLeaderboardEntry(
                rank=e.rank,
                user=WeeklyLeaderboardUser(
                    id=e.user.id,
                    twitch_username=e.user.twitch_username,
                    twitch_display_name=e.user.twitch_display_name,
                    twitch_avatar_url=e.user.twitch_avatar_url,
                    equipped_badge_id=e.user.equipped_badge_id,
                    equipped_name_template_id=e.user.equipped_name_template_id,
                    equipped_phantom_skin_id=e.user.equipped_phantom_skin_id,
                ),
                total_points=e.total_points,
                dailies_played=e.dailies_played,
                total_deaths=e.total_deaths,
                weapon_combos=e.weapon_combos,
            )
            for e in data.entries
        ],
    )


@router.get("/{daily_date}", response_model=RaceDetailResponse)
async def get_daily_by_date(
    daily_date: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> RaceDetailResponse:
    """Return the Daily Seed for a specific rotation date."""
    try:
        parsed_date = datetime.strptime(daily_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Daily seed not found"
        ) from exc
    race = (
        await db.execute(
            select(Race).where(Race.daily_date == parsed_date).options(*_detail_options())
        )
    ).scalar_one_or_none()
    if race is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily seed not found")
    return _race_detail_response(race, user=user)
