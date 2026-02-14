<!-- markdownlint-disable MD036 MD001 -->

# Training Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add solo training mode where users practice on dedicated seed pools with full mod tracking, session history, and live DAG visualization.

**Architecture:** New `TrainingSession` model separate from `Race`. Dedicated WS endpoints (`/ws/training/{id}` for mod, `/ws/training/{id}/spectate` for web) using same protocol but simplified (no leaderboard, no multi-player). Training pools distinguished by `type = "training"` in their `config.toml`.

**Tech Stack:** Python/FastAPI (server), SvelteKit 5 (web), Rust (mod), SQLAlchemy 2.0, Alembic, pytest-asyncio

**Design doc:** `docs/plans/2026-02-14-training-mode-design.md`

---

### Task 1: TrainingSession Model + Enum

**Files:**

- Modify: `server/speedfog_racing/models.py`
- Test: `server/tests/test_training.py` (create)

**Step 1: Write the failing test**

Create `server/tests/test_training.py`:

```python
"""Tests for training mode."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
    generate_token,
)


@pytest.fixture
async def training_user(async_session):
    """A regular user for training."""
    async with async_session() as db:
        user = User(
            twitch_id="train_user_1",
            twitch_username="trainer",
            api_token=generate_token(),
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def training_seed(async_session, sample_graph_json):
    """A seed in a training pool."""
    async with async_session() as db:
        seed = Seed(
            seed_number="train_001",
            pool_name="training_standard",
            graph_json=sample_graph_json,
            total_layers=10,
            folder_path="/tmp/seed_train_001.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return seed


@pytest.mark.asyncio
async def test_create_training_session(async_session, training_user, training_seed):
    """TrainingSession can be created and persisted."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        assert session.id is not None
        assert session.status == TrainingSessionStatus.ACTIVE
        assert session.mod_token is not None
        assert len(session.mod_token) > 20
        assert session.igt_ms == 0
        assert session.death_count == 0
        assert session.progress_nodes is None
        assert session.finished_at is None


@pytest.mark.asyncio
async def test_training_session_seed_stays_available(
    async_session, training_user, training_seed
):
    """Creating a training session does NOT consume the seed."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

        # Reload seed
        result = await db.execute(select(Seed).where(Seed.id == training_seed.id))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.AVAILABLE
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_training.py -v -x`
Expected: FAIL — `ImportError: cannot import name 'TrainingSession'`

**Step 3: Write minimal implementation**

Add to `server/speedfog_racing/models.py`:

After `SeedStatus` enum, add:

```python
class TrainingSessionStatus(enum.Enum):
    """Training session lifecycle status."""

    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"
```

After the `Invite` class, add:

```python
class TrainingSession(Base):
    """A solo training session."""

    __tablename__ = "training_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seeds.id"), nullable=False
    )
    mod_token: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=generate_token
    )
    status: Mapped[TrainingSessionStatus] = mapped_column(
        Enum(TrainingSessionStatus), default=TrainingSessionStatus.ACTIVE
    )
    igt_ms: Mapped[int] = mapped_column(Integer, default=0)
    death_count: Mapped[int] = mapped_column(Integer, default=0)
    progress_nodes: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship()
    seed: Mapped["Seed"] = relationship()
```

Note: `progress_nodes` stores `list[dict]` like `[{"node_id": "abc", "igt_ms": 12345}, ...]` matching `Participant.zone_history` format for consistency.

**Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_training.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add server/speedfog_racing/models.py server/tests/test_training.py
git commit -m "feat(training): add TrainingSession model and enum"
```

---

### Task 2: Alembic Migration

**Files:**

- Create: `server/alembic/versions/xxxx_add_training_sessions.py` (auto-generated)

**Step 1: Generate migration**

Run: `cd server && uv run alembic revision --autogenerate -m "add training_sessions table"`

**Step 2: Review generated migration**

Read the generated file and verify it creates `training_sessions` table with all columns and the `trainingsessionstatus` enum type.

**Step 3: Run migration against test DB**

Run: `cd server && uv run alembic upgrade head`

**Step 4: Commit**

```bash
git add server/alembic/versions/
git commit -m "feat(training): add training_sessions migration"
```

---

### Task 3: Pool Type Filtering

**Files:**

- Modify: `server/speedfog_racing/services/seed_service.py` — `get_pool_config` reads `type`
- Modify: `server/speedfog_racing/api/pools.py` — accept `?type=` query param
- Modify: `server/speedfog_racing/schemas.py` — add `type` to `PoolConfig`
- Test: `server/tests/test_training.py`

**Step 1: Write the failing test**

Append to `server/tests/test_training.py`:

```python
from speedfog_racing.services.seed_service import get_pool_config


def test_pool_config_includes_type(tmp_path, monkeypatch):
    """get_pool_config reads the type field from config.toml."""
    pool_dir = tmp_path / "training_standard"
    pool_dir.mkdir()
    (pool_dir / "config.toml").write_text(
        '[display]\ntype = "training"\nestimated_duration = "~1h"\n'
    )
    monkeypatch.setattr(
        "speedfog_racing.services.seed_service.settings",
        type("S", (), {"seeds_pool_dir": str(tmp_path)})(),
    )
    config = get_pool_config("training_standard")
    assert config is not None
    assert config["type"] == "training"


def test_pool_config_defaults_to_race(tmp_path, monkeypatch):
    """Pools without type field default to 'race'."""
    pool_dir = tmp_path / "standard"
    pool_dir.mkdir()
    (pool_dir / "config.toml").write_text(
        '[display]\nestimated_duration = "~1h"\n'
    )
    monkeypatch.setattr(
        "speedfog_racing.services.seed_service.settings",
        type("S", (), {"seeds_pool_dir": str(tmp_path)})(),
    )
    config = get_pool_config("standard")
    assert config is not None
    assert config["type"] == "race"
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_training.py::test_pool_config_includes_type -v -x`
Expected: FAIL — `assert config["type"] == "training"` (key missing)

**Step 3: Implement pool type in seed service**

In `server/speedfog_racing/services/seed_service.py`, in `get_pool_config()`, add `type` to the returned dict:

After `display = data.get("display", {})` line, the return dict should include:

```python
"type": display.get("type", "race"),
```

as the first entry in the returned dict.

**Step 4: Add `type` to PoolConfig schema**

In `server/speedfog_racing/schemas.py`, add to `PoolConfig`:

```python
class PoolConfig(BaseModel):
    type: str = "race"
    estimated_duration: str | None = None
    # ... rest unchanged
