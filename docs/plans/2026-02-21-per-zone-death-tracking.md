# Per-Zone Death Tracking

## Summary

Track deaths per zone for each participant and display them in the MetroDAG node popup's "Visited By" section.

## Approach

**Server-side delta computation** — no mod changes required.

The server already receives `death_count` (cumulative total) every 1s via `status_update`. On each update, if `death_count` increased, the delta is attributed to the `zone_history` entry matching `participant.current_zone`.

## Data Model

Zone history entries gain an optional `deaths` field:

```
Before: { node_id: str, igt_ms: int }
After:  { node_id: str, igt_ms: int, deaths: int }
```

Backward-compatible: missing `deaths` field means 0. No DB migration needed (JSON column).

## Server Changes

### `websocket/mod.py` — `handle_status_update()`

After reading the new `death_count` from the message:

1. Compute `delta = new_death_count - participant.death_count`
2. If `delta > 0` and `participant.current_zone` exists:
   - Find the `zone_history` entry matching `current_zone`
   - Increment its `deaths` field by `delta`
   - Reassign `participant.zone_history` to trigger SQLAlchemy dirty detection
3. Update `participant.death_count` as before

### Broadcast

No changes needed. `zone_history` is already included in all WebSocket broadcasts (`leaderboard_update`, `player_update`, `race_state`) via `ParticipantInfo.zone_history`.

### Reset

Already handled: `zone_history = None` on race reset clears everything.

## Frontend Changes

### `websocket.ts`

Update `zone_history` type from `{ node_id: string; igt_ms: number }[]` to include optional `deaths`:

```typescript
zone_history: { node_id: string; igt_ms: number; deaths?: number }[] | null;
```

### `popupData.ts`

- Add `deaths?: number` to `PopupVisitor` interface
- In `computeVisitors()`, read `entry.deaths` from zone_history entry

### `NodePopup.svelte`

Display deaths before IGT in the "Visited by" section, only when > 0:

```
● Alice    ☠3  1:23 (0:45)
● Bob          2:10 (1:30)
```

Skull + count aligned, absent when deaths is 0 or undefined.

## Edge Cases

- **No zone_history yet**: Skip death attribution (player hasn't started)
- **current_zone not in zone_history**: Skip (shouldn't happen, but defensive)
- **Multiple deaths between status_updates**: Delta captures all of them correctly
- **Revisited zones**: `current_zone` is always up-to-date (updated on revisits and zone_query), so deaths are attributed to the correct geographic zone
