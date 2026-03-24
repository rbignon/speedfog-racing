# Conditional Death Markers (Racing Side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggregate deaths per zone across all race participants and broadcast to mods so they can set EMEVD event flags that control in-game bloodstain visibility.

**Architecture:** Event-driven aggregation in `handle_status_update()`. On death attribution (delta > 0), aggregate deaths by node_id across all participants and broadcast a `death_counts` message to all mods. The mod applies thresholds (1/3/5) and sets event flags via the existing `EventFlagReader.set_flag()`. No new DB columns, no timers.

**Tech Stack:** Python/FastAPI (server), Rust (mod), WebSocket protocol, Pydantic v2, serde

**Spec:** `docs/plans/2026-03-24-conditional-death-markers-racing.md`

---

## Tasks

### Task 1: Server schemas (DeathCountsMessage + SeedInfo.death_flags)

**Files:**

- Modify: `server/speedfog_racing/websocket/schemas.py`
- Test: `server/tests/test_websocket.py`

- [ ] **Step 1: Write tests for new schema types**

In `server/tests/test_websocket.py`, add to `TestSchemas`:

```python
def test_death_counts_message(self):
    """Test DeathCountsMessage serialization."""
    msg = DeathCountsMessage(counts={"node_a": 4, "node_b": 1})
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "death_counts"
    assert data["counts"] == {"node_a": 4, "node_b": 1}

def test_death_counts_message_empty(self):
    """Test DeathCountsMessage with empty counts."""
    msg = DeathCountsMessage(counts={})
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "death_counts"
    assert data["counts"] == {}

def test_seed_info_death_flags(self):
    """Test SeedInfo includes death_flags."""
    info = SeedInfo(
        total_layers=5,
        death_flags={"node_a": [1040292500, 1040292501, 1040292502]},
    )
    data = json.loads(info.model_dump_json())
    assert data["death_flags"] == {"node_a": [1040292500, 1040292501, 1040292502]}

def test_seed_info_death_flags_default_empty(self):
    """Test SeedInfo death_flags defaults to empty dict."""
    info = SeedInfo(total_layers=5)
    assert info.death_flags == {}
```

Add `DeathCountsMessage` to the import block at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_websocket.py::TestSchemas::test_death_counts_message tests/test_websocket.py::TestSchemas::test_seed_info_death_flags -v`
Expected: ImportError or AttributeError (DeathCountsMessage doesn't exist yet)

- [ ] **Step 3: Implement schema changes**

In `server/speedfog_racing/websocket/schemas.py`, add `DeathCountsMessage` after `ErrorMessage`:

```python
class DeathCountsMessage(BaseModel):
    """Aggregated death counts per zone, broadcast to mods."""

    type: Literal["death_counts"] = "death_counts"
    counts: dict[str, int]  # node_id -> total deaths across all participants
```

Add `death_flags` field to `SeedInfo`, after `spawn_items`:

```python
    death_flags: dict[str, list[int]] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_websocket.py::TestSchemas -v`
Expected: All pass including the 4 new tests

- [ ] **Step 5: Run full server test suite**

Run: `cd server && uv run pytest -x -q`
Expected: All pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/schemas.py server/tests/test_websocket.py
git commit -m "feat: add DeathCountsMessage and SeedInfo.death_flags schemas"
```

---

