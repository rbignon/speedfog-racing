"""Race management API routes."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import StreamingResponse

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
from speedfog_racing.database import async_session_maker, get_db
from speedfog_racing.discord import (
    create_scheduled_event,
    delete_scheduled_event,
    fire_race_finished_notifications,
    notify_race_created,
    notify_race_started,
    set_event_status,
    update_scheduled_event,
)
from speedfog_racing.models import (
    Caster,
    Invite,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.schemas import (
    AddCasterRequest,
    AddParticipantRequest,
    AddParticipantResponse,
    CasterResponse,
    CreateRaceRequest,
    InviteResponse,
    ParticipantResponse,
    PendingInviteResponse,
    PoolConfig,
    RaceDetailResponse,
    RaceListResponse,
    RaceResponse,
    UpdateRaceRequest,
)
from speedfog_racing.services import (
    assign_seed_to_race,
    generate_player_config,
    get_pool_config,
    reroll_seed_for_race,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.services.seed_pack_service import (
    sanitize_filename,
    stream_seed_pack_with_config,
)
from speedfog_racing.websocket import broadcast_race_start, broadcast_race_state_update
from speedfog_racing.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _seed_total_nodes(seed: Seed) -> int:
    """Compute total node count from graph_json."""
    gj = seed.graph_json or {}
    total = gj.get("total_nodes")
    if total is not None:
        return int(total)
    nodes = gj.get("nodes", {})
    return len(nodes) if isinstance(nodes, dict) else 0


def _seed_total_paths(seed: Seed) -> int:
    """Compute total path count from graph_json."""
    gj = seed.graph_json or {}
    return int(gj.get("total_paths", 0))


def _race_detail_response(race: Race, user: User | None = None) -> RaceDetailResponse:
    """Convert Race model to RaceDetailResponse."""
    casters = (
        [caster_response(c) for c in race.casters]
        if hasattr(race, "casters") and race.casters is not None
        else []
    )
    is_organizer = user is not None and race.organizer_id == user.id
    pending_invites = (
        [
            PendingInviteResponse(
                id=inv.id,
                twitch_username=inv.twitch_username,
                created_at=inv.created_at,
                token=inv.token if is_organizer else None,
            )
            for inv in race.invites
            if not inv.accepted
        ]
        if hasattr(race, "invites") and race.invites is not None
        else []
    )
    pool_config = None
    if race.seed:
        raw = get_pool_config(race.seed.pool_name)
        if raw is not None:
            pool_config = PoolConfig(**raw)
    return RaceDetailResponse(
        id=race.id,
        name=race.name,
        organizer=user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        is_public=race.is_public,
        open_registration=race.open_registration,
        max_participants=race.max_participants,
        created_at=race.created_at,
        scheduled_at=race.scheduled_at,
        started_at=race.started_at,
        seeds_released_at=race.seeds_released_at,
        participant_count=len(race.participants),
        seed_number=race.seed.seed_number if race.seed else None,
        seed_total_layers=race.seed.total_layers if race.seed else None,
        seed_total_nodes=_seed_total_nodes(race.seed) if race.seed else None,
        seed_total_paths=_seed_total_paths(race.seed) if race.seed else None,
        participants=[participant_response(p) for p in race.participants],
        casters=casters,
        pending_invites=pending_invites,
        pool_config=pool_config,
    )


async def _get_race_or_404(
    db: AsyncSession,
    race_id: UUID,
    load_participants: bool = False,
    load_casters: bool = False,
    load_invites: bool = False,
) -> Race:
    """Get race by ID or raise 404."""
    query = select(Race).where(Race.id == race_id)
    options = [selectinload(Race.organizer), selectinload(Race.seed)]
    if load_participants:
        options.append(selectinload(Race.participants).selectinload(Participant.user))
    if load_casters:
        options.append(selectinload(Race.casters).selectinload(Caster.user))
    if load_invites:
        options.append(selectinload(Race.invites))
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


async def _transition_status(
    db: AsyncSession,
    race: Race,
    expected_statuses: list[RaceStatus],
    new_status: RaceStatus,
    **extra_fields: object,
) -> None:
    """Atomically transition race status with optimistic locking.

    Uses UPDATE ... WHERE status IN (...) AND version = :v to prevent
    concurrent status mutations. Raises 409 on conflict.

    Note: updates the in-memory race object directly. Callers must
    commit (or flush) before any ORM query that might refresh the race.
    """
    current_version = race.version
    values: dict[str, object] = {
        "status": new_status,
        "version": current_version + 1,
        **extra_fields,
    }
    result = await db.execute(
        update(Race)
        .where(
            Race.id == race.id,
            Race.status.in_(expected_statuses),
            Race.version == current_version,
        )
        .values(**values)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Race was modified concurrently, please retry",
        )
    # Sync the in-memory object
    race.status = new_status
    race.version = current_version + 1
    for k, v in extra_fields.items():
        setattr(race, k, v)


@router.post("", response_model=RaceResponse, status_code=status.HTTP_201_CREATED)
async def create_race(
    request: CreateRaceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Create a new race with a seed from the specified pool."""
    if user.role not in {UserRole.ORGANIZER, UserRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to create races",
        )

    # Validate scheduled_at is not in the past
    if request.scheduled_at is not None:
        scheduled = request.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=UTC)
        if scheduled < datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled time cannot be in the past",
            )

    # Create race
    race = Race(
        name=request.name,
        organizer_id=user.id,
        organizer=user,
        config=request.config,
        status=RaceStatus.SETUP,
        scheduled_at=request.scheduled_at,
        is_public=request.is_public,
        open_registration=request.open_registration,
        max_participants=request.max_participants,
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

    # Fire-and-forget Discord notification (public races only)
    if race.is_public:
        scheduled_str = f"<t:{int(race.scheduled_at.timestamp())}:F>" if race.scheduled_at else None
        task = asyncio.create_task(
            notify_race_created(
                race_name=race.name,
                race_id=str(race.id),
                pool_name=race.seed.pool_name if race.seed else None,
                organizer_name=race.organizer.twitch_display_name or race.organizer.twitch_username,
                organizer_avatar_url=race.organizer.twitch_avatar_url,
                scheduled_at=scheduled_str,
            )
        )
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    # Fire-and-forget Discord scheduled event (public races with scheduled_at)
    if race.is_public and race.scheduled_at:
        _race_id = race.id
        _race_name = race.name
        _scheduled_at = race.scheduled_at

        async def _create_discord_event() -> None:
            event_id = await create_scheduled_event(
                race_name=_race_name,
                race_id=str(_race_id),
                scheduled_at=_scheduled_at,
            )
            if event_id:
                async with async_session_maker() as s:
                    r = await s.get(Race, _race_id)
                    if r:
                        r.discord_event_id = event_id
                        await s.commit()

        ev_task = asyncio.create_task(_create_discord_event())
        ev_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    return race_response(race)


@router.get("", response_model=RaceListResponse)
async def list_races(
    status_filter: str | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user_optional),
) -> RaceListResponse:
    """List races, optionally filtered by status with pagination."""
    query = select(Race).options(
        selectinload(Race.organizer),
        selectinload(Race.seed),
        selectinload(Race.participants).selectinload(Participant.user),
        selectinload(Race.casters).selectinload(Caster.user),
    )

    # Only show public races in the listing
    query = query.where(Race.is_public.is_(True))

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

    # Sort depends on what statuses are requested
    finished_only = status_filter and all(s.strip() == "finished" for s in status_filter.split(","))
    if finished_only:
        # Recent results: most recent first
        query = query.order_by(
            Race.started_at.desc().nulls_last(),
            Race.created_at.desc(),
        )
    else:
        # Mixed listing: running first, then setup, then finished
        query = query.order_by(
            case(
                (Race.status == RaceStatus.RUNNING, 0),
                (Race.status == RaceStatus.SETUP, 1),
                else_=2,
            ),
            # Within setup: scheduled_at ASC (nulls last)
            case(
                (Race.scheduled_at.is_(None), 1),
                else_=0,
            ),
            Race.scheduled_at.asc(),
            Race.created_at.desc(),
        )

    # Pagination
    if limit is not None:
        # Count total before applying offset/limit
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        races = list(result.scalars().all())
        return RaceListResponse(
            races=[race_response(r) for r in races],
            total=total,
            has_more=(offset + limit) < total,
        )

    result = await db.execute(query)
    races = list(result.scalars().all())
    return RaceListResponse(races=[race_response(r) for r in races])


