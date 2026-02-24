# Training Ghost Replay

**Date:** 2026-02-24
**Status:** Approved

## Concept

On a **finished** training session page (`/training/:id`), a "Map / Replay" toggle (identical to race pages) launches an animated replay. The player's run is replayed alongside **ghosts** — all other players who completed the same seed in training.

This brings the competitive dimension of race replays to solo training, like time-trial ghosts in racing games.

## Visual Design

| Element               | Style                                             |
| --------------------- | ------------------------------------------------- |
| Current player dot    | Colored (player color), full opacity, normal size |
| Ghost dots            | Gray (`#888`), ~50% opacity                       |
| Current player skulls | Full opacity (same as race replay)                |
| Ghost skulls          | Gray, ~30% opacity                                |
| Node heatmap          | Cumulative deaths from all players (same as race) |
| Leader tracking       | Disabled (not relevant)                           |
| Commentary            | Disabled (not relevant)                           |
| Ghost counter         | Small "X ghosts" label near replay controls       |

## Controls

Identical to race replay: play/pause, scrubable progress bar, speed selector (0.5x / 1x / 2x), fixed 60-second duration.

## API

### `GET /api/training/{session_id}/ghosts`

Returns zone history for all **finished** training sessions on the same seed as the given session, excluding the session itself.

**Response:**

```json
[
  {
    "zone_history": [
      { "node_id": "stormveil_main", "igt_ms": 120000, "deaths": 2 },
      ...
    ],
    "total_igt_ms": 600000,
    "death_count": 5
  },
  ...
]
```

Ghosts are anonymous — no user identity in the response.

## Frontend

### Data Flow

1. Page loads training session detail (existing REST call)
2. If session is `finished`, fetch ghosts from `/api/training/seeds/{seed_id}/ghosts`
3. Map current session + ghosts → `ReplayParticipant[]`
4. Feed into existing `ReplayDag` + `ReplayControls` components

### Component Reuse

- **`ReplayDag`**: Receives participants array. Needs conditioning for:
  - Color: player color for current player, gray for ghosts
  - Skull opacity: full for current player, reduced for ghosts
- **`ReplayControls`**: Used as-is, plus a "X ghosts" counter
- **`timeline.ts`**: All pure functions reused directly (buildReplayParticipants, igtToReplayMs, computePlayerPosition, collectSkullEvents, computeNodeHeat)

### Current Player Identification

The current player is identified by matching participant ID or a dedicated `isCurrentPlayer` flag set during the mapping step.

## Edge Cases

- **Solo (no ghosts)**: Replay works with just the current player's dot. Ghost counter shows "0 ghosts" or is hidden.
- **Active/abandoned sessions**: No replay button shown (only `finished`).
- **Many ghosts**: No cap for now. Monitor if visual clutter becomes an issue.

## Approach

Reuse the existing race replay engine (Approach A). The replay components already support N participants. Minimal new code:

- One new API endpoint (server)
- Ghost data fetching + mapping (frontend)
- Color/opacity conditioning in ReplayDag (frontend)
- Ghost counter in controls area (frontend)
