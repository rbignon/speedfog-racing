# Open Registration Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make open-registration races visually discoverable through a navbar badge, race card indicators, and a dashboard section.

**Architecture:** `can_join` boolean field computed server-side in `race_response()` and returned on every race listing. New `GET /api/races/joinable` endpoint for the navbar count and dashboard section. RaceCard reads `race.can_join` directly (no prop needed).

**Tech Stack:** Python/FastAPI, SQLAlchemy async, SvelteKit 5 (runes), CSS

---

## Task 1: Add `can_join` field to `RaceResponse` and `race_response()`

**Files:**

- Modify: `server/speedfog_racing/schemas.py`
- Modify: `server/speedfog_racing/api/helpers.py`
- Modify: `server/speedfog_racing/api/races.py`
- Test: `server/tests/test_can_join_field.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for can_join field on race responses."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
    Participant,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
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
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="cj_org",
            twitch_username="cj_org",
            twitch_display_name="Organizer",
            api_token="cj_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="cj_player",
            twitch_username="cj_player",
            twitch_display_name="Player",
            api_token="cj_player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="cj_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/cj_seed.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _create_race(db, organizer, seed, *, open_registration=True, max_participants=None, status=RaceStatus.SETUP):
    """Helper to create a race directly in the DB."""
    race = Race(
        name="Test Race",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
        open_registration=open_registration,
        max_participants=max_participants,
    )
    db.add(race)
    await db.commit()
    await db.refresh(race)
    return race


# =============================================================================
# can_join field tests
# =============================================================================


@pytest.mark.asyncio
async def test_can_join_true_for_open_setup_race(test_client, organizer, player, seed, async_session):
    """Open setup race returns can_join=True for unrelated player."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is True


@pytest.mark.asyncio
async def test_can_join_false_for_organizer(test_client, organizer, seed, async_session):
    """Organizer's own open race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_participant(test_client, organizer, player, seed, async_session):
    """Player already in the race gets can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Participant(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_caster(test_client, organizer, player, seed, async_session):
    """Caster gets can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Caster(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_invite_only(test_client, organizer, player, seed, async_session):
    """Invite-only race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, open_registration=False)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_running_race(test_client, organizer, player, seed, async_session):
    """Running open race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, status=RaceStatus.RUNNING)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=running",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_when_full(test_client, organizer, player, seed, async_session):
    """Full open race returns can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed, max_participants=1)
        filler = User(
            twitch_id="cj_filler",
            twitch_username="cj_filler",
            twitch_display_name="Filler",
            api_token="cj_filler_token",
            role=UserRole.USER,
        )
        db.add(filler)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=filler.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_true_unauthenticated(test_client, organizer, seed, async_session):
    """Unauthenticated users see can_join=True for open setup races (CTA)."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get("/api/races?status=setup")
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_can_join_field.py -v`
Expected: All tests FAIL (`can_join` field missing from response).

- [ ] **Step 3: Add `can_join` to `RaceResponse` schema**

In `server/speedfog_racing/schemas.py`, add the field to `RaceResponse` (after `casters`, around line 234):

```python
    can_join: bool = False
```

- [ ] **Step 4: Update `race_response()` in helpers**

In `server/speedfog_racing/api/helpers.py`, update `race_response` to accept an optional user and compute `can_join`:

```python
def race_response(race: Race, user: User | None = None) -> RaceResponse:
    """Convert Race model to RaceResponse."""
    if race.status == RaceStatus.FINISHED:
        finished = sorted(
            [p for p in race.participants if p.status == ParticipantStatus.FINISHED],
            key=lambda p: p.igt_ms,
        )
        non_finished = [p for p in race.participants if p.status != ParticipantStatus.FINISHED]
        all_previews = [
            participant_preview(p.user, placement=i + 1) for i, p in enumerate(finished)
        ] + [participant_preview(p.user) for p in non_finished]
        previews = all_previews[:5]
    else:
        previews = [participant_preview(p.user) for p in race.participants[:5]]

    # Compute can_join
    participant_count = len(race.participants)
    is_open_setup = race.open_registration and race.status == RaceStatus.SETUP
    is_full = race.max_participants is not None and participant_count >= race.max_participants

    if not is_open_setup or is_full:
        can_join = False
    elif user is None:
        can_join = True
    else:
        casters = race.casters if hasattr(race, "casters") and race.casters is not None else []
        is_involved = (
            race.organizer_id == user.id
            or any(p.user_id == user.id for p in race.participants)
            or any(c.user_id == user.id for c in casters)
        )
        can_join = not is_involved

    return RaceResponse(
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
        participant_count=participant_count,
        participant_previews=previews,
        casters=[caster_response(c) for c in race.casters] if "casters" in race.__dict__ else [],
        can_join=can_join,
    )
```

