# Report Buggy Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow organizers to flag seeds as buggy during re-roll, quarantining them for admin review.

**Architecture:** Add `REPORTED` status to `SeedStatus` enum with report metadata on the `Seed` model. Extend the re-roll API to accept an optional report payload. Add admin endpoints to list and resolve reported seeds. Update the re-roll confirmation modal with a checkbox and reason field.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0, Alembic, SvelteKit 5, shell script

---

## Task 1: Add REPORTED status and report fields to Seed model

**Files:**

- Modify: `server/speedfog_racing/models.py:52-57` (SeedStatus enum)
- Modify: `server/speedfog_racing/models.py:101-117` (Seed model)

- [ ] **Step 1: Add REPORTED to SeedStatus enum**

In `server/speedfog_racing/models.py`, add `REPORTED` to the `SeedStatus` enum:

```python
class SeedStatus(enum.Enum):
    """Seed availability status."""

    AVAILABLE = "available"
    CONSUMED = "consumed"
    DISCARDED = "discarded"
    REPORTED = "reported"
```

- [ ] **Step 2: Add report fields to Seed model**

In `server/speedfog_racing/models.py`, add three nullable columns and a relationship to the `Seed` class, after the `created_at` field (line 114):

```python
class Seed(Base):
    """A SpeedFog seed available for racing."""

    __tablename__ = "seeds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seed_number: Mapped[str] = mapped_column(String(50), nullable=False)
    pool_name: Mapped[str] = mapped_column(String(50), nullable=False)  # "standard", "sprint"
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    total_layers: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_score: Mapped[float] = mapped_column(default=0.0, server_default="0.0")
    folder_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[SeedStatus] = mapped_column(Enum(SeedStatus), default=SeedStatus.AVAILABLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reported_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    races: Mapped[list["Race"]] = relationship(back_populates="seed")
    reported_by: Mapped["User | None"] = relationship(foreign_keys=[reported_by_id])
```

Note: `ForeignKey` and `Text` must be imported from `sqlalchemy`. Check existing imports at the top of the file and add `ForeignKey` and `Text` if missing.

- [ ] **Step 3: Commit**

```bash
git add server/speedfog_racing/models.py
git commit -m "feat: add REPORTED status and report fields to Seed model"
```

---

## Task2: Create Alembic migration

**Files:**

- Create: `server/alembic/versions/<auto>_add_reported_seed_status.py`

- [ ] **Step 1: Generate migration**

```bash
cd server && uv run alembic revision --autogenerate -m "add reported seed status and report fields"
```

- [ ] **Step 2: Review and fix the generated migration**

Alembic's autogenerate may not handle enum value additions for PostgreSQL. Verify the migration includes:

1. Adding `REPORTED` to the `seedstatus` enum type (PostgreSQL needs `ALTER TYPE seedstatus ADD VALUE 'REPORTED'`)
2. Adding three columns: `reported_by_id` (UUID, FK to users.id), `reported_reason` (Text), `reported_at` (DateTime with timezone)

If the enum alteration is missing or wrong, manually add it. The migration should look like:

```python
def upgrade() -> None:
    # Add REPORTED to seedstatus enum
    op.execute("ALTER TYPE seedstatus ADD VALUE IF NOT EXISTS 'REPORTED'")

    op.add_column("seeds", sa.Column("reported_by_id", sa.UUID(), nullable=True))
    op.add_column("seeds", sa.Column("reported_reason", sa.Text(), nullable=True))
    op.add_column("seeds", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_seeds_reported_by_id", "seeds", "users", ["reported_by_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_seeds_reported_by_id", "seeds", type_="foreignkey")
    op.drop_column("seeds", "reported_at")
    op.drop_column("seeds", "reported_reason")
    op.drop_column("seeds", "reported_by_id")
    # Note: cannot remove enum value in PostgreSQL
```

- [ ] **Step 3: Commit**

```bash
git add server/alembic/versions/
git commit -m "migration: add reported seed status and report fields"
```

---

## Task3: Update seed service (report on re-roll, exclude REPORTED from available)

**Files:**

