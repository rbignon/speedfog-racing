# Backtrack Fog Gate Detection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable detection of fog gate re-traversals during backtracking, and improve zone_query fallback for death/remembrance.

**Architecture:** Two independent fixes — (1) mod clears event flags after capture so they can be re-detected on backtrack, (2) server picks the most recently visited node when zone_query is ambiguous and no grace_entity_id is provided (death/remembrance context).

**Tech Stack:** Rust (mod/tracker.rs), Python (server/grace_service.py), pytest

---

## Task 1: Server — Add "most recent" fallback to resolve_zone_query

**Files:**

- Modify: `server/speedfog_racing/services/grace_service.py:70-127`
- Test: `server/tests/test_grace_service.py`

Step 1: Update existing test expectations

The test `test_resolve_zone_query_ambiguous_both_explored` (line 169) currently asserts `None` when both candidates are explored and no `grace_entity_id` is provided. With the new fallback, it should return the most recently visited node.

In `server/tests/test_grace_service.py`, update:

```python
def test_resolve_zone_query_ambiguous_both_explored():
    """Ambiguous map_id with both candidates explored: picks most recently visited (death/remembrance heuristic)."""
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    history = [
        {"node_id": "node_a", "igt_ms": 0},
        {"node_id": "node_b", "igt_ms": 5000},
    ]
    node_id = resolve_zone_query(graph, mapping, map_id="m10_00_00_00", zone_history=history)
    assert node_id == "node_b"
```

Step 2: Add test for fast travel with failed grace lookup

```python
def test_resolve_zone_query_fast_travel_failed_grace_no_fallback():
    """Fast travel with unmapped grace_entity_id: do NOT fall back to most recent.

    grace_entity_id being present signals fast travel — guessing would pollute the DAG.
    """
    graph = {
        "nodes": {
            "node_a": {"zones": ["stormveil_godrick"], "layer": 1},
            "node_b": {"zones": ["stormhill"], "layer": 0},
        }
    }
    mapping = load_graces_mapping()
    history = [
        {"node_id": "node_a", "igt_ms": 0},
        {"node_id": "node_b", "igt_ms": 5000},
    ]
    # grace_entity_id=99999999 won't resolve, but its presence means fast travel
    node_id = resolve_zone_query(
        graph,
        mapping,
        grace_entity_id=99999999,
        map_id="m10_00_00_00",
        zone_history=history,
    )
    assert node_id is None
```

Step 3: Add test for death/remembrance most-recent fallback

```python
def test_resolve_zone_query_death_most_recent_fallback():
    """Death/remembrance (no grace_entity_id): picks most recent visited node among candidates."""
    graph = {
        "nodes": {
            "leyndell_1259": {"zones": ["leyndell"], "layer": 5},
            "leyndell_sanctuary_d3e5": {"zones": ["leyndell_sanctuary"], "layer": 8},
        }
    }
    mapping = load_graces_mapping()
    history = [
        {"node_id": "leyndell_1259", "igt_ms": 120000},
        {"node_id": "leyndell_sanctuary_d3e5", "igt_ms": 300000},
        {"node_id": "leyndell_1259", "igt_ms": 400000},  # backtracked
    ]
    # No grace → death context. Most recent matching = leyndell_1259
    node_id = resolve_zone_query(
        graph,
        mapping,
        map_id="m11_00_00_00",
        zone_history=history,
    )
    assert node_id == "leyndell_1259"
```

Step 4: Run tests to verify failures

Run: `cd server && uv run pytest tests/test_grace_service.py -v`
Expected: 2 new tests FAIL (function not updated yet), 1 existing test FAIL (changed assertion)

Step 5: Implement the fallback in resolve_zone_query

In `server/speedfog_racing/services/grace_service.py`, modify `resolve_zone_query`:

```python
def resolve_zone_query(
    graph_json: dict[str, Any],
    graces_mapping: dict[str, dict[str, Any]],
    *,
    grace_entity_id: int | None = None,
    map_id: str | None = None,
    position: tuple[float, float, float] | None = None,
    play_region_id: int | None = None,
    zone_history: list[dict[str, Any]] | None = None,
) -> str | None:
    """Resolve a zone query to a graph node_id.

    Strategies (in order):
    1. Grace lookup (grace_entity_id → zone_id → node)
    2. Map-based lookup (map_id → fog.txt zone mapping → filter graph nodes)
       a. Get candidate zone_ids from fog.txt (complete map→zone mapping)
       b. If position available, use submaps.txt to narrow to one zone_id
       c. Find graph nodes whose zones intersect candidates
       d. If still ambiguous, narrow by zone_history (visited nodes only)
       e. If still ambiguous and no grace (death/remembrance), pick most recently visited
    3. None (ambiguous or no data)
    """
    # Strategy 1: grace lookup (highest confidence)
    if grace_entity_id is not None and grace_entity_id != 0:
        node_id = resolve_grace_to_node(grace_entity_id, graph_json, graces_mapping)
        if node_id is not None:
            return node_id

    # Strategy 2: map_id → fog.txt zone lookup + position disambiguation
    if map_id is not None:
        zone_ids_for_map = get_zones_for_map(map_id)

        # Use position to narrow candidates when available
        if position is not None and zone_ids_for_map:
            resolved = resolve_zone_by_position(map_id, *position)
            if resolved and resolved in zone_ids_for_map:
                zone_ids_for_map = {resolved}

        # Find graph nodes whose zones intersect candidates
        nodes = graph_json.get("nodes", {})
        matching: list[str] = []
        for nid, node_data in nodes.items():
            if isinstance(node_data, dict):
                zones = node_data.get("zones", [])
                if any(z in zone_ids_for_map for z in zones):
                    matching.append(nid)

        # Filter by history: player can only be in an explored zone
        if matching and zone_history:
            explored = {e["node_id"] for e in zone_history if "node_id" in e}
            matching = [nid for nid in matching if nid in explored]

        if len(matching) == 1:
            return matching[0]

        # Death/remembrance fallback: pick most recently visited among candidates.
        # Only when grace_entity_id is absent — fast travel with failed grace lookup
        # should NOT guess (wrong entries pollute the MetroDag).
        if (
            len(matching) > 1
            and zone_history
            and (grace_entity_id is None or grace_entity_id == 0)
        ):
            matching_set = set(matching)
            for entry in reversed(zone_history):
                nid = entry.get("node_id")
                if nid in matching_set:
                    return nid

    return None
```

Step 6: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_grace_service.py -v`
Expected: ALL PASS

Step 7: Commit

```
fix: resolve ambiguous zone_query by picking most recently visited node

