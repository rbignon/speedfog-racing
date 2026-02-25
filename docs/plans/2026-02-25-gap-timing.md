# Gap Timing (F1-Style)

## Problem

The leaderboard shows `X/Y` progression for each player, but during a race several players are often on the same layer. There's no way to see how far behind the leader you actually are in time.

## Design

### Overview

Show the time gap to the leader next to each player's progression in the leaderboard overlay. The gap is computed server-side and sent as a new `gap_ms` field in `ParticipantInfo`.

### Gap Calculation (Server)

Computed in `participant_to_info()` or `broadcast_leaderboard()`:

1. Identify the **leader** (first sorted participant with status playing or finished)
2. Build **leader split times per layer** from `zone_history`: for each entry, resolve the layer via `get_layer_for_node()`, keep the **first IGT** recorded for each layer
3. For each participant:
   - **Playing**: `gap_ms = participant.igt_ms - leader_splits[participant.current_layer]`
   - **Finished (non-leader)**: `gap_ms = participant.igt_ms - leader.igt_ms`
   - **Leader / Ready / Registered**: `gap_ms = null`

### Protocol

New optional field in `ParticipantInfo`:

```python
# server — websocket/schemas.py
gap_ms: int | None = None
```

```rust
// mod — core/protocol.rs
#[serde(default)]
pub gap_ms: Option<i32>,
```

No new WebSocket message type. Backward compatible (field defaults to null/None).

### Overlay (Mod)

In `render_participant_row()`, the right side of each row changes based on status:

- **Playing (with gap)**: `+M:SS    X/Y`
- **Playing (no gap / leader)**: `X/Y` (unchanged)
- **Finished (leader)**: `H:MM:SS` (unchanged)
- **Finished (non-leader)**: `+M:SS  H:MM:SS`
- **Ready**: `X/Y` (unchanged)

Gap format: `+M:SS` for < 1h, `+H:MM:SS` for >= 1h.

#### Column Alignment

The gap and progress/time columns must be **vertically aligned** across all leaderboard rows. This means:

1. **Pre-compute max widths** for each column before rendering any row:
   - Gap column: measure the widest gap string across all visible participants
   - Right column: measure the widest progress/time string
2. **Right-align both columns** using the pre-computed widths
3. Gap column sits to the left of the right column, separated by a fixed gap

Layout with alignment:

```
 1. Rakushain_              32/32
 2. wospins        +2:15    25/32
 3. Armigraph      +5:30    19/32
14. SomeGuy       +12:05    14/32
```

The gap text is right-aligned within its column so the `+` signs and colons line up.

### Edge Cases

- **No playing/finished leader**: `gap_ms = null` for everyone
- **Player at layer 0**: `gap_ms = 0` if leader also started, else `null`
- **Leader changes**: gaps recalculated on next `broadcast_leaderboard` (automatic)
- **Leader has no split for player's layer**: should not happen (leader is ahead), fallback to `gap_ms = null`

### Scope

- **Server**: `websocket/schemas.py` (add field), `websocket/manager.py` (compute gap in `participant_to_info` or `broadcast_leaderboard`)
- **Mod**: `core/protocol.rs` (add field), `dll/ui.rs` (update `render_participant_row` with gap display + column alignment)
- **Tests**: server-side tests for gap calculation logic
