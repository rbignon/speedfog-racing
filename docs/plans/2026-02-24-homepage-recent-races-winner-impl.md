# Homepage Recent Races & Winner Display — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show the 2 most recent finished races on the homepage and display the winner on finished race cards.

**Architecture:** Add a `ParticipantPreview` schema (extends `UserResponse` with `placement`) to the server API. For finished races, `race_response()` returns all participants sorted by placement. The frontend reads placement from `participant_previews[0]` to show the winner on `RaceCard`, and the homepage fetches the 2 most recent finished races.

**Tech Stack:** Python/FastAPI (Pydantic v2), SvelteKit 5 (runes), TypeScript

---

## Task 1: Server — Add `ParticipantPreview` schema

**Files:**

- Modify: `server/speedfog_racing/schemas.py:66-74` (after `UserResponse`)
- Modify: `server/speedfog_racing/schemas.py:219` (`participant_previews` type)

### Step 1: Add `ParticipantPreview` class

In `server/speedfog_racing/schemas.py`, add after the `UserResponse` class (after line 74):

```python
class ParticipantPreview(UserResponse):
    """User with optional placement for race previews."""

    placement: int | None = None
```

### Step 2: Update `RaceResponse.participant_previews` type

In `RaceResponse`, change:

```python
participant_previews: list[UserResponse] = []
```

to:

```python
participant_previews: list[ParticipantPreview] = []
```

### Step 3: Run linting

Run: `cd server && uv run ruff check speedfog_racing/schemas.py && uv run mypy speedfog_racing/schemas.py`
Expected: PASS (no errors)

### Step 4: Commit

```bash
git add server/speedfog_racing/schemas.py
git commit -m "feat(server): add ParticipantPreview schema with placement field"
```

---

## Task 2: Server — Update `race_response()` with placement logic

**Files:**

- Modify: `server/speedfog_racing/api/helpers.py`

### Step 1: Update imports

In `helpers.py`, add `ParticipantPreview` to the imports from `schemas` and add `ParticipantStatus, RaceStatus` from `models`:

```python
from speedfog_racing.models import Caster, Participant, ParticipantStatus, Race, RaceStatus, User
from speedfog_racing.schemas import (
    CasterResponse,
    ParticipantPreview,
    ParticipantResponse,
    RaceResponse,
    UserResponse,
)
```

### Step 2: Add `participant_preview` helper function

Add this function after `user_response()`:

```python
def participant_preview(user: User, placement: int | None = None) -> ParticipantPreview:
    """Convert User model to ParticipantPreview."""
    return ParticipantPreview(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        placement=placement,
    )
```

### Step 3: Update `race_response()` to compute placement

Replace the `participant_previews` line in `race_response()`. The full updated function:

```python
def race_response(race: Race) -> RaceResponse:
    """Convert Race model to RaceResponse."""
    if race.status == RaceStatus.FINISHED:
        # Sort finished participants by igt_ms, then non-finished at the end
        finished = sorted(
            [p for p in race.participants if p.status == ParticipantStatus.FINISHED],
            key=lambda p: p.igt_ms,
        )
        non_finished = [p for p in race.participants if p.status != ParticipantStatus.FINISHED]
        previews = [
            participant_preview(p.user, placement=i + 1) for i, p in enumerate(finished)
        ] + [participant_preview(p.user) for p in non_finished]
    else:
        previews = [participant_preview(p.user) for p in race.participants[:5]]

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
        participant_count=len(race.participants),
        participant_previews=previews,
        casters=[caster_response(c) for c in race.casters] if "casters" in race.__dict__ else [],
    )
```

### Step 4: Run linting

Run: `cd server && uv run ruff check speedfog_racing/api/helpers.py && uv run mypy speedfog_racing/api/helpers.py`
Expected: PASS

### Step 5: Commit

```bash
git add server/speedfog_racing/api/helpers.py
git commit -m "feat(server): compute placement in race_response for finished races"
```

---

## Task 3: Server — Test placement in race listing

**Files:**

- Modify: `server/tests/test_races.py`

### Step 1: Write test for finished race placement

Add after the existing `test_list_races_filter_by_status` test (around line 297):

