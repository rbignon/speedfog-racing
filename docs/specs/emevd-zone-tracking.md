# EMEVD Event-Based Zone Tracking & Race Finish Detection

**Date:** 2026-02-07
**Status:** Draft

---

## 1. Problem Statement

The current zone tracking in the SpeedFog Racing mod relies on reading the player's `map_id` from game memory. This is unreliable because:

- **Multiple zones share the same map_id** — Elden Ring's map coordinates don't correspond 1:1 to SpeedFog's logical zones. A single map_id can cover different areas.
- **Race finish detection is not implemented** — there is no mechanism to detect when a player defeats the final boss. The `finished` message protocol exists but is never triggered.
- **Zone transitions are imprecise** — detecting a map_id change misses fog gate traversals that stay within the same map tile.

---

## 2. Solution Overview

Replace map_id-based zone tracking with **EMEVD custom event flags**:

1. **SpeedFog generator** injects custom EMEVD events that fire when a player traverses a fog gate or defeats the final boss
2. **graph.json** is extended with a mapping from event flag IDs to destination nodes
3. **The racing mod** monitors a list of event flag IDs in game memory and reports triggered flags to the server
4. **The server** resolves event flag IDs to DAG nodes, updates zone history, and handles race finish

This design is anti-spoiler by default: the mod only sees opaque numeric IDs and has no knowledge of what they represent.

---

## 3. Architecture

### 3.1 Data Flow

```
SpeedFog Generator (seed creation)
  ├─ Injects EMEVD: fog gate traversal → set event flag N
  ├─ Injects EMEVD: final boss death → set event flag M
  └─ Writes graph.json v4 with event_map and finish_event

Server (race start)
  ├─ Reads graph.json from seed
  └─ Sends event_ids list to mod via auth_ok

Mod (runtime, game thread tick loop)
  ├─ Reads event flags from game memory
  ├─ Detects 0→1 transitions
  └─ Sends event_flag message to server (flag_id + igt_ms)

Server (message handler)
  ├─ Looks up flag_id in seed.graph_json["event_map"]
  ├─ If flag_id == finish_event → trigger race finish
  ├─ Otherwise → update zone_history, recompute layer
  └─ Broadcast leaderboard update
```

### 3.2 Event Flag Mechanism

EMEVD event flags in Elden Ring are **persistent boolean values** stored in the save file. When SpeedFog's EMEVD sets a flag upon fog gate traversal, it stays set for the remainder of the playthrough. This is acceptable because:

- The server ignores duplicate events (node already in `zone_history`)
- Flags are reset on New Game (new character), which is when a race seed is used
- Persistence actually helps: if the mod disconnects and reconnects mid-race, it can re-read all set flags to reconstruct state

The mod polls event flags every tick (~10ms). When it detects a flag transition from 0 to 1, it sends an `event_flag` message to the server.

For re-traversals (player going back through an already-traversed fog gate), the flag is already 1, so no new event fires. The server wouldn't act on it anyway (node already discovered).

### 3.3 Event Flag ID Range

SpeedFog must use event flag IDs that don't conflict with vanilla Elden Ring or the Fog Gate Randomizer itself.

**Proposed range:** `9000000–9000999` (1000 flags, far more than any seed needs)

This range is in the "custom mod" space and won't conflict with vanilla flags (which are typically in the 0–8999999 range). The exact range is a convention agreed between SpeedFog and the racing mod.

---

## 4. SpeedFog Generator Changes

> **This section is addressed to the SpeedFog developer.**

### 4.1 EMEVD Event Injection

During seed generation, SpeedFog must add custom EMEVD events for racing support. Two categories:

#### Fog Gate Traversal Events

For each fog gate in the randomized world, add an EMEVD event that **sets an event flag** when the player passes through. Each destination node in the DAG gets a unique event flag ID.

**Rules:**

