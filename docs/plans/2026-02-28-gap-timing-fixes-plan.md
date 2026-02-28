# Gap Timing Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two gap timing bugs: arbitrary leader selection on same layer, and gap drifting after finish/race end.

**Architecture:** Bug 1 is server-side only (sort key change in `sort_leaderboard`). Bug 2 is mod-side only (gap freeze logic in `render_leaderboard`). No protocol changes needed.

**Tech Stack:** Python (server), Rust (mod)

---

## Task 1: Fix leader sort to use layer entry IGT

**Files:**

- Modify: `server/speedfog_racing/websocket/manager.py:422-451` (`sort_leaderboard`)
- Modify: `server/speedfog_racing/websocket/manager.py:208` (call site)
- Test: `server/tests/test_websocket.py`

### Step 1: Write the failing test

Add to `TestSortLeaderboard` in `server/tests/test_websocket.py`:

```python
def test_sort_playing_same_layer_by_entry_igt(self):
    """On same layer, player who entered first should be ranked higher."""
    graph = {
        "nodes": {
            "start": {"layer": 0, "tier": 1},
            "zone_a": {"layer": 1, "tier": 2},
            "zone_b": {"layer": 2, "tier": 3},
        }
    }
    # Player A entered layer 2 first (at IGT 100s) but has higher total IGT now
    p1 = MockParticipant(
        status=ParticipantStatus.PLAYING,
        current_layer=2,
        igt_ms=120000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 30000},
            {"node_id": "zone_b", "igt_ms": 100000},
        ],
    )
    # Player B entered layer 2 later (at IGT 110s) but has lower total IGT
    p2 = MockParticipant(
        status=ParticipantStatus.PLAYING,
        current_layer=2,
        igt_ms=115000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0},
            {"node_id": "zone_a", "igt_ms": 40000},
            {"node_id": "zone_b", "igt_ms": 110000},
        ],
    )

    sorted_list = sort_leaderboard([p2, p1], graph_json=graph)

    # Player A should be first (entered layer 2 at 100000 < 110000)
    assert sorted_list[0].igt_ms == 120000  # p1
    assert sorted_list[1].igt_ms == 115000  # p2
```

### Step 2: Run test to verify it fails

Run: `cd server && uv run pytest tests/test_websocket.py::TestSortLeaderboard::test_sort_playing_same_layer_by_entry_igt -v`

Expected: FAIL — `sort_leaderboard` does not accept `graph_json` yet.

### Step 3: Implement the fix

In `server/speedfog_racing/websocket/manager.py`, change `sort_leaderboard` signature and sort key:

```python
def sort_leaderboard(
    participants: list[Participant],
    *,
    graph_json: dict[str, Any] | None = None,
) -> list[Participant]:
    """Sort participants for leaderboard display.

    Priority:
    1. Finished players first, sorted by IGT (lowest first)
    2. Playing players by layer (highest first), then layer entry IGT (lowest first)
    3. Ready players
    4. Registered players
    5. Abandoned (DNF) players last, sorted by layer (highest first), then IGT (lowest first)
    """
    status_priority = {
        "finished": 0,
        "playing": 1,
        "ready": 2,
        "registered": 3,
        "abandoned": 4,
    }

    # Pre-compute layer entry IGTs for playing participants
    entry_igts: dict[Any, int] = {}
    if graph_json:
        for p in participants:
            if p.status.value == "playing":
                entry = get_layer_entry_igt(p.zone_history, p.current_layer, graph_json)
                entry_igts[p.id] = entry if entry is not None else p.igt_ms

    def sort_key(p: Participant) -> tuple[int, int, int]:
        status = p.status.value
        priority = status_priority.get(status, 99)

        if status == "finished":
            return (priority, p.igt_ms, 0)
        elif status == "playing":
            entry_igt = entry_igts.get(p.id, p.igt_ms)
            return (priority, -p.current_layer, entry_igt)
        elif status == "abandoned":
            return (priority, -p.current_layer, p.igt_ms)
        else:
            return (priority, 0, 0)

    return sorted(participants, key=sort_key)
```