- Modify: `server/speedfog_racing/services/seed_service.py:120-142` (get_available_seed)
- Modify: `server/speedfog_racing/services/seed_service.py:174-206` (reroll_seed_for_race)
- Modify: `server/speedfog_racing/services/seed_service.py:231-255` (discard_pool)
- Modify: `server/speedfog_racing/services/seed_service.py:209-228` (get_pool_stats)
- Test: `server/tests/test_seed_service.py` (new file)

- [ ] **Step 1: Write failing tests for seed service changes**

Create `server/tests/test_seed_service.py`:

```python
"""Tests for seed service report/quarantine behavior."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Race, RaceStatus, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.seed_service import (
    discard_pool,
    get_available_seed,
    reroll_seed_for_race,
)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def reporter(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="reporter1",
            twitch_username="reporter",
            api_token="reporter_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_reported_seeds_excluded_from_available(async_session):
    """Seeds with REPORTED status are not returned by get_available_seed."""
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="reported1",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": {}},
                total_layers=5,
                folder_path="/test/reported1",
                status=SeedStatus.REPORTED,
            )
        )
        await db.commit()

        result = await get_available_seed(db, "standard")
        assert result is None


@pytest.mark.asyncio
async def test_reroll_with_report(async_session, reporter):
    """Re-roll with report_buggy=True quarantines the old seed."""
    async with async_session() as db:
        seed_old = Seed(
            seed_number="old1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/old1",
            status=SeedStatus.CONSUMED,
        )
        seed_new = Seed(
            seed_number="new1",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/new1",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_old, seed_new])
        await db.flush()

        race = Race(
            name="Report Test",
            organizer_id=reporter.id,
            seed_id=seed_old.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        # Eager-load seed relationship
        race.seed = seed_old

        old_id = seed_old.id
        new_seed = await reroll_seed_for_race(
            db, race, reporter_id=reporter.id, report_reason="broken fog gate"
        )
        await db.commit()

        assert new_seed.status == SeedStatus.CONSUMED

        result = await db.execute(select(Seed).where(Seed.id == old_id))
        old = result.scalar_one()
        assert old.status == SeedStatus.REPORTED
        assert old.reported_by_id == reporter.id
        assert old.reported_reason == "broken fog gate"
        assert old.reported_at is not None


@pytest.mark.asyncio
async def test_reroll_without_report(async_session, reporter):
    """Re-roll without report returns old seed to AVAILABLE (unchanged behavior)."""
    async with async_session() as db:
        seed_old = Seed(
            seed_number="old2",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/old2",
            status=SeedStatus.CONSUMED,
        )
        seed_new = Seed(
            seed_number="new2",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/new2",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_old, seed_new])
        await db.flush()

        race = Race(
            name="No Report Test",
            organizer_id=reporter.id,
            seed_id=seed_old.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        race.seed = seed_old

        old_id = seed_old.id
        await reroll_seed_for_race(db, race)
        await db.commit()

        result = await db.execute(select(Seed).where(Seed.id == old_id))
        old = result.scalar_one()
        assert old.status == SeedStatus.AVAILABLE
        assert old.reported_by_id is None


@pytest.mark.asyncio
async def test_discard_pool_includes_reported(async_session):
    """discard_pool marks REPORTED seeds as DISCARDED too."""
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="rep_disc",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": {}},
                total_layers=5,
                folder_path="/test/rep_disc",
                status=SeedStatus.REPORTED,
            )
        )
        await db.commit()

        count = await discard_pool(db, "standard")
        assert count == 1

        result = await db.execute(
            select(Seed).where(Seed.seed_number == "rep_disc")
        )
        assert result.scalar_one().status == SeedStatus.DISCARDED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_seed_service.py -v
```

Expected: failures on `reroll_seed_for_race` signature (no `reporter_id` param) and `REPORTED` not excluded from available.

- [ ] **Step 3: Implement seed service changes**

In `server/speedfog_racing/services/seed_service.py`:

**a) Update `get_available_seed` (line 133):** No change needed; the query already filters `status == SeedStatus.AVAILABLE`, which naturally excludes `REPORTED`. Confirm this is the case.

**b) Update `reroll_seed_for_race` (lines 174-206):** Add optional report parameters:

```python
async def reroll_seed_for_race(
    db: AsyncSession,
    race: Race,
    reporter_id: uuid.UUID | None = None,
    report_reason: str | None = None,
) -> Seed:
    """Re-roll the seed for a race, releasing the old one.

    Picks a new available seed from the same pool, excluding the current seed.
    If reporter_id is provided, the old seed is quarantined as REPORTED instead
    of returned to AVAILABLE.

    Note: ``race.seed`` must be eager-loaded (selectinload) before calling.

    Raises:
        ValueError: If no other seeds are available in the pool
    """
    old_seed = race.seed
    if old_seed is None:
        raise ValueError("Race has no seed assigned")

    pool_name = old_seed.pool_name

    new_seed = await get_available_seed(db, pool_name, exclude_id=old_seed.id)
    if new_seed is None:
        raise ValueError(f"No available seeds in pool '{pool_name}'")

    # Release or quarantine old seed
    if reporter_id is not None:
        old_seed.status = SeedStatus.REPORTED
        old_seed.reported_by_id = reporter_id
        old_seed.reported_reason = report_reason
        old_seed.reported_at = datetime.now(UTC)
    elif old_seed.status != SeedStatus.DISCARDED:
        old_seed.status = SeedStatus.AVAILABLE

    # Assign new seed
    new_seed.status = SeedStatus.CONSUMED
    race.seed_id = new_seed.id
    race.seed = new_seed

    logger.info(
        f"Re-rolled seed for race {race.id}: {old_seed.seed_number} -> {new_seed.seed_number}"
        + (f" (reported by {reporter_id})" if reporter_id else "")
    )
    return new_seed
```

Add `from datetime import UTC, datetime` to the imports at the top of the file (merge with existing datetime imports if any).

**c) Update `discard_pool` (lines 244-248):** Add `SeedStatus.REPORTED` to the status filter:

```python
Seed.status.in_([SeedStatus.AVAILABLE, SeedStatus.CONSUMED, SeedStatus.REPORTED]),
```

**d) Update `get_pool_stats` (lines 209-228):** Add `reported` key to the default dict:

```python
stats[pool_name] = {"available": 0, "consumed": 0, "discarded": 0, "reported": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_seed_service.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd server && uv run pytest -x -q
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/services/seed_service.py server/tests/test_seed_service.py
git commit -m "feat: support seed reporting in seed service"
```

---

## Task4: Add RerollSeedRequest schema and update re-roll API endpoint

**Files:**

- Modify: `server/speedfog_racing/schemas.py:14-15` (add RerollSeedRequest)
- Modify: `server/speedfog_racing/api/races.py:1215-1265` (reroll_seed endpoint)
- Test: `server/tests/test_races.py:1261-1412` (add report test cases)

- [ ] **Step 1: Write failing tests for report on re-roll API**

Add these tests after the existing re-roll tests in `server/tests/test_races.py` (after line 1412):

```python
@pytest.mark.asyncio
async def test_reroll_seed_with_report(test_client, organizer, async_session):
    """Re-rolling with report_buggy=True quarantines the old seed."""
    async with async_session() as db:
        seed_a = Seed(
            seed_number="report_a",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/report_a",
            status=SeedStatus.CONSUMED,
        )
        seed_b = Seed(
            seed_number="report_b",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/report_b",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_a, seed_b])
        await db.flush()

        race = Race(
            name="Report Reroll Test",
            organizer_id=organizer.id,
            seed_id=seed_a.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)
        seed_a_id = seed_a.id

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={
                "Authorization": f"Bearer {organizer.api_token}",
                "Content-Type": "application/json",
            },
            json={"report_buggy": True, "report_reason": "fog gate broken"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(Seed).where(Seed.id == seed_a_id))
        old_seed = result.scalar_one()
        assert old_seed.status == SeedStatus.REPORTED
        assert old_seed.reported_reason == "fog gate broken"
        assert old_seed.reported_by_id == organizer.id


@pytest.mark.asyncio
async def test_reroll_seed_without_report_body(test_client, organizer, async_session):
    """Re-rolling without body preserves backward compatibility."""
    async with async_session() as db:
        seed_a = Seed(
            seed_number="noreport_a",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/noreport_a",
            status=SeedStatus.CONSUMED,
        )
        seed_b = Seed(
            seed_number="noreport_b",
            pool_name="standard",
            graph_json={"total_layers": 7, "nodes": {}},
            total_layers=7,
            folder_path="/test/noreport_b",
            status=SeedStatus.AVAILABLE,
        )
        db.add_all([seed_a, seed_b])
        await db.flush()

        race = Race(
            name="No Report Reroll Test",
            organizer_id=organizer.id,
            seed_id=seed_a.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)
        seed_a_id = seed_a.id

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/reroll-seed",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        from sqlalchemy import select

        result = await db.execute(select(Seed).where(Seed.id == seed_a_id))
        assert result.scalar_one().status == SeedStatus.AVAILABLE
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_races.py::test_reroll_seed_with_report tests/test_races.py::test_reroll_seed_without_report_body -v
```