- One event flag per **destination node** (not per edge). If two fog gates lead to the same node (e.g., a merge point in the DAG), both trigger the same flag.
- The start node does not need a fog gate event (the player begins there).
- Flag IDs are allocated sequentially starting from a base (e.g., `9000000`).

#### Final Boss Death Event

Add an EMEVD event that sets a specific flag when the seed's final boss is defeated. This is separate from the fog gate events — it fires on boss death, not on fog gate traversal.

### 4.2 graph.json v4 Format

Extend graph.json with two new top-level fields:

```json
{
  "version": "4.0",
  "seed": 971565517,
  "total_layers": 12,
  "total_nodes": 18,
  "total_paths": 6,

  "event_map": {
    "9000001": "dragonbarrow_cave_3b1c",
    "9000002": "caelid_abandonedcave_aa21",
    "9000003": "academy_d5a9",
    "9000047": "haligtree_loretta_19ab"
  },

  "finish_event": 9000047,

  "nodes": {
    "chapel_start_4f96": {
      "type": "start",
      "display_name": "Chapel of Anticipation",
      "zones": ["chapel_start"],
      "layer": 0,
      "tier": 1,
      "weight": 1
    }
  },
  "edges": [],
  "connections": [],
  "area_tiers": {}
}
```

**New fields:**

| Field          | Type             | Description                                                                                                                                           |
| -------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `event_map`    | `dict[str, str]` | Maps event flag ID (as string) to destination node_id. Keys are string because JSON keys must be strings.                                             |
| `finish_event` | `int`            | The event flag ID that signals race completion (final boss defeated). This flag ID MUST also appear in `event_map`, mapping to the `final_boss` node. |

**Notes:**

- `event_map` keys are stringified integers (JSON constraint), but values are node_ids from the `nodes` dict
- The `finish_event` value is the integer flag ID, not a string
- The start node (`chapel_start_4f96` in the example) is NOT in `event_map` — the player starts there, no fog gate traversal needed
- Existing fields (`connections`, `area_tiers`, `nodes`, `edges`) remain unchanged for backward compatibility with the web visualization

### 4.3 Seed Pack Contents

The seed pack currently includes `graph.json` in the zip. With EMEVD events, the mod no longer needs graph.json (it only needs the event flag IDs, which come from the server via WebSocket). However, **graph.json should remain in the seed pack for now** — it's needed by ModEngine for the fog gate randomizer itself. The racing mod ignores it.

### 4.4 EMEVD Implementation Notes

This section outlines the expected behavior. The SpeedFog developer knows best how to implement this within the EMEVD framework.

**For each fog gate leading to node X:**

- When the player enters the fog gate → set event flag `event_map[X]`
- The event should fire every time (not just the first time), but since flags are persistent, the practical effect is "set once, stays set"

**For the final boss:**

- When the boss's HP reaches 0 (or the boss death animation triggers) → set event flag `finish_event`
- This must be the actual defeat, not entering the boss arena

**Event flag range convention:**

- Base: `9000000`
- Per-seed allocation: `9000000 + i` where `i` is 0-indexed per node
- The finish_event can be the same flag as the final_boss node in event_map (the boss defeat and "reached final boss area" can share a flag if the trigger is boss death)

---

## 5. Mod Changes (Rust)

### 5.1 Protocol Changes

#### New Client → Server Message: `event_flag`

Replaces `zone_entered`. Sent when the mod detects an event flag transition.

```rust
// protocol.rs - ClientMessage enum
EventFlag {
    flag_id: u32,
    igt_ms: u32,
},
```

Wire format:

```json
{ "type": "event_flag", "flag_id": 9000003, "igt_ms": 4532100 }
```

#### Updated Server → Client: `auth_ok`

The `SeedInfo` struct gains an `event_ids` field:

```rust
// protocol.rs
pub struct SeedInfo {
    pub total_layers: i32,
    pub event_ids: Vec<u32>,  // NEW: list of flag IDs to monitor
}
```

Wire format:

```json
{
  "type": "auth_ok",
  "race": { "id": "...", "name": "...", "status": "open" },
  "seed": {
    "total_layers": 12,
    "event_ids": [9000001, 9000002, 9000003, 9000047]
  },
  "participants": [...]
}
```

#### Removed/Modified Messages

| Message                      | Change                                                 |
| ---------------------------- | ------------------------------------------------------ |
| `zone_entered`               | **Removed** — replaced by `event_flag`                 |
| `status_update.current_zone` | **Removed** — zone is determined by events, not map_id |
| `status_update`              | Simplified to `{ type, igt_ms, death_count }` only     |

### 5.2 Event Flag Reading

New module: `mod/src/eldenring/event_flags.rs`

Event flags in Elden Ring are stored as bits in a large bitfield. Reading a specific flag requires:

1. Find the `VirtualMemoryFlag` manager via a base address pointer
2. Compute the byte offset and bit position for the target flag ID
3. Read the byte and extract the bit

```rust
// Pseudocode — actual offsets need discovery/verification
pub struct EventFlagReader {
    // Pointer to VirtualMemoryFlag manager
    base_ptr: PointerChain<usize>,
}

impl EventFlagReader {
    /// Read whether a specific event flag is set
    pub fn is_flag_set(&self, flag_id: u32) -> Option<bool> {
        let manager = self.base_ptr.read()?;
        // VirtualMemoryFlag stores flags as bits
        // Offset calculation depends on the game's internal layout
        let section = flag_id / 1000; // or similar grouping
        let bit_index = flag_id % (8 * ...);
        // Read the byte containing this flag
        // Extract the bit
        todo!("Implementation depends on VirtualMemoryFlag layout")
    }
}
```

**Note:** The exact memory layout for event flag reading needs to be discovered. The `libeldenring` crate may already provide base addresses for the event flag manager. If not, the offset needs to be found via reverse engineering (Cheat Engine, x64dbg). The eldenring-practice-tool community likely has documented these offsets.

### 5.3 Tracker Changes

Replace zone detection logic in `tracker.rs`:

```rust
pub struct RaceTracker {
    // ... existing fields ...

    // REMOVE:
    // last_zone: Option<String>,

    // ADD:
    event_flag_reader: EventFlagReader,
    event_ids: Vec<u32>,           // From auth_ok
    triggered_flags: HashSet<u32>, // Already-triggered flags (avoid re-sending)
}
```

**AuthOk handling — clear flags on new race:**

When receiving `AuthOk`, the tracker must reset its event tracking state. This prevents stale flags from a previous race (or reconnection with a different seed) from leaking.

```rust
IncomingMessage::AuthOk { race, seed, participants } => {
    self.race_state.race = Some(race);
    self.race_state.participants = participants;

    // Extract event_ids and reset tracking state
    self.event_ids = seed.event_ids.clone();
    self.triggered_flags.clear();

    self.race_state.seed = Some(seed);
}
```

**Updated tick loop:**

```rust
fn update(&mut self) {
    // ... hotkeys, ws poll, game reading ...

    // Send ready + re-scan flags on (re)connect
    if !self.ready_sent {
        self.ws_client.send_ready();
        self.ready_sent = true;

        // Re-scan all event flags after (re)connect.
        // Since flags are persistent in the save file, any that fired
        // while disconnected are still set and can be recovered.
        for &flag_id in &self.event_ids {
            if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                self.triggered_flags.insert(flag_id);
                self.ws_client.send_event_flag(flag_id, igt_ms);
                info!(flag_id = flag_id, "[RACE] Event flag re-sent after reconnect");
            }
        }
    }

    // Event flag monitoring (replaces zone detection)
    for &flag_id in &self.event_ids {
        if !self.triggered_flags.contains(&flag_id) {
            if let Some(true) = self.event_flag_reader.is_flag_set(flag_id) {
                // New flag detected!
                self.triggered_flags.insert(flag_id);
                self.ws_client.send_event_flag(flag_id, igt_ms);
                info!(flag_id = flag_id, "[RACE] Event flag triggered");
            }
        }
    }

    // Status updates: simplified (no current_zone)
    if self.last_status_update.elapsed() >= Duration::from_secs(1) {
        self.ws_client.send_status_update(igt_ms, deaths);
        self.last_status_update = Instant::now();
    }
}
```

