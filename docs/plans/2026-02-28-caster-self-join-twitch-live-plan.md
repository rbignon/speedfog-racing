# Caster Self-Join & Twitch Live Detection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow any authenticated user to self-join/leave as a caster on a race, and auto-detect Twitch live status for participants and casters.

**Architecture:** Feature A adds two new REST endpoints (`cast-join`, `cast-leave`) mirroring the existing `join`/`leave` pattern, with frontend CasterList changes to support self-join/leave. Feature B adds a `TwitchLiveService` background task that polls the Twitch Helix API every 60s to detect live streams, injecting `is_live`/`stream_url` into WebSocket broadcasts.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, SvelteKit 5 with runes, Twitch Helix API, httpx

**Design doc:** `docs/plans/2026-02-28-caster-self-join-twitch-live.md`

---

## Task 1: Server — `cast-join` endpoint

**Files:**

- Modify: `server/speedfog_racing/api/races.py` (add endpoint after `leave_race` at ~line 932)
- Test: `server/tests/test_races.py`

### Step 1: Write failing tests

Add tests at the end of `server/tests/test_races.py`:

```python
# --- cast-join / cast-leave ---


@pytest.mark.asyncio
async def test_cast_join_success(test_client, organizer, player, seed):
    """Authenticated user can self-join as caster."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        caster_names = [c["user"]["twitch_username"] for c in data["casters"]]
        assert "player1" in caster_names


@pytest.mark.asyncio
async def test_cast_join_already_participant(test_client, organizer, player, seed):
    """Cannot cast-join if already a participant."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        # Add as participant first
        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        resp = await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cast_join_already_caster(test_client, organizer, player, seed):
    """Cannot cast-join twice."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        resp = await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cast_join_finished_race(test_client, organizer, player, seed):
    """Cannot cast-join a finished race."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        # Add participant so we can start
        await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "player1"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        await client.post(
            f"/api/races/{race_id}/release-seeds",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        await client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        await client.post(
            f"/api/races/{race_id}/finish",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )

        # Create a second user to be the caster
        # Use organizer since player is a participant
        resp = await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 400
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_races.py -k "cast_join" -v`
Expected: FAIL — 404 (endpoint doesn't exist)

### Step 3: Implement the endpoint

Add to `server/speedfog_racing/api/races.py` after the `leave_race` function (~line 932):

```python
@router.post("/{race_id}/cast-join", response_model=RaceDetailResponse)
async def cast_join(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RaceDetailResponse:
    """Self-register as a caster for a race."""
    race = await _get_race_or_404(db, race_id, load_participants=True)

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
    caster_result = await db.execute(
        select(Caster).where(
            Caster.race_id == race.id,
            Caster.user_id == user.id,
        )
    )
    if caster_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a caster for this race",
        )

    caster = Caster(race_id=race.id, user_id=user.id, user=user, race=race)
    db.add(caster)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a caster for this race",
        )

    return await _build_race_detail(db, race_id)
```

Ensure `Caster` is imported at the top of `races.py` (check existing imports — it should already be imported for the organizer add-caster endpoint).

### Step 4: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_races.py -k "cast_join" -v`
Expected: all 4 tests PASS

### Step 5: Commit

```bash
git add server/speedfog_racing/api/races.py server/tests/test_races.py
git commit -m "feat(api): add POST /races/{id}/cast-join endpoint for caster self-join"
```

---

## Task 2: Server — `cast-leave` endpoint

**Files:**

- Modify: `server/speedfog_racing/api/races.py` (add after `cast_join`)
- Test: `server/tests/test_races.py`

### Step 1: Write failing tests

```python
@pytest.mark.asyncio
async def test_cast_leave_success(test_client, organizer, player, seed):
    """Caster can self-remove."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        # Join as caster
        await client.post(
            f"/api/races/{race_id}/cast-join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )

        # Leave
        resp = await client.post(
            f"/api/races/{race_id}/cast-leave",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        caster_names = [c["user"]["twitch_username"] for c in data["casters"]]
        assert "player1" not in caster_names


@pytest.mark.asyncio
async def test_cast_leave_not_caster(test_client, organizer, player, seed):
    """Cannot leave if not a caster."""
    async with test_client as client:
        create_resp = await client.post(
            "/api/races",
            json={"name": "Cast Test"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/races/{race_id}/cast-leave",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 404
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_races.py -k "cast_leave" -v`
Expected: FAIL — 404 (endpoint doesn't exist)

### Step 3: Implement the endpoint

Add to `server/speedfog_racing/api/races.py` after `cast_join`:

```python
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

    return await _build_race_detail(db, race_id)
```

### Step 4: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_races.py -k "cast_leave" -v`
Expected: all 2 tests PASS

### Step 5: Run full test suite

Run: `cd server && uv run pytest -v`
Expected: all tests PASS

### Step 6: Commit

```bash
git add server/speedfog_racing/api/races.py server/tests/test_races.py
git commit -m "feat(api): add POST /races/{id}/cast-leave endpoint for caster self-remove"
```

---

## Task 3: Frontend — API client + CasterList self-join/leave

**Files:**

- Modify: `web/src/lib/api.ts` (add `castJoin`, `castLeave` functions after `leaveRace` at ~line 409)
- Modify: `web/src/lib/components/CasterList.svelte` (add self-join/leave UI)
- Modify: `web/src/routes/race/[id]/+page.svelte` (pass new props to CasterList)

### Step 1: Add API functions

Add to `web/src/lib/api.ts` after the `leaveRace` function:

```typescript
/**
 * Self-register as a caster for a race.
 */
export async function castJoin(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/cast-join`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Self-remove as a caster from a race.
 */
export async function castLeave(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/cast-leave`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}
```

### Step 2: Update CasterList component

Update `web/src/lib/components/CasterList.svelte` to support self-join/leave:

- Add new props: `canCast` (show "Cast this race" button), `isCaster` (current user is caster), `currentUserId` (to identify "(You)"), `raceId` is already present
- Add `castJoin`/`castLeave` imports and handlers
- Show "(You)" badge + "Leave" button when user is a caster
- Show "Cast this race" button when `canCast` is true

The script section becomes:

```svelte
<script lang="ts">
  import { removeCaster, fetchRace, castJoin, castLeave, type Caster, type RaceDetail } from '$lib/api';
  import ParticipantSearch from './ParticipantSearch.svelte';

  interface Props {
    casters: Caster[];
    editable?: boolean;
    canCast?: boolean;
    isCaster?: boolean;
    currentUserId?: string | null;
    raceId?: string;
    onRaceUpdated?: (race: RaceDetail) => void;
  }

  let { casters, editable = false, canCast = false, isCaster = false, currentUserId = null, raceId, onRaceUpdated }: Props = $props();

  let showSearch = $state(false);
  let error = $state<string | null>(null);
  let casting = $state(false);

  async function handleRemove(caster: Caster) {
    if (!raceId) return;
    error = null;
    try {
      await removeCaster(raceId, caster.id);
      if (raceId && onRaceUpdated) {
        const updated = await fetchRace(raceId);
        onRaceUpdated(updated);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to remove caster';
    }
  }

  async function handleAdded() {
    showSearch = false;
    if (raceId && onRaceUpdated) {
      const updated = await fetchRace(raceId);
      onRaceUpdated(updated);
    }
  }

  async function handleCastJoin() {
    if (!raceId) return;
    casting = true;
    error = null;
    try {
      const updated = await castJoin(raceId);
      onRaceUpdated?.(updated);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to join as caster';
    } finally {
      casting = false;
    }
  }

  async function handleCastLeave() {
    if (!raceId) return;
    casting = true;
    error = null;
    try {
      const updated = await castLeave(raceId);
      onRaceUpdated?.(updated);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to leave as caster';
    } finally {
      casting = false;
    }
  }
</script>
```

In the template, add "(You)" badge and leave button for the current user's caster entry:

```svelte
{#each casters as caster (caster.id)}
  <li class="caster-item">
    <!-- existing avatar + name + twitch link -->
    {#if currentUserId && caster.user.id === currentUserId}
      <span class="you-badge">You</span>
      <button class="remove-btn" onclick={handleCastLeave} disabled={casting} title="Leave casting">
        &times;
      </button>
    {:else if editable}
      <button class="remove-btn" onclick={() => handleRemove(caster)} title="Remove caster">
        &times;
      </button>
    {/if}
  </li>
{/each}
```

After the caster list, add the "Cast this race" button:

```svelte
{#if canCast}
  <button class="add-btn" onclick={handleCastJoin} disabled={casting}>
    {casting ? 'Joining...' : 'Cast this race'}
  </button>
{/if}
```

Add `.you-badge` style:

```css
.you-badge {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-purple);
  background: rgba(168, 85, 247, 0.15);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-weight: 600;
  flex-shrink: 0;
}
```

### Step 3: Update race detail page

In `web/src/routes/race/[id]/+page.svelte`, update the `<CasterList>` call (~line 544) to pass the new props:

```svelte
<CasterList
  casters={initialRace.casters}
  editable={isOrganizer && raceStatus === 'setup'}
  canCast={auth.isLoggedIn && !myParticipant && !isCaster && raceStatus !== 'finished'}
  {isCaster}
  currentUserId={auth.user?.id ?? null}
  raceId={initialRace.id}
  onRaceUpdated={handleRaceUpdated}
/>
```

Note: `editable` adds the ability to add/remove other casters (organizer feature). `canCast` adds the self-join button for any logged-in non-participant.

### Step 4: Run frontend checks

Run: `cd web && npm run check && npm run lint`
Expected: no errors

### Step 5: Commit

```bash
git add web/src/lib/api.ts web/src/lib/components/CasterList.svelte web/src/routes/race/\[id\]/+page.svelte
git commit -m "feat(web): add caster self-join/leave UI with Cast this race button"
```

---

## Task 4: Server — Twitch app access token helper

**Files:**

- Modify: `server/speedfog_racing/auth.py` (add `get_app_access_token()`)
- Test: `server/tests/test_twitch_live.py` (new file)

### Step 1: Write failing test

Create `server/tests/test_twitch_live.py`:

```python
"""Tests for Twitch live detection service."""

import time

import pytest

from speedfog_racing.auth import AppAccessToken, get_app_access_token


@pytest.mark.asyncio
async def test_get_app_access_token(monkeypatch):
    """App access token is fetched and cached."""

    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 200

            def json(self):
                return {"access_token": "test_token_123", "expires_in": 3600}

        return MockResponse()

    monkeypatch.setattr("speedfog_racing.auth.httpx.AsyncClient.post", mock_post)

    # Clear cache
    get_app_access_token._cache = None

    token = await get_app_access_token()
    assert token == "test_token_123"


@pytest.mark.asyncio
async def test_app_access_token_cached(monkeypatch):
    """Cached token is returned without re-fetching."""
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        class MockResponse:
            status_code = 200

            def json(self):
                return {"access_token": f"token_{call_count}", "expires_in": 3600}

        return MockResponse()

    monkeypatch.setattr("speedfog_racing.auth.httpx.AsyncClient.post", mock_post)

    # Clear cache
    get_app_access_token._cache = None

    token1 = await get_app_access_token()
    token2 = await get_app_access_token()
    assert token1 == token2
    assert call_count == 1
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_twitch_live.py -v`
Expected: FAIL — ImportError

### Step 3: Implement

Add to the end of `server/speedfog_racing/auth.py` (before the FastAPI dependencies section):

```python
@dataclass
class AppAccessToken:
    """Cached Twitch app access token."""

    token: str
    expires_at: float  # time.monotonic() timestamp


async def get_app_access_token() -> str:
    """Get a Twitch app access token (client credentials flow).

    Cached in memory; refreshes 60s before expiry.
    """
    cache: AppAccessToken | None = getattr(get_app_access_token, "_cache", None)
    if cache and time.monotonic() < cache.expires_at - 60:
        return cache.token

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)

        get_app_access_token._cache = AppAccessToken(  # type: ignore[attr-defined]
            token=token,
            expires_at=time.monotonic() + expires_in,
        )
        return token
```

Add `import time` at the top of `auth.py`.

### Step 4: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_twitch_live.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add server/speedfog_racing/auth.py server/tests/test_twitch_live.py
git commit -m "feat(auth): add Twitch app access token helper with caching"
```

---

## Task 5: Server — TwitchLiveService

**Files:**

- Create: `server/speedfog_racing/services/twitch_live.py`
- Test: `server/tests/test_twitch_live.py` (extend)

### Step 1: Write failing tests

Add to `server/tests/test_twitch_live.py`:

```python
from unittest.mock import AsyncMock, patch

from speedfog_racing.services.twitch_live import TwitchLiveService


@pytest.mark.asyncio
async def test_check_live_status_detects_live():
    """Service detects live users from Twitch API response."""
    service = TwitchLiveService()

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"user_login": "player1", "type": "live"},
            {"user_login": "player2", "type": "live"},
        ]
    }

    with patch("speedfog_racing.services.twitch_live.get_app_access_token", return_value="tok"):
        with patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            live_set = await service.check_live_status(["player1", "player2", "player3"])

    assert live_set == {"player1", "player2"}