Expected: fail because the endpoint doesn't accept a body yet.

- [ ] **Step 3: Add RerollSeedRequest schema**

In `server/speedfog_racing/schemas.py`, add after the `AddCasterRequest` class (around line 63):

```python
class RerollSeedRequest(BaseModel):
    """Optional request body for re-rolling a seed with bug report."""

    report_buggy: bool = False
    report_reason: str | None = None
```

- [ ] **Step 4: Update the re-roll endpoint**

In `server/speedfog_racing/api/races.py`, update the `reroll_seed` function (lines 1215-1265):

```python
@router.post("/{race_id}/reroll-seed", response_model=RaceDetailResponse)
async def reroll_seed(
    race_id: UUID,
    body: RerollSeedRequest | None = None,
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

    report_buggy = body.report_buggy if body else False
    logger.info(
        "Seed reroll requested: race=%s, by=%s, report=%s",
        race_id,
        user.twitch_username,
        report_buggy,
    )
    try:
        await reroll_seed_for_race(
            db,
            race,
            reporter_id=user.id if report_buggy else None,
            report_reason=body.report_reason if body and report_buggy else None,
        )
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
```

Add `RerollSeedRequest` to the imports from `speedfog_racing.schemas` at the top of the file.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_races.py -k reroll -v
```

Expected: all re-roll tests pass (including existing ones).

- [ ] **Step 6: Run full test suite**

```bash
cd server && uv run pytest -x -q
```

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/races.py server/tests/test_races.py
git commit -m "feat: accept bug report in re-roll API endpoint"
```

---

## Task5: Add admin endpoints for reported seeds

**Files:**

- Modify: `server/speedfog_racing/api/admin.py` (add reported-seeds and resolve endpoints)
- Test: `server/tests/test_admin.py` (add reported seed tests)

- [ ] **Step 1: Write failing tests for admin endpoints**

Add to the end of `server/tests/test_admin.py`:

```python
@pytest.fixture
async def organizer_user(async_session):
    """Create an organizer user."""
    async with async_session() as db:
        user = User(
            twitch_id="org456",
            twitch_username="organizer_user",
            api_token="organizer_test_token",
            role=UserRole.ORGANIZER,
            last_seen=datetime.now(UTC),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_reported_seeds_list(test_client, admin_user, organizer_user, async_session):
    """Admin can list reported seeds."""
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="rep001",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": {}},
                total_layers=5,
                folder_path="/test/rep001",
                status=SeedStatus.REPORTED,
                reported_by_id=organizer_user.id,
                reported_reason="broken fog gate",
                reported_at=datetime.now(UTC),
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/reported-seeds",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["seed_number"] == "rep001"
        assert data[0]["reported_reason"] == "broken fog gate"
        assert data[0]["reported_by"] == "organizer_user"


@pytest.mark.asyncio
async def test_reported_seeds_requires_admin(test_client, regular_user):
    """Non-admin cannot list reported seeds."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/reported-seeds",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_seed_discard(test_client, admin_user, organizer_user, async_session):
    """Admin can discard a reported seed."""
    async with async_session() as db:
        seed = Seed(
            seed_number="resolve_d",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/resolve_d",
            status=SeedStatus.REPORTED,
            reported_by_id=organizer_user.id,
            reported_at=datetime.now(UTC),
        )
        db.add(seed)
        await db.commit()
        seed_id = str(seed.id)

    async with test_client as client:
        response = await client.post(
            f"/api/admin/seeds/{seed_id}/resolve",
            headers={
                "Authorization": f"Bearer {admin_user.api_token}",
                "Content-Type": "application/json",
            },
            json={"action": "discard"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        result = await db.execute(select(Seed).where(Seed.seed_number == "resolve_d"))
        assert result.scalar_one().status == SeedStatus.DISCARDED


@pytest.mark.asyncio
async def test_resolve_seed_restore(test_client, admin_user, organizer_user, async_session):
    """Admin can restore a reported seed to AVAILABLE."""
    async with async_session() as db:
        seed = Seed(
            seed_number="resolve_r",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/resolve_r",
            status=SeedStatus.REPORTED,
            reported_by_id=organizer_user.id,
            reported_reason="false alarm",
            reported_at=datetime.now(UTC),
        )
        db.add(seed)
        await db.commit()
        seed_id = str(seed.id)

    async with test_client as client:
        response = await client.post(
            f"/api/admin/seeds/{seed_id}/resolve",
            headers={
                "Authorization": f"Bearer {admin_user.api_token}",
                "Content-Type": "application/json",
            },
            json={"action": "restore"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        result = await db.execute(select(Seed).where(Seed.seed_number == "resolve_r"))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.AVAILABLE
        assert seed.reported_by_id is None
        assert seed.reported_reason is None
        assert seed.reported_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_admin.py -k reported -v
```

