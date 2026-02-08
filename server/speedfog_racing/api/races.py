"""Race management API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.api.helpers import (
    caster_response,
    participant_response,
    race_response,
    user_response,
)
from speedfog_racing.auth import (
    get_current_user,
    get_current_user_optional,
    get_user_by_twitch_username,
)
from speedfog_racing.database import get_db
from speedfog_racing.models import Caster, Invite, Participant, Race, RaceStatus, User
from speedfog_racing.schemas import (
    AddCasterRequest,
    AddParticipantRequest,
    AddParticipantResponse,
    CasterResponse,
    CreateRaceRequest,
    DownloadInfo,
    GenerateSeedPacksResponse,
    InviteResponse,
    RaceDetailResponse,
    RaceListResponse,
    RaceResponse,
)
from speedfog_racing.services import (
    assign_seed_to_race,
    generate_race_seed_packs,
    get_participant_seed_pack_path,
)
from speedfog_racing.websocket import broadcast_race_start, broadcast_race_state_update

router = APIRouter()


def _race_detail_response(race: Race) -> RaceDetailResponse:
    """Convert Race model to RaceDetailResponse."""
    casters = (
        [caster_response(c) for c in race.casters]
        if hasattr(race, "casters") and race.casters is not None
        else []
    )
    return RaceDetailResponse(
        id=race.id,
        name=race.name,
        organizer=user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        created_at=race.created_at,
        participant_count=len(race.participants),
        seed_total_layers=race.seed.total_layers if race.seed else None,
        participants=[participant_response(p) for p in race.participants],
        casters=casters,
    )


async def _get_race_or_404(
    db: AsyncSession,
    race_id: UUID,
    load_participants: bool = False,
    load_casters: bool = False,
) -> Race:
    """Get race by ID or raise 404."""
    query = select(Race).where(Race.id == race_id)
    options = [selectinload(Race.organizer), selectinload(Race.seed)]
    if load_participants:
        options.append(selectinload(Race.participants).selectinload(Participant.user))
    if load_casters:
        options.append(selectinload(Race.casters).selectinload(Caster.user))
    query = query.options(*options)

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

    # Auto-add organizer as participant if requested
    if request.organizer_participates:
        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            user=user,
            race=race,
            color_index=0,
        )
        db.add(participant)

    await db.commit()

    # Reload race with relationships
    race = await _get_race_or_404(db, race.id, load_participants=True)

    return race_response(race)


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
        selectinload(Race.participants).selectinload(Participant.user),
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

    return RaceListResponse(races=[race_response(r) for r in races])


@router.get("/{race_id}", response_model=RaceDetailResponse)
async def get_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user_optional),
) -> RaceDetailResponse:
    """Get race details with participants and casters."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
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

        # Check if user is a caster (mutual exclusion)
        caster_result = await db.execute(
            select(Caster).where(
                Caster.race_id == race.id,
                Caster.user_id == target_user.id,
            )
        )
        if caster_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is a caster for this race",
            )

        # Organizer irreversibility: non-participating organizer can't join later
        if target_user.id == race.organizer_id:
            has_existing = any(p.user_id == target_user.id for p in race.participants)
            if not has_existing:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Non-participating organizer cannot join as participant"
                        " — DAG already visible"
                    ),
                )

        # Compute next color_index
        max_result = await db.execute(
            select(func.max(Participant.color_index)).where(Participant.race_id == race.id)
        )
        max_color = max_result.scalar()
        next_color = (max_color + 1) if max_color is not None else 0

        # Create participant
        participant = Participant(
            race_id=race.id,
            user_id=target_user.id,
            user=target_user,
            race=race,
            color_index=next_color,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(participant)

        return AddParticipantResponse(participant=participant_response(participant))

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


# =============================================================================
# Caster Management Endpoints
# =============================================================================


@router.post(
    "/{race_id}/casters",
    response_model=CasterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_caster(
    race_id: UUID,
    request: AddCasterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CasterResponse:
    """Add a caster to a race. Works at any race status."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    # Resolve target user
    target_user = await get_user_by_twitch_username(db, request.twitch_username)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if already a caster
    existing = await db.execute(
        select(Caster).where(
            Caster.race_id == race.id,
            Caster.user_id == target_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a caster for this race",
        )

    # Mutual exclusion: cannot be both caster and participant
    for p in race.participants:
        if p.user_id == target_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is a participant in this race",
            )

    caster = Caster(
        race_id=race.id,
        user_id=target_user.id,
        user=target_user,
    )
    db.add(caster)
    await db.commit()
    await db.refresh(caster)

    return caster_response(caster)


@router.delete(
    "/{race_id}/casters/{caster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_caster(
    race_id: UUID,
    caster_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Remove a caster from a race."""
    race = await _get_race_or_404(db, race_id)
    _require_organizer(race, user)

    result = await db.execute(
        select(Caster).where(
            Caster.id == caster_id,
            Caster.race_id == race_id,
        )
    )
    caster = result.scalar_one_or_none()

    if not caster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Caster not found",
        )

    await db.delete(caster)
    await db.commit()


@router.post("/{race_id}/start", response_model=RaceResponse)
async def start_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Start the race immediately."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
    _require_organizer(race, user)

    # Check race status
    if race.status not in (RaceStatus.DRAFT, RaceStatus.OPEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Race has already started or finished",
        )

    race.status = RaceStatus.RUNNING

    await db.commit()
    await db.refresh(race)

    # Notify connected clients
    await broadcast_race_start(race_id)
    await broadcast_race_state_update(race_id, race)

    return race_response(race)


@router.post("/{race_id}/open", response_model=RaceResponse)
async def open_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Transition race from DRAFT to OPEN."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
    _require_organizer(race, user)

    if race.status != RaceStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft races can be opened",
        )

    race.status = RaceStatus.OPEN
    await db.commit()
    await db.refresh(race)

    await broadcast_race_state_update(race_id, race)

    return race_response(race)


# =============================================================================
# Seed Pack Generation Endpoints
# =============================================================================


@router.post("/{race_id}/generate-seed-packs", response_model=GenerateSeedPacksResponse)
async def generate_seed_packs(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GenerateSeedPacksResponse:
    """Generate personalized seed packs for all participants."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    if not race.participants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Race has no participants",
        )

    try:
        seed_pack_paths = await generate_race_seed_packs(db, race)
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
        if participant.id in seed_pack_paths:
            downloads.append(
                DownloadInfo(
                    participant_id=participant.id,
                    twitch_username=participant.user.twitch_username,
                    url=f"/api/races/{race_id}/download/{participant.mod_token}",
                )
            )

    return GenerateSeedPacksResponse(downloads=downloads)


@router.get("/{race_id}/my-seed-pack")
async def download_my_seed_pack(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Download the authenticated user's personalized seed pack for a race."""
    # Find participant by race_id and user_id
    result = await db.execute(
        select(Participant)
        .where(Participant.race_id == race_id, Participant.user_id == user.id)
        .options(selectinload(Participant.user))
    )
    participant = result.scalar_one_or_none()

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this race",
        )

    seed_pack_result = await get_participant_seed_pack_path(race_id, participant.mod_token, db)

    if seed_pack_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seed packs not generated yet",
        )

    seed_pack_path, _ = seed_pack_result

    return FileResponse(
        path=seed_pack_path,
        filename=f"speedfog_{user.twitch_username}.zip",
        media_type="application/zip",
    )


@router.get("/{race_id}/download/{mod_token}")
async def download_seed_pack(
    race_id: UUID,
    mod_token: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download personalized seed pack for a participant."""
    result = await get_participant_seed_pack_path(race_id, mod_token, db)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seed pack not found. Make sure the organizer has generated the seed packs.",
        )

    seed_pack_path, participant = result

    return FileResponse(
        path=seed_pack_path,
        filename=f"speedfog_{participant.user.twitch_username}.zip",
        media_type="application/zip",
    )