Then update the call site at line 208:

```python
sorted_participants = sort_leaderboard(participants, graph_json=graph_json)
```

### Step 4: Verify existing tests still pass

The existing `sort_leaderboard` tests don't pass `graph_json`, which is fine since it defaults to `None` and falls back to `p.igt_ms`. Verify no tests break.

Run: `cd server && uv run pytest tests/test_websocket.py::TestSortLeaderboard -v`

Expected: All existing tests PASS (fallback to `igt_ms` when no `graph_json`).

### Step 5: Run the new test

Run: `cd server && uv run pytest tests/test_websocket.py::TestSortLeaderboard::test_sort_playing_same_layer_by_entry_igt -v`

Expected: PASS

### Step 6: Run full test suite

Run: `cd server && uv run pytest -x -v`

Expected: All tests PASS.

### Step 7: Commit

```bash
git add server/speedfog_racing/websocket/manager.py server/tests/test_websocket.py
git commit -m "fix(ws): sort same-layer players by layer entry IGT instead of total IGT"
```

---

## Task 2: Freeze gaps in mod after finish or race end

**Files:**

- Modify: `mod/src/dll/ui.rs:464-489` (gap pre-computation in `render_leaderboard`)

### Step 1: Implement the fix

In `mod/src/dll/ui.rs`, replace the gap pre-computation block (lines 464-489) with logic that uses `p.gap_ms` from server when the player is finished or the race is over:

```rust
        // Pre-compute gaps for all participants
        let race_finished = self
            .race_info()
            .is_some_and(|r| r.status.as_str() == "finished");

        let gaps: Vec<Option<i32>> = participants
            .iter()
            .enumerate()
            .map(|(i, p)| {
                if !has_leader {
                    return None;
                }
                // Finished players or race ended: use server-computed gap (frozen)
                if p.status == "finished" || race_finished {
                    return p.gap_ms;
                }
                // Playing, race running: recompute client-side for real-time updates
                let igt = if my_id.is_some_and(|id| id == &p.id) {
                    local_igt.unwrap_or(p.igt_ms)
                } else {
                    interpolate_igt(p)
                };
                crate::core::compute_gap(
                    igt,
                    p.current_layer,
                    p.layer_entry_igt,
                    leader_splits,
                    i == 0,
                    &p.status,
                    leader_igt_ms,
                )
            })
            .collect();
```

### Step 2: Run Rust checks

Run: `cd mod && cargo check --lib`

Expected: Compiles without errors. (Cannot run full build on Linux — DLL requires MSVC on Windows.)

### Step 3: Run Rust tests

Run: `cd mod && cargo test`

Expected: All existing tests PASS. The `compute_gap` unit tests in `format.rs` are unchanged.

### Step 4: Commit

```bash
git add mod/src/dll/ui.rs
git commit -m "fix(mod): freeze gap display when player finishes or race ends"
```

---

## Task 3: Update docs

**Files:**

- Modify: `docs/EVENT_FLAG_TRACKING.md` (gap timing section)

### Step 1: Update gap timing documentation

In `docs/EVENT_FLAG_TRACKING.md`, find the gap timing section and add a note about the freeze behavior:

> When a player finishes or the race ends, the mod uses the server-computed `gap_ms` (frozen at the time of the last leaderboard update) instead of recomputing client-side. This prevents gap drift from game memory IGT continuing to tick after finish.

Also document the leader sort change:

> Players on the same layer are sorted by layer entry IGT (who arrived first), not total IGT. This ensures the true leader on a layer is the one who reached it first.

### Step 2: Commit

```bash
git add docs/EVENT_FLAG_TRACKING.md
git commit -m "docs: update gap timing docs for freeze behavior and leader sort"
```