**Reconnection handling:** On reconnect, the mod re-reads all event flags and re-sends any that are set. This handles the case where the mod disconnects and misses events — since flags are persistent, they can be recovered. The server ignores duplicate events (node already in `zone_history`), so re-sending is safe.

### 5.4 WebSocket Client Changes

```rust
// websocket.rs — OutgoingMessage enum
EventFlag {
    flag_id: u32,
    igt_ms: u32,
},

// Remove ZoneEntered variant

// Update StatusUpdate to remove current_zone:
StatusUpdate {
    igt_ms: u32,
    death_count: u32,
},
```

Add `send_event_flag()` method, remove `send_zone_entered()`.

---

## 6. Server Changes (Python)

### 6.1 Schema Changes

#### New Client Message: `EventFlagMessage`

```python
# websocket/schemas.py
class EventFlagMessage(BaseModel):
    type: Literal["event_flag"] = "event_flag"
    flag_id: int
    igt_ms: int
```

#### Updated `StatusUpdateMessage`

Remove `current_zone`:

```python
class StatusUpdateMessage(BaseModel):
    type: Literal["status_update"] = "status_update"
    igt_ms: int
    death_count: int
```

#### Updated `SeedInfo`

Add `event_ids`:

```python
class SeedInfo(BaseModel):
    total_layers: int
    graph_json: dict[str, object] | None = None
    total_nodes: int | None = None
    total_paths: int | None = None
    event_ids: list[int] | None = None  # For mods only
```

#### Remove `ZoneEnteredMessage`

No longer used.

### 6.2 auth_ok Changes

In `websocket/mod.py`, update `send_auth_ok()` to include event_ids:

```python
async def send_auth_ok(websocket: WebSocket, participant: Participant) -> None:
    race = participant.race
    seed = race.seed

    # Extract event_ids from graph_json
    event_ids = []
    if seed and seed.graph_json:
        event_map = seed.graph_json.get("event_map", {})
        event_ids = sorted(int(k) for k in event_map.keys())

    message = AuthOkMessage(
        race=RaceInfo(id=str(race.id), name=race.name, status=race.status.value),
        seed=SeedInfo(
            total_layers=seed.total_layers if seed else 0,
            graph_json=None,  # Mods don't need the graph
            event_ids=event_ids,
        ),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())
```

### 6.3 New Message Handler: `handle_event_flag`

Replaces `handle_zone_entered`:

```python
async def handle_event_flag(
    db: AsyncSession, participant: Participant, msg: dict[str, Any]
) -> None:
    """Handle event flag trigger from mod."""
    flag_id = msg.get("flag_id")
    if not isinstance(flag_id, int):
        return

    seed = participant.race.seed
    if not seed or not seed.graph_json:
        return

    event_map = seed.graph_json.get("event_map", {})
    finish_event = seed.graph_json.get("finish_event")

    # Resolve flag_id to node_id
    node_id = event_map.get(str(flag_id))
    if node_id is None:
        logger.warning(f"Unknown event flag {flag_id} from participant {participant.id}")
        return

    # Update IGT
    igt = msg.get("igt_ms", 0) if isinstance(msg.get("igt_ms"), int) else 0
    participant.igt_ms = igt

    # Check if node already discovered (ignore duplicates)
    old_history = participant.zone_history or []
    if any(entry.get("node_id") == node_id for entry in old_history):
        return  # Already discovered, no action needed

    # Update zone history and layer
    nodes = seed.graph_json.get("nodes", {})
    node_data = nodes.get(node_id, {})
    layer = node_data.get("layer", 0)

    participant.current_layer = layer
    participant.current_zone = node_id  # Store node_id instead of map_id
    entry = {"node_id": node_id, "igt_ms": igt}
    participant.zone_history = [*old_history, entry]

    # Check if this is the finish event (after updating zone_history)
    if flag_id == finish_event:
        await handle_finished(db, participant, {"igt_ms": igt})
        return

    await db.commit()

    # Broadcast updated leaderboard
    await db.refresh(participant.race, ["participants"])
    for p in participant.race.participants:
        await db.refresh(p, ["user"])
    await manager.broadcast_leaderboard(participant.race_id, participant.race.participants)
```