Add the missing import at the top of `helpers.py`:

```python
from speedfog_racing.models import RaceStatus
```

(Check if `RaceStatus` is already imported; if so, skip this.)

- [ ] **Step 5: Pass `user` to all `race_response()` calls in `races.py`**

In `server/speedfog_racing/api/races.py`, update every call to `race_response(race)` to pass the user:

- Line 338 (`create_race`): `return race_response(race, user)`
- Line 418 (`list_races`, paginated): `races=[race_response(r, _user) for r in races],`
- Line 425 (`list_races`, non-paginated): `return RaceListResponse(races=[race_response(r, _user) for r in races])`
- Line 551 (`update_race`): `return race_response(race, user)`
- Line 1163 (`update_race_registration`): `return race_response(race, user)`
- Line 1310 (`remove_participant`): `return race_response(race, user)`
- Line 1352 (`start_race`): `return race_response(race, user)`
- Line 1407 (`cancel_race`): `return race_response(race, user)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_can_join_field.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 7: Run full test suite**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/helpers.py server/speedfog_racing/api/races.py server/tests/test_can_join_field.py
git commit -m "api: add can_join field to RaceResponse, computed server-side"
```

---

## Task 2: API endpoint `GET /api/races/joinable`

**Files:**

- Modify: `server/speedfog_racing/api/races.py`
- Test: `server/tests/test_joinable_races.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for GET /api/races/joinable endpoint."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
    Participant,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
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
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="joinable_org",
            twitch_username="joinable_org",
            twitch_display_name="Organizer",
            api_token="joinable_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="joinable_player",
            twitch_username="joinable_player",
            twitch_display_name="Player",
            api_token="joinable_player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="joinable_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/joinable_seed.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _create_race(db, organizer, seed, *, open_registration=True, max_participants=None, status=RaceStatus.SETUP, is_public=True):
    """Helper to create a race directly in the DB."""
    race = Race(
        name="Test Race",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
        open_registration=open_registration,
        max_participants=max_participants,
        is_public=is_public,
    )
    db.add(race)
    await db.commit()
    await db.refresh(race)
    return race


# =============================================================================
# Joinable races listing
# =============================================================================


@pytest.mark.asyncio
async def test_joinable_returns_open_setup_races(test_client, organizer, player, seed, async_session):
    """Open setup races where the user is not involved are returned."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["races"]) == 1
        assert data["races"][0]["can_join"] is True


@pytest.mark.asyncio
async def test_joinable_excludes_invite_only(test_client, organizer, player, seed, async_session):
    """Invite-only races are excluded."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, open_registration=False)

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_running_races(test_client, organizer, player, seed, async_session):
    """Running races are excluded even if open registration."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, status=RaceStatus.RUNNING)

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_organizer_races(test_client, organizer, seed, async_session):
    """Organizer's own races are excluded."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_participant_races(test_client, organizer, player, seed, async_session):
    """Races where the user is already a participant are excluded."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Participant(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_caster_races(test_client, organizer, player, seed, async_session):
    """Races where the user is a caster are excluded."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Caster(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_full_races(test_client, organizer, player, seed, async_session):
    """Full races (participant_count >= max_participants) are excluded."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed, max_participants=1)
        filler = User(
            twitch_id="filler",
            twitch_username="filler",
            twitch_display_name="Filler",
            api_token="filler_token",
            role=UserRole.USER,
        )
        db.add(filler)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=filler.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_excludes_private_races(test_client, organizer, player, seed, async_session):
    """Private races are excluded."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, is_public=False)

    async with test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["races"]) == 0


@pytest.mark.asyncio
async def test_joinable_requires_auth(test_client, organizer, seed, async_session):
    """Unauthenticated requests get 401."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get("/api/races/joinable")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_joinable_races.py -v`
