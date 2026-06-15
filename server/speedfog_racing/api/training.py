"""Training session API routes."""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import StreamingResponse

from speedfog_racing.api.helpers import format_pool_display_name, parse_enum_csv, user_response
from speedfog_racing.auth import get_current_user, get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.download_ticket import sign_download_ticket, verify_download_ticket
from speedfog_racing.models import (
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.rate_limit import limiter
from speedfog_racing.schemas import (
    CreateTrainingRequest,
    DownloadTicketResponse,
    GhostResponse,
    PoolConfig,
    TrainingSessionDetailResponse,
    TrainingSessionResponse,
)
from speedfog_racing.services import get_pool
from speedfog_racing.services.seed_pack_service import (
    generate_training_config,
    sanitize_filename,
    stream_seed_pack_with_config,
)
from speedfog_racing.services.training_service import create_training_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _session_load_options() -> list[Any]:
    return [
        selectinload(TrainingSession.user),
        selectinload(TrainingSession.seed),
    ]


async def _get_session_or_404(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> TrainingSession:
    """Load training session, verify ownership."""
    result = await db.execute(
        select(TrainingSession)
        .options(*_session_load_options())
        .where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solo session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your solo session")
    return session


async def _get_session_or_404_public(db: AsyncSession, session_id: uuid.UUID) -> TrainingSession:
    """Load training session without ownership check (public read-only)."""
    result = await db.execute(
        select(TrainingSession)
        .options(*_session_load_options())
        .where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solo session not found")
    return session


def _build_list_response(session: TrainingSession) -> TrainingSessionResponse:
    current_layer = 0
    if session.zone_history and session.seed.graph_json:
        nodes = session.seed.graph_json.get("nodes", {})
        for entry in session.zone_history:
            node_data = nodes.get(entry.get("node_id"), {})
            tier = node_data.get("tier")
            if isinstance(tier, int | float) and int(tier) > current_layer:
                current_layer = int(tier)
        if session.status == TrainingSessionStatus.FINISHED:
            current_layer = session.seed.total_layers

    return TrainingSessionResponse(
        id=session.id,
        user=user_response(session.user),
        status=session.status,
        pool_name=session.seed.pool_name,
        pool_display_name=format_pool_display_name(session.seed.pool),
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        created_at=session.created_at,
        finished_at=session.finished_at,
        seed_total_layers=session.seed.total_layers,
        seed_total_nodes=(
            session.seed.graph_json.get("total_nodes") if session.seed.graph_json else None
        ),
        current_layer=current_layer,
    )


def _build_detail_response(session: TrainingSession) -> TrainingSessionDetailResponse:
    seed = session.seed
    raw_config = seed.pool.config or None
    return TrainingSessionDetailResponse(
        id=session.id,
        user=user_response(session.user),
        status=session.status,
        pool_name=seed.pool_name,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        zone_history=session.zone_history,
        created_at=session.created_at,
        finished_at=session.finished_at,
        seed_number=seed.seed_number,
        seed_total_layers=seed.total_layers,
        seed_total_nodes=seed.graph_json.get("total_nodes") if seed.graph_json else None,
        seed_total_paths=seed.graph_json.get("total_paths") if seed.graph_json else None,
        graph_json=seed.graph_json,
        pool_config=PoolConfig(**raw_config) if raw_config else None,
    )


@router.post("", response_model=TrainingSessionDetailResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_session(
    request: Request,
    body: CreateTrainingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrainingSessionDetailResponse:
    """Create a new training session."""
    # SAFETY: TOCTOU race window exists (SELECT then INSERT without partial
    # unique index). Acceptable: training is single-user, rate-limited at
    # 10/min, and the frontend hides the creation form when active sessions
    # exist. A concurrent duplicate would be harmless (two active sessions).
    active_result = await db.execute(
        select(TrainingSession.id).where(
            TrainingSession.user_id == user.id,
            TrainingSession.status == TrainingSessionStatus.ACTIVE,
        )
    )
    if active_result.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active training session",
        )

    # Validate pool exists, is enabled, and is a training pool.
    pool = await get_pool(db, body.pool_name)
    raw_config = pool.config if pool and pool.config else None
    if not pool or not pool.enabled or not raw_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{body.pool_name}' is not available",
        )
    if raw_config.get("type", "race") != "training":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{body.pool_name}' is not a training mode",
        )

    try:
        session = await create_training_session(db, user.id, body.pool_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    return _build_detail_response(session)


@router.get("", response_model=list[TrainingSessionResponse])
async def list_sessions(
    # ``status_filter`` keeps the function body free of the ``fastapi.status``
    # shadow; the URL surface stays ``?status=`` via the alias.
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TrainingSessionResponse]:
    """List current user's training sessions (most recent first).

    ``status`` is an optional comma-separated list of
    ``TrainingSessionStatus`` values (e.g. ``active``) to restrict the
    response.
    """
    status_enums = parse_enum_csv(status_filter, TrainingSessionStatus)
    query = (
        select(TrainingSession)
        .options(*_session_load_options())
        .where(TrainingSession.user_id == user.id)
        .order_by(TrainingSession.created_at.desc())
    )
    if status_enums:
        query = query.where(TrainingSession.status.in_(status_enums))
    result = await db.execute(query)
    sessions = list(result.scalars().all())
    return [_build_list_response(s) for s in sessions]


@router.get("/{session_id}", response_model=TrainingSessionDetailResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user_optional),
) -> TrainingSessionDetailResponse:
    """Get training session detail (public read-only)."""
    session = await _get_session_or_404_public(db, session_id)
    return _build_detail_response(session)


@router.post("/{session_id}/abandon", response_model=TrainingSessionDetailResponse)
async def abandon_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrainingSessionDetailResponse:
    """Abandon an active training session."""
    session = await _get_session_or_404(db, session_id, user.id)
    if session.status != TrainingSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot abandon session in status '{session.status.value}'",
        )

    has_progress = bool(session.zone_history)
    session.status = (
        TrainingSessionStatus.ABANDONED if has_progress else TrainingSessionStatus.CANCELLED
    )
    session.finished_at = datetime.now(UTC)
    await db.commit()

    # Reload for response
    session = await _get_session_or_404(db, session_id, user.id)
    return _build_detail_response(session)


@router.get("/{session_id}/pack-ticket", response_model=DownloadTicketResponse)
async def create_pack_ticket(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DownloadTicketResponse:
    """Mint a short-lived signed ticket for a native training-pack download."""
    session = await _get_session_or_404(db, session_id, user.id)
    if session.status != TrainingSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only download pack for active sessions",
        )
    ticket = sign_download_ticket("training", user.id, session_id, datetime.now(UTC))
    return DownloadTicketResponse(ticket=ticket)


@router.get("/{session_id}/pack")
async def download_pack(
    session_id: uuid.UUID,
    t: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user_opt: User | None = Depends(get_current_user_optional),
) -> StreamingResponse:
    """Download seed pack for a training session.

    Auth via the bearer header or a signed ``?t=`` download ticket.
    """
    if t is not None:
        ticket_user_id = verify_download_ticket(t, "training", session_id, datetime.now(UTC))
        if ticket_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired download ticket",
            )
        user = await db.get(User, ticket_user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired download ticket",
            )
    elif user_opt is not None:
        user = user_opt
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session = await _get_session_or_404(db, session_id, user.id)
    if session.status != TrainingSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only download pack for active sessions",
        )

    try:
        config = generate_training_config(session)
        stream, content_length = stream_seed_pack_with_config(
            Path(session.seed.folder_path), config
        )
    except FileNotFoundError:
        logger.warning("Seed zip missing for training session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This seed pack is no longer available."
            " Seed files are periodically removed after use.",
        )

    filename = f"speedfog_training_{sanitize_filename(session.user.twitch_username)}.zip"
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(content_length),
        },
    )


@router.get("/{session_id}/ghosts", response_model=list[GhostResponse])
async def get_ghosts(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[GhostResponse]:
    """Get anonymous ghost data for all finished training sessions on the same seed."""
    # Load the target session to get its seed_id
    result = await db.execute(select(TrainingSession).where(TrainingSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solo session not found")

    # Find all other finished sessions on the same seed
    result = await db.execute(
        select(TrainingSession)
        .where(
            TrainingSession.seed_id == session.seed_id,
            TrainingSession.status == TrainingSessionStatus.FINISHED,
            TrainingSession.id != session_id,
            TrainingSession.zone_history.isnot(None),
        )
        .limit(100)
    )
    ghosts = list(result.scalars().all())

    return [
        GhostResponse(
            zone_history=g.zone_history or [],
            igt_ms=g.igt_ms,
            death_count=g.death_count,
        )
        for g in ghosts
    ]
