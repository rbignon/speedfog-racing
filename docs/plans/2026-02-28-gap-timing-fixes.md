# Gap Timing Fixes

Two bugs in the gap timing system.

## Bug 1: Arbitrary leader selection on same layer

### Problem

`sort_leaderboard()` sorts "playing" participants by `(-current_layer, igt_ms)`.
When two players are on the same layer, the one with lowest **total IGT** is first —
not the one who **arrived first** on that layer.

Example: Player A enters layer 3 at IGT 100s (now at 120s). Player B enters layer 3
at IGT 110s (now at 115s). B has lower total IGT → B is "leader" → A shows a negative
gap despite being objectively behind.

### Fix

Change sort key for "playing" from `(-current_layer, igt_ms)` to
`(-current_layer, layer_entry_igt)`. Pass `graph_json` to `sort_leaderboard()` so it
can compute `layer_entry_igt` via `get_layer_entry_igt()`.

Fallback: if `layer_entry_igt` is `None` (no zone_history yet), fall back to `igt_ms`.

## Bug 2: Gap keeps drifting after finish/abandon/race end

### Problem

The mod recomputes gaps client-side at every frame (ignores `p.gap_ms` from server).
Two sources of drift:

1. **Self finished**: `local_igt = self.read_igt()` keeps ticking from game memory →
   `compute_gap("finished", local_igt, ..., leader_igt_ms)` = growing value.
2. **Race finished**: `elapsed_ms` keeps growing → `interpolate_igt` inflates IGTs
   of cached "playing" participants → their gaps drift.

### Fix

In `render_leaderboard()` gap pre-computation:

- If `p.status == "finished"` → use `p.gap_ms` from server (frozen at finish time).
- If race status == "finished" → use `p.gap_ms` from server for all participants
  (last leaderboard_update values, frozen).
- Otherwise (playing, race running) → recompute client-side as before
  (local_igt for self, interpolate_igt for others).

This leverages the existing `gap_ms` field in `ParticipantInfo` that the server
already computes correctly but the mod currently ignores.
