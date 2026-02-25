# Race Abandon — Design

Allow a participant to voluntarily abandon a running race, and auto-abandon inactive players whose IGT has not changed for 5 minutes.

## Data Model

Add one column to `Participant`:

```python
last_igt_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Updated in `handle_status_update` and `handle_event_flag` **only when `igt_ms` actually changes** compared to the stored value. Stays `None` until the participant starts playing.

`ParticipantStatus.ABANDONED` already exists — no enum change needed.

## API Endpoint

```
POST /api/races/{race_id}/abandon
Auth: Bearer (current user)
```

**Preconditions:**

- Race status is `RUNNING`
- Current user has a participant entry in this race
- Participant status is `PLAYING`

**Actions:**

1. Set `participant.status = ParticipantStatus.ABANDONED`
2. Commit
3. Broadcast `leaderboard_update` + `player_update` via WebSocket
4. Check if all participants are now FINISHED or ABANDONED → auto-finish the race (same optimistic locking pattern as `mod.py` finish handler)

**Response:** `RaceResponse`

**Errors:**

- 404 if race not found or user not a participant
- 400 if race not RUNNING or participant not PLAYING

## Inactivity Monitor

Background `asyncio.Task` launched in FastAPI lifespan, cancelled on shutdown.

**Loop (every 60 seconds):**

1. Query all participants where:
   - `status = PLAYING`
   - `race.status = RUNNING`
   - `last_igt_change_at IS NOT NULL`
   - `last_igt_change_at < now() - 5 minutes`
2. For each match: set `status = ABANDONED`, commit
3. Broadcast WebSocket updates per affected race
4. Check auto-finish per affected race

**Edge cases:**

- `last_igt_change_at IS NULL` → participant hasn't sent any status_update yet → don't auto-abandon (they may be loading the game)
- Race finishes between query and update → optimistic lock handles it

## WebSocket Changes (mod.py)

In `handle_status_update`:

```python
if isinstance(msg.get("igt_ms"), int):
    if msg["igt_ms"] != participant.igt_ms:
        participant.last_igt_change_at = datetime.now(UTC)
    participant.igt_ms = msg["igt_ms"]
```

In `handle_event_flag`: also set `last_igt_change_at = now()` since an event flag implies active play.

Reject messages from ABANDONED participants (same as FINISHED — silently drop).

## Frontend

### Race detail page — running state, sidebar

When the current user is a participant with status PLAYING, show an "Abandon" button below the leaderboard:

- Click → inline confirmation ("Are you sure? This is irreversible." + Confirm / Cancel)
- Confirm → `POST /api/races/{id}/abandon`
- After success: button disappears, leaderboard shows participant as abandoned
- Same UX pattern as training session abandon

### API client (`api.ts`)

```typescript
export async function abandonRace(raceId: string): Promise<RaceResponse> {
  const response = await fetch(`${API_BASE}/races/${raceId}/abandon`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!response.ok) throw new ApiError(response);
  return response.json();
}
```

## Auto-Finish Logic

Extracted into a shared helper (used by abandon endpoint, inactivity monitor, and existing finish handler in `mod.py`):

```python
async def check_race_auto_finish(db: AsyncSession, race: Race) -> bool:
    """If all participants are FINISHED or ABANDONED, transition race to FINISHED."""
```

This avoids duplicating the optimistic locking logic in three places.

## Impact on Existing Features

- **Leaderboard / DAG / Highlights:** Already handle `abandoned` status — no changes needed
- **Overlay (mod):** Already shows abandoned participants correctly
- **Force-finish:** Still works as before (marks remaining PLAYING as ABANDONED)
- **Mod WS handler:** ABANDONED participants' messages are silently dropped (new guard, same as FINISHED)
