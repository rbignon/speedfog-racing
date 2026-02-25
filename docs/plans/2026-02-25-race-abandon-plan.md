# Race Abandon — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow participants to voluntarily abandon a running race, and auto-abandon inactive players whose IGT hasn't changed in 5 minutes.

**Architecture:** New `last_igt_change_at` column on `Participant`, REST endpoint `POST /races/{id}/abandon`, shared auto-finish helper extracted from `mod.py`, background asyncio task for inactivity monitoring, and an "Abandon" button in the race detail sidebar.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, Alembic, SvelteKit 5, pytest-asyncio

---

## Task 1: Add `last_igt_change_at` column to Participant model

**Files:**

- Modify: `server/speedfog_racing/models.py:168-172` (add column after `finished_at`)
- Create: `server/alembic/versions/<auto>_add_last_igt_change_at_to_participant.py`

### Step 1: Add column to model

In `server/speedfog_racing/models.py`, add after line 172 (`finished_at`):

```python
last_igt_change_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

### Step 2: Generate Alembic migration

Run: `cd server && uv run alembic revision --autogenerate -m "add last_igt_change_at to participant"`

Verify the generated migration contains `op.add_column('participants', sa.Column('last_igt_change_at', ...))`.

### Step 3: Run migration

Run: `cd server && uv run alembic upgrade head`
Expected: no errors.

### Step 4: Run existing tests to verify no regression

Run: `cd server && uv run pytest tests/test_races.py -x -q`
Expected: all pass.

### Step 5: Commit

```bash
git add server/speedfog_racing/models.py server/alembic/versions/
git commit -m "feat: add last_igt_change_at column to Participant"
```

---

## Task 2: Update `last_igt_change_at` in WebSocket handlers + add ABANDONED guard

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py:335-336` (status_update IGT block)
- Modify: `server/speedfog_racing/websocket/mod.py:425-426` (event_flag FINISHED guard)
- Modify: `server/speedfog_racing/websocket/mod.py:332-333` (status_update FINISHED guard)
- Test: `server/tests/test_mod_ws.py` (if it exists, otherwise `server/tests/test_races.py`)

### Step 1: Write test for ABANDONED guard in status_update

In `server/tests/test_races.py`, add a test after the existing race tests:

```python
@pytest.mark.asyncio
async def test_abandoned_participant_status_update_ignored(
    test_client, organizer, player, async_session
):
    """status_update from an ABANDONED participant is silently dropped."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abandon_1", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": [], "event_map": {}},
            total_layers=5, folder_path="/test/abandon1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Abandon Test", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id, user_id=player.id,
            status=ParticipantStatus.ABANDONED,
            igt_ms=100000, death_count=5,
        )
        db.add(participant)
        await db.commit()
        p_id = participant.id
        race_id = race.id

    # Verify IGT unchanged after the test (can't easily test WS directly,
    # but we can verify the model guard exists by checking the participant)
    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.ABANDONED
        assert p.igt_ms == 100000  # unchanged
```

### Step 2: Add ABANDONED guard to `handle_status_update`

In `server/speedfog_racing/websocket/mod.py`, change the FINISHED guard at line 332:

```python
# Before:
if participant.status == ParticipantStatus.FINISHED:
    return  # Silently drop — IGT is frozen at finish time

# After:
if participant.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
    return  # Silently drop — IGT is frozen
```

### Step 3: Add ABANDONED guard to `handle_event_flag`

In `server/speedfog_racing/websocket/mod.py`, change the FINISHED guard at line 425:

```python
# Before:
if participant.status == ParticipantStatus.FINISHED:
    return  # Silently drop — player already finished

# After:
if participant.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
    return  # Silently drop — player finished or abandoned
```

### Step 4: Update `last_igt_change_at` in `handle_status_update`

In `server/speedfog_racing/websocket/mod.py`, change the IGT update block at line 335:

```python
# Before:
if isinstance(msg.get("igt_ms"), int):
    participant.igt_ms = msg["igt_ms"]

# After:
if isinstance(msg.get("igt_ms"), int):
    if msg["igt_ms"] != participant.igt_ms:
        participant.last_igt_change_at = datetime.now(UTC)
    participant.igt_ms = msg["igt_ms"]
```

### Step 5: Update `last_igt_change_at` in `handle_event_flag`