@router.get("/{race_id}", response_model=RaceDetailResponse)
async def get_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> RaceDetailResponse:
    """Get race details with participants and casters."""
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)


@router.patch("/{race_id}", response_model=RaceResponse)
async def update_race(
    race_id: UUID,
    request: UpdateRaceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Update race properties. Organizer only."""
    race = await _get_race_or_404(db, race_id, load_participants=True)
    _require_organizer(race, user)

    old_event_id = race.discord_event_id

    # is_public can be changed at any status
    if request.is_public is not None:
        race.is_public = request.is_public

    # scheduled_at only editable in SETUP (includes clearing via null)
    if "scheduled_at" in request.model_fields_set:
        if race.status != RaceStatus.SETUP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only update schedule for setup races",
            )
        if request.scheduled_at is not None:
            scheduled = request.scheduled_at
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=UTC)
            if scheduled < datetime.now(UTC):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Scheduled time cannot be in the past",
                )
        race.scheduled_at = request.scheduled_at
    await db.commit()

    # Sync Discord scheduled event
    if old_event_id:
        if not race.is_public or race.scheduled_at is None:
            # Race no longer qualifies → delete event
            race.discord_event_id = None
            await db.commit()
            task = asyncio.create_task(delete_scheduled_event(old_event_id))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        elif "scheduled_at" in request.model_fields_set and race.scheduled_at:
            # Time changed → update event
            task = asyncio.create_task(
                update_scheduled_event(old_event_id, scheduled_at=race.scheduled_at)
            )
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    elif race.is_public and race.scheduled_at:
        # Newly qualifies → create event
        _race_id = race.id
        _race_name = race.name
        _scheduled_at = race.scheduled_at

        async def _create_discord_event() -> None:
            event_id = await create_scheduled_event(
                race_name=_race_name,
                race_id=str(_race_id),
                scheduled_at=_scheduled_at,
            )
            if event_id:
                async with async_session_maker() as s:
                    r = await s.get(Race, _race_id)
                    if r:
                        r.discord_event_id = event_id
                        await s.commit()

        ev_task = asyncio.create_task(_create_discord_event())
        ev_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    race = await _get_race_or_404(db, race_id, load_participants=True)
    return race_response(race)


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
    if race.status not in (RaceStatus.SETUP,):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add participants to a race that has started",
        )

    # Check if user exists
    target_user = await get_user_by_twitch_username(db, request.twitch_username)

    if target_user:
        # Check if already a participant (DB query to avoid TOCTOU)
        existing_participant = await db.execute(
            select(Participant).where(
                Participant.race_id == race.id,
                Participant.user_id == target_user.id,
            )
        )
        if existing_participant.scalar_one_or_none():
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
                    detail="Non-participating organizer cannot join as participant",
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
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a participant in this race",
            )
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
    if race.status not in (RaceStatus.SETUP,):
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


@router.delete("/{race_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    race_id: UUID,
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Revoke a pending invite from a race."""
    race = await _get_race_or_404(db, race_id)
    _require_organizer(race, user)

    if race.status not in (RaceStatus.SETUP,):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke invites for a race that has started",
        )

    result = await db.execute(
        select(Invite).where(
            Invite.id == invite_id,
            Invite.race_id == race_id,
        )
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        )

    if invite.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke an accepted invite",
        )

    await db.delete(invite)
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