Expected: All tests FAIL (endpoint does not exist, 404 or 405).

- [ ] **Step 3: Implement the endpoint**

Add the following endpoint in `server/speedfog_racing/api/races.py`, before the `list_races` function (around line 341). It must come before `/{race_id}` to avoid route conflict.

```python
@router.get("/joinable", response_model=RaceListResponse)
async def list_joinable_races(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceListResponse:
    """List open-registration setup races the user can join."""
    my_participant_races = select(Participant.race_id).where(Participant.user_id == user.id)
    my_caster_races = select(Caster.race_id).where(Caster.user_id == user.id)

    # Count participants per race for the "not full" check
    participant_count_sq = (
        select(Participant.race_id, func.count().label("cnt"))
        .group_by(Participant.race_id)
        .subquery()
    )

    query = (
        select(Race)
        .options(
            selectinload(Race.organizer),
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.casters).selectinload(Caster.user),
        )
        .outerjoin(participant_count_sq, Race.id == participant_count_sq.c.race_id)
        .where(
            Race.status == RaceStatus.SETUP,
            Race.open_registration.is_(True),
            Race.is_public.is_(True),
            Race.organizer_id != user.id,
            Race.id.notin_(my_participant_races),
            Race.id.notin_(my_caster_races),
            or_(
                Race.max_participants.is_(None),
                Race.max_participants > func.coalesce(participant_count_sq.c.cnt, 0),
            ),
        )
        .order_by(
            case((Race.scheduled_at.is_(None), 1), else_=0),
            Race.scheduled_at.asc(),
            Race.created_at.desc(),
        )
    )

    result = await db.execute(query)
    races = list(result.scalars().all())
    return RaceListResponse(races=[race_response(r, user) for r in races])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_joinable_races.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/api/races.py server/tests/test_joinable_races.py
git commit -m "api: add GET /api/races/joinable endpoint"
```

---

## Task 3: Frontend type + API client

**Files:**

- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Add `can_join` to `Race` interface**

In the `Race` interface (around line 48, after `my_death_count`):

```typescript
can_join: boolean;
```

- [ ] **Step 2: Add `fetchJoinableRaces` function**

Add after the `fetchRacesPaginated` function (around line 229):

```typescript
/**
 * Fetch open-registration races the current user can join.
 * Requires authentication.
 */
export async function fetchJoinableRaces(): Promise<Race[]> {
  const response = await fetch(`${API_BASE}/races/joinable`, {
    headers: getAuthHeaders(),
  });
  const data = await handleResponse<RaceListResponse>(response);
  return data.races;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "web: add can_join to Race type and fetchJoinableRaces function"
```

---

## Task 4: "Open" badge CSS class

**Files:**

- Modify: `web/src/app.css`

- [ ] **Step 1: Add `.badge-open` class**

Add after the `.badge-setup` block (around line 195):

```css
.badge-open {
  background: rgba(16, 185, 129, 0.15);
  color: var(--color-success);
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/app.css
git commit -m "web: add badge-open CSS class"
```

---

## Task 5: RaceCard "Open" badge + "Join" button

**Files:**

- Modify: `web/src/lib/components/RaceCard.svelte`

- [ ] **Step 1: Add derived state for Open badge**

Add after the existing derived declarations (around line 30):

```typescript
let showOpenBadge = $derived(race.open_registration && race.status === "setup");
```

- [ ] **Step 2: Add "Open" badge in the header badges row**

In the `race-badges` div (around line 68), add the Open badge before the role badge:

```svelte
<div class="race-badges">
    {#if showOpenBadge}
        <span class="badge badge-open">Open</span>
    {/if}
    {#if role}
        <span class="badge badge-role">{role}</span>
    {/if}
    <span class="badge badge-{race.status}">{statusLabel(race.status)}</span>
</div>
```