```python
@pytest.mark.asyncio
async def test_list_finished_races_includes_placement(test_client, organizer, async_session):
    """Finished races include participant placement sorted by igt_ms."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_place",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/place",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Finished Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        # Player who finished second (slower)
        player2 = User(
            twitch_id="p2",
            twitch_username="player2",
            twitch_display_name="Player Two",
            api_token="token_p2",
        )
        # Player who finished first (faster)
        player1 = User(
            twitch_id="p1",
            twitch_username="player1_fast",
            twitch_display_name="Player One",
            api_token="token_p1",
        )
        # Player who abandoned (no placement)
        player3 = User(
            twitch_id="p3",
            twitch_username="player3",
            twitch_display_name="Player Three",
            api_token="token_p3",
        )
        db.add_all([player1, player2, player3])
        await db.flush()

        p1 = Participant(
            race_id=race.id,
            user_id=player1.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=100000,
            death_count=2,
        )
        p2 = Participant(
            race_id=race.id,
            user_id=player2.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=200000,
            death_count=5,
        )
        p3 = Participant(
            race_id=race.id,
            user_id=player3.id,
            status=ParticipantStatus.ABANDONED,
            igt_ms=50000,
            death_count=1,
        )
        db.add_all([p1, p2, p3])
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/races?status=finished")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1

        previews = races[0]["participant_previews"]
        assert len(previews) == 3

        # First: fastest finished player (placement 1)
        assert previews[0]["twitch_username"] == "player1_fast"
        assert previews[0]["placement"] == 1

        # Second: slower finished player (placement 2)
        assert previews[1]["twitch_username"] == "player2"
        assert previews[1]["placement"] == 2

        # Third: abandoned player (no placement)
        assert previews[2]["twitch_username"] == "player3"
        assert previews[2]["placement"] is None
```

### Step 2: Write test for setup race previews (no placement)

```python
@pytest.mark.asyncio
async def test_list_setup_races_no_placement(test_client, organizer, async_session):
    """Setup races have participant previews without placement (capped at 5)."""
    async with async_session() as db:
        seed = Seed(
            seed_number="s_setup",
            pool_name="standard",
            graph_json={},
            total_layers=10,
            folder_path="/test/setup",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Setup Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
        )
        db.add(race)
        await db.flush()

        for i in range(7):
            user = User(
                twitch_id=f"setup_p{i}",
                twitch_username=f"setup_player{i}",
                api_token=f"token_setup_{i}",
            )
            db.add(user)
            await db.flush()
            db.add(Participant(
                race_id=race.id,
                user_id=user.id,
                status=ParticipantStatus.REGISTERED,
                igt_ms=0,
                death_count=0,
            ))
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/races?status=setup")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) == 1

        previews = races[0]["participant_previews"]
        # Capped at 5 for non-finished races
        assert len(previews) == 5
        # No placement on setup races
        for p in previews:
            assert p["placement"] is None
```

### Step 3: Run the tests

Run: `cd server && uv run pytest tests/test_races.py::test_list_finished_races_includes_placement tests/test_races.py::test_list_setup_races_no_placement -v`
Expected: PASS

### Step 4: Run full test suite

Run: `cd server && uv run pytest -x -q`
Expected: All tests pass (existing tests should not break since `ParticipantPreview` extends `UserResponse`)

### Step 5: Commit

```bash
git add server/tests/test_races.py
git commit -m "test(server): add placement tests for race listing"
```

---

## Task 4: Frontend — Update types and add `ParticipantPreview`

**Files:**

- Modify: `web/src/lib/api.ts:11-16` (User type area) and `web/src/lib/api.ts:40` (Race interface)

### Step 1: Add `ParticipantPreview` interface

In `web/src/lib/api.ts`, add after the `User` interface (after line 16):

```typescript
export interface ParticipantPreview extends User {
  placement: number | null;
}
```

### Step 2: Update `Race.participant_previews` type

In the `Race` interface, change:

```typescript
participant_previews: User[];
```

to:

```typescript
participant_previews: ParticipantPreview[];
```

### Step 3: Run type checking

Run: `cd web && npm run check`
Expected: PASS (or only pre-existing errors unrelated to this change)

### Step 4: Commit

```bash
git add web/src/lib/api.ts
git commit -m "feat(web): add ParticipantPreview type with placement"
```

---

## Task 5: Frontend — Add winner row to `RaceCard`

**Files:**

- Modify: `web/src/lib/components/RaceCard.svelte`

### Step 1: Add winner derived state

In the `<script>` block of `RaceCard.svelte`, add after the existing derived values (around line 25):

```typescript
let winner = $derived(
  race.status === "finished" && race.participant_previews[0]?.placement === 1
    ? race.participant_previews[0]
    : null,
);
```

### Step 2: Add winner row in the template