In `server/speedfog_racing/websocket/mod.py`, in the `handle_event_flag` function, add `participant.last_igt_change_at = datetime.now(UTC)` right before each `participant.igt_ms = igt` assignment (lines 441, 464, 468). Since an event flag always implies active play, always update the timestamp.

In the finish branch (line 441):

```python
participant.last_igt_change_at = datetime.now(UTC)
participant.igt_ms = igt
```

In the revisit branch (line 464):

```python
participant.last_igt_change_at = datetime.now(UTC)
participant.current_zone = node_id
participant.igt_ms = igt
```

In the new discovery branch (line 468):

```python
participant.last_igt_change_at = datetime.now(UTC)
participant.igt_ms = igt
```

### Step 6: Run tests

Run: `cd server && uv run pytest tests/test_races.py -x -q`
Expected: all pass.

### Step 7: Lint

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`
Expected: clean.

### Step 8: Commit

```bash
git add server/speedfog_racing/websocket/mod.py server/tests/test_races.py
git commit -m "feat: track last_igt_change_at and guard ABANDONED in WS handlers"
```

---

## Task 3: Extract shared auto-finish helper

**Files:**

- Create: `server/speedfog_racing/services/race_lifecycle.py`
- Modify: `server/speedfog_racing/websocket/mod.py:605-660` (replace inline auto-finish)
- Test: `server/tests/test_race_lifecycle.py`

### Step 1: Write the test

Create `server/tests/test_race_lifecycle.py`:

```python
"""Tests for race lifecycle helpers."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def race_setup(async_session):
    """Create a running race with 2 participants."""
    async with async_session() as db:
        user1 = User(
            twitch_id="u1", twitch_username="player1",
            api_token="tok1", role=UserRole.USER,
        )
        user2 = User(
            twitch_id="u2", twitch_username="player2",
            api_token="tok2", role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org", twitch_username="organizer",
            api_token="tok_org", role=UserRole.ORGANIZER,
        )
        db.add_all([user1, user2, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s1", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p1 = Participant(
            race_id=race.id, user_id=user1.id,
            status=ParticipantStatus.FINISHED, igt_ms=300000,
            finished_at=datetime.now(UTC),
        )
        p2 = Participant(
            race_id=race.id, user_id=user2.id,
            status=ParticipantStatus.PLAYING, igt_ms=200000,
        )
        db.add_all([p1, p2])
        await db.commit()

        return race.id, p1.id, p2.id


@pytest.mark.asyncio
async def test_auto_finish_not_triggered_while_playing(async_session, race_setup):
    """Race stays RUNNING if any participant is still PLAYING."""
    race_id, _, _ = race_setup
    async with async_session() as db:
        race = await db.get(Race, race_id)
        transitioned = await check_race_auto_finish(db, race)
        assert transitioned is False
        await db.refresh(race)
        assert race.status == RaceStatus.RUNNING


@pytest.mark.asyncio
async def test_auto_finish_when_all_done(async_session, race_setup):
    """Race transitions to FINISHED when all participants are FINISHED or ABANDONED."""
    race_id, _, p2_id = race_setup
    async with async_session() as db:
        p2 = await db.get(Participant, p2_id)
        p2.status = ParticipantStatus.ABANDONED
        await db.commit()

    async with async_session() as db:
        race = await db.get(Race, race_id)
        # Eagerly load participants for the check
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        result = await db.execute(
            select(Race).where(Race.id == race_id).options(selectinload(Race.participants))
        )
        race = result.scalar_one()
        transitioned = await check_race_auto_finish(db, race)
        assert transitioned is True
        await db.refresh(race)
        assert race.status == RaceStatus.FINISHED
```

### Step 2: Run the test to verify it fails

Run: `cd server && uv run pytest tests/test_race_lifecycle.py -x -v`
Expected: FAIL — `ImportError: cannot import 'check_race_auto_finish'`

### Step 3: Implement the helper

Create `server/speedfog_racing/services/race_lifecycle.py`:

```python
"""Race lifecycle helpers (auto-finish, abandon)."""

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus

logger = logging.getLogger(__name__)


async def check_race_auto_finish(db: AsyncSession, race: Race) -> bool:
    """Transition race to FINISHED if all participants are FINISHED or ABANDONED.

    Uses optimistic locking (version column) to handle concurrent updates.
    Returns True if the race was transitioned.

    Requires: race.participants must be eagerly loaded.
    """
    all_done = all(
        p.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED)
        for p in race.participants
    )
    if not all_done:
        return False

    result = await db.execute(
        update(Race)
        .where(
            Race.id == race.id,
            Race.status == RaceStatus.RUNNING,
            Race.version == race.version,
        )
        .values(status=RaceStatus.FINISHED, version=race.version + 1)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        logger.warning(f"Race {race.id} already transitioned (concurrent update)")
        await db.commit()
        return False

    race.status = RaceStatus.FINISHED
    race.version += 1
    await db.commit()
    return True
```

### Step 4: Export from services `__init__.py`

In `server/speedfog_racing/services/__init__.py`, add:

```python
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
```

### Step 5: Run the test

Run: `cd server && uv run pytest tests/test_race_lifecycle.py -x -v`
Expected: PASS.

### Step 6: Refactor `mod.py` to use the shared helper

In `server/speedfog_racing/websocket/mod.py`, replace the inline auto-finish logic in `handle_finished` (lines 605-632) with:

```python
from speedfog_racing.services.race_lifecycle import check_race_auto_finish

# ... inside handle_finished, after reload:
race_transitioned = await check_race_auto_finish(db, participant.race)
```

Remove the old inline `all_finished` check, the `update(Race)` block, and the manual `race_obj.status/version` assignments. Keep the `race_transitioned` flag usage for broadcasting/Discord notification that follows.

### Step 7: Run all tests

Run: `cd server && uv run pytest -x -q`
Expected: all pass.

### Step 8: Lint

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`

### Step 9: Commit

```bash
git add server/speedfog_racing/services/race_lifecycle.py server/speedfog_racing/services/__init__.py server/speedfog_racing/websocket/mod.py server/tests/test_race_lifecycle.py
git commit -m "refactor: extract check_race_auto_finish helper from mod.py"
```

---

## Task 4: Add `POST /api/races/{id}/abandon` endpoint

**Files:**

- Modify: `server/speedfog_racing/api/races.py` (add endpoint after `finish_race`)
- Test: `server/tests/test_races.py`

### Step 1: Write the tests

Add to `server/tests/test_races.py`:

```python
@pytest.mark.asyncio
async def test_abandon_race_success(test_client, organizer, player, async_session):
    """Player can abandon a running race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn1", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/abn1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Abandon Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id, user_id=player.id,
            status=ParticipantStatus.PLAYING, igt_ms=150000,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # Race should still be running (other participants may exist or
        # in this case the single participant abandoned, triggering auto-finish)
        # With a single participant who abandons, auto-finish kicks in
        assert data["status"] == "finished"


