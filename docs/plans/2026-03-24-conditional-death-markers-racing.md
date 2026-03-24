# Conditional Death Markers: speedfog-racing Implementation

Server-side aggregation, WebSocket broadcast, and mod-side flag setting for conditional
death markers. Companion to `../speedfog/docs/specs/2026-03-24-conditional-death-markers.md`.

## Approach

Event-driven aggregation in `handle_status_update()`. When a death delta is attributed,
aggregate deaths per node_id across all participants and broadcast `death_counts` to all
mods. No new DB columns, no timers, no cached state.

## Protocol Changes

### New server-to-client message: `death_counts`

```json
{
  "type": "death_counts",
  "counts": { "node_id_1": 4, "node_id_2": 1 }
}
```

Broadcast to all mods in the race room when a death is attributed (delta > 0).

### SeedInfo extension: `death_flags`

Added to `auth_ok` payload. Extracted from `graph_json["death_flags"]`.

```json
{
  "seed": {
    "total_layers": 5,
    "event_ids": [...],
    "death_flags": {
      "node_id_1": [1040292500, 1040292501, 1040292502],
      "node_id_2": [1040292503, 1040292504, 1040292505]
    }
  }
}
```

### Backward compatibility

- Old mods ignore unknown `death_counts` messages (catch-all `_ => {}` in websocket.rs).
- Old servers omit `death_flags`; mod deserializes as empty HashMap via `#[serde(default)]`.
- Python `SeedInfo` uses `Field(default_factory=dict)` for the same reason.

## Server Changes

### schemas.py

New message type:

```python
class DeathCountsMessage(BaseModel):
    type: Literal["death_counts"] = "death_counts"
    counts: dict[str, int]  # node_id -> total deaths across all participants
```

Add `death_flags` to `SeedInfo`:

```python
death_flags: dict[str, list[int]] = Field(default_factory=dict)
```

### mod.py: aggregation utility

```python
def aggregate_death_counts(participants: list[Participant]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in participants:
        for entry in (p.zone_history or []):
            deaths = entry.get("deaths", 0)
            if deaths > 0:
                node_id = entry.get("node_id")
                if node_id:
                    counts[node_id] = counts.get(node_id, 0) + deaths
    return counts
```

Reused at two call sites (status_update broadcast and reconnect unicast).

### mod.py: broadcast on death

In `handle_status_update()`, after `db.commit()` and session close, when `delta > 0`:

```python
counts = aggregate_death_counts(participant.race.participants)
await manager.broadcast_to_mods(
    race_id,
    DeathCountsMessage(counts=counts).model_dump_json(),
)
```

Uses detached objects (`expire_on_commit=False`), same pattern as leaderboard broadcasts.

### mod.py: reconnect unicast

After `send_zone_update` on reconnect (existing block at line ~175), unicast current
death counts to the reconnecting mod:

```python
counts = aggregate_death_counts(race.participants)
if counts:
    msg = DeathCountsMessage(counts=counts)
    await websocket.send_text(msg.model_dump_json())
```

### mod.py: send_auth_ok

Extract `death_flags` from `graph_json` and pass to `SeedInfo`:

```python
death_flags = {}
if seed and seed.graph_json:
    death_flags = seed.graph_json.get("death_flags", {})
```

## Mod Changes

### protocol.rs

New `ServerMessage` variant:

```rust
DeathCounts {
    counts: HashMap<String, u32>,
},
```

New field on `SeedInfo`:

```rust
#[serde(default)]
pub death_flags: HashMap<String, [u32; 3]>,
```

### websocket.rs

Forward `DeathCounts` via `IncomingMessage`:

```rust
ServerMessage::DeathCounts { counts } => {
    let _ = incoming_tx.send(IncomingMessage::DeathCounts(counts));
}
```

New `IncomingMessage` variant to match.

### tracker.rs

On receiving `IncomingMessage::DeathCounts(counts)`:

```rust
for (node_id, total) in &counts {
    if let Some(flags) = self.seed_info.death_flags.get(node_id) {
        self.event_flag_reader.set_flag(flags[0], total >= &1);
        self.event_flag_reader.set_flag(flags[1], total >= &3);
        self.event_flag_reader.set_flag(flags[2], total >= &5);
    }
}
```

Uses existing `set_flag()` (already used for clearing flags after capture).

## Tests

### Server (pytest)

- `test_death_counts_broadcast`: 2 participants, one dies, verify other mod receives
  `death_counts` with correct aggregate.
- `test_death_counts_aggregation`: unit test of `aggregate_death_counts` with multiple
  participants and zones.
- `test_death_counts_on_reconnect`: mod reconnects mid-race, receives `death_counts`
  after `auth_ok`.
- `test_death_flags_in_auth_ok`: verify `SeedInfo` contains `death_flags` from graph_json.

### Mod (cargo test)

- `test_death_counts_deserialize`: new `ServerMessage::DeathCounts` variant.
- `test_seed_info_with_death_flags`: `death_flags` deserializes correctly.
- `test_seed_info_without_death_flags`: backward compat, absent field gives empty HashMap.

## Files Changed

| File                                          | Change                                                                                        |
| --------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `server/speedfog_racing/websocket/schemas.py` | `DeathCountsMessage`, `SeedInfo.death_flags`                                                  |
| `server/speedfog_racing/websocket/mod.py`     | `aggregate_death_counts()`, broadcast on death, reconnect unicast, `send_auth_ok` death_flags |
| `mod/src/core/protocol.rs`                    | `DeathCounts` variant, `SeedInfo.death_flags`                                                 |
| `mod/src/dll/websocket.rs`                    | Forward `DeathCounts` to `IncomingMessage`                                                    |
| `mod/src/dll/tracker.rs`                      | Apply thresholds, set event flags                                                             |
