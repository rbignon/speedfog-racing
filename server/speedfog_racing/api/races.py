"""Race management API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import (
    get_current_user,
    get_current_user_optional,
    get_user_by_twitch_username,
)
from speedfog_racing.database import get_db
from speedfog_racing.models import Invite, Participant, Race, RaceStatus, User
from speedfog_racing.schemas import (
    AddParticipantRequest,
    AddParticipantResponse,
    CreateRaceRequest,
    DownloadInfo,
    GenerateZipsResponse,
    InviteResponse,
    ParticipantResponse,
    RaceDetailResponse,
    RaceListResponse,
    RaceResponse,
    StartRaceRequest,
    UserResponse,
)
from speedfog_racing.services import (
    assign_seed_to_race,
    generate_race_zips,
    get_participant_zip_path,
)

router = APIRouter()


def _user_response(user: User) -> UserResponse:
    """Convert User model to UserResponse."""
    return UserResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
    )


def _participant_response(participant: Participant) -> ParticipantResponse:
    """Convert Participant model to ParticipantResponse."""
    return ParticipantResponse(
        id=participant.id,
        user=_user_response(participant.user),
        status=participant.status,
        current_layer=participant.current_layer,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
    )


def _race_response(race: Race) -> RaceResponse:
    """Convert Race model to RaceResponse."""
    return RaceResponse(
        id=race.id,
        name=race.name,
        organizer=_user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        scheduled_start=race.scheduled_start,
        created_at=race.created_at,
        participant_count=len(race.participants),
    )


def _race_detail_response(race: Race) -> RaceDetailResponse:
    """Convert Race model to RaceDetailResponse."""
    return RaceDetailResponse(
        id=race.id,
        name=race.name,
        organizer=_user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        scheduled_start=race.scheduled_start,
        created_at=race.created_at,
        participant_count=len(race.participants),
        seed_total_layers=race.seed.total_layers if race.seed else None,
        participants=[_participant_response(p) for p in race.participants],
    )


async def _get_race_or_404(
    db: AsyncSession, race_id: UUID, load_participants: bool = False
) -> Race:
    """Get race by ID or raise 404."""
    query = select(Race).where(Race.id == race_id)
    if load_participants:
        query = query.options(
            selectinload(Race.organizer),
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
    else:
        query = query.options(selectinload(Race.organizer), selectinload(Race.seed))

    result = await db.execute(query)
    race = result.scalar_one_or_none()

    if not race:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Race not found")

    return race


def _require_organizer(race: Race, user: User) -> None:
    """Raise 403 if user is not the race organizer."""
    if race.organizer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the race organizer can perform this action",
        )


@router.post("", response_model=RaceResponse, status_code=status.HTTP_201_CREATED)
async def create_race(
    request: CreateRaceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Create a new race with a seed from the specified pool."""
    # Create race
    race = Race(
        name=request.name,
        organizer_id=user.id,
        organizer=user,
        config=request.config,
        status=RaceStatus.DRAFT,
    )
    db.add(race)
    await db.flush()

    # Assign seed from pool
    try:
        await assign_seed_to_race(db, race, request.pool_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    await db.commit()

    # Reload race with relationships
    race = await _get_race_or_404(db, race.id, load_participants=True)

    return _race_response(race)


@router.get("", response_model=RaceListResponse)
async def list_races(
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user_optional),
) -> RaceListResponse:
    """List races, optionally filtered by status."""
    query = select(Race).options(
        selectinload(Race.organizer),
        selectinload(Race.seed),
        selectinload(Race.participants),
    )

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        try:
            status_enums = [RaceStatus(s) for s in statuses]
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status value: {e}",
            ) from e
        query = query.where(Race.status.in_(status_enums))

    query = query.order_by(Race.created_at.desc())
    result = await db.execute(query)
    races = list(result.scalars().all())

    return RaceListResponse(races=[_race_response(r) for r in races])