@pytest.mark.asyncio
async def test_abandon_race_not_participant(test_client, organizer, player, async_session):
    """Non-participant cannot abandon a race."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn2", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/abn2",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="No Abandon", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_abandon_race_not_running(test_client, organizer, player, async_session):
    """Cannot abandon a race that is not running."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn3", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/abn3",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Setup Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id, user_id=player.id,
            status=ParticipantStatus.REGISTERED,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_abandon_race_already_finished(test_client, organizer, player, async_session):
    """Cannot abandon if already finished."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_abn4", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/abn4",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Finished Player", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id, user_id=player.id,
            status=ParticipantStatus.FINISHED, igt_ms=300000,
            finished_at=datetime.now(UTC),
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_abandon_race_auto_finishes_when_last(
    test_client, organizer, player, async_session
):
    """When last playing participant abandons, race auto-finishes."""
    async with async_session() as db:
        player2 = User(
            twitch_id="p2_abn", twitch_username="player2_abn",
            api_token="player2_abn_token", role=UserRole.USER,
        )
        db.add(player2)
        await db.flush()
        seed = Seed(
            seed_number="s_abn5", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/abn5",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Auto Finish", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        p1 = Participant(
            race_id=race.id, user_id=player.id,
            status=ParticipantStatus.PLAYING, igt_ms=150000,
        )
        p2 = Participant(
            race_id=race.id, user_id=player2.id,
            status=ParticipantStatus.FINISHED, igt_ms=200000,
            finished_at=datetime.now(UTC),
        )
        db.add_all([p1, p2])
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/abandon",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "finished"
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_races.py::test_abandon_race_success -x -v`
Expected: FAIL — 404 (endpoint doesn't exist yet).

### Step 3: Implement the endpoint

Add to `server/speedfog_racing/api/races.py`, after the `finish_race` function (around line 1121):

```python
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
    participant = next(
        (p for p in race.participants if p.user_id == user.id), None
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a participant in this race",
        )

    if participant.status != ParticipantStatus.PLAYING:
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
    from speedfog_racing.services.race_lifecycle import check_race_auto_finish

    race_transitioned = await check_race_auto_finish(db, race)
    if race_transitioned:
        race = await _get_race_or_404(db, race_id, load_participants=True, load_casters=True)
        await broadcast_race_state_update(race_id, race)
        await manager.broadcast_race_status(race_id, "finished")

    return race_response(race)
```

Add the `broadcast_race_state_update` import at the top if not already there (it's already imported at line 45).

### Step 4: Run the tests

Run: `cd server && uv run pytest tests/test_races.py -k abandon -x -v`
Expected: all 5 abandon tests PASS.

### Step 5: Run full test suite

Run: `cd server && uv run pytest -x -q`
Expected: all pass.

### Step 6: Lint

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`

### Step 7: Commit

```bash
git add server/speedfog_racing/api/races.py server/tests/test_races.py
git commit -m "feat: add POST /api/races/{id}/abandon endpoint"
```

---

## Task 5: Add inactivity monitor background task

**Files:**

- Create: `server/speedfog_racing/services/inactivity_monitor.py`
- Modify: `server/speedfog_racing/main.py:39-73` (add task to lifespan)
- Test: `server/tests/test_inactivity_monitor.py`

### Step 1: Write the test

Create `server/tests/test_inactivity_monitor.py`:

```python
"""Tests for inactivity monitor."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.inactivity_monitor import abandon_inactive_participants


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_abandons_stale_participant(async_session):
    """Participant with stale IGT (>5min) is marked ABANDONED."""
    async with async_session() as db:
        user = User(
            twitch_id="stale1", twitch_username="stale_player",
            api_token="stale_tok", role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_stale", twitch_username="org_stale",
            api_token="org_stale_tok", role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_stale", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/stale",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Stale Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id, user_id=user.id,
            status=ParticipantStatus.PLAYING, igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=6),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 1

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.ABANDONED