Death/remembrance always returns to last grace, so picking the most
recently visited candidate is the correct heuristic. Fast travel with
failed grace lookup still returns None to avoid polluting the DAG.
```

---

## Task 2: Mod — Clear event flags after capture

**Files:**

- Modify: `mod/src/dll/tracker.rs:440-476` (10Hz poll loop)
- Modify: `mod/src/dll/tracker.rs:350-383` (loading-exit immediate scan)
- Modify: `mod/src/dll/tracker.rs:505-516` (reconnect rescan)

Step 1: Update the 10Hz poll loop (line ~440)

In the regular fog gate branch (non-finish), after pushing to `deferred_event_flags`, clear the flag in game memory and do NOT insert into `triggered_flags`:

```rust
// Lines 440-476 — replace the full polling block
// Event flag polling runs ALWAYS (even when disconnected).
// Flags are transient in game memory (~seconds), so we must detect them immediately.
// Regular flags are deferred until loading exit; finish_event is sent immediately.
if !self.event_ids.is_empty() && self.last_flag_poll.elapsed() >= Duration::from_millis(100)
{
    self.last_flag_poll = Instant::now();
    let igt_ms = self.game_state.read_igt().unwrap_or(0);
    for &flag_id in &self.event_ids {
        if self.finish_event == Some(flag_id) {
            // finish_event: one-shot — use triggered_flags guard
            if !self.triggered_flags.contains(&flag_id) {
                if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                    self.triggered_flags.insert(flag_id);
                    if self.ws_client.is_connected()
                        && self.is_race_running()
                        && !self.am_i_finished()
                        && !self.is_countdown_active()
                    {
                        self.ws_client.send_event_flag(flag_id, igt_ms);
                        self.last_sent_debug = Some(format!(
                            "event_flag({}, igt={}ms) [finish]",
                            flag_id, igt_ms
                        ));
                        info!(flag_id, "[RACE] Finish event sent immediately");
                    } else if !self.am_i_finished() {
                        self.pending_event_flags.push((flag_id, igt_ms));
                    }
                }
            }
        } else {
            // Regular fog gate — clear after capture so re-traversals are detected
            if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                self.event_flag_reader.set_flag(flag_id, false);
                self.deferred_event_flags.push((flag_id, igt_ms));
                info!(flag_id, "[RACE] Event flag deferred until loading exit");
            }
        }
    }
}
```

Step 2: Update the loading-exit immediate scan (line ~350)

Same logic: finish_event stays one-shot with `triggered_flags`, regular flags are cleared after capture:

```rust
// Lines 355-383 — replace the flag scan block inside
// "if !self.event_ids.is_empty()"
let igt_ms = self.game_state.read_igt().unwrap_or(0);
for &flag_id in &self.event_ids {
    if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
        if self.finish_event == Some(flag_id) {
            if !self.triggered_flags.contains(&flag_id) {
                self.triggered_flags.insert(flag_id);
                if self.ws_client.is_connected()
                    && self.is_race_running()
                    && !self.am_i_finished()
                    && !self.is_countdown_active()
                {
                    self.ws_client.send_event_flag(flag_id, igt_ms);
                    self.last_sent_debug = Some(format!(
                        "event_flag({}, igt={}ms) [finish/loading-exit]",
                        flag_id, igt_ms
                    ));
                    info!(flag_id, "[RACE] Finish event caught at loading exit");
                } else if !self.am_i_finished() {
                    self.pending_event_flags.push((flag_id, igt_ms));
                }
            }
        } else {
            self.event_flag_reader.set_flag(flag_id, false);
            self.deferred_event_flags.push((flag_id, igt_ms));
            info!(flag_id, "[RACE] Event flag caught at loading exit");
        }
    }
}
```

Step 3: Update the reconnect rescan (line ~505)

For reconnect, scan all non-finish flags that are currently set (they were set during the disconnect window). Clear after capture:

```rust
// Lines 505-516 — replace the rescan block
// Safety-net rescan: catch any flags still set in memory that polling missed
for &flag_id in &self.event_ids {
    if self.finish_event == Some(flag_id) {
        if !self.triggered_flags.contains(&flag_id) {
            if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                self.triggered_flags.insert(flag_id);
                self.ws_client.send_event_flag(flag_id, igt_ms);
                self.last_sent_debug =
                    Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                info!(flag_id, "[RACE] Finish event re-sent after reconnect");
            }
        }
    } else if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
        self.event_flag_reader.set_flag(flag_id, false);
        self.ws_client.send_event_flag(flag_id, igt_ms);
        self.last_sent_debug =
            Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
        info!(flag_id, "[RACE] Event flag re-sent after reconnect");
    }
}
```

Step 4: Update the auth_ok comment (line ~626)

The comment about `triggered_flags` should be updated to reflect the new behavior:

```rust
// Don't clear triggered_flags on reconnect: finish_event is one-shot.
// Regular fog gate flags are no longer tracked in triggered_flags —
// they're cleared in game memory after capture for re-traversal detection.
```

Step 5: Verify compilation

Run: `cd mod && cargo check --lib`
Expected: Compiles without errors (or warnings only from Windows-specific code)

Step 6: Commit

```
fix: clear event flags after capture to enable backtrack fog detection

EMEVD event flags are one-shot booleans — once set, they stay set.
Previously, triggered_flags prevented re-detection, so backtracking
through fog gates fell through to zone_query (which often failed).

Now the mod clears each flag in game memory after capturing it,
allowing the EMEVD script to re-set it on the next fog traversal.
finish_event remains one-shot (player can only finish once).
```

---

## Task 3: Verify and update documentation

**Files:**

- Modify: `docs/EVENT_FLAG_TRACKING.md` (if backtrack behavior is documented)
- Modify: `docs/plans/2026-03-08-backtrack-fog-detection.md` (mark complete)

Step 1: Check if EVENT_FLAG_TRACKING.md mentions triggered_flags or backtrack behavior

Read `docs/EVENT_FLAG_TRACKING.md` and update any references to the old "fire once" behavior.

Step 2: Commit

```
docs: update event flag tracking for backtrack re-detection
```
