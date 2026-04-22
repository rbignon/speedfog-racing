"""Feedback API: CSAT submission and prompt-flag management."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Feedback,
    FeedbackSource,
    Participant,
    ParticipantStatus,
    User,
)
from speedfog_racing.schemas import FeedbackCreate, FeedbackResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=FeedbackResponse)
async def create_feedback(
    payload: FeedbackCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Feedback:
    """Submit feedback (rating + optional comment) from a signed-in user."""
    if payload.source == FeedbackSource.POST_FIRST_RACE:
        if payload.race_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="race_id required for post_first_race source",
            )
        result = await db.execute(
            select(Participant).where(
                Participant.race_id == payload.race_id,
                Participant.user_id == user.id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a participant of this race",
            )
    else:
        if payload.race_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="race_id must be null for user_menu source",
            )

    count = await db.scalar(
        select(func.count())
        .select_from(Participant)
        .where(
            Participant.user_id == user.id,
            Participant.status.in_([ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED]),
        )
    )

    feedback = Feedback(
        user_id=user.id,
        rating=payload.rating,
        comment=payload.comment,
        source=payload.source,
        race_id=payload.race_id,
        races_played_at_feedback=int(count or 0),
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    logger.info(
        "Feedback submitted: user=%s source=%s rating=%s",
        user.id,
        payload.source.value,
        payload.rating,
    )
    return feedback