- [ ] **Step 3: Add "Join" button in the avatar row**

In the avatar row, add the Join button in the winner position (between avatar stack and relative time). Replace the avatar row block (lines 76-114) with:

```svelte
{#if race.participant_previews.length > 0}
    <div class="avatar-row" class:has-winner={winner}>
        <div class="avatar-stack">
            {#each race.participant_previews as user}
                {#if user.twitch_avatar_url}
                    <img
                        src={user.twitch_avatar_url}
                        alt={user.twitch_display_name || user.twitch_username}
                        class="avatar"
                    />
                {:else}
                    <span class="avatar avatar-placeholder">
                        {(user.twitch_display_name || user.twitch_username).charAt(0).toUpperCase()}
                    </span>
                {/if}
            {/each}
            {#if overflowCount > 0}
                <span class="avatar avatar-overflow">+{overflowCount}</span>
            {/if}
        </div>
        {#if winner}
            <div class="winner-info">
                <svg class="trophy-icon" viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                    <path d="M12 2C9.24 2 7 4.24 7 7h-3c-1.1 0-2 .9-2 2v2c0 2.21 1.79 4 4 4h.68A7.01 7.01 0 0012 19.87V22H8v2h8v-2h-4v-2.13A7.01 7.01 0 0017.32 15H18c2.21 0 4-1.79 4-4V9c0-1.1-.9-2-2-2h-3c0-2.76-2.24-5-5-5zM4 11V9h3v4.83C5.17 13.1 4 11.65 4 11zm16 0c0 1.65-1.17 3.1-3 3.83V9h3v2z"/>
                </svg>
                {#if winner.twitch_avatar_url}
                    <img src={winner.twitch_avatar_url} alt="" class="winner-avatar" />
                {/if}
                <span class="winner-name">{winner.twitch_display_name || winner.twitch_username}</span>
            </div>
        {:else if race.can_join}
            <span class="join-cta">Join</span>
        {/if}
        <span class="relative-time">{relativeTime}</span>
    </div>
{:else}
    <div class="avatar-row">
        <span class="no-participants">No players yet</span>
        {#if race.can_join}
            <span class="join-cta">Join</span>
        {/if}
        <span class="relative-time">{relativeTime}</span>
    </div>
{/if}
```

- [ ] **Step 4: Update player count format when max_participants is set**

In the meta row (around line 136), update the participant count display:

```svelte
<span>
    {race.participant_count}{#if race.max_participants}/{race.max_participants}{/if} player{race.participant_count !== 1 ? 's' : ''}
    {#if race.pool_name}
        &middot; {formatPoolName(race.pool_name)}
    {/if}
</span>
```

- [ ] **Step 5: Add CSS for the Join CTA**

Add the following styles in the `<style>` block (after the `.winner-name` styles, around line 359):

```css
.join-cta {
  border: 1px solid var(--color-success);
  color: var(--color-success);
  font-weight: 600;
  font-size: var(--font-size-xs);
  padding: 0.2rem 0.65rem;
  border-radius: var(--radius-sm);
  letter-spacing: 0.03em;
}
```

- [ ] **Step 6: Verify with dev server**

Run: `cd web && npm run check`
Expected: No type errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/components/RaceCard.svelte
git commit -m "web: add Open badge and Join CTA to RaceCard"
```

---

## Task 6: Navbar badge on "Races" button

**Files:**

- Modify: `web/src/routes/+layout.svelte`

- [ ] **Step 1: Add joinable count state and fetch**

In the `<script>` tag of `+layout.svelte`, add the import and state (after the existing imports, around line 7):

```typescript
import { fetchJoinableRaces } from "$lib/api";

