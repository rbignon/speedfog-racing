"""Daily Seed API routes.

Daily seeds live in the regular ``races`` table; these endpoints are the
discovery surface for them. Regular ``/api/races`` listings exclude rows
where ``daily_date IS NOT NULL`` so the two surfaces never compete for
the same audience.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from speedfog_racing.api.helpers import race_response
from speedfog_racing.api.races import _race_detail_response
from speedfog_racing.auth import get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.models import Caster, Participant, Race, User
from speedfog_racing.schemas import RaceDetailResponse, RaceListResponse, RaceResponse
from speedfog_racing.services.daily_seed_loop import daily_date_for

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