Expected: 404 errors (endpoints don't exist yet).

- [ ] **Step 3: Add admin endpoints**

In `server/speedfog_racing/api/admin.py`, add `Seed` and `SeedStatus` to the model imports, add `select` to the SQLAlchemy imports if missing, and append these schemas and endpoints:

```python
# Add to imports at top of file:
# from speedfog_racing.models import ... Seed, SeedStatus ...
# from sqlalchemy.orm import selectinload  (already imported)

class ReportedSeedResponse(BaseModel):
    """A reported seed for admin review."""

    id: uuid.UUID
    seed_number: str
    pool_name: str
    difficulty_score: float
    reported_by: str
    reported_reason: str | None
    reported_at: datetime


class ResolveSeedRequest(BaseModel):
    """Request to resolve a reported seed."""

    action: str  # "discard" or "restore"


@router.get("/reported-seeds", response_model=list[ReportedSeedResponse])
async def list_reported_seeds(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[ReportedSeedResponse]:
    """List all seeds with REPORTED status. Requires admin role."""
    result = await db.execute(
        select(Seed)
        .where(Seed.status == SeedStatus.REPORTED)
        .options(selectinload(Seed.reported_by))
        .order_by(Seed.reported_at.desc())
    )
    seeds = result.scalars().all()
    return [
        ReportedSeedResponse(
            id=s.id,
            seed_number=s.seed_number,
            pool_name=s.pool_name,
            difficulty_score=s.difficulty_score,
            reported_by=s.reported_by.twitch_username if s.reported_by else "unknown",
            reported_reason=s.reported_reason,
            reported_at=s.reported_at,
        )
        for s in seeds
    ]


@router.post("/seeds/{seed_id}/resolve")
async def resolve_reported_seed(
    seed_id: uuid.UUID,
    request: ResolveSeedRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """Discard or restore a reported seed. Requires admin role."""
    if request.action not in ("discard", "restore"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be 'discard' or 'restore'",
        )

    result = await db.execute(select(Seed).where(Seed.id == seed_id))
    seed = result.scalar_one_or_none()
    if not seed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    if seed.status != SeedStatus.REPORTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seed is not in REPORTED status",
        )

    if request.action == "discard":
        seed.status = SeedStatus.DISCARDED
    else:
        seed.status = SeedStatus.AVAILABLE
        seed.reported_by_id = None
        seed.reported_reason = None
        seed.reported_at = None

    await db.commit()
    return {"status": "ok"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_admin.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd server && uv run pytest -x -q
```

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/api/admin.py server/tests/test_admin.py
git commit -m "feat: add admin endpoints for reported seed management"
```

---

## Task6: Update pool stats to include reported count

**Files:**

- Modify: `server/speedfog_racing/api/admin.py:64-76` (PoolStats model)

- [ ] **Step 1: Add reported field to PoolStats**

In `server/speedfog_racing/api/admin.py`, update the `PoolStats` class:

```python
class PoolStats(BaseModel):
    """Statistics for a single pool."""

    available: int
    consumed: int
    discarded: int = 0
    reported: int = 0
```

- [ ] **Step 2: Run tests**

```bash
cd server && uv run pytest tests/test_admin.py -x -q
```

- [ ] **Step 3: Commit**

```bash
git add server/speedfog_racing/api/admin.py
git commit -m "feat: include reported count in pool stats"
```

---

## Task7: Update deploy script

**Files:**

- Modify: `deploy/deploy-seeds.sh:141` (discard_seeds SQL)

- [ ] **Step 1: Update the SQL WHERE clause**

In `deploy/deploy-seeds.sh`, update the `discard_seeds()` function (line 141). Change:

```sql
"UPDATE seeds SET status = 'DISCARDED' WHERE status IN ('AVAILABLE', 'CONSUMED') AND pool_name = '$pool'"
```

To:

```sql
"UPDATE seeds SET status = 'DISCARDED' WHERE status IN ('AVAILABLE', 'CONSUMED', 'REPORTED') AND pool_name = '$pool'"
```

- [ ] **Step 2: Commit**

```bash
git add deploy/deploy-seeds.sh
git commit -m "fix: include REPORTED seeds in deploy --discard cleanup"
```

---

## Task8: Update frontend API client

**Files:**

- Modify: `web/src/lib/api.ts:500-506` (rerollSeed function)
- Modify: `web/src/lib/api.ts:949-954` (AdminPoolStats interface)
- Modify: `web/src/lib/api.ts` (add admin report functions and types, after line 998)

- [ ] **Step 1: Update rerollSeed to accept report params**

In `web/src/lib/api.ts`, replace the `rerollSeed` function (lines 500-506):

```typescript
/**
 * Re-roll the seed for a SETUP race, optionally reporting it as buggy.
 */
export async function rerollSeed(
  raceId: string,
  reportBuggy?: boolean,
  reportReason?: string,
): Promise<RaceDetail> {
  const body =
    reportBuggy != null && reportBuggy
      ? { report_buggy: true, report_reason: reportReason || null }
      : undefined;
  const response = await fetch(`${API_BASE}/races/${raceId}/reroll-seed`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<RaceDetail>(response);
}
```

- [ ] **Step 2: Update AdminPoolStats to include reported**

In `web/src/lib/api.ts`, update the `AdminPoolStats` interface (lines 949-954):

```typescript
export interface AdminPoolStats {
  pools: Record<
    string,
    { available: number; consumed: number; discarded: number; reported: number }
  >;
}
```

- [ ] **Step 3: Add reported seed types and functions**

In `web/src/lib/api.ts`, add after the `adminScanPool` function (after line 998):

```typescript
export interface ReportedSeed {
  id: string;
  seed_number: string;
  pool_name: string;
  difficulty_score: number;
  reported_by: string;
  reported_reason: string | null;
  reported_at: string;
}

/**
 * Fetch reported seeds (admin only).
 */
export async function fetchReportedSeeds(): Promise<ReportedSeed[]> {
  const response = await fetch(`${API_BASE}/admin/reported-seeds`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<ReportedSeed[]>(response);
}

/**
 * Resolve a reported seed (admin only).
 */
export async function resolveReportedSeed(
  seedId: string,
  action: "discard" | "restore",
): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/admin/seeds/${seedId}/resolve`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
  return handleResponse<{ status: string }>(response);
}
```

- [ ] **Step 4: Run type check**

```bash
cd web && npm run check
```

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat: add reported seed API functions to frontend client"
```

---

## Task9: Update re-roll confirmation modal

**Files:**

- Modify: `web/src/lib/components/RaceControls.svelte:72-91` (handleReroll + modal)

- [ ] **Step 1: Add report state and update handleReroll**

In `web/src/lib/components/RaceControls.svelte`, add state variables after the existing state declarations (around line 27, after `let seedsReleased`):

```typescript
let reportBuggy = $state(false);
let reportReason = $state("");
```

Replace the `handleReroll` function (lines 72-92):

```typescript
function handleReroll() {
  reportBuggy = false;
  reportReason = "";
  requestConfirm({
    title: "Re-roll Seed",
    message: seedsReleased
      ? "Participants may have already downloaded. Re-rolling will require everyone to re-download. Continue?"
      : "Re-roll the seed? Participants will need to download a new seed pack.",
    confirmLabel: "Re-roll",
    async action() {
      loading = true;
      error = null;
      try {
        const updated = await rerollSeed(
          race.id,
          reportBuggy || undefined,
          reportReason.trim() || undefined,
        );
        onRaceUpdated(updated);
      } catch (e) {
        error = e instanceof Error ? e.message : "Failed to re-roll seed";
      } finally {
        loading = false;
      }
    },
  });
}
```

- [ ] **Step 2: Add checkbox and reason field to the confirm modal**

The current `ConfirmModal` only takes a `message` string. Instead of modifying the shared component, add the report UI directly in the `RaceControls` modal section. Replace the `{#if pendingConfirm}` block (lines 346-355):

```svelte
{#if pendingConfirm}
    <ConfirmModal
        title={pendingConfirm.title}
        message={pendingConfirm.message}
        confirmLabel={pendingConfirm.confirmLabel}
        danger={pendingConfirm.danger ?? false}
        onConfirm={executeConfirm}
        onCancel={() => (pendingConfirm = null)}
    >
        {#if pendingConfirm.title === 'Re-roll Seed'}
            <label class="report-check">
                <input type="checkbox" bind:checked={reportBuggy} />
                Report this seed as buggy
            </label>
            {#if reportBuggy}
                <input
                    class="report-reason"
                    type="text"
                    placeholder="Describe the issue..."
                    bind:value={reportReason}
                    maxlength="500"
                />
            {/if}
        {/if}
    </ConfirmModal>
{/if}
```

- [ ] **Step 3: Update ConfirmModal to accept a slot**

The `ConfirmModal` component currently has no slot. Add a default slot between the message and the actions. In `web/src/lib/components/ConfirmModal.svelte`, add a `children` snippet prop and render it:

Update the Props interface:

```typescript
import type { Snippet } from "svelte";

interface Props {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children?: Snippet;
}
```

Update the destructuring:

```typescript
let {
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  loading = false,
  error = null,
  onConfirm,
  onCancel,
  children,
}: Props = $props();
```

In the template, add the slot render between the message and error:

```svelte
<p class="message">{message}</p>

{#if children}
    {@render children()}
{/if}

{#if error}
    <p class="error">{error}</p>
{/if}
```

- [ ] **Step 4: Add styles for report UI**

In `web/src/lib/components/RaceControls.svelte`, add these styles inside the `<style>` block:

```css
.report-check {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  margin-bottom: 0.5rem;
}

.report-check input[type="checkbox"] {
  accent-color: var(--color-gold);
  cursor: pointer;
}

.report-reason {
  width: 100%;
  padding: 0.4rem 0.6rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  margin-bottom: 0.75rem;
  box-sizing: border-box;
}

.report-reason:focus {
  outline: none;
  border-color: var(--color-gold);
}
```

- [ ] **Step 5: Run type check and lint**

```bash
cd web && npm run check && npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/components/ConfirmModal.svelte web/src/lib/components/RaceControls.svelte
git commit -m "feat: add bug report checkbox to re-roll confirmation modal"
```

---

## Task10: Add reported seeds section to admin page

**Files:**

- Modify: `web/src/routes/admin/+page.svelte`

- [ ] **Step 1: Add imports, state, and handlers**

In `web/src/routes/admin/+page.svelte`, add `fetchReportedSeeds`, `resolveReportedSeed`, and `type ReportedSeed` to the imports from `$lib/api` (line 4-15).

Add state variables after the existing state block (around line 36):

```typescript
let reportedSeeds: ReportedSeed[] = $state([]);
let reportedLoading = $state(false);
```

Add handler functions (before `formatFullDate`, around line 107):

```typescript
async function loadReportedSeeds() {
  reportedLoading = true;
  try {
    reportedSeeds = await fetchReportedSeeds();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load reported seeds.";
  } finally {
    reportedLoading = false;
  }
}

async function handleResolve(seedId: string, action: "discard" | "restore") {
  actionLoading = { ...actionLoading, [`resolve_${seedId}`]: true };
  try {
    await resolveReportedSeed(seedId, action);
    reportedSeeds = reportedSeeds.filter((s) => s.id !== seedId);
    await loadSeedStats();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to resolve seed.";
  } finally {
    actionLoading = { ...actionLoading, [`resolve_${seedId}`]: false };
  }
}
```

Update `switchTab` (line 98-106) to also load reported seeds when switching to seeds tab:

```typescript
function switchTab(tab: Tab) {
  activeTab = tab;
  if (tab === "seeds" && !seedStats) {
    loadSeedStats();
    loadReportedSeeds();
  }
  if (tab === "activity" && !activity) {
    loadActivity();
  }
}
```

- [ ] **Step 2: Add reported seeds table**

In the Seeds tab section, insert the reported seeds table before the pool stats table. Find `{:else if activeTab === 'seeds'}` (line 287) and add between the loading check and the pool stats table (right after the `{:else}` on line 292, before the `<div class="table-wrapper">`):

```svelte
{#if reportedSeeds.length > 0}
    <div class="reported-section">
        <h2>Reported Seeds</h2>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Seed</th>
                        <th>Pool</th>
                        <th>Reporter</th>
                        <th>Reason</th>
                        <th>Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {#each reportedSeeds as seed (seed.id)}
                        <tr>
                            <td class="mono">{seed.seed_number}</td>
                            <td>{formatPoolName(seed.pool_name)}</td>
                            <td>{seed.reported_by}</td>
                            <td class="reason-cell">{seed.reported_reason || '-'}</td>
                            <td class="date-cell">{formatDate(seed.reported_at)}</td>
                            <td class="actions-cell">
                                <button
                                    class="action-btn discard"
                                    disabled={actionLoading[`resolve_${seed.id}`]}
                                    onclick={() => handleResolve(seed.id, 'discard')}
                                >
                                    Discard
                                </button>
                                <button
                                    class="action-btn scan"
                                    disabled={actionLoading[`resolve_${seed.id}`]}
                                    onclick={() => handleResolve(seed.id, 'restore')}
                                >
                                    Restore
                                </button>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    </div>
{/if}
```

- [ ] **Step 3: Add reported count column to pool stats table**

In the pool stats table header (around line 296-302), add a `Reported` column:

```svelte
<thead>
    <tr>
        <th>Pool Name</th>
        <th class="num-col">Available</th>
        <th class="num-col">Consumed</th>
        <th class="num-col">Reported</th>
        <th class="num-col">Discarded</th>
        <th>Actions</th>
    </tr>
</thead>
```

In the table body row (around line 305-328), add the reported cell after consumed:

```svelte
<td class="num-cell">{stats.reported ?? 0}</td>
```

- [ ] **Step 4: Add styles**

Add these styles in the `<style>` block:

```css
.reported-section {
  margin-bottom: 2rem;
}

.reported-section h2 {
  color: var(--color-warning, #f59e0b);
  font-size: var(--font-size-lg);
  margin-bottom: 0.75rem;
}

.reason-cell {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 5: Run type check and lint**

```bash
cd web && npm run check && npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/admin/+page.svelte
git commit -m "feat: add reported seeds section to admin panel"
```

---

## Task11: Run linters and fix issues

**Files:**

- All modified files

- [ ] **Step 1: Run server linters**

```bash
cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/
```

Fix any issues found.

- [ ] **Step 2: Run frontend linters**

```bash
cd web && npm run check && npm run lint && npm run format
```

Fix any issues found.

- [ ] **Step 3: Run full test suites**

```bash
cd server && uv run pytest -x -q
```

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -u
git commit -m "fix: lint and type fixes"
```

---

## Task12: Launch code review agent

- [ ] **Step 1: Run the code review agent**

Launch the `superpowers:code-reviewer` agent to review all changes against the spec in `docs/plans/2026-04-01-report-buggy-seed.md`.