# =============================================================================
# Open Registration (Self Join / Leave)
# =============================================================================


@router.post(
    "/{race_id}/join",
    response_model=ParticipantResponse,
    status_code=status.HTTP_200_OK,
)
async def join_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ParticipantResponse:
    """Self-register as a participant in an open-registration race."""
    race = await _get_race_or_404(db, race_id, load_participants=True)

    if race.status != RaceStatus.SETUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only join a race in setup status",
        )

    if not race.open_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This race does not allow open registration",
        )

    # Check capacity
    if race.max_participants is not None and len(race.participants) >= race.max_participants:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Race is full",
        )

    # Check if already a participant
    existing_participant = await db.execute(
        select(Participant).where(
            Participant.race_id == race.id,
            Participant.user_id == user.id,
        )
    )
    if existing_participant.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a participant in this race",
        )

    # Mutual exclusion: cannot be both caster and participant
    caster_result = await db.execute(
        select(Caster).where(
            Caster.race_id == race.id,
            Caster.user_id == user.id,
        )
    )
    if caster_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are a caster for this race",
        )

    # Organizer irreversibility: non-participating organizer can't join
    if user.id == race.organizer_id:
        has_existing = any(p.user_id == user.id for p in race.participants)
        if not has_existing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Non-participating organizer cannot join as participant",
            )

    # Compute next color_index
    max_result = await db.execute(
        select(func.max(Participant.color_index)).where(Participant.race_id == race.id)
    )
    max_color = max_result.scalar()
    next_color = (max_color + 1) if max_color is not None else 0

    participant = Participant(
        race_id=race.id,
        user_id=user.id,
        user=user,
        race=race,
        color_index=next_color,
    )
    db.add(participant)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a participant in this race",
        )
    await db.refresh(participant)

    return participant_response(participant)