### 6.4 Layer Service Changes

Replace `get_layer_for_zone()` which uses `area_tiers` with direct node lookup:

```python
def get_layer_for_node(node_id: str, graph_json: dict[str, Any]) -> int:
    """Get layer for a node_id from graph_json nodes."""
    nodes = graph_json.get("nodes", {})
    node_data = nodes.get(node_id, {})
    return node_data.get("layer", 0)
```

The old `get_layer_for_zone()` and `get_node_for_zone()` become unused and can be removed (or kept for backward compatibility with v3 seeds during transition).

### 6.5 Updated `handle_status_update`

Remove `current_zone` handling:

```python
async def handle_status_update(
    db: AsyncSession, participant: Participant, msg: dict[str, Any]
) -> None:
    if isinstance(msg.get("igt_ms"), int):
        participant.igt_ms = msg["igt_ms"]
    if isinstance(msg.get("death_count"), int):
        participant.death_count = msg["death_count"]

    # Set to playing if race is running
    race = participant.race
    if race.status == RaceStatus.RUNNING and participant.status == ParticipantStatus.READY:
        participant.status = ParticipantStatus.PLAYING

    await db.commit()
    await db.refresh(participant, ["user"])
    await manager.broadcast_player_update(participant.race_id, participant)
```

### 6.6 Message Routing

In `handle_mod_websocket`, replace `zone_entered` with `event_flag`:

```python
# Remove:
elif msg_type == "zone_entered":
    await handle_zone_entered(db, participant, msg)

# Add:
elif msg_type == "event_flag":
    await handle_event_flag(db, participant, msg)
```

---

## 7. Seed Pack Service Changes

The seed pack service (`seed_pack_service.py`) copies the entire seed folder contents into the zip. No changes needed — graph.json remains in the pack for ModEngine, and the mod ignores it.

---

## 8. PROTOCOL.md Updates

### Updated Client → Server Messages

#### `status_update` (modified)

```json
{
  "type": "status_update",
  "igt_ms": 123456,
  "death_count": 5
}
```

`current_zone` removed. Zone tracking is now event-based.

#### `event_flag` (new, replaces `zone_entered`)

```json
{
  "type": "event_flag",
  "flag_id": 9000003,
  "igt_ms": 4532100
}
```

Sent when the mod detects an event flag transition (0 → 1).

#### `zone_entered` (removed)

Replaced by `event_flag`.

### Updated Server → Client Messages

#### `auth_ok` (modified)

```json
{
  "type": "auth_ok",
  "race": { "id": "uuid", "name": "Sunday Showdown", "status": "open" },
  "seed": {
    "total_layers": 12,
    "event_ids": [9000001, 9000002, 9000003, 9000047]
  },
  "participants": [...]
}
```

New field `event_ids`: flat list of event flag IDs the mod should monitor. Opaque to the mod — no mapping to zones or nodes.

---

## 9. Migration & Compatibility

### Seed Pool

Existing seeds in the pool (graph.json v3) do not have `event_map` or `finish_event`. They must be **regenerated** with the updated SpeedFog generator. Since we are not in production, this is not a compatibility concern — regenerate all pools.

### Database

No schema changes needed:

- `Participant.current_zone` stores node_id instead of map_id (still a string)
- `Participant.zone_history` format unchanged: `[{node_id, igt_ms}, ...]`
- `Seed.graph_json` stores whatever graph.json contains (v3 or v4)