After the closing `{/if}` of the caster row block (after line 120), add:

```svelte
{#if winner}
  <div class="winner-row">
    <svg class="trophy-icon" viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
      <path d="M12 2C9.24 2 7 4.24 7 7h-3c-1.1 0-2 .9-2 2v2c0 2.21 1.79 4 4 4h.68A7.01 7.01 0 0012 19.87V22H8v2h8v-2h-4v-2.13A7.01 7.01 0 0017.32 15H18c2.21 0 4-1.79 4-4V9c0-1.1-.9-2-2-2h-3c0-2.76-2.24-5-5-5zM4 11V9h3v4.83C5.17 13.1 4 11.65 4 11zm16 0c0 1.65-1.17 3.1-3 3.83V9h3v2z"/>
    </svg>
    {#if winner.twitch_avatar_url}
      <img src={winner.twitch_avatar_url} alt="" class="winner-avatar" />
    {/if}
    <span class="winner-name">{winner.twitch_display_name || winner.twitch_username}</span>
  </div>
{/if}
```

### Step 3: Add winner row styles

Add in the `<style>` block:

```css
/* Winner row */
.winner-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: var(--font-size-sm);
  color: var(--color-success);
  margin-bottom: 0.5rem;
}

.trophy-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.winner-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
}

.winner-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

### Step 4: Run checks

Run: `cd web && npm run check`
Expected: PASS

### Step 5: Commit

```bash
git add web/src/lib/components/RaceCard.svelte
git commit -m "feat(web): show winner on finished race cards"
```

---

## Task 6: Frontend — Add "Recent Results" section to homepage

**Files:**

- Modify: `web/src/routes/+page.svelte`

### Step 1: Update imports

Add `fetchRacesPaginated` to the import from `$lib/api`:

```typescript
import {
  fetchRaces,
  fetchRacesPaginated,
  getTwitchLoginUrl,
  type Race,
} from "$lib/api";
```

### Step 2: Add state for recent races

After the existing `loadingRaces` state (around line 13), add:

```typescript
let recentRaces: Race[] = $state([]);
let loadingRecent = $state(true);
```

### Step 3: Add fetch in `onMount`

Inside `onMount()`, after the existing `fetchRaces` call (after line 38), add:

```typescript
fetchRacesPaginated("finished", 0, 2)
  .then((data) => (recentRaces = data.races))
  .catch((e) => console.error("Failed to fetch recent races:", e))
  .finally(() => (loadingRecent = false));
```

### Step 4: Add "Recent Results" section in template

After the closing `{/if}` of the loading block (after line 147, before `</main>`), add:

```svelte
{#if loadingRecent}
  <p class="loading">Loading recent results...</p>
{:else if recentRaces.length > 0}
  <section class="public-races">
    <h2>Recent Results</h2>
    <div class="race-grid">
      {#each recentRaces as race}
        <RaceCard {race} />
      {/each}
    </div>
    <div class="see-all">
      <a href="/races" class="see-all-link">See all results &rarr;</a>
    </div>
  </section>
{/if}
```

### Step 5: Add styles for "see all" link

Add in the `<style>` block:

```css
.see-all {
  display: flex;
  justify-content: center;
  margin-top: 1rem;
}

.see-all-link {
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: var(--font-size-sm);
  transition: color 0.15s ease;
}

.see-all-link:hover {
  color: var(--color-purple);
}
```

### Step 6: Run checks

Run: `cd web && npm run check`
Expected: PASS

### Step 7: Commit

```bash
git add web/src/routes/+page.svelte
git commit -m "feat(web): add recent results section to homepage"
```

---

## Task 7: Final verification

### Step 1: Run full server test suite

Run: `cd server && uv run pytest -x -q`
Expected: All tests pass

### Step 2: Run full frontend checks

Run: `cd web && npm run check && npm run lint`
Expected: PASS

### Step 3: Run server linting

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`
Expected: PASS

### Step 4: Manual verification checklist

- [ ] `GET /api/races?status=finished` returns `participant_previews` with `placement` field
- [ ] Placement 1 = fastest `igt_ms` among finished participants
- [ ] Abandoned/non-finished participants have `placement: null`
- [ ] `GET /api/races?status=setup` returns previews capped at 5, all with `placement: null`
- [ ] Homepage shows "Recent Results" section with 2 cards below live/upcoming
- [ ] Finished race cards show trophy + winner name
- [ ] Clicking a finished race card navigates to race detail