```

**Step 5: Add query param filtering to pools API**

In `server/speedfog_racing/api/pools.py`, modify `list_pools`:

```python
@router.get("", response_model=dict[str, PoolStats])
async def list_pools(
    db: AsyncSession = Depends(get_db),
    pool_type: str | None = Query(None, alias="type"),
) -> dict[str, PoolStats]:
    """Get availability statistics for seed pools.

    Optional filter: ?type=race or ?type=training
    """
    stats = await get_pool_stats(db)

    result: dict[str, PoolStats] = {}
    for name, counts in stats.items():
        raw_config = get_pool_config(name)
        # Filter by type if requested
        if pool_type and raw_config:
            if raw_config.get("type", "race") != pool_type:
                continue
        elif pool_type and not raw_config:
            if pool_type != "race":
                continue
        result[name] = PoolStats(
            available=counts.get("available", 0),
            consumed=counts.get("consumed", 0),
            pool_config=PoolConfig(**raw_config) if raw_config else None,
        )

    return result
```

Add `Query` to the imports from fastapi.

**Step 6: Run all tests**

Run: `cd server && uv run pytest tests/test_training.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add server/speedfog_racing/services/seed_service.py server/speedfog_racing/api/pools.py server/speedfog_racing/schemas.py server/tests/test_training.py
git commit -m "feat(training): add pool type filtering"
```

---

### Task 4: Training Service

**Files:**

- Create: `server/speedfog_racing/services/training_service.py`
- Modify: `server/speedfog_racing/services/__init__.py`
- Test: `server/tests/test_training.py`

**Step 1: Write the failing tests**

Append to `server/tests/test_training.py`:

```python
from speedfog_racing.services.training_service import (
    get_training_seed,
    create_training_session,
)


@pytest.mark.asyncio
async def test_get_training_seed_excludes_played(async_session, training_user, training_seed):
    """get_training_seed skips seeds already played by the user."""
    async with async_session() as db:
        # First pick should work
        seed = await get_training_seed(db, "training_standard", training_user.id)
        assert seed is not None
        assert seed.id == training_seed.id

        # Create a session for this seed
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

    async with async_session() as db:
        # Second pick should return None (only seed is already played)
        seed = await get_training_seed(db, "training_standard", training_user.id)
        assert seed is None


@pytest.mark.asyncio
async def test_get_training_seed_resets_when_exhausted(
    async_session, training_user, training_seed
):
    """When all seeds are played, reset and pick from all."""
    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
        )
        db.add(session)
        await db.commit()

    async with async_session() as db:
        seed = await get_training_seed(
            db, "training_standard", training_user.id, allow_reset=True
        )
        assert seed is not None
        assert seed.id == training_seed.id


@pytest.mark.asyncio
async def test_create_training_session_service(
    async_session, training_user, training_seed
):
    """create_training_session creates a session and returns it with seed loaded."""
    async with async_session() as db:
        session = await create_training_session(
            db, training_user.id, "training_standard"
        )
        assert session.status == TrainingSessionStatus.ACTIVE
        assert session.seed_id == training_seed.id
        assert session.user_id == training_user.id
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_training.py::test_get_training_seed_excludes_played -v -x`
Expected: FAIL — `ImportError: cannot import name 'get_training_seed'`

**Step 3: Write the training service**

Create `server/speedfog_racing/services/training_service.py`:

```python
"""Training session management service."""

import logging
import random
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Seed, SeedStatus, TrainingSession, TrainingSessionStatus

logger = logging.getLogger(__name__)


async def get_training_seed(
    db: AsyncSession,
    pool_name: str,
    user_id: uuid.UUID,
    *,
    allow_reset: bool = True,
) -> Seed | None:
    """Get a random training seed, excluding seeds already played by this user.

    Args:
        db: Database session
        pool_name: Training pool name (e.g., "training_standard")
        user_id: User to exclude played seeds for
        allow_reset: If True and all seeds played, reset and pick from all

    Returns:
        A random Seed, or None if pool is empty
    """
    # Subquery: seeds already played by this user in this pool
    played_subq = (
        select(TrainingSession.seed_id)
        .join(Seed, TrainingSession.seed_id == Seed.id)
        .where(
            TrainingSession.user_id == user_id,
            Seed.pool_name == pool_name,
        )
    ).scalar_subquery()

    result = await db.execute(
        select(Seed).where(
            Seed.pool_name == pool_name,
            Seed.status == SeedStatus.AVAILABLE,
            Seed.id.not_in(played_subq),
        )
    )
    available = list(result.scalars().all())

    if available:
        return random.choice(available)

    if not allow_reset:
        return None

    # Pool exhausted for this user — reset: pick from all available seeds
    logger.info(f"User {user_id} exhausted training pool '{pool_name}', resetting")
    result = await db.execute(
        select(Seed).where(
            Seed.pool_name == pool_name,
            Seed.status == SeedStatus.AVAILABLE,
        )
    )
    all_seeds = list(result.scalars().all())
    return random.choice(all_seeds) if all_seeds else None


async def create_training_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    pool_name: str,
) -> TrainingSession:
    """Create a new training session with a random seed.

    Raises:
        ValueError: If no seeds are available in the pool
    """
    seed = await get_training_seed(db, pool_name, user_id)
    if seed is None:
        raise ValueError(f"No available seeds in training pool '{pool_name}'")

    session = TrainingSession(
        user_id=user_id,
        seed_id=seed.id,
    )
    db.add(session)
    await db.flush()

    # Eagerly load relationships for the response
    result = await db.execute(
        select(TrainingSession)
        .options(selectinload(TrainingSession.user), selectinload(TrainingSession.seed))
        .where(TrainingSession.id == session.id)
    )
    session = result.scalar_one()

    logger.info(
        f"Created training session {session.id} for user {user_id} "
        f"with seed {seed.seed_number} from pool '{pool_name}'"
    )
    return session