@router.get("/{race_id}", response_model=RaceDetailResponse)
async def get_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user_optional),
) -> RaceDetailResponse:
    """Get race details with participants."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    return _race_detail_response(race)


@router.post("/{race_id}/participants", response_model=AddParticipantResponse)
async def add_participant(
    race_id: UUID,
    request: AddParticipantRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AddParticipantResponse:
    """Add a participant to a race.

    If the user exists, creates a Participant directly.
    If the user doesn't exist, creates an Invite.
    """
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    # Check race status
    if race.status not in (RaceStatus.DRAFT, RaceStatus.OPEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add participants to a race that has started",
        )

    # Check if user exists
    target_user = await get_user_by_twitch_username(db, request.twitch_username)

    if target_user:
        # Check if already a participant
        for p in race.participants:
            if p.user_id == target_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User is already a participant in this race",
                )

        # Create participant
        participant = Participant(
            race_id=race.id,
            user_id=target_user.id,
            user=target_user,
            race=race,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(participant)

        return AddParticipantResponse(participant=_participant_response(participant))

    else:
        # Check if invite already exists
        result = await db.execute(
            select(Invite).where(
                Invite.race_id == race.id,
                Invite.twitch_username.ilike(request.twitch_username),
                Invite.accepted == False,  # noqa: E712
            )
        )
        existing_invite = result.scalar_one_or_none()

        if existing_invite:
            return AddParticipantResponse(
                invite=InviteResponse(
                    token=existing_invite.token,
                    twitch_username=existing_invite.twitch_username,
                    race_id=race.id,
                )
            )

        # Create invite
        invite = Invite(
            race_id=race.id,
            twitch_username=request.twitch_username,
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)

        return AddParticipantResponse(
            invite=InviteResponse(
                token=invite.token,
                twitch_username=invite.twitch_username,
                race_id=race.id,
            )
        )


@router.delete("/{race_id}/participants/{participant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    race_id: UUID,
    participant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Remove a participant from a race."""
    race = await _get_race_or_404(db, race_id)
    _require_organizer(race, user)

    # Check race status
    if race.status not in (RaceStatus.DRAFT, RaceStatus.OPEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove participants from a race that has started",
        )

    # Find participant
    result = await db.execute(
        select(Participant).where(
            Participant.id == participant_id,
            Participant.race_id == race_id,
        )
    )
    participant = result.scalar_one_or_none()

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )

    await db.delete(participant)
    await db.commit()


@router.post("/{race_id}/start", response_model=RaceResponse)
async def start_race(
    race_id: UUID,
    request: StartRaceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Start the race countdown."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    # Check race status
    if race.status not in (RaceStatus.DRAFT, RaceStatus.OPEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Race has already started or finished",
        )

    # Update race
    race.scheduled_start = request.scheduled_start
    race.status = RaceStatus.COUNTDOWN

    await db.commit()
    await db.refresh(race)

    return _race_response(race)


# =============================================================================
# Zip Generation Endpoints
# =============================================================================


@router.post("/{race_id}/generate-zips", response_model=GenerateZipsResponse)
async def generate_zips(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GenerateZipsResponse:
    """Generate personalized zips for all participants."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    if not race.participants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Race has no participants",
        )

    try:
        zip_paths = await generate_race_zips(db, race)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed folder not found: {e}",
        ) from e

    # Build download URLs
    downloads = []
    for participant in race.participants:
        if participant.id in zip_paths:
            downloads.append(
                DownloadInfo(
                    participant_id=participant.id,
                    twitch_username=participant.user.twitch_username,
                    url=f"/api/races/{race_id}/download/{participant.mod_token}",
                )
            )

    return GenerateZipsResponse(downloads=downloads)


@router.get("/{race_id}/download/{mod_token}")
async def download_zip(
    race_id: UUID,
    mod_token: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download personalized zip for a participant."""
    result = await get_participant_zip_path(race_id, mod_token, db)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zip not found. Make sure the race organizer has generated the zips.",
        )

    zip_path, participant = result

    return FileResponse(
        path=zip_path,
        filename=f"speedfog_{participant.user.twitch_username}.zip",
        media_type="application/zip",
    )