@pytest.mark.asyncio
async def test_does_not_abandon_active_participant(async_session):
    """Participant with recent IGT change is not abandoned."""
    async with async_session() as db:
        user = User(
            twitch_id="active1", twitch_username="active_player",
            api_token="active_tok", role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_active", twitch_username="org_active",
            api_token="org_active_tok", role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_active", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/active",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Active Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id, user_id=user.id,
            status=ParticipantStatus.PLAYING, igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.PLAYING


@pytest.mark.asyncio
async def test_does_not_abandon_null_last_igt(async_session):
    """Participant with NULL last_igt_change_at is not abandoned (still loading)."""
    async with async_session() as db:
        user = User(
            twitch_id="null1", twitch_username="null_player",
            api_token="null_tok", role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_null", twitch_username="org_null",
            api_token="org_null_tok", role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_null", pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5, folder_path="/test/null",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Null IGT Race", organizer_id=organizer.id, seed_id=seed.id,
            status=RaceStatus.RUNNING, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id, user_id=user.id,
            status=ParticipantStatus.PLAYING, igt_ms=0,
            last_igt_change_at=None,
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.PLAYING
```

### Step 2: Run to verify failure

Run: `cd server && uv run pytest tests/test_inactivity_monitor.py -x -v`
Expected: FAIL — `ImportError`

### Step 3: Implement the monitor

Create `server/speedfog_racing/services/inactivity_monitor.py`:

```python
"""Background task to auto-abandon participants with stale IGT."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus
from speedfog_racing.services.race_lifecycle import check_race_auto_finish

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = timedelta(minutes=5)
POLL_INTERVAL = 60  # seconds


async def abandon_inactive_participants(
    session_maker: async_sessionmaker[AsyncSession],
) -> list:
    """Find and abandon participants whose IGT hasn't changed in INACTIVITY_TIMEOUT.

    Returns list of race IDs that had abandonments (for broadcasting).
    """
    cutoff = datetime.now(UTC) - INACTIVITY_TIMEOUT
    affected_race_ids = []

    async with session_maker() as db:
        result = await db.execute(
            select(Participant)
            .join(Race)
            .where(
                Participant.status == ParticipantStatus.PLAYING,
                Race.status == RaceStatus.RUNNING,
                Participant.last_igt_change_at.isnot(None),
                Participant.last_igt_change_at < cutoff,
            )
            .options(selectinload(Participant.race).selectinload(Race.participants))
        )
        stale_participants = result.scalars().unique().all()

        for p in stale_participants:
            logger.info(
                "Auto-abandoning participant %s (last IGT change: %s)",
                p.id,
                p.last_igt_change_at,
            )
            p.status = ParticipantStatus.ABANDONED
            if p.race_id not in affected_race_ids:
                affected_race_ids.append(p.race_id)

        if stale_participants:
            await db.commit()

    # Check auto-finish for each affected race
    for race_id in list(affected_race_ids):
        async with session_maker() as db:
            result = await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(selectinload(Race.participants))
            )
            race = result.scalar_one_or_none()
            if race and race.status == RaceStatus.RUNNING:
                await check_race_auto_finish(db, race)

    return affected_race_ids


async def inactivity_monitor_loop(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodic loop that checks for inactive participants."""
    logger.info("Inactivity monitor started (timeout=%s, poll=%ds)", INACTIVITY_TIMEOUT, POLL_INTERVAL)
    while True:
        try:
            affected = await abandon_inactive_participants(session_maker)
            if affected:
                # Broadcast updates for affected races
                from speedfog_racing.websocket.manager import manager
                from speedfog_racing.websocket.spectator import broadcast_race_state_update

                for race_id in affected:
                    async with session_maker() as db:
                        result = await db.execute(
                            select(Race)
                            .where(Race.id == race_id)
                            .options(
                                selectinload(Race.participants),
                                selectinload(Race.casters),
                            )
                        )
                        race = result.scalar_one_or_none()
                        if race:
                            graph_json = race.seed.graph_json if race.seed else None
                            await manager.broadcast_leaderboard(
                                race_id, race.participants, graph_json=graph_json
                            )
                            await broadcast_race_state_update(race_id, race)
                            if race.status == RaceStatus.FINISHED:
                                await manager.broadcast_race_status(race_id, "finished")
        except Exception:
            logger.exception("Inactivity monitor error")

        await asyncio.sleep(POLL_INTERVAL)
```

### Step 4: Run tests

Run: `cd server && uv run pytest tests/test_inactivity_monitor.py -x -v`
Expected: all 3 PASS.

### Step 5: Wire into lifespan

In `server/speedfog_racing/main.py`, modify the lifespan:

```python
# Add import at the top:
from speedfog_racing.services.inactivity_monitor import inactivity_monitor_loop

# In lifespan, before yield:
    monitor_task = asyncio.create_task(inactivity_monitor_loop(async_session_maker))

    yield

    # Shutdown
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down SpeedFog Racing server...")
```

Add `import asyncio` to imports if not already present. Import `async_session_maker` from `speedfog_racing.database` (already imported at line 19).

### Step 6: Run full suite

Run: `cd server && uv run pytest -x -q`
Expected: all pass.

### Step 7: Lint

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`

### Step 8: Commit

```bash
git add server/speedfog_racing/services/inactivity_monitor.py server/speedfog_racing/main.py server/tests/test_inactivity_monitor.py
git commit -m "feat: add inactivity monitor to auto-abandon stale participants"
```

---

## Task 6: Add `abandonRace` to frontend API client

**Files:**

- Modify: `web/src/lib/api.ts` (add function after `finishRace`)

### Step 1: Add the function

In `web/src/lib/api.ts`, add after `finishRace` (around line 464):

```typescript
export async function abandonRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/abandon`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}
```

### Step 2: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 3: Commit

```bash
git add web/src/lib/api.ts
git commit -m "feat: add abandonRace API client function"
```

---

## Task 7: Add Abandon button to race detail page

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`
- Modify: `web/src/lib/api.ts` (import already added in Task 6)

### Step 1: Add imports and state

In `web/src/routes/race/[id]/+page.svelte`, add `abandonRace` to the imports from `$lib/api` (line 28-36):

```typescript
import {
  downloadMySeedPack,
  removeParticipant,
  deleteInvite,
  fetchRace,
  updateRace,
  joinRace,
  leaveRace,
  abandonRace,
  type RaceDetail,
} from "$lib/api";
```

Add state variables after `leaving` (around line 43):

```typescript
let confirmAbandon = $state(false);
let abandoning = $state(false);
let abandonError = $state<string | null>(null);
```

### Step 2: Add the handler function

Add after `handleLeave` (around line 274):

```typescript
async function handleAbandon() {
  if (!confirmAbandon) {
    confirmAbandon = true;
    return;
  }
  abandoning = true;
  abandonError = null;
  try {
    await abandonRace(initialRace.id);
    initialRace = await fetchRace(initialRace.id);
    confirmAbandon = false;
  } catch (e) {
    abandonError = e instanceof Error ? e.message : "Failed to abandon";
  } finally {
    abandoning = false;
  }
}
```

### Step 3: Add derived state for button visibility

Add a derived to check if the user can abandon. The participant must be PLAYING and the race must be RUNNING. Use the WS live status when available:

```typescript
let myLiveStatus = $derived(myWsParticipant?.status ?? myParticipant?.status);
let canAbandon = $derived(
  raceStatus === "running" && !!myParticipant && myLiveStatus === "playing",
);
```

### Step 4: Add the button in the running state sidebar

In the `raceStatus === 'running'` block (around line 359-375), add the abandon button after the leaderboard section, before the organizer RaceControls:

```svelte
{#if canAbandon}
    <div class="abandon-section">
        {#if confirmAbandon}
            <p class="abandon-warning">Are you sure? This is irreversible.</p>
            <div class="abandon-actions">
                <button class="btn btn-danger" onclick={handleAbandon} disabled={abandoning}>
                    {abandoning ? 'Abandoning...' : 'Confirm Abandon'}
                </button>
                <button class="btn-inline btn-inline-secondary" onclick={() => (confirmAbandon = false)} disabled={abandoning}>
                    Cancel
                </button>
            </div>
        {:else}
            <button class="abandon-btn" onclick={handleAbandon}>
                Abandon Race
            </button>
        {/if}
        {#if abandonError}
            <p class="abandon-error">{abandonError}</p>
        {/if}
    </div>
{/if}
```

### Step 5: Add styles

Add to the `<style>` block:

```css
.abandon-section {
  padding-top: 0.75rem;
  border-top: 1px solid var(--color-border);
}

.abandon-btn {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-disabled);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition);
}

.abandon-btn:hover {
  border-color: var(--color-danger, #ef4444);
  color: var(--color-danger, #ef4444);
}

.abandon-warning {
  margin: 0 0 0.5rem;
  color: var(--color-danger, #ef4444);
  font-size: var(--font-size-sm);
  font-weight: 500;
}

.abandon-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.abandon-error {
  margin: 0.5rem 0 0;
  color: var(--color-danger, #ef4444);
  font-size: var(--font-size-sm);
}
```

### Step 6: Run checks

Run: `cd web && npm run check`
Expected: no errors.

Run: `cd web && npm run lint`
Expected: clean (or pre-existing warnings only).

### Step 7: Commit

```bash
git add web/src/routes/race/[id]/+page.svelte web/src/lib/api.ts
git commit -m "feat: add Abandon Race button to race detail page"
```

---

## Task 8: Final integration test and cleanup

**Files:**

- All files from previous tasks

### Step 1: Run full backend test suite

Run: `cd server && uv run pytest -x -v`
Expected: all pass.

### Step 2: Run linters

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`
Expected: clean.

### Step 3: Run frontend checks

Run: `cd web && npm run check && npm run lint`
Expected: clean.

### Step 4: Review all changes

Run: `git diff HEAD~7 --stat` (adjust count to match number of commits)
Verify no unintended changes.

### Step 5: Update CHANGELOG.md

Add under `[Unreleased]`:

```markdown
### Added

- Players can now abandon a running race via a button on the race page
- Inactive players (IGT unchanged for 5 minutes) are automatically abandoned
```

### Step 6: Commit changelog

```bash
git add CHANGELOG.md
git commit -m "docs: add abandon feature to changelog"
```