```

**Step 4: Export from services `__init__.py`**

Add to `server/speedfog_racing/services/__init__.py`:

```python
from speedfog_racing.services.training_service import (
    create_training_session,
    get_training_seed,
)
```

And add both to `__all__`.

**Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_training.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add server/speedfog_racing/services/training_service.py server/speedfog_racing/services/__init__.py server/tests/test_training.py
git commit -m "feat(training): add training service with anti-repetition seed selection"
```

---

### Task 5: Training Schemas

**Files:**

- Modify: `server/speedfog_racing/schemas.py`

**Step 1: Add request and response schemas**

Append to `server/speedfog_racing/schemas.py`:

```python
from speedfog_racing.models import TrainingSessionStatus  # add to existing imports


# =============================================================================
# Training Schemas
# =============================================================================


class CreateTrainingRequest(BaseModel):
    """Request to create a training session."""

    pool_name: str = "training_standard"


class TrainingSessionResponse(BaseModel):
    """Training session in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: TrainingSessionStatus
    pool_name: str
    igt_ms: int
    death_count: int
    created_at: datetime
    finished_at: datetime | None = None
    seed_total_layers: int | None = None
    seed_total_nodes: int | None = None


class TrainingSessionDetailResponse(BaseModel):
    """Detailed training session with graph data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: TrainingSessionStatus
    pool_name: str
    igt_ms: int
    death_count: int
    progress_nodes: list[dict[str, Any]] | None = None
    created_at: datetime
    finished_at: datetime | None = None
    seed_total_layers: int | None = None
    seed_total_nodes: int | None = None
    seed_total_paths: int | None = None
    graph_json: dict[str, Any] | None = None
    pool_config: PoolConfig | None = None
```

Note: `pool_name` and seed info are computed in the API endpoint from `session.seed`, not stored on the model.

**Step 2: Verify imports work**

Run: `cd server && uv run python -c "from speedfog_racing.schemas import CreateTrainingRequest, TrainingSessionResponse, TrainingSessionDetailResponse; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add server/speedfog_racing/schemas.py
git commit -m "feat(training): add training request/response schemas"
```

---

### Task 6: Training REST API

**Files:**

- Create: `server/speedfog_racing/api/training.py`
- Modify: `server/speedfog_racing/api/__init__.py`
- Test: `server/tests/test_training.py`

**Step 1: Write the failing tests**

Append to `server/tests/test_training.py`:

```python
from httpx import ASGITransport, AsyncClient
from speedfog_racing.main import app


@pytest.fixture
async def auth_client(training_user):
    """Authenticated HTTP client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["Authorization"] = f"Bearer {training_user.api_token}"
        yield client


@pytest.mark.asyncio
async def test_create_training_session_api(auth_client, training_seed):
    """POST /api/training creates a session."""
    resp = await auth_client.post(
        "/api/training", json={"pool_name": "training_standard"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "active"
    assert data["pool_name"] == "training_standard"
    assert data["seed_total_layers"] == 10


@pytest.mark.asyncio
async def test_list_training_sessions_api(auth_client, training_seed):
    """GET /api/training lists user's sessions."""
    # Create a session first
    await auth_client.post("/api/training", json={"pool_name": "training_standard"})

    resp = await auth_client.get("/api/training")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "active"


@pytest.mark.asyncio
async def test_get_training_session_detail_api(auth_client, training_seed):
    """GET /api/training/{id} returns detail with graph_json."""
    create_resp = await auth_client.post(
        "/api/training", json={"pool_name": "training_standard"}
    )
    session_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/training/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["graph_json"] is not None
    assert data["seed_total_layers"] == 10


@pytest.mark.asyncio
async def test_abandon_training_session_api(auth_client, training_seed):
    """POST /api/training/{id}/abandon transitions to ABANDONED."""
    create_resp = await auth_client.post(
        "/api/training", json={"pool_name": "training_standard"}
    )
    session_id = create_resp.json()["id"]

    resp = await auth_client.post(f"/api/training/{session_id}/abandon")
    assert resp.status_code == 200
    assert resp.json()["status"] == "abandoned"
    assert resp.json()["finished_at"] is not None
```

**Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_training.py::test_create_training_session_api -v -x`
Expected: FAIL — 404 (route not registered)

**Step 3: Create the training API module**

Create `server/speedfog_racing/api/training.py`:

```python
"""Training session API routes."""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from speedfog_racing.auth import get_current_user
from speedfog_racing.database import get_db
from speedfog_racing.models import (
    Seed,
    TrainingSession,
    TrainingSessionStatus,
    User,
)
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


def _session_load_options():
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your training session")
    return session


def _build_list_response(session: TrainingSession) -> TrainingSessionResponse:
    return TrainingSessionResponse(
        id=session.id,
        user=session.user,
        status=session.status,
        pool_name=session.seed.pool_name,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        created_at=session.created_at,
        finished_at=session.finished_at,
        seed_total_layers=session.seed.total_layers,
        seed_total_nodes=session.seed.graph_json.get("total_nodes") if session.seed.graph_json else None,
    )


def _build_detail_response(session: TrainingSession) -> TrainingSessionDetailResponse:
    seed = session.seed
    raw_config = get_pool_config(seed.pool_name)
    return TrainingSessionDetailResponse(
        id=session.id,
        user=session.user,
        status=session.status,
        pool_name=seed.pool_name,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        progress_nodes=session.progress_nodes,
        created_at=session.created_at,
        finished_at=session.finished_at,
        seed_total_layers=seed.total_layers,
        seed_total_nodes=seed.graph_json.get("total_nodes") if seed.graph_json else None,
        seed_total_paths=seed.graph_json.get("total_paths") if seed.graph_json else None,
        graph_json=seed.graph_json,
        pool_config=PoolConfig(**raw_config) if raw_config else None,
    )