@router.post("/{race_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Self-remove from a race during setup."""
    race = await _get_race_or_404(db, race_id)

    if race.status != RaceStatus.SETUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only leave a race in setup status",
        )

    # Find participant
    result = await db.execute(
        select(Participant).where(
            Participant.race_id == race_id,
            Participant.user_id == user.id,
        )
    )
    participant = result.scalar_one_or_none()

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a participant in this race",
        )

    # Organizer cannot leave their own race
    if user.id == race.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organizer cannot leave their own race",
        )

    await db.delete(participant)
    await db.commit()


@router.post("/{race_id}/cast-join", response_model=RaceDetailResponse)
async def cast_join(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Self-register as a caster for a race."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)

    if race.status not in (RaceStatus.SETUP, RaceStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only join as caster during setup or running",
        )

    # Mutual exclusion: cannot be both participant and caster
    for p in race.participants:
        if p.user_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are a participant in this race",
            )

    # Check not already a caster
    for c in race.casters:
        if c.user_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already a caster for this race",
            )

    caster = Caster(race_id=race.id, user_id=user.id)
    db.add(caster)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a caster for this race",
        )

    # Expire cached race so reload fetches fresh casters
    db.expire(race)
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)


@router.post("/{race_id}/cast-leave", response_model=RaceDetailResponse)
async def cast_leave(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Self-remove as a caster from a race."""
    race = await _get_race_or_404(db, race_id)

    result = await db.execute(
        select(Caster).where(
            Caster.race_id == race.id,
            Caster.user_id == user.id,
        )
    )
    caster = result.scalar_one_or_none()

    if not caster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a caster for this race",
        )

    await db.delete(caster)
    await db.commit()

    db.expire(race)
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)


@router.post("/{race_id}/start", response_model=RaceResponse)
async def start_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Start the race immediately."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
    _require_organizer(race, user)

    if race.status != RaceStatus.SETUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Race has already started or finished",
        )

    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seeds must be released before starting the race",
        )

    await _transition_status(
        db,
        race,
        [RaceStatus.SETUP],
        RaceStatus.RUNNING,
        started_at=datetime.now(UTC),
    )

    await db.commit()
    await db.refresh(race)

    # Notify connected clients
    started_iso = race.started_at.isoformat() if race.started_at else None
    await broadcast_race_start(
        race_id,
        started_at=started_iso,
        graph_json=race.seed.graph_json if race.seed else None,
    )
    await broadcast_race_state_update(race_id, race)

    # Fire-and-forget Discord notification (public races only)
    if race.is_public:
        task = asyncio.create_task(
            notify_race_started(
                race_name=race.name,
                race_id=str(race.id),
                pool_name=race.seed.pool_name if race.seed else None,
                participant_count=len(race.participants),
                organizer_name=race.organizer.twitch_display_name or race.organizer.twitch_username,
                organizer_avatar_url=race.organizer.twitch_avatar_url,
            )
        )
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    # Fire-and-forget: set Discord event to ACTIVE
    if race.discord_event_id:
        ev_task = asyncio.create_task(set_event_status(race.discord_event_id, 2))
        ev_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    return race_response(race)


@router.post("/{race_id}/reroll-seed", response_model=RaceDetailResponse)
async def reroll_seed(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Re-roll the seed for a SETUP race."""
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    _require_organizer(race, user)

    if race.status not in (RaceStatus.SETUP,):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only re-roll seed for setup races",
        )

    try:
        await reroll_seed_for_race(db, race)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Optimistic locking: atomic version bump
    current_version = race.version
    result = await db.execute(
        update(Race)
        .where(
            Race.id == race.id,
            Race.version == current_version,
        )
        .values(version=current_version + 1, seed_id=race.seed_id, seeds_released_at=None)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Race was modified concurrently, please retry",
        )
    race.version = current_version + 1
    race.seeds_released_at = None
    await db.commit()

    # Re-fetch with all relationships
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)