### Frontend

No changes needed. The DAG visualization already works with node_ids from `zone_history`. The `current_zone` field displayed in the leaderboard will now show a node_id instead of a map_id, but this is an internal identifier not shown to end users.

---

## 10. Testing

### Server Tests

- **`test_event_flag_basic`**: Send event_flag → verify zone_history updated, layer computed
- **`test_event_flag_finish`**: Send finish_event → verify participant marked finished AND zone_history includes final boss node
- **`test_event_flag_duplicate`**: Send same flag twice → verify zone_history not duplicated, no error
- **`test_event_flag_unknown`**: Send unknown flag_id → verify ignored with warning
- **`test_event_flag_all_finished`**: All participants send finish → verify race marked finished
- **`test_auth_ok_event_ids`**: Verify auth_ok includes correct sorted event_ids from seed
- **`test_event_flag_reconnect_resend`**: Same flag sent twice from reconnected mod → verify idempotent

### Mod Tests (Rust)

- **`test_event_flag_message_serialize`**: Verify EventFlag JSON format
- **`test_seed_info_deserialize`**: Verify SeedInfo with event_ids parses correctly
- **`test_seed_info_event_ids_empty`**: Verify SeedInfo with empty event_ids (v3 seed fallback)
- **`test_status_update_no_zone`**: Verify simplified status_update format (no current_zone)

### Integration Tests

- Full flow: mod connects → auth_ok with event_ids → simulate flag triggers → verify leaderboard updates → simulate finish → verify race ends
- Reconnection: mod disconnects mid-race → reconnects → re-sends set flags → verify server state consistent

---

## 11. Implementation Order

### Step 1: SpeedFog Generator (external project)

- Implement EMEVD event injection for fog gates
- Implement final boss death event
- Extend graph.json output to v4 format (add `event_map`, `finish_event`)
- Regenerate seed pools

### Step 2: Server Protocol Update

- Add `EventFlagMessage` schema
- Update `SeedInfo` with `event_ids`
- Implement `handle_event_flag` handler
- Update `send_auth_ok` to include event_ids
- Remove `handle_zone_entered`, simplify `handle_status_update`
- Update layer_service
- Write tests

### Step 3: Mod Event Flag Reading

- Discover/document VirtualMemoryFlag memory layout for event flag reading
- Implement `EventFlagReader` in `eldenring/event_flags.rs`
- Add `EventFlag` variant to `ClientMessage`
- Update `SeedInfo` struct with `event_ids`
- Update `RaceTracker` tick loop (replace zone detection with flag polling)
- Handle reconnection (re-read all flags)
- Remove zone_entered and current_zone from status_update
- Write tests

### Step 4: Protocol Cleanup

- Update PROTOCOL.md
- Remove dead code (old zone_entered paths)
- Regenerate hero-seed.json with v4 format (add dummy event_map for homepage DAG)

---

## 12. Open Questions

1. **VirtualMemoryFlag memory layout**: The exact offsets for reading event flags from Elden Ring memory need to be discovered. The eldenring-practice-tool community (libeldenring) may have this documented. This is the main technical risk.

2. **Event flag range safety**: Is `9000000–9000999` safe from collisions with vanilla ER and Fog Gate Randomizer? The SpeedFog developer should confirm this range doesn't conflict with existing EMEVD usage.

3. **Boss death trigger specificity**: For the final boss death event, what's the most reliable EMEVD trigger? Boss HP reaching 0, death animation starting, or a specific game event? The SpeedFog developer knows best.

4. **Multiple runs on same save**: If a player starts a new race with a different seed on the same NG cycle, old event flags from a previous seed might still be set. Since flag IDs are allocated per-seed, different seeds use different IDs, so there's no collision. But if the same seed is reused across races, the flags would already be set. **Mitigation**: each seed should use a unique base offset, or the mod should clear its tracked flags on new auth_ok.