@router.post("", response_model=TrainingSessionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateTrainingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrainingSessionDetailResponse:
    """Create a new training session."""
    # Validate pool is a training pool
    raw_config = get_pool_config(request.pool_name)
    if not raw_config or raw_config.get("type", "race") != "training":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{request.pool_name}' is not a training pool",
        )

    try:
        session = await create_training_session(db, user.id, request.pool_name)
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
    user: User = Depends(get_current_user),
) -> TrainingSessionDetailResponse:
    """Get training session detail."""
    session = await _get_session_or_404(db, session_id, user.id)
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

    temp_path = await asyncio.to_thread(
        generate_seed_pack_on_demand_training, session
    )

    return FileResponse(
        path=temp_path,
        filename=f"speedfog_training_{sanitize_filename(session.user.twitch_username)}.zip",
        media_type="application/zip",
        background=BackgroundTask(os.unlink, temp_path),
    )
```

**Step 4: Register the router**

In `server/speedfog_racing/api/__init__.py`, add:

```python
from speedfog_racing.api.training import router as training_router
```

and:

```python
api_router.include_router(training_router, prefix="/training", tags=["training"])
```

**Step 5: Create `generate_seed_pack_on_demand_training` stub**

In `server/speedfog_racing/services/seed_pack_service.py`, add:

```python
def generate_seed_pack_on_demand_training(session: "TrainingSession") -> Path:
    """Generate seed pack for a training session.

    Similar to generate_seed_pack_on_demand but:
    - Points WS URL to /ws/training/{session_id}
    - Adds training = true to config
    """
    from speedfog_racing.models import TrainingSession  # avoid circular

    seed_zip = Path(session.seed.folder_path)
    if not seed_zip.exists():
        raise FileNotFoundError(f"Seed zip not found: {seed_zip}")

    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".zip")
    temp_path = Path(temp_path_str)
    try:
        os.close(temp_fd)
        shutil.copy2(seed_zip, temp_path)

        top_dir = _get_top_dir(temp_path)

        config_content = generate_training_config(session)
        config_path = f"{top_dir}/lib/speedfog_race.toml" if top_dir else "lib/speedfog_race.toml"
        with zipfile.ZipFile(temp_path, "a") as zf:
            zf.writestr(config_path, config_content)

        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def generate_training_config(session: "TrainingSession") -> str:
    """Generate TOML config for training mod connection."""
    ws_url = settings.websocket_url
    return f"""[server]
url = "{ws_url}"
mod_token = "{session.mod_token}"
race_id = "{session.id}"
training = true

[overlay]
enabled = true
font_size = 32.0
background_color = "#141414"
background_opacity = 0.3
text_color = "#FFFFFF"
text_disabled_color = "#808080"
"""
```

**Step 6: Run tests**

Run: `cd server && uv run pytest tests/test_training.py -v`
Expected: PASS (API tests may need the seed to exist on disk for pack download — skip that test for now, it will be tested in integration)

**Step 7: Commit**

```bash
git add server/speedfog_racing/api/training.py server/speedfog_racing/api/__init__.py server/speedfog_racing/services/seed_pack_service.py server/tests/test_training.py
git commit -m "feat(training): add REST API endpoints"
```

---

### Task 7: Training WS Manager

**Files:**

- Create: `server/speedfog_racing/websocket/training_manager.py`

**Step 1: Create the training connection manager**

```python
"""Connection management for training sessions."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

SEND_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


@dataclass
class TrainingModConnection:
    websocket: WebSocket
    user_id: uuid.UUID


@dataclass
class TrainingSpectatorConnection:
    websocket: WebSocket
    user_id: uuid.UUID


@dataclass
class TrainingRoom:
    """A training session room with at most one mod and one spectator."""

    session_id: uuid.UUID
    mod: TrainingModConnection | None = None
    spectator: TrainingSpectatorConnection | None = None

    async def broadcast_to_spectator(self, message: str) -> None:
        """Send message to spectator if connected."""
        if self.spectator is None:
            return
        try:
            await asyncio.wait_for(
                self.spectator.websocket.send_text(message), timeout=SEND_TIMEOUT
            )
        except Exception:
            logger.warning(f"Failed to send to spectator for session {self.session_id}")
            try:
                await self.spectator.websocket.close()
            except Exception:
                pass
            self.spectator = None


class TrainingConnectionManager:
    """Manages training session WebSocket connections."""

    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, TrainingRoom] = {}

    def get_or_create_room(self, session_id: uuid.UUID) -> TrainingRoom:
        if session_id not in self.rooms:
            self.rooms[session_id] = TrainingRoom(session_id=session_id)
        return self.rooms[session_id]

    def get_room(self, session_id: uuid.UUID) -> TrainingRoom | None:
        return self.rooms.get(session_id)

    async def connect_mod(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
    ) -> None:
        room = self.get_or_create_room(session_id)
        room.mod = TrainingModConnection(websocket=websocket, user_id=user_id)
        logger.info(f"Mod connected to training session {session_id}")

    async def disconnect_mod(self, session_id: uuid.UUID) -> None:
        room = self.rooms.get(session_id)
        if room:
            room.mod = None
            if room.spectator is None:
                del self.rooms[session_id]
        logger.info(f"Mod disconnected from training session {session_id}")

    async def connect_spectator(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
    ) -> None:
        room = self.get_or_create_room(session_id)
        # Close previous spectator if any
        if room.spectator:
            try:
                await room.spectator.websocket.close()
            except Exception:
                pass
        room.spectator = TrainingSpectatorConnection(websocket=websocket, user_id=user_id)
        logger.info(f"Spectator connected to training session {session_id}")

    async def disconnect_spectator(self, session_id: uuid.UUID) -> None:
        room = self.rooms.get(session_id)
        if room:
            room.spectator = None
            if room.mod is None:
                del self.rooms[session_id]
        logger.info(f"Spectator disconnected from training session {session_id}")

    def is_mod_connected(self, session_id: uuid.UUID) -> bool:
        room = self.rooms.get(session_id)
        return room is not None and room.mod is not None


training_manager = TrainingConnectionManager()
```

**Step 2: Verify import**

Run: `cd server && uv run python -c "from speedfog_racing.websocket.training_manager import training_manager; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add server/speedfog_racing/websocket/training_manager.py
git commit -m "feat(training): add training WS connection manager"
```

---

### Task 8: Training WS Mod Handler

**Files:**

- Create: `server/speedfog_racing/websocket/training_mod.py`

**Step 1: Create the training mod WS handler**

This follows the same pattern as `mod.py` but simplified: no `ready`, no leaderboard broadcast, no race lifecycle.

```python
"""WebSocket handler for training mod connections."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from starlette.websockets import WebSocketDisconnect