### Task 2: Server aggregation utility + death_flags in auth_ok

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py`
- Test: `server/tests/test_websocket.py`

- [ ] **Step 1: Write unit test for aggregate_death_counts**

In `server/tests/test_websocket.py`, add a new test class after `TestSchemas`:

```python
class TestAggregateDeathCounts:
    """Test aggregate_death_counts utility."""

    def test_single_participant_single_zone(self):
        p = MockParticipant(
            zone_history=[{"node_id": "node_a", "igt_ms": 10000, "deaths": 3}]
        )
        counts = aggregate_death_counts([p])
        assert counts == {"node_a": 3}

    def test_multiple_participants_same_zone(self):
        p1 = MockParticipant(
            zone_history=[{"node_id": "node_a", "igt_ms": 10000, "deaths": 2}]
        )
        p2 = MockParticipant(
            zone_history=[{"node_id": "node_a", "igt_ms": 15000, "deaths": 1}]
        )
        counts = aggregate_death_counts([p1, p2])
        assert counts == {"node_a": 3}

    def test_multiple_zones(self):
        p = MockParticipant(
            zone_history=[
                {"node_id": "node_a", "igt_ms": 10000, "deaths": 2},
                {"node_id": "node_b", "igt_ms": 20000, "deaths": 5},
            ]
        )
        counts = aggregate_death_counts([p])
        assert counts == {"node_a": 2, "node_b": 5}

    def test_no_deaths(self):
        p = MockParticipant(
            zone_history=[{"node_id": "node_a", "igt_ms": 10000}]
        )
        counts = aggregate_death_counts([p])
        assert counts == {}

    def test_empty_history(self):
        p = MockParticipant(zone_history=None)
        counts = aggregate_death_counts([p])
        assert counts == {}

    def test_backtrack_aggregates_all_visits(self):
        """Deaths across multiple visits of the same node are summed."""
        p = MockParticipant(
            zone_history=[
                {"node_id": "node_a", "igt_ms": 10000, "deaths": 2},
                {"node_id": "node_b", "igt_ms": 20000, "deaths": 1},
                {"node_id": "node_a", "igt_ms": 30000, "type": "backtrack", "deaths": 3},
            ]
        )
        counts = aggregate_death_counts([p])
        assert counts == {"node_a": 5, "node_b": 1}