let joinableCount = $state(0);
```

Add an `$effect` to fetch the count when the user is logged in (after the `onMount` block, around line 40):

```typescript
$effect(() => {
  if (auth.isLoggedIn) {
    fetchJoinableRaces()
      .then((races) => {
        joinableCount = races.length;
      })
      .catch(() => {
        joinableCount = 0;
      });
  } else {
    joinableCount = 0;
  }
});
```

- [ ] **Step 2: Add the badge to the "Races" link**

Replace the "Races" link (line 82) with:

```svelte
<a href="/races" class="btn btn-secondary btn-with-badge">
    Races
    {#if joinableCount > 0}
        <span class="nav-badge">{joinableCount}</span>
    {/if}
</a>
```

- [ ] **Step 3: Add CSS for the badge**

Add the following styles in the `<style>` block (after the `.nav-icon:hover` styles, around line 230):

```css
.btn-with-badge {
  position: relative;
}

.nav-badge {
  position: absolute;
  top: -7px;
  right: -7px;
  background: var(--color-success);
  color: var(--color-bg);
  font-size: 0.6rem;
  font-weight: 700;
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  line-height: 1;
}
```

- [ ] **Step 4: Verify with dev server**

Run: `cd web && npm run check`
Expected: No type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/+layout.svelte
git commit -m "web: add joinable races count badge to navbar"
```

---

## Task 7: Dashboard "Races to Join" section

**Files:**

- Modify: `web/src/routes/dashboard/+page.svelte`

- [ ] **Step 1: Add joinable races state and fetch**

In the `<script>` tag, add `fetchJoinableRaces` to the existing import from `$lib/api` (around line 8):

```typescript
import { fetchJoinableRaces } from "$lib/api"; // add to existing import
```

Add the import for RaceCard (after the other component imports, around line 21):

```typescript
import RaceCard from "$lib/components/RaceCard.svelte";
```

Add state for joinable races (after the `trainingSessions` state, around line 28):

```typescript
let joinableRaces: Race[] = $state([]);
```

In the `Promise.all` block (around line 59), add `fetchJoinableRaces()`:

```typescript
Promise.all([
  fetchUserProfile(username),
  fetchUserActivity(username, 0, 20),
  fetchMyRaces(),
  fetchTrainingSessions(),
  fetchUserPoolStats(username),
  fetchJoinableRaces(),
]).then(([p, a, r, t, ps, jr]) => {
  profile = p;
  activity = a.items;
  myRaces = r;
  trainingSessions = t;
  poolStats = ps;
  joinableRaces = jr;
});
```

- [ ] **Step 2: Add the "Races to Join" section in the template**

After the closing `</section>` of the "Active Now" section (around line 310) and before the "Recent Activity" section, add:

```svelte
<!-- Races to Join Section -->
{#if joinableRaces.length > 0}
    <section class="joinable-section">
        <h2>Races to Join</h2>
        <div class="joinable-cards">
            {#each joinableRaces as race}
                <RaceCard {race} />
            {/each}
        </div>
        <div class="joinable-footer">
            <a href="/races" class="joinable-more">Browse all races</a>
        </div>
    </section>
{/if}
```

- [ ] **Step 3: Add CSS for the section**

Add the following styles in the `<style>` block (after the `.active-card-meta` styles, around line 650):

```css
/* Races to Join */
.joinable-section {
  margin-bottom: 2rem;
}

.joinable-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

.joinable-footer {
  padding-top: 0.75rem;
  text-align: center;
}

.joinable-more {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
}

.joinable-more:hover {
  color: var(--color-gold);
}
```

Add the responsive rule inside the existing `@media (max-width: 640px)` block:

```css
.joinable-cards {
  grid-template-columns: 1fr;
}
```

- [ ] **Step 4: Verify with dev server**

Run: `cd web && npm run check`
Expected: No type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/dashboard/+page.svelte
git commit -m "web: add Races to Join section on dashboard"
```

---

## Task 8: Integration check and linting

**Files:** All modified files from previous tasks.

- [ ] **Step 1: Run server tests**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run server linting**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Expected: No errors.

- [ ] **Step 3: Run frontend type check**

Run: `cd web && npm run check`
Expected: No errors.

- [ ] **Step 4: Run frontend linting**

Run: `cd web && npm run lint`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 5: Fix any issues and commit**

If any issues found, fix them and commit:

```bash
git add -u
git commit -m "fix: address lint/type issues from open registration visibility"
```