@router.post("/{race_id}/release-seeds", response_model=RaceDetailResponse)
async def release_seeds(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Release seeds so participants can download their packs."""
    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    _require_organizer(race, user)

    if race.status != RaceStatus.SETUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only release seeds for setup races",
        )

    if race.seeds_released_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seeds are already released",
        )

    # Atomic update with optimistic locking
    now = datetime.now(UTC)
    current_version = race.version
    result = await db.execute(
        update(Race)
        .where(Race.id == race.id, Race.version == current_version)
        .values(seeds_released_at=now, version=current_version + 1)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Race was modified concurrently, please retry",
        )
    race.seeds_released_at = now
    race.version = current_version + 1
    await db.commit()

    # Notify connected clients
    await broadcast_race_state_update(race_id, race)

    race = await _get_race_or_404(
        db, race_id, load_participants=True, load_casters=True, load_invites=True
    )
    return _race_detail_response(race, user=user)


@router.post("/{race_id}/reset", response_model=RaceResponse)
async def reset_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Reset a race back to SETUP status, clearing all participant progress."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
    _require_organizer(race, user)

    if race.status not in (RaceStatus.RUNNING, RaceStatus.FINISHED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only reset a running or finished race",
        )

    # Close all WebSocket connections before mutating state
    await manager.close_room(race_id, code=1000, reason="Race reset")

    await _transition_status(
        db,
        race,
        [RaceStatus.RUNNING, RaceStatus.FINISHED],
        RaceStatus.SETUP,
        started_at=None,
    )

    for p in race.participants:
        p.status = ParticipantStatus.REGISTERED
        p.current_zone = None
        p.current_layer = 0
        p.igt_ms = 0
        p.death_count = 0
        p.finished_at = None
        p.zone_history = None

    await db.commit()

    # Re-query with eager-loaded relationships (refresh only reloads columns)
    race = await _get_race_or_404(db, race.id, load_participants=True)

    return race_response(race)


@router.post("/{race_id}/finish", response_model=RaceResponse)
async def finish_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Force finish a running race."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
    _require_organizer(race, user)

    if race.status != RaceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only force-finish a running race",
        )

    await _transition_status(db, race, [RaceStatus.RUNNING], RaceStatus.FINISHED)

    # Mark remaining playing participants as abandoned
    for p in race.participants:
        if p.status == ParticipantStatus.PLAYING:
            p.status = ParticipantStatus.ABANDONED

    await db.commit()

    # Re-query with eager-loaded relationships (refresh only reloads columns)
    race = await _get_race_or_404(db, race.id, load_participants=True, load_casters=True)

    # Push full race_state (status + zone_history) before status change
    # so spectators get everything atomically in one message.
    await broadcast_race_state_update(race_id, race)
    await manager.broadcast_race_status(race_id, "finished")

    fire_race_finished_notifications(race)

    return race_response(race)


@router.post("/{race_id}/abandon", response_model=RaceResponse)
async def abandon_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceResponse:
    """Abandon a running race as a participant."""
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)

    if race.status != RaceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only abandon a running race",
        )

    # Find current user's participation
    participant = next((p for p in race.participants if p.user_id == user.id), None)
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a participant in this race",
        )

    if participant.status not in (
        ParticipantStatus.REGISTERED,
        ParticipantStatus.READY,
        ParticipantStatus.PLAYING,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot abandon: current status is '{participant.status.value}'",
        )

    participant.status = ParticipantStatus.ABANDONED
    await db.commit()

    # Re-query with eager-loaded relationships
    race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)

    # Broadcast updates
    graph_json = race.seed.graph_json if race.seed else None
    await manager.broadcast_leaderboard(race_id, race.participants, graph_json=graph_json)
    await broadcast_race_state_update(race_id, race)

    # Check auto-finish
    race_transitioned = await check_race_auto_finish(db, race)
    if race_transitioned:
        race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
        await broadcast_race_state_update(race_id, race)
        await manager.broadcast_race_status(race_id, "finished")
        fire_race_finished_notifications(race)

    return race_response(race)


@router.delete("/{race_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a race and all associated data."""
    race = await _get_race_or_404(db, race_id)
    _require_organizer(race, user)

    await manager.close_room(race_id, code=4001, reason="Race deleted")

    # Delete invites explicitly (belt-and-suspenders with ORM cascade)
    await db.execute(delete(Invite).where(Invite.race_id == race_id))

    # Release seed back to pool only if the race was never started.
    # Started races (RUNNING/FINISHED) keep their seed consumed so it
    # cannot be reused — players have already seen it.
    if race.seed_id and race.status in (RaceStatus.SETUP,):
        result = await db.execute(select(Seed).where(Seed.id == race.seed_id))
        seed = result.scalar_one_or_none()
        if seed and seed.status != SeedStatus.DISCARDED:
            seed.status = SeedStatus.AVAILABLE

    discord_event_id = race.discord_event_id

    await db.delete(race)
    await db.commit()

    # Fire-and-forget: delete Discord scheduled event
    if discord_event_id:
        task = asyncio.create_task(delete_scheduled_event(discord_event_id))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


# =============================================================================
# Seed Pack Download Endpoints
# =============================================================================


@router.get("/{race_id}/my-seed-pack")
async def download_my_seed_pack(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the authenticated user's personalized seed pack for a race.

    Streams the original seed zip with an injected per-participant config.
    No temp file or full-file copy — uses ~64 KB of RAM.
    """
    race = await _get_race_or_404(db, race_id)

    # Gate download on seed release
    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeds have not been released yet",
        )

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

    if not race.seed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Race has no seed assigned",
        )

    try:
        config = generate_player_config(participant, race)
        stream, content_length = stream_seed_pack_with_config(Path(race.seed.folder_path), config)
    except FileNotFoundError:
        logger.warning("Seed zip missing for race %s (cleaned up)", race_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This seed pack is no longer available."
            " Seed files are removed after a race ends.",
        )

    filename = f"speedfog_{sanitize_filename(user.twitch_username)}.zip"
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(content_length),
        },
    )


@router.get("/{race_id}/download/{mod_token}")
async def download_seed_pack(
    race_id: UUID,
    mod_token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download personalized seed pack for a participant.

    Streams the pack on-demand. Requires authentication.
    Caller must be the participant, the race organizer, or a caster.
    """
    race = await _get_race_or_404(db, race_id)

    # Gate download on seed release
    if race.seeds_released_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeds have not been released yet",
        )

    # Find participant by mod_token
    result = await db.execute(
        select(Participant)
        .where(Participant.race_id == race_id, Participant.mod_token == mod_token)
        .options(selectinload(Participant.user))
    )
    participant = result.scalar_one_or_none()

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )

    # Authorize: participant themselves, organizer, or caster
    is_owner = participant.user_id == user.id
    if not is_owner:
        is_organizer = race.organizer_id == user.id
        is_caster = False
        if not is_organizer:
            caster_result = await db.execute(
                select(Caster).where(Caster.race_id == race_id, Caster.user_id == user.id)
            )
            is_caster = caster_result.scalar_one_or_none() is not None
        if not (is_organizer or is_caster):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to download this seed pack",
            )

    if not race.seed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Race has no seed assigned",
        )

    try:
        config = generate_player_config(participant, race)
        stream, content_length = stream_seed_pack_with_config(Path(race.seed.folder_path), config)
    except FileNotFoundError:
        logger.warning("Seed zip missing for race %s (cleaned up)", race_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This seed pack is no longer available."
            " Seed files are removed after a race ends.",
        )

    filename = f"speedfog_{sanitize_filename(participant.user.twitch_username)}.zip"
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(content_length),
        },
    )
