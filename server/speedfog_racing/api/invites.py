"""Invite management API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import Invite, Participant, Race, RaceStatus, User
from speedfog_racing.schemas import (
    AcceptInviteResponse,
    InviteInfoResponse,
    ParticipantResponse,
    UserResponse,
)

router = APIRouter()


async def _get_invite_or_404(db: AsyncSession, token: str) -> Invite:
    """Get invite by token or raise 404."""
    result = await db.execute(
        select(Invite)
        .where(Invite.token == token)
        .options(selectinload(Invite.race).selectinload(Race.organizer))
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    return invite


@router.get("/{token}", response_model=InviteInfoResponse)
async def get_invite_info(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InviteInfoResponse:
    """Get public information about an invite."""
    invite = await _get_invite_or_404(db, token)

    return InviteInfoResponse(
        token=invite.token,
        race_name=invite.race.name,
        organizer_name=invite.race.organizer.twitch_display_name
        or invite.race.organizer.twitch_username,
        race_status=invite.race.status,
        twitch_username=invite.twitch_username,
    )


@router.post("/{token}/accept", response_model=AcceptInviteResponse)
async def accept_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AcceptInviteResponse:
    """Accept an invite and become a participant.

    The authenticated user's Twitch username must match the invite.
    """
    invite = await _get_invite_or_404(db, token)

    # Check if invite is already accepted
    if invite.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite has already been accepted",
        )

    # Check race status
    if invite.race.status not in (RaceStatus.DRAFT, RaceStatus.OPEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot join a race that has already started or finished",
        )

    # Check username matches (case-insensitive)
    if user.twitch_username.lower() != invite.twitch_username.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invite is not for your account",
        )

    # Check if user is already a participant
    result = await db.execute(
        select(Participant).where(
            Participant.race_id == invite.race_id,
            Participant.user_id == user.id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already a participant in this race",
        )

    # Create participant
    participant = Participant(
        race_id=invite.race_id,
        user_id=user.id,
        user=user,
    )
    db.add(participant)

    # Mark invite as accepted
    invite.accepted = True

    await db.commit()
    await db.refresh(participant)

    return AcceptInviteResponse(
        participant=ParticipantResponse(
            id=participant.id,
            user=UserResponse(
                id=user.id,
                twitch_username=user.twitch_username,
                twitch_display_name=user.twitch_display_name,
                twitch_avatar_url=user.twitch_avatar_url,
            ),
            status=participant.status,
            current_layer=participant.current_layer,
            igt_ms=participant.igt_ms,
            death_count=participant.death_count,
        ),
        race_id=invite.race_id,
    )