from speedfog_racing.models import Seed, TrainingSession, TrainingSessionStatus
from speedfog_racing.services.layer_service import (
    compute_zone_update,
    get_layer_for_node,
)
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    AuthOkMessage,
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStartMessage,
    SeedInfo,
    ZoneUpdateMessage,
)
from speedfog_racing.websocket.training_manager import training_manager

MOD_AUTH_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 30.0
SEND_TIMEOUT = 5.0
STATUS_UPDATE_INTERVAL = 1.0

logger = logging.getLogger(__name__)


def _load_options():
    return [
        selectinload(TrainingSession.user),
        selectinload(TrainingSession.seed),
    ]


async def _load_session(
    db: AsyncSession, session_id: uuid.UUID
) -> TrainingSession | None:
    result = await db.execute(
        select(TrainingSession).options(*_load_options()).where(TrainingSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def handle_training_mod_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle mod WebSocket for a training session."""
    await websocket.accept()

    authenticated = False

    try:
        # Auth phase
        try:
            auth_data = await asyncio.wait_for(
                websocket.receive_text(), timeout=MOD_AUTH_TIMEOUT
            )
        except TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await _send_auth_error(websocket, "Invalid JSON")
            return

        if auth_msg.get("type") != "auth" or "mod_token" not in auth_msg:
            await _send_auth_error(websocket, "Invalid auth message")
            return

        mod_token = auth_msg["mod_token"]

        async with session_maker() as db:
            # Find session by mod_token
            result = await db.execute(
                select(TrainingSession)
                .options(*_load_options())
                .where(
                    TrainingSession.id == session_id,
                    TrainingSession.mod_token == mod_token,
                )
            )
            session = result.scalar_one_or_none()

            if not session:
                await _send_auth_error(websocket, "Invalid mod token or session")
                return

            if session.status != TrainingSessionStatus.ACTIVE:
                await _send_auth_error(websocket, "Training session is not active")
                return

            if training_manager.is_mod_connected(session_id):
                await _send_auth_error(websocket, "Already connected from another client")
                return

            user_id = session.user_id

            # Send auth_ok
            await _send_auth_ok(websocket, session)

            # Send race_start immediately (training starts right away)
            await websocket.send_text(RaceStartMessage().model_dump_json())

            # Send initial zone_update if session has progress
            seed = session.seed
            if seed and seed.graph_json:
                from speedfog_racing.services.layer_service import get_start_node

                last_node = None
                if session.progress_nodes:
                    last_node = session.progress_nodes[-1].get("node_id")
                if not last_node:
                    last_node = get_start_node(seed.graph_json)
                if last_node:
                    zone_update = compute_zone_update(
                        last_node,
                        seed.graph_json,
                        session.progress_nodes or [],
                    )
                    if zone_update:
                        await websocket.send_text(json.dumps(zone_update))

        # Register connection
        await training_manager.connect_mod(session_id, user_id, websocket)
        authenticated = True

        # Start heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "pong":
                    pass
                elif msg_type == "status_update":
                    await _handle_status_update(session_maker, session_id, msg)
                elif msg_type == "event_flag":
                    await _handle_event_flag(
                        websocket, session_maker, session_id, msg
                    )
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Training mod disconnected: session={session_id}")
    except Exception:
        logger.exception(f"Training mod handler error: session={session_id}")
    finally:
        if authenticated:
            await training_manager.disconnect_mod(session_id)


async def _heartbeat_loop(websocket: WebSocket) -> None:
    ping_json = PingMessage().model_dump_json()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await asyncio.wait_for(websocket.send_text(ping_json), timeout=SEND_TIMEOUT)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


async def _send_auth_error(websocket: WebSocket, message: str) -> None:
    logger.warning(f"Training auth error: {message}")
    try:
        await websocket.send_text(AuthErrorMessage(message=message).model_dump_json())
        await websocket.close(code=4003, reason=message)
    except Exception:
        pass


async def _send_auth_ok(websocket: WebSocket, session: TrainingSession) -> None:
    """Send auth_ok with training session info."""
    seed = session.seed

    event_ids = None
    if seed and seed.graph_json:
        event_map = seed.graph_json.get("event_map", {})
        if event_map:
            event_ids = sorted(int(k) for k in event_map.keys())
            finish = seed.graph_json.get("finish_event")
            if isinstance(finish, int) and finish not in event_ids:
                event_ids.append(finish)

    participant_info = ParticipantInfo(
        id=str(session.id),
        twitch_username=session.user.twitch_username,
        status="playing",
        current_zone=None,
        current_layer=0,
        current_layer_tier=None,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        color_index=0,
        mod_connected=True,
        zone_history=None,
    )

    message = AuthOkMessage(
        participant_id=str(session.id),
        race=RaceInfo(
            id=str(session.id),
            name="Training",
            status="running",
            started_at=session.created_at.isoformat() if session.created_at else None,
        ),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,
            event_ids=event_ids,
        ),
        participants=[participant_info],
    )
    await websocket.send_text(message.model_dump_json())


async def _handle_status_update(
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Update IGT and death count."""
    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            return

        session.igt_ms = msg.get("igt_ms", 0)
        session.death_count = msg.get("death_count", 0)
        await db.commit()

    # Broadcast to spectator
    await _broadcast_participant_update(session)


async def _handle_event_flag(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Handle fog gate traversal or boss kill event flag."""
    flag_id = msg.get("flag_id")
    if flag_id is None:
        return

    igt = msg.get("igt_ms", 0)
    node_id = None
    seed_graph = None

    async with session_maker() as db:
        session = await _load_session(db, session_id)
        if not session or session.status != TrainingSessionStatus.ACTIVE:
            return

        seed = session.seed
        if not seed or not seed.graph_json:
            return

        seed_graph = seed.graph_json
        event_map = seed_graph.get("event_map", {})
        finish_event = seed_graph.get("finish_event")

        # Check finish first
        if flag_id == finish_event:
            session.igt_ms = igt
            session.status = TrainingSessionStatus.FINISHED
            session.finished_at = datetime.now(UTC)
            await db.commit()

            # Broadcast finish to spectator
            await _broadcast_participant_update(session)
            await _broadcast_status_change(session_id, "finished")
            return

        # Fog gate traversal
        node_id = event_map.get(str(flag_id))
        if node_id is None:
            logger.warning(f"Unknown event flag {flag_id} in training session {session_id}")
            return

        # Check not duplicate
        old_history = session.progress_nodes or []
        if any(e.get("node_id") == node_id for e in old_history):
            return

        # Record
        node_layer = get_layer_for_node(node_id, seed_graph)
        session.igt_ms = igt
        session.progress_nodes = [*old_history, {"node_id": node_id, "igt_ms": igt}]
        await db.commit()

    # Broadcast to spectator
    if session:
        await _broadcast_participant_update(session)

    # Send zone_update to mod
    if node_id and seed_graph:
        zone_update = compute_zone_update(
            node_id, seed_graph, session.progress_nodes or []
        )
        if zone_update:
            try:
                await websocket.send_text(json.dumps(zone_update))
            except Exception:
                pass


async def _broadcast_participant_update(session: TrainingSession) -> None:
    """Send leaderboard_update (single participant) to spectator."""
    room = training_manager.get_room(session.id)
    if not room:
        return

    seed = session.seed
    tier = None
    current_zone = None
    if session.progress_nodes:
        current_zone = session.progress_nodes[-1].get("node_id")
        if current_zone and seed and seed.graph_json:
            from speedfog_racing.services.layer_service import get_tier_for_node

            tier = get_tier_for_node(current_zone, seed.graph_json)

    current_layer = 0
    if session.progress_nodes and seed and seed.graph_json:
        for entry in session.progress_nodes:
            nid = entry.get("node_id")
            if nid:
                layer = get_layer_for_node(nid, seed.graph_json)
                if layer > current_layer:
                    current_layer = layer

    info = ParticipantInfo(
        id=str(session.id),
        twitch_username=session.user.twitch_username,
        status=session.status.value,
        current_zone=current_zone,
        current_layer=current_layer,
        current_layer_tier=tier,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        color_index=0,
        mod_connected=room.mod is not None,
        zone_history=session.progress_nodes if session.status == TrainingSessionStatus.FINISHED else None,
    )

    message = LeaderboardUpdateMessage(participants=[info])
    await room.broadcast_to_spectator(message.model_dump_json())


async def _broadcast_status_change(session_id: uuid.UUID, new_status: str) -> None:
    """Notify spectator of status change."""
    room = training_manager.get_room(session_id)
    if not room:
        return

    message = json.dumps({"type": "race_status_change", "status": new_status})
    await room.broadcast_to_spectator(message)
```

**Step 2: Verify import**

Run: `cd server && uv run python -c "from speedfog_racing.websocket.training_mod import handle_training_mod_websocket; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add server/speedfog_racing/websocket/training_mod.py
git commit -m "feat(training): add training mod WS handler"
```

---

### Task 9: Training WS Spectator Handler

**Files:**

- Create: `server/speedfog_racing/websocket/training_spectator.py`

**Step 1: Create the training spectator handler**

```python
"""WebSocket handler for training session spectators (the player's web view)."""

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from starlette.websockets import WebSocketDisconnect

from speedfog_racing.auth import get_user_by_token
from speedfog_racing.models import TrainingSession, TrainingSessionStatus
from speedfog_racing.websocket.schemas import (
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PingMessage,
    RaceInfo,
    RaceStateMessage,
    SeedInfo,
)
from speedfog_racing.websocket.training_manager import training_manager

AUTH_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 30.0
SEND_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


async def handle_training_spectator_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Handle spectator WebSocket for a training session.

    Only the session owner can spectate their own training.
    """
    await websocket.accept()

    user_id = None

    try:
        # Auth required (not optional like race spectator)
        try:
            auth_data = await asyncio.wait_for(
                websocket.receive_text(), timeout=AUTH_TIMEOUT
            )
        except TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await websocket.close(code=4003, reason="Invalid JSON")
            return

        if auth_msg.get("type") != "auth" or not isinstance(auth_msg.get("token"), str):
            await websocket.close(code=4003, reason="Invalid auth")
            return

        async with session_maker() as db:
            user = await get_user_by_token(db, auth_msg["token"])
            if not user:
                await websocket.close(code=4003, reason="Invalid token")
                return

            user_id = user.id

            # Load session and verify ownership
            result = await db.execute(
                select(TrainingSession)
                .options(
                    selectinload(TrainingSession.user),
                    selectinload(TrainingSession.seed),
                )
                .where(TrainingSession.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                await websocket.close(code=4004, reason="Session not found")
                return

            if session.user_id != user_id:
                await websocket.close(code=4003, reason="Not your session")
                return

            # Send initial state
            await _send_initial_state(websocket, session)

        # Register connection
        await training_manager.connect_spectator(session_id, user_id, websocket)

        # Start heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

        try:
            # Spectators only listen
            while True:
                await websocket.receive_text()
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Training spectator disconnected: session={session_id}")
    except Exception:
        logger.exception(f"Training spectator error: session={session_id}")
    finally:
        if user_id:
            await training_manager.disconnect_spectator(session_id)


async def _heartbeat_loop(websocket: WebSocket) -> None:
    ping_json = PingMessage().model_dump_json()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await asyncio.wait_for(websocket.send_text(ping_json), timeout=SEND_TIMEOUT)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


async def _send_initial_state(
    websocket: WebSocket, session: TrainingSession
) -> None:
    """Send current training session state to spectator."""
    seed = session.seed

    from speedfog_racing.services.layer_service import get_layer_for_node, get_tier_for_node

    current_zone = None
    current_layer = 0
    tier = None
    if session.progress_nodes:
        current_zone = session.progress_nodes[-1].get("node_id")
        if current_zone and seed and seed.graph_json:
            tier = get_tier_for_node(current_zone, seed.graph_json)
        for entry in session.progress_nodes:
            nid = entry.get("node_id")
            if nid and seed and seed.graph_json:
                layer = get_layer_for_node(nid, seed.graph_json)
                if layer > current_layer:
                    current_layer = layer

    include_history = session.status == TrainingSessionStatus.FINISHED
    room = training_manager.get_room(session.id)

    participant = ParticipantInfo(
        id=str(session.id),
        twitch_username=session.user.twitch_username,
        status=session.status.value,
        current_zone=current_zone,
        current_layer=current_layer,
        current_layer_tier=tier,
        igt_ms=session.igt_ms,
        death_count=session.death_count,
        color_index=0,
        mod_connected=room is not None and room.mod is not None,
        zone_history=session.progress_nodes if include_history else None,
    )

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(session.id),
            name="Training",
            status="running" if session.status == TrainingSessionStatus.ACTIVE else session.status.value,
            started_at=session.created_at.isoformat() if session.created_at else None,
        ),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=seed.graph_json if seed else None,
            total_nodes=seed.graph_json.get("total_nodes") if seed and seed.graph_json else None,
            total_paths=seed.graph_json.get("total_paths") if seed and seed.graph_json else None,
        ),
        participants=[participant],
    )
    await websocket.send_text(message.model_dump_json())
```

**Step 2: Verify import**

Run: `cd server && uv run python -c "from speedfog_racing.websocket.training_spectator import handle_training_spectator_websocket; print('OK')"`

**Step 3: Commit**

```bash
git add server/speedfog_racing/websocket/training_spectator.py
git commit -m "feat(training): add training spectator WS handler"
```

---

### Task 10: Register WS Endpoints + Exports

**Files:**

- Modify: `server/speedfog_racing/main.py`
- Modify: `server/speedfog_racing/websocket/__init__.py`

**Step 1: Update websocket `__init__.py`**

Add imports:

```python
from speedfog_racing.websocket.training_manager import training_manager
from speedfog_racing.websocket.training_mod import handle_training_mod_websocket
from speedfog_racing.websocket.training_spectator import handle_training_spectator_websocket
```

Add to `__all__`:

```python
"training_manager",
"handle_training_mod_websocket",
"handle_training_spectator_websocket",
```

**Step 2: Register WS routes in main.py**

Add import:

```python
from speedfog_racing.websocket import (
    handle_mod_websocket,
    handle_spectator_websocket,
    handle_training_mod_websocket,
    handle_training_spectator_websocket,
)
```

Add WS routes after existing ones:

```python
@app.websocket("/ws/training/{session_id}")
async def websocket_training_mod(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """WebSocket endpoint for training mod connections."""
    await handle_training_mod_websocket(websocket, session_id, async_session_maker)


@app.websocket("/ws/training/{session_id}/spectate")
async def websocket_training_spectator(
    websocket: WebSocket, session_id: uuid.UUID
) -> None:
    """WebSocket endpoint for training spectator connections."""
    await handle_training_spectator_websocket(websocket, session_id, async_session_maker)
```

**Step 3: Run existing tests to verify no regressions**

Run: `cd server && uv run pytest -v --timeout=30`
Expected: All existing tests PASS

**Step 4: Commit**

```bash
git add server/speedfog_racing/main.py server/speedfog_racing/websocket/__init__.py
git commit -m "feat(training): register training WS endpoints"
```

---

### Task 11: Mod Rust Changes

**Files:**

- Modify: `mod/src/dll/config.rs`
- Modify: `mod/src/dll/websocket.rs`
- Modify: `mod/src/dll/tracker.rs`
- Modify: `mod/src/dll/ui.rs`

**Step 1: Add `training` field to ServerSettings**

In `mod/src/dll/config.rs`, add to `ServerSettings`:

```rust
pub struct ServerSettings {
    pub url: String,
    pub mod_token: String,
    pub race_id: String,
    /// Training mode — hides leaderboard, uses /ws/training/ endpoint
    #[serde(default)]
    pub training: bool,
}
```

Update `Default` impl to include `training: false`.

**Step 2: Update WS URL construction**

In `mod/src/dll/websocket.rs`, change the URL construction (around line 245):

```rust
let endpoint = if settings.training { "training" } else { "mod" };
let url = format!("{}/ws/{}/{}", ws_base, endpoint, settings.race_id);
```

**Step 3: Skip `ready` in training mode**

In `mod/src/dll/tracker.rs`, the section that sends `ready` (around line 258-283). Wrap with:

```rust
if !self.config.server.training && !self.ready_sent {
    // existing ready logic
}
```

**Step 4: Update overlay for training mode**

In `mod/src/dll/ui.rs`, in the `render` method (around line 85-94):

```rust
.build(|| {
    self.render_player_status(ui, max_width);
    self.render_exits(ui, max_width);
    if !self.config.server.training {
        ui.separator();
        self.render_leaderboard(ui, max_width);
    }
    if self.show_debug {
        ui.separator();
        self.render_debug(ui);
    }
});
```

In `render_player_status`, the race name display — when `training` is true, show "Training" instead of the race name. Find where `race.name` is displayed and add:

```rust
let display_name = if self.config.server.training {
    "Training"
} else {
    race.name.as_str()
};
```

**Step 5: Verify compilation**

Run: `cd mod && cargo check --lib`
Expected: Compiles without errors (Linux cross-check)

**Step 6: Run Rust tests**

Run: `cd mod && cargo test`
Expected: PASS

**Step 7: Commit**

```bash
git add mod/src/dll/config.rs mod/src/dll/websocket.rs mod/src/dll/tracker.rs mod/src/dll/ui.rs
git commit -m "feat(training): add training mode support to mod"
```

---

### Task 12: Frontend — `/training` Page

**Files:**

- Create: `web/src/routes/training/+page.svelte`
- Modify: `web/src/lib/api.ts` — add training API functions and types
- Modify: `web/src/routes/+layout.svelte` — add "Training" to navbar

**Step 1: Add API types and functions**

In `web/src/lib/api.ts`, add types:

```typescript
export interface TrainingSession {
  id: string;
  user: User;
  status: "active" | "finished" | "abandoned";
  pool_name: string;
  igt_ms: number;
  death_count: number;
  created_at: string;
  finished_at: string | null;
  seed_total_layers: number | null;
  seed_total_nodes: number | null;
}

export interface TrainingSessionDetail extends TrainingSession {
  seed_total_paths: number | null;
  progress_nodes: Array<{ node_id: string; igt_ms: number }> | null;
  graph_json: Record<string, unknown> | null;
  pool_config: PoolConfig | null;
}
```

Add API functions:

```typescript
export async function getTrainingPools(): Promise<Record<string, PoolStats>> {
  return apiFetch("/api/pools?type=training");
}

export async function createTrainingSession(
  pool_name: string,
): Promise<TrainingSessionDetail> {
  return apiFetch("/api/training", {
    method: "POST",
    body: JSON.stringify({ pool_name }),
  });
}

export async function getTrainingSessions(): Promise<TrainingSession[]> {
  return apiFetch("/api/training");
}

export async function getTrainingSession(
  id: string,
): Promise<TrainingSessionDetail> {
  return apiFetch(`/api/training/${id}`);
}

export async function abandonTrainingSession(
  id: string,
): Promise<TrainingSessionDetail> {
  return apiFetch(`/api/training/${id}/abandon`, { method: "POST" });
}
```

**Step 2: Create the training list page**

Create `web/src/routes/training/+page.svelte` with:

- Pool selection cards (from `getTrainingPools()`) with Start buttons
- History table (from `getTrainingSessions()`)
- Auth check — redirect to login if not authenticated
- Pool card shows estimated_duration, description
- Start button calls `createTrainingSession(pool_name)` then navigates to `/training/{id}`
- History rows show: pool*name (strip "training*" prefix), formatted IGT, death count, status badge, date

Use existing component patterns from the codebase (check `+page.svelte` files for style patterns).

**Step 3: Add navbar link**

In the layout, add a "Training" link next to existing nav items. Only visible when logged in.

**Step 4: Verify dev server runs**

Run: `cd web && npm run dev` (check in browser)

**Step 5: Run type check**

Run: `cd web && npm run check`
Expected: No new errors

**Step 6: Commit**

```bash
git add web/src/lib/api.ts web/src/routes/training/+page.svelte web/src/routes/+layout.svelte
git commit -m "feat(training): add /training page with pool selection and history"
```

---

### Task 13: Frontend — `/training/[id]` Page

**Files:**

- Create: `web/src/routes/training/[id]/+page.svelte`
- Create: `web/src/lib/stores/training.ts` — training session store (WS-fed)

**Step 1: Create the training store**

Create `web/src/lib/stores/training.ts` following the pattern of `web/src/lib/stores/race.ts`:

- Connect to `/ws/training/{id}/spectate` with auth token
- Parse `race_state` initial message
- Handle `leaderboard_update` (single participant) and `race_status_change` messages
- Expose reactive state: session status, participant info, seed/graph data

**Step 2: Create the training detail page**

Create `web/src/routes/training/[id]/+page.svelte`:

- Load session detail on mount (`getTrainingSession(id)`)
- Connect training store for live updates
- Render:
  - Header with "Training — {pool_display_name}" + status badge
  - Stats bar: formatted IGT, death count, progress (nodes traversed / total layers)
  - DAG section with toggle (hidden by default when ACTIVE, shown when FINISHED)
  - Reuse existing `MetroDAG` component with player progression
  - "Download Pack" button (links to `/api/training/{id}/pack` with auth)
  - "Abandon" button with confirmation dialog
- Disconnect WS on destroy

**Step 3: Type check and lint**

Run: `cd web && npm run check && npm run lint`

**Step 4: Commit**

```bash
git add web/src/lib/stores/training.ts web/src/routes/training/\[id\]/+page.svelte
git commit -m "feat(training): add /training/[id] page with live DAG and stats"
```

---

### Task 14: Integration Testing

**Files:**

- Modify: `server/tests/test_training.py` — add WS integration tests

**Step 1: Write WS integration test**

```python
@pytest.mark.asyncio
async def test_training_mod_websocket_flow(async_session, training_user, training_seed):
    """Full training WS flow: auth → status_update → event_flag → finish."""
    # Create session via service
    async with async_session() as db:
        session = await create_training_session(db, training_user.id, "training_standard")
        await db.commit()
        session_id = session.id
        mod_token = session.mod_token

    # Connect via WS test client
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        async with client.websocket_connect(f"/ws/training/{session_id}") as ws:
            # Auth
            await ws.send_json({"type": "auth", "mod_token": mod_token})
            auth_ok = await ws.receive_json()
            assert auth_ok["type"] == "auth_ok"
            assert auth_ok["seed"]["event_ids"] is not None

            # Should receive race_start immediately
            start = await ws.receive_json()
            assert start["type"] == "race_start"

            # Send status update
            await ws.send_json({"type": "status_update", "igt_ms": 5000, "death_count": 1})

            # Verify update persisted
            async with async_session() as db:
                result = await db.execute(
                    select(TrainingSession).where(TrainingSession.id == session_id)
                )
                s = result.scalar_one()
                assert s.igt_ms == 5000
                assert s.death_count == 1
```

**Step 2: Run all tests**

Run: `cd server && uv run pytest -v --timeout=30`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add server/tests/test_training.py
git commit -m "test(training): add integration tests for training WS flow"
```

---

### Task 15: Final Polish + Pool TOML Configs

**Files:**

- Create: `tools/pools/training_sprint.toml`, `tools/pools/training_standard.toml`, `tools/pools/training_marathon.toml`
- Modify: `docs/PROTOCOL.md` — document training WS endpoints

**Step 1: Create training pool configs**

Copy existing pool configs but add `type = "training"` and adjust descriptions. Example for `training_standard.toml`:

```toml
[display]
type = "training"
estimated_duration = "~1h"
description = "Standard training — balanced, ~1h"
```

Copy the rest of the config from `standard.toml` (requirements, structure, starting_items, etc. stay the same).

**Step 2: Update PROTOCOL.md**

Add a "Training WebSocket" section documenting:

- `/ws/training/{session_id}` — same protocol as mod, simplified behavior
- `/ws/training/{session_id}/spectate` — spectator for live web updates

**Step 3: Run full test suite**

Run: `cd server && uv run pytest -v --timeout=30`
Run: `cd web && npm run check`
Run: `cd mod && cargo check --lib`

**Step 4: Commit**

```bash
git add tools/pools/training_*.toml docs/PROTOCOL.md
git commit -m "feat(training): add training pool configs and update protocol docs"
```