@pytest.mark.asyncio
async def test_check_live_status_batches_over_100():
    """Usernames are batched in groups of 100."""
    service = TwitchLiveService()

    usernames = [f"user{i}" for i in range(150)]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}

    with patch("speedfog_racing.services.twitch_live.get_app_access_token", return_value="tok"):
        with patch("speedfog_racing.services.twitch_live.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            await service.check_live_status(usernames)

    # Should have been called twice: 100 + 50
    assert mock_client.get.call_count == 2
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_twitch_live.py::test_check_live_status_detects_live -v`
Expected: FAIL — ImportError

### Step 3: Implement TwitchLiveService

Create `server/speedfog_racing/services/twitch_live.py`:

```python
"""Twitch live status polling service."""

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.auth import get_app_access_token
from speedfog_racing.config import settings
from speedfog_racing.models import Caster, Participant, Race, RaceStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
BATCH_SIZE = 100  # Twitch API max per request


class TwitchLiveService:
    """Polls Twitch Helix API to detect live streams among race participants/casters."""

    def __init__(self) -> None:
        self.live_usernames: set[str] = set()

    async def check_live_status(self, usernames: list[str]) -> set[str]:
        """Query Twitch API for which usernames are currently live.

        Returns set of live usernames (lowercase).
        """
        if not usernames:
            return set()

        live: set[str] = set()
        token = await get_app_access_token()

        async with httpx.AsyncClient() as client:
            for i in range(0, len(usernames), BATCH_SIZE):
                batch = usernames[i : i + BATCH_SIZE]
                params = [("user_login", name) for name in batch]
                try:
                    resp = await client.get(
                        "https://api.twitch.tv/helix/streams",
                        params=params,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Client-Id": settings.twitch_client_id,
                        },
                    )
                    if resp.status_code == 200:
                        for stream in resp.json().get("data", []):
                            if stream.get("type") == "live":
                                live.add(stream["user_login"].lower())
                    else:
                        logger.warning("Twitch streams API returned %d", resp.status_code)
                except Exception:
                    logger.exception("Failed to query Twitch streams API")

        return live

    async def _collect_usernames(self, session: AsyncSession) -> list[str]:
        """Collect all unique twitch_usernames from active races."""
        result = await session.execute(
            select(Race)
            .where(Race.status.in_([RaceStatus.SETUP, RaceStatus.RUNNING]))
            .options(
                selectinload(Race.participants).selectinload(Participant.user),
                selectinload(Race.casters).selectinload(Caster.user),
            )
        )
        races = result.scalars().all()

        usernames: set[str] = set()
        for race in races:
            for p in race.participants:
                usernames.add(p.user.twitch_username.lower())
            for c in race.casters:
                usernames.add(c.user.twitch_username.lower())

        return sorted(usernames)

    async def poll_once(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        """Run one polling cycle: collect usernames, check Twitch, update state."""
        async with session_maker() as session:
            usernames = await self._collect_usernames(session)

        if not usernames:
            self.live_usernames = set()
            return

        new_live = await self.check_live_status(usernames)
        self.live_usernames = new_live

    def is_live(self, twitch_username: str) -> bool:
        """Check if a username is currently live."""
        return twitch_username.lower() in self.live_usernames

    def stream_url(self, twitch_username: str) -> str | None:
        """Return stream URL if user is live, else None."""
        if self.is_live(twitch_username):
            return f"https://twitch.tv/{twitch_username}"
        return None


# Module-level singleton
twitch_live_service = TwitchLiveService()


async def twitch_live_poll_loop(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Background loop that polls Twitch every POLL_INTERVAL seconds."""
    logger.info("Twitch live polling started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            await twitch_live_service.poll_once(session_maker)
            live_count = len(twitch_live_service.live_usernames)
            if live_count > 0:
                logger.debug("Twitch live: %d users online", live_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Twitch live poll error")
        await asyncio.sleep(POLL_INTERVAL)
```

### Step 4: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_twitch_live.py -v`
Expected: all tests PASS

### Step 5: Commit

```bash
git add server/speedfog_racing/services/twitch_live.py server/tests/test_twitch_live.py
git commit -m "feat(server): add TwitchLiveService for polling Twitch stream status"
```

---

## Task 6: Server — Wire TwitchLiveService into lifespan + WebSocket schemas

**Files:**

- Modify: `server/speedfog_racing/main.py` (start/stop poll loop in lifespan)
- Modify: `server/speedfog_racing/websocket/schemas.py` (add `is_live`, `stream_url` to `ParticipantInfo`)
- Modify: `server/speedfog_racing/websocket/manager.py` (inject live status in `participant_to_info`)

### Step 1: Add live fields to ParticipantInfo

In `server/speedfog_racing/websocket/schemas.py`, add to `ParticipantInfo` class (after `layer_entry_igt` at line 81):

```python
    is_live: bool = False
    stream_url: str | None = None
```

### Step 2: Inject live status in participant_to_info

In `server/speedfog_racing/websocket/manager.py`, update `participant_to_info()` (~line 390):

- Import at top: `from speedfog_racing.services.twitch_live import twitch_live_service`
- Add to the `ParticipantInfo(...)` constructor:

```python
        is_live=twitch_live_service.is_live(participant.user.twitch_username),
        stream_url=twitch_live_service.stream_url(participant.user.twitch_username),
```

### Step 3: Wire poll loop into lifespan

In `server/speedfog_racing/main.py`:

- Add import: `from speedfog_racing.services.twitch_live import twitch_live_poll_loop`
- In the `lifespan` function, after the `monitor_task` creation (~line 73), add:

```python
    # Start Twitch live polling (only if Twitch credentials are configured)
    twitch_live_task = None
    if settings.twitch_client_id and settings.twitch_client_secret:
        twitch_live_task = asyncio.create_task(twitch_live_poll_loop(async_session_maker))
```

- In the shutdown section, after `monitor_task.cancel()`, add:

```python
    if twitch_live_task:
        twitch_live_task.cancel()
        try:
            await twitch_live_task
        except asyncio.CancelledError:
            pass
```

### Step 4: Run full test suite

Run: `cd server && uv run pytest -v`
Expected: all tests PASS (the live status defaults to `False` so existing tests aren't affected)

### Step 5: Commit

```bash
git add server/speedfog_racing/websocket/schemas.py server/speedfog_racing/websocket/manager.py server/speedfog_racing/main.py
git commit -m "feat(server): wire TwitchLiveService into lifespan and WebSocket broadcasts"
```

---

## Task 7: Frontend — Add `is_live`/`stream_url` to WsParticipant + LIVE badge in ParticipantCard

**Files:**

- Modify: `web/src/lib/websocket.ts` (add `is_live`, `stream_url` to `WsParticipant`)
- Modify: `web/src/lib/components/ParticipantCard.svelte` (show LIVE badge)
- Modify: `web/src/lib/api.ts` (add `is_live` to `Caster` type if needed for REST response)

### Step 1: Update WsParticipant type

In `web/src/lib/websocket.ts`, add to `WsParticipant` interface (after `zone_history` at line 22):

```typescript
is_live: boolean;
stream_url: string | null;
```

### Step 2: Add LIVE badge to ParticipantCard

In `web/src/lib/components/ParticipantCard.svelte`, add a prop for live status and render a badge. Read the file first to identify exact insertion points.

Add to props interface:

```typescript
  isLive?: boolean;
  streamUrl?: string | null;
```

In the template, after the "(You)" or "(Org)" badge area, add:

```svelte
{#if isLive}
  <a
    href={streamUrl ?? `https://twitch.tv/${participant.user.twitch_username}`}
    target="_blank"
    rel="noopener noreferrer"
    class="live-badge"
    title="Watch live on Twitch"
    onclick={(e) => e.stopPropagation()}
  >LIVE</a>
{/if}
```

Add CSS:

```css
.live-badge {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #fff;
  background: #e91916;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  text-decoration: none;
  flex-shrink: 0;
  animation: pulse-live 2s ease-in-out infinite;
}

@keyframes pulse-live {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}
```

### Step 3: Pass live status to ParticipantCard

In `web/src/routes/race/[id]/+page.svelte`, wherever `ParticipantCard` is rendered, find the corresponding WsParticipant and pass `isLive`/`streamUrl`. The WsParticipant data is in `raceStore.participants`. Look for where `ParticipantCard` is rendered and add:

```svelte
isLive={raceStore.participants.find(wp => wp.twitch_username === participant.user.twitch_username)?.is_live ?? false}
streamUrl={raceStore.participants.find(wp => wp.twitch_username === participant.user.twitch_username)?.stream_url}
```

### Step 4: Add LIVE badge to CasterList

In `web/src/lib/components/CasterList.svelte`, add a `liveCasters` prop (a `Set<string>` of live twitch_usernames) and show a LIVE badge next to live casters. The caster list doesn't use WebSocket data directly, so the race detail page should pass this down.

Add to CasterList props:

```typescript
  liveUsernames?: Set<string>;
```

In the template, after the twitch link, add:

```svelte
{#if liveUsernames?.has(caster.user.twitch_username)}
  <a
    href="https://twitch.tv/{caster.user.twitch_username}"
    target="_blank"
    rel="noopener noreferrer"
    class="live-badge"
  >LIVE</a>
{/if}
```

Add the same `.live-badge` CSS as in ParticipantCard.

In the race detail page, compute live caster usernames from WebSocket data and pass to CasterList. Since casters aren't in the WsParticipant list, the live status for casters needs to come from somewhere. The simplest approach: the TwitchLiveService already tracks all usernames. Add a `liveUsernames` field to the spectator `race_state` message or broadcast caster live status separately.

**Alternative simpler approach:** Add a `CasterInfo` schema to the WebSocket `race_state` message that includes `is_live`/`stream_url`, mirroring how `ParticipantInfo` works. This requires more schema changes but is cleaner.

**Simplest approach for now:** Caster live status can be derived from the REST API. Add `is_live` and `stream_url` to the `CasterResponse` schema in `server/speedfog_racing/schemas.py`, and compute it from `twitch_live_service` when building the response. This way `initialRace.casters` already has the live status. It won't update in real-time without page refresh, but it's a reasonable v1.

Add to `CasterResponse` in `server/speedfog_racing/schemas.py`:

```python
class CasterResponse(BaseModel):
    id: UUID
    user: UserResponse
    is_live: bool = False
    stream_url: str | None = None
```

And in the API when building `RaceDetailResponse`, inject live status for casters.

### Step 5: Run checks

Run: `cd web && npm run check && npm run lint`
Expected: no errors

### Step 6: Commit

```bash
git add web/src/lib/websocket.ts web/src/lib/components/ParticipantCard.svelte web/src/lib/components/CasterList.svelte web/src/routes/race/\[id\]/+page.svelte server/speedfog_racing/schemas.py server/speedfog_racing/websocket/schemas.py
git commit -m "feat(web): add LIVE badge for streaming participants and casters"
```

---

## Task 8: Integration test + final verification

**Files:**

- Test: `server/tests/test_races.py` (verify cast-join endpoints with full flow)

### Step 1: Run full server test suite

Run: `cd server && uv run pytest -v`
Expected: all tests PASS

### Step 2: Run linters

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`
Expected: no errors

### Step 3: Run frontend checks

Run: `cd web && npm run check && npm run lint`
Expected: no errors

### Step 4: Commit any fixes

If any linting/type issues, fix and commit.

---

## Summary of all tasks

| #   | Task                                      | Type     | Files                                                                       |
| --- | ----------------------------------------- | -------- | --------------------------------------------------------------------------- |
| 1   | `cast-join` endpoint                      | Server   | `api/races.py`, `tests/test_races.py`                                       |
| 2   | `cast-leave` endpoint                     | Server   | `api/races.py`, `tests/test_races.py`                                       |
| 3   | Frontend API + CasterList self-join/leave | Frontend | `api.ts`, `CasterList.svelte`, `+page.svelte`                               |
| 4   | Twitch app access token helper            | Server   | `auth.py`, `tests/test_twitch_live.py`                                      |
| 5   | TwitchLiveService                         | Server   | `services/twitch_live.py`, `tests/test_twitch_live.py`                      |
| 6   | Wire into lifespan + WS schemas           | Server   | `main.py`, `schemas.py`, `manager.py`                                       |
| 7   | Frontend LIVE badges                      | Frontend | `websocket.ts`, `ParticipantCard.svelte`, `CasterList.svelte`, `schemas.py` |
| 8   | Integration test + verification           | Both     | full suite                                                                  |