```

Add `aggregate_death_counts` to the imports from `speedfog_racing.websocket.mod`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_websocket.py::TestAggregateDeathCounts -v`
Expected: ImportError (aggregate_death_counts doesn't exist)

- [ ] **Step 3: Implement aggregate_death_counts**

In `server/speedfog_racing/websocket/mod.py`, add the function before `handle_mod_websocket`:

```python
def aggregate_death_counts(participants: list[Participant]) -> dict[str, int]:
    """Aggregate deaths per node_id across all participants' zone_history."""
    counts: dict[str, int] = {}
    for p in participants:
        for entry in p.zone_history or []:
            deaths = entry.get("deaths", 0)
            if deaths > 0:
                node_id = entry.get("node_id")
                if node_id:
                    counts[node_id] = counts.get(node_id, 0) + deaths
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_websocket.py::TestAggregateDeathCounts -v`
Expected: All 6 tests pass

- [ ] **Step 5: Add death_flags to send_auth_ok**

In `server/speedfog_racing/websocket/mod.py`, in `send_auth_ok()`, extract `death_flags` from `graph_json` and pass to `SeedInfo`. After the `spawn_items` extraction line, add:

```python
    death_flags = seed.graph_json.get("death_flags", {}) if seed and seed.graph_json else {}
```

Then add `death_flags=death_flags` to the `SeedInfo(...)` constructor call.

Also add `DeathCountsMessage` to the import from `speedfog_racing.websocket.schemas`.

- [ ] **Step 6: Run full test suite**

Run: `cd server && uv run pytest -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/websocket/mod.py server/tests/test_websocket.py
git commit -m "feat: add aggregate_death_counts utility and death_flags in auth_ok"
```

---

### Task 3: Server broadcast on death + reconnect unicast

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py`
- Test: `server/tests/test_integration.py`

- [ ] **Step 1: Add broadcast in handle_status_update**

In `server/speedfog_racing/websocket/mod.py`, in `handle_status_update()`, after the session closes (after line 408 `await db.commit()`), add the death_counts broadcast. This goes after the session block closes and before the `became_playing` if/else, independent of that branch:

```python
    # Broadcast death counts to all mods when deaths are attributed
    if delta > 0:
        counts = aggregate_death_counts(participant.race.participants)
        room = manager.get_room(participant.race_id)
        if room:
            await room.broadcast_to_mods(
                DeathCountsMessage(counts=counts).model_dump_json()
            )
```

Note: `delta` is currently only defined inside `if isinstance(new_death_count, int):` and would be undefined if that branch is not taken. Add `delta = 0` at the top of `handle_status_update`, right after the function signature and before `async with session_maker() as db:`. The existing `delta = new_death_count - participant.death_count` assignment inside the session block will overwrite it when deaths occur. After the session closes, `delta` is guaranteed to be 0 (no deaths) or positive (deaths attributed).

- [ ] **Step 2: Add reconnect unicast**

In `handle_mod_websocket()`, inside the auth session block, after the existing reconnect block. The existing code looks like:

```python
            seed = participant.race.seed
            if participant.race.status == RaceStatus.RUNNING and seed and seed.graph_json:
                zone = participant.current_zone or get_start_node(seed.graph_json)
                if zone:
                    await send_zone_update(...)
        # Session closed, released back to pool
```

Add the death_counts unicast inside the `if RUNNING and seed and seed.graph_json:` block, at the same indentation level as `if zone:` (NOT nested inside `if zone:`):

```python
            seed = participant.race.seed
            if participant.race.status == RaceStatus.RUNNING and seed and seed.graph_json:
                zone = participant.current_zone or get_start_node(seed.graph_json)
                if zone:
                    await send_zone_update(...)

                # Send current death counts on reconnect
                counts = aggregate_death_counts(race.participants)
                if counts:
                    await websocket.send_text(
                        DeathCountsMessage(counts=counts).model_dump_json()
                    )
```

- [ ] **Step 3: Write integration test for death_counts broadcast**

In `server/tests/test_integration.py`, add:

```python
def test_death_counts_broadcast(integration_client, race_with_participants):
    """Deaths broadcast death_counts to all connected mods."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        assert mod1.auth()["type"] == "auth_ok"

        # Player 0 discovers node_a
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")
        mod1.receive_until_type("leaderboard_update")

        # Player 0 dies twice in node_a
        mod0.send_status_update(igt_ms=15000, death_count=2)
        time.sleep(0.3)

        # Both mods should receive death_counts
        msg0 = mod0.receive_until_type("death_counts")
        assert msg0["counts"]["node_a"] == 2

        msg1 = mod1.receive_until_type("death_counts")
        assert msg1["counts"]["node_a"] == 2
```

- [ ] **Step 4: Write integration test for death_flags in auth_ok**

In `server/tests/test_integration.py`, add two tests. The first verifies the default (no death_flags in graph_json), which works with the existing seed fixture. The second patches the seed to include death_flags.

```python
def test_death_flags_default_empty_in_auth_ok(integration_client, race_with_participants):
    """auth_ok includes empty death_flags when graph_json has no death_flags."""
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["death_flags"] == {}


def test_death_flags_populated_in_auth_ok(
    integration_client, race_with_participants, integration_db
):
    """auth_ok includes death_flags from graph_json when present."""
    import asyncio

    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]

    # Patch the seed's graph_json to include death_flags
    async def add_death_flags():
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id))
            )
            race = result.scalar_one()
            result = await db.execute(
                select(Seed).where(Seed.id == race.seed_id)
            )
            seed = result.scalar_one()
            graph = dict(seed.graph_json)
            graph["death_flags"] = {
                "node_a": [1040292500, 1040292501, 1040292502],
            }
            seed.graph_json = graph
            await db.commit()

    asyncio.run(add_death_flags())

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        mod = ModTestClient(ws, players[0]["mod_token"])
        auth = mod.auth(drain=False)
        assert auth["type"] == "auth_ok"
        assert auth["seed"]["death_flags"] == {
            "node_a": [1040292500, 1040292501, 1040292502],
        }
```

Note: `test_death_flags_populated_in_auth_ok` requires `integration_db` in the fixture signature. `select`, `Race`, `Seed`, and `uuid` are already imported at the top of the test file.

- [ ] **Step 5: Run the new integration tests**

Run: `cd server && uv run pytest tests/test_integration.py::test_death_counts_broadcast tests/test_integration.py::test_death_flags_in_auth_ok -v`
Expected: Both pass

- [ ] **Step 6: Run full test suite**

Run: `cd server && uv run pytest -x -q`
Expected: All pass

- [ ] **Step 7: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Expected: Clean

- [ ] **Step 8: Commit**

```bash
git add server/speedfog_racing/websocket/mod.py server/tests/test_integration.py
git commit -m "feat: broadcast death_counts on death attribution and reconnect"
```

---

### Task 4: Mod protocol (Rust)

**Files:**

- Modify: `mod/src/core/protocol.rs`

- [ ] **Step 1: Write tests for DeathCounts deserialization**

In `mod/src/core/protocol.rs`, add to `mod tests`:

```rust
#[test]
fn test_server_death_counts_deserialize() {
    let json = r#"{
        "type": "death_counts",
        "counts": {"node_a": 4, "node_b": 1}
    }"#;
    let msg: ServerMessage = serde_json::from_str(json).unwrap();
    match msg {
        ServerMessage::DeathCounts { counts } => {
            assert_eq!(counts.get("node_a"), Some(&4));
            assert_eq!(counts.get("node_b"), Some(&1));
            assert_eq!(counts.len(), 2);
        }
        _ => panic!("Expected DeathCounts"),
    }
}

#[test]
fn test_seed_info_with_death_flags() {
    let json = r#"{
        "total_layers": 5,
        "death_flags": {
            "node_a": [1040292500, 1040292501, 1040292502]
        }
    }"#;
    let seed: SeedInfo = serde_json::from_str(json).unwrap();
    let flags = seed.death_flags.get("node_a").unwrap();
    assert_eq!(*flags, [1040292500, 1040292501, 1040292502]);
}

#[test]
fn test_seed_info_without_death_flags() {
    // Backward compat: old server sends no death_flags field
    let json = r#"{"total_layers": 5}"#;
    let seed: SeedInfo = serde_json::from_str(json).unwrap();
    assert!(seed.death_flags.is_empty());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mod && cargo test`
Expected: Compilation error (DeathCounts variant and death_flags field don't exist)

- [ ] **Step 3: Add DeathCounts variant to ServerMessage**

In `mod/src/core/protocol.rs`, add to the `ServerMessage` enum, before `Ping`:

```rust
    /// Aggregated death counts per zone (for conditional death markers)
    DeathCounts {
        counts: HashMap<String, u32>,
    },
```

- [ ] **Step 4: Add death_flags to SeedInfo**

In `mod/src/core/protocol.rs`, add to `SeedInfo`, after `seed_id`:

```rust
    /// Death marker event flags per cluster: [flag_low, flag_med, flag_high]
    #[serde(default)]
    pub death_flags: HashMap<String, [u32; 3]>,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd mod && cargo test`
Expected: All pass including the 3 new tests

- [ ] **Step 6: Commit**

```bash
git add mod/src/core/protocol.rs
git commit -m "feat: add DeathCounts message and SeedInfo.death_flags to mod protocol"
```

---

### Task 5: Mod WebSocket forwarding + tracker handling

**Files:**

- Modify: `mod/src/dll/websocket.rs`
- Modify: `mod/src/dll/tracker.rs`

- [ ] **Step 1: Add IncomingMessage variant**

In `mod/src/dll/websocket.rs`, add to `IncomingMessage` enum, before `RequeueEventFlag`:

```rust
    /// Aggregated death counts per zone for death marker flags
    DeathCounts(HashMap<String, u32>),
```

- [ ] **Step 2: Forward DeathCounts in message_loop**

In `mod/src/dll/websocket.rs`, in `message_loop()`, in the `match msg` block (around line 495), add before the `ServerMessage::Error` arm:

```rust
                        ServerMessage::DeathCounts { counts } => {
                            let _ = incoming_tx.send(IncomingMessage::DeathCounts(counts));
                        }
```

- [ ] **Step 3: Add death_counts field to RaceState**

In `mod/src/dll/tracker.rs`, add to `RaceState`:

```rust
    pub death_counts: HashMap<String, u32>,
```

Ensure `HashMap` is imported (it already is via `std::collections::HashMap`).

- [ ] **Step 4: Handle DeathCounts in tracker**

In `mod/src/dll/tracker.rs`, in `handle_ws_message()`, add a new arm before `IncomingMessage::Error`:

```rust
            IncomingMessage::DeathCounts(counts) => {
                self.last_received_debug = Some(format!("death_counts({} zones)", counts.len()));
                self.race_state.death_counts = counts.clone();
                if let Some(ref seed) = self.race_state.seed {
                    for (node_id, total) in &counts {
                        if let Some(flags) = seed.death_flags.get(node_id) {
                            self.event_flag_reader.set_flag(flags[0], *total >= 1);
                            self.event_flag_reader.set_flag(flags[1], *total >= 3);
                            self.event_flag_reader.set_flag(flags[2], *total >= 5);
                        }
                    }
                }
            }
```

- [ ] **Step 5: Verify compilation**

Run: `cd mod && cargo check --lib`
Expected: Compiles without errors (on Linux, won't build DLL but checks syntax)

- [ ] **Step 6: Run tests**

Run: `cd mod && cargo test`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add mod/src/dll/websocket.rs mod/src/dll/tracker.rs
git commit -m "feat: handle DeathCounts message in mod websocket and tracker"
```

---

### Task 6: PROTOCOL.md documentation

**Files:**

- Modify: `docs/PROTOCOL.md`

- [ ] **Step 1: Add death_counts to Server -> Client messages**

In `docs/PROTOCOL.md`, in the Mod WebSocket "Server -> Client" section, add after the `zone_update` documentation:

```markdown
#### `death_counts`

Aggregated death counts per DAG node across all race participants. Broadcast to all mods when a death is attributed (delta > 0). Also sent as a unicast on reconnect if any deaths have occurred.

The mod uses these counts with `death_flags` from `SeedInfo` to set EMEVD event flags that control in-game bloodstain visibility. Three thresholds: low (1+), med (3+), high (5+).

\`\`\`json
{
"type": "death_counts",
"counts": {
"node_a": 4,
"node_b": 1
}
}
\`\`\`

`counts`: sparse dict of node_id to total deaths. Nodes with zero deaths are omitted. Deaths only increase during a race.
```

- [ ] **Step 2: Add death_flags to SeedInfo table**

In `docs/PROTOCOL.md`, in the SeedInfo table, add a row after `spawn_items`:

```markdown
| `death_flags` | `object` | yes | no | Death marker flags per cluster `{node_id: [low, med, high]}` |
```

- [ ] **Step 3: Add death_counts to training exclusion note**

In the Training Mod WebSocket section, update the "Server -> Client messages" line to include `death_counts` in the exclusion:

The existing line lists the messages available for training. `death_counts` is racing-only, so note it is not sent in training sessions.

- [ ] **Step 4: Commit**

```bash
git add docs/PROTOCOL.md
git commit -m "docs: add death_counts message and death_flags to protocol reference"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full server test suite**

Run: `cd server && uv run pytest -x -q`
Expected: All pass

- [ ] **Step 2: Run server linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Expected: Clean

- [ ] **Step 3: Run mod checks**

Run: `cd mod && cargo check --lib && cargo test`
Expected: Compiles and all tests pass

- [ ] **Step 4: Review all changes**

Run: `git log --oneline HEAD~6..HEAD`
Expected: 6 commits covering schemas, aggregation, broadcast, protocol, tracker, docs
