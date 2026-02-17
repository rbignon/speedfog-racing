"""Training session API routes."""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from speedfog_racing.api.helpers import user_response
from speedfog_racing.auth import get_current_user, get_current_user_optional
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    TrainingSession,
    TrainingSessionStatus,
    User,
)
from speedfog_racing.rate_limit import limiter
from speedfog_racing.schemas import (
    CreateTrainingRequest,
    PoolConfig,
    TrainingSessionDetailResponse,
    TrainingSessionResponse,
)
from speedfog_racing.services import get_pool_config
from speedfog_racing.services.seed_pack_service import (
    generate_seed_pack_on_demand_training,
    sanitize_filename,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found"
        )
    if session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not your training session"
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found"
        )
    return session


def _build_list_response(session: TrainingSession) -> TrainingSessionResponse:
    current_layer = 0
    if session.progress_nodes and session.seed.graph_json:
        nodes = session.seed.graph_json.get("nodes", {})
        for entry in session.progress_nodes:
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
    raw_config = get_pool_config(seed.pool_name)
    return TrainingSessionDetailResponse(
        id=session.id,
        user=user_response(session.user),
        status=session.status,
        pool_name=seed.pool_name,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        progress_nodes=session.progress_nodes,
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

    # Validate pool is a training pool
    raw_config = get_pool_config(body.pool_name)
    if not raw_config or raw_config.get("type", "race") != "training":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{body.pool_name}' is not a training pool",
        )

    try:
        session = await create_training_session(db, user.id, body.pool_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    return _build_detail_response(session)


@router.get("", response_model=list[TrainingSessionResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TrainingSessionResponse]:
    """List current user's training sessions (most recent first)."""
    result = await db.execute(
        select(TrainingSession)
        .options(*_session_load_options())
        .where(TrainingSession.user_id == user.id)
        .order_by(TrainingSession.created_at.desc())
    )
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

    session.status = TrainingSessionStatus.ABANDONED
    session.finished_at = datetime.now(UTC)
    await db.commit()

    # Reload for response
    session = await _get_session_or_404(db, session_id, user.id)
    return _build_detail_response(session)


@router.get("/{session_id}/pack")
async def download_pack(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Download seed pack for a training session."""
    session = await _get_session_or_404(db, session_id, user.id)
    if session.status != TrainingSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only download pack for active sessions",
        )

    try:
        temp_path = await asyncio.to_thread(generate_seed_pack_on_demand_training, session)
    except FileNotFoundError:
        logger.warning("Seed zip missing for training session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This seed pack is no longer available."
            " Seed files are periodically removed after use.",
        )

    return FileResponse(
        path=temp_path,
        filename=f"speedfog_training_{sanitize_filename(session.user.twitch_username)}.zip",
        media_type="application/zip",
        background=BackgroundTask(os.unlink, temp_path),
    )
