# Zone Query message_id Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `message_id` to `zone_query` messages for dedup, in-flight tracking, requeue on disconnect, and logging parity with `event_flag`.

**Architecture:** Mirror the existing `event_flag` message_id pattern: the mod assigns a timestamp-seeded `message_id` to each `zone_query`, tracks in-flight queries, requeues on disconnect, and replays on reconnect. The server deduplicates `backtrack` entries in `zone_history` by `message_id`, stores it in new entries, and returns it in the `zone_update` response. For early-return paths (unresolved query, wrong state), a lightweight `zone_query_ack` is sent to clear the in-flight entry.

**Tech Stack:** Rust (mod protocol/websocket/tracker), Python (FastAPI websocket handlers, Pydantic schemas)

---

## Task 1: Protocol - Add message_id to ZoneQuery and ZoneUpdate (mod)

**Files:**

- Modify: `mod/src/core/protocol.rs:30-40` (ClientMessage::ZoneQuery)
- Modify: `mod/src/core/protocol.rs:150-162` (ServerMessage::ZoneUpdate)
- Modify: `mod/src/core/protocol.rs:559-589` (tests)

- [ ] **Step 1: Add message_id field to ClientMessage::ZoneQuery**

```rust
    /// Zone query at loading screen exit (server resolves to graph node)
    ZoneQuery {
        igt_ms: u32,
        #[serde(skip_serializing_if = "Option::is_none")]
        grace_entity_id: Option<u32>,
        #[serde(skip_serializing_if = "Option::is_none")]
        map_id: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        position: Option<[f32; 3]>,
        #[serde(skip_serializing_if = "Option::is_none")]
        play_region_id: Option<u32>,
        message_id: u64,
    },
```

- [ ] **Step 2: Add message_id field to ServerMessage::ZoneUpdate**

```rust
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        #[serde(default)]
        original_tier: Option<i32>,
        #[serde(default)]
        layer: Option<i32>,
        #[serde(default)]
        is_first_visit: bool,
        #[serde(default)]
        exits: Vec<ExitInfo>,
        #[serde(default)]
        message_id: Option<u64>,
    },
```

- [ ] **Step 3: Add ServerMessage::ZoneQueryAck variant**

After the `EventFlagAck` variant:

```rust
    /// Acknowledges a zone_query that could not produce a zone_update
    /// (unresolved, wrong state, etc.) so the mod can clear in-flight tracking.
    ZoneQueryAck { message_id: u64 },
```

- [ ] **Step 4: Update existing ZoneQuery tests to include message_id**

```rust
    #[test]
    fn test_client_zone_query_grace_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 60000,
            grace_entity_id: Some(10002950),
            map_id: None,
            position: None,
            play_region_id: None,
            message_id: 42,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":60000"#));
        assert!(json.contains(r#""grace_entity_id":10002950"#));
        assert!(json.contains(r#""message_id":42"#));
        assert!(!json.contains("map_id"));
    }

    #[test]
    fn test_client_zone_query_map_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 120000,
            grace_entity_id: None,
            map_id: Some("m10_00_00_00".into()),
            position: Some([100.0, 50.0, 200.0]),
            play_region_id: Some(12345),
            message_id: 99,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":120000"#));
        assert!(json.contains(r#""map_id":"m10_00_00_00""#));
        assert!(json.contains(r#""message_id":99"#));
        assert!(!json.contains("grace_entity_id"));
    }
```

- [ ] **Step 5: Add test for ZoneUpdate with message_id deserialization**

```rust
    #[test]
    fn test_server_zone_update_with_message_id() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "message_id": 42,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, Some(42));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_message_id() {
        // Backward compat: old server sends no message_id field
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_query_ack_deserialize() {
        let json = r#"{"type":"zone_query_ack","message_id":55}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneQueryAck { message_id } => assert_eq!(message_id, 55),
            _ => panic!("Expected ZoneQueryAck"),
        }
    }
```

- [ ] **Step 6: Run tests**

Run: `cd mod && cargo test`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add mod/src/core/protocol.rs
git commit -m "feat: add message_id to ZoneQuery/ZoneUpdate protocol"
```

---

## Task 2: WebSocket layer - wire message_id through OutgoingMessage/IncomingMessage (mod)

**Files:**

- Modify: `mod/src/dll/websocket.rs:48-54` (OutgoingMessage::ZoneQuery)
- Modify: `mod/src/dll/websocket.rs:76-84` (IncomingMessage::ZoneUpdate)
- Modify: `mod/src/dll/websocket.rs:86-92` (add IncomingMessage::RequeueZoneQuery)
- Modify: `mod/src/dll/websocket.rs:93-95` (add IncomingMessage::ZoneQueryAck)
- Modify: `mod/src/dll/websocket.rs:219-238` (send_zone_query)
- Modify: `mod/src/dll/websocket.rs:320-351` (drain loop)
- Modify: `mod/src/dll/websocket.rs:548-567` (message_loop send)
- Modify: `mod/src/dll/websocket.rs:620-641` (message_loop receive ZoneUpdate)
- Add handling for ServerMessage::ZoneQueryAck in message_loop receive

- [ ] **Step 1: Add message_id to OutgoingMessage::ZoneQuery**

```rust
    ZoneQuery {
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
    },
```

- [ ] **Step 2: Add message_id to IncomingMessage::ZoneUpdate and add RequeueZoneQuery + ZoneQueryAck variants**

```rust
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        original_tier: Option<i32>,
        layer: Option<i32>,
        is_first_visit: bool,
        exits: Vec<ExitInfo>,
        message_id: Option<u64>,
    },
```

After `RequeueEventFlag`:

```rust
    /// Zone query drained from outgoing channel on reconnect, must be re-buffered
    RequeueZoneQuery {
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
    },
    ZoneQueryAck {
        message_id: u64,
    },
```

- [ ] **Step 3: Update send_zone_query to accept message_id**

```rust
    pub fn send_zone_query(
        &self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
    ) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::ZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            }) {
                warn!("[WS] Failed to queue zone_query: {}", e);
            }
        }
    }
```

- [ ] **Step 4: Add ZoneQuery to the drain loop (alongside EventFlag)**

In the `while let Ok(msg) = outgoing_rx.try_recv()` block (~line 324), after the `OutgoingMessage::EventFlag` arm:

```rust
                        OutgoingMessage::ZoneQuery {
                            igt_ms,
                            grace_entity_id,
                            map_id,
                            position,
                            play_region_id,
                            message_id,
                        } => {
                            let _ = incoming_tx.send(IncomingMessage::RequeueZoneQuery {
                                igt_ms,
                                grace_entity_id,
                                map_id,
                                position,
                                play_region_id,
                                message_id,
                            });
                        }
```

- [ ] **Step 5: Update message_loop send for ZoneQuery to include message_id and logging**

```rust
            Ok(OutgoingMessage::ZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            }) => {
                info!(?grace_entity_id, ?map_id, message_id, "[WS] Sending: zone_query");
                let msg = ClientMessage::ZoneQuery {
                    igt_ms,
                    grace_entity_id,
                    map_id,
                    position,
                    play_region_id,
                    message_id,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
```

- [ ] **Step 6: Update message_loop receive for ZoneUpdate to pass message_id**

```rust
                        ServerMessage::ZoneUpdate {
                            node_id,
                            display_name,
                            tier,
                            original_tier,
                            layer,
                            is_first_visit,
                            exits,
                            message_id,
                        } => {
                            if incoming_tx
                                .send(IncomingMessage::ZoneUpdate {
                                    node_id,
                                    display_name,
                                    tier,
                                    original_tier,
                                    layer,
                                    is_first_visit,
                                    exits,
                                    message_id,
                                })
                                .is_err()
                            {
                                warn!("[WS] Incoming channel full/closed: zone_update dropped");
                            }
                        }
```

- [ ] **Step 7: Add ZoneQueryAck handling in message_loop receive**

After the `ServerMessage::EventFlagAck` arm:

```rust
                        ServerMessage::ZoneQueryAck { message_id } => {
                            let _ = incoming_tx.send(IncomingMessage::ZoneQueryAck { message_id });
                        }
```

- [ ] **Step 8: Run cargo check**

Run: `cd mod && cargo check --lib`
Expected: compiles (tracker.rs will have warnings for unused fields, fixed in Task 3)

- [ ] **Step 9: Commit**

```bash
git add mod/src/dll/websocket.rs
git commit -m "feat: wire message_id through zone_query websocket layer"
```

---

## Task 3: Tracker - in-flight tracking, requeue, and replay for zone_query (mod)

**Files:**

- Modify: `mod/src/dll/tracker.rs:155-245` (struct fields)
- Modify: `mod/src/dll/tracker.rs:355-376` (constructor)
- Modify: `mod/src/dll/tracker.rs:558-586` (send_zone_query call site)
- Modify: `mod/src/dll/tracker.rs:698-710` (reconnect replay)
- Modify: `mod/src/dll/tracker.rs:807-843` (add send_tracked_zone_query, replay_in_flight_zone_queries)
- Modify: `mod/src/dll/tracker.rs:854-856` (Reconnecting handler)
- Modify: `mod/src/dll/tracker.rs:1053-1074` (ZoneUpdate handler)
- Add: RequeueZoneQuery + ZoneQueryAck handlers

- [ ] **Step 1: Add BufferedZoneQuery struct and tracker fields**

After the `BufferedEventFlag` struct (~line 155):

```rust
#[derive(Debug, Clone)]
struct BufferedZoneQuery {
    igt_ms: u32,
    grace_entity_id: Option<u32>,
    map_id: Option<String>,
    position: Option<[f32; 3]>,
    play_region_id: Option<u32>,
}
```

Add fields to `RaceTracker` struct, after `next_event_message_id` (line 206):

```rust
    in_flight_zone_queries: HashMap<u64, BufferedZoneQuery>,
```

Note: `next_event_message_id` is shared between event_flag and zone_query (rename mentally to "next message id"). No new counter needed.

- [ ] **Step 2: Initialize in constructor**

In `RaceTracker::new()`, after `next_event_message_id`:

```rust
            in_flight_zone_queries: HashMap::new(),
```

- [ ] **Step 3: Create send_tracked_zone_query method**

After `send_tracked_event_flag` (~line 816):

```rust
    fn send_tracked_zone_query(
        &mut self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
    ) {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_zone_queries.insert(
            message_id,
            BufferedZoneQuery {
                igt_ms,
                grace_entity_id: grace_entity_id,
                map_id: map_id.clone(),
                position,
                play_region_id,
            },
        );
        self.ws_client.send_zone_query(
            igt_ms,
            grace_entity_id,
            map_id,
            position,
            play_region_id,
            message_id,
        );
    }
```

- [ ] **Step 4: Create replay_in_flight_zone_queries method**

After `replay_in_flight_event_flags`:

```rust
    fn replay_in_flight_zone_queries(&mut self) {
        if self.in_flight_zone_queries.is_empty() {
            return;
        }

        let mut message_ids: Vec<u64> = self.in_flight_zone_queries.keys().copied().collect();
        message_ids.sort_unstable();
        for message_id in message_ids {
            if let Some(zq) = self.in_flight_zone_queries.get(&message_id) {
                self.ws_client.send_zone_query(
                    zq.igt_ms,
                    zq.grace_entity_id,
                    zq.map_id.clone(),
                    zq.position,
                    zq.play_region_id,
                    message_id,
                );
                info!(message_id, "[RACE] Replaying in-flight zone query");
            }
        }
    }
```

- [ ] **Step 5: Update the zone_query send call site to use send_tracked_zone_query**

Replace the direct `self.ws_client.send_zone_query(...)` call (~line 569) with:

```rust
                    if grace_opt.is_some() || map_id.is_some() {
                        self.send_tracked_zone_query(
                            igt_ms,
                            grace_opt,
                            map_id.clone(),
                            position,
                            play_region_id,
                        );
                        self.last_sent_debug = Some(format!(
                            "zone_query(grace={:?}, map={:?})",
                            grace_opt, map_id
                        ));
                        info!(?grace_opt, "[RACE] Zone query sent at loading exit");
                    }
```

- [ ] **Step 6: Add zone_query replay on reconnect**

After `self.replay_in_flight_event_flags();` (~line 701):

```rust
                // Replay in-flight zone queries (sent but not ACKed before disconnect)
                self.replay_in_flight_zone_queries();
```

- [ ] **Step 7: Update ZoneUpdate handler to clear in-flight entry**

In the `IncomingMessage::ZoneUpdate` match arm (~line 1053), add message_id extraction and in-flight removal:

```rust
            IncomingMessage::ZoneUpdate {
                node_id,
                display_name,
                tier,
                original_tier,
                layer,
                is_first_visit,
                exits,
                message_id,
            } => {
                if let Some(mid) = message_id {
                    self.in_flight_zone_queries.remove(&mid);
                }
                self.last_received_debug = Some(format!("zone_update({})", display_name));
                // ... rest unchanged
```

- [ ] **Step 8: Add RequeueZoneQuery and ZoneQueryAck handlers**

After the `IncomingMessage::RequeueEventFlag` arm (~line 1087):

```rust
            IncomingMessage::RequeueZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            } => {
                // Zone query was in the outgoing channel but never transmitted.
                // Ensure it stays in in_flight_zone_queries so it gets replayed
                // on reconnect (with the same message_id for server-side dedup).
                self.in_flight_zone_queries.entry(message_id).or_insert(
                    BufferedZoneQuery {
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                    },
                );
                info!(message_id, "[WS] Re-queued drained zone query");
            }
            IncomingMessage::ZoneQueryAck { message_id } => {
                if let Some(_) = self.in_flight_zone_queries.remove(&message_id) {
                    info!(message_id, "[WS] Zone query acknowledged (no zone_update)");
                } else {
                    warn!(message_id, "[WS] Ack for unknown zone query");
                }
            }
```

- [ ] **Step 9: Run tests**

Run: `cd mod && cargo test`
Expected: all tests pass

Run: `cd mod && cargo check --lib`
Expected: compiles cleanly

- [ ] **Step 10: Commit**

```bash
git add mod/src/dll/tracker.rs
git commit -m "feat: add in-flight tracking and requeue for zone_query"
```

---

## Task 4: Server schemas and helpers

**Files:**

- Modify: `server/speedfog_racing/websocket/schemas.py:223-233` (ZoneUpdateMessage)
- Modify: `server/speedfog_racing/websocket/schemas.py` (add ZoneQueryAckMessage)
- Modify: `server/speedfog_racing/websocket/common.py:206-242` (ZoneQueryInput, parse_zone_query_input)
- Modify: `server/speedfog_racing/websocket/common.py:132-157` (send_zone_update)
- Add: `send_zone_query_ack` to `server/speedfog_racing/websocket/common.py`

- [ ] **Step 1: Add message_id to ZoneUpdateMessage schema**

```python
class ZoneUpdateMessage(BaseModel):
    """Unicast zone update sent to originating mod."""

    type: Literal["zone_update"] = "zone_update"
    node_id: str
    display_name: str
    tier: int | None = None
    original_tier: int | None = None
    layer: int | None = None
    is_first_visit: bool = False
    exits: list[ExitInfo]
    message_id: int | None = None
```

- [ ] **Step 2: Add ZoneQueryAckMessage schema**

After `EventFlagAckMessage`:

```python
class ZoneQueryAckMessage(BaseModel):
    """Acknowledges a zone_query that could not produce a zone_update."""

    type: Literal["zone_query_ack"] = "zone_query_ack"
    message_id: int
```

- [ ] **Step 3: Add message_id to ZoneQueryInput**

```python
@dataclass
class ZoneQueryInput:
    """Parsed zone_query message fields."""

    grace_entity_id: int | None
    map_id: str | None
    position: tuple[Any, ...] | None
    play_region_id: int | None
    igt_ms: int | None
    message_id: int | None
```

- [ ] **Step 4: Extract message_id in parse_zone_query_input**

Add before the return statement (~line 234):

```python
    raw_message_id = msg.get("message_id")
    message_id = raw_message_id if isinstance(raw_message_id, int) else None
```

And update the return:

```python
    return ZoneQueryInput(
        grace_entity_id=grace_entity_id,
        map_id=map_id_str,
        position=position,
        play_region_id=play_region_id,
        igt_ms=igt_ms,
        message_id=message_id,
    )
```

- [ ] **Step 5: Add message_id parameter to send_zone_update**

```python
async def send_zone_update(
    websocket: WebSocket,
    node_id: str,
    graph_json: dict[str, Any],
    zone_history: list[dict[str, Any]] | None,
    locale: str = "en",
    *,
    is_first_visit: bool = False,
    send_timeout: float = SEND_TIMEOUT,
    race_id: object | None = None,
    participant_id: object | None = None,
    message_id: int | None = None,
) -> None:
    """Send a zone_update unicast to the originating mod."""
    msg = compute_zone_update(node_id, graph_json, zone_history, is_first_visit=is_first_visit)
    if msg:
        if message_id is not None:
            msg["message_id"] = message_id
        msg = translate_zone_update(msg, locale)
        try:
            await asyncio.wait_for(websocket.send_text(json.dumps(msg)), timeout=send_timeout)
        except Exception:
            logger.warning(
                "Failed to send zone_update: race=%s, participant=%s, node=%s",
                race_id,
                participant_id,
                node_id,
            )
```

- [ ] **Step 6: Add send_zone_query_ack helper**

After `send_event_flag_ack`:

```python
async def send_zone_query_ack(
    websocket: WebSocket, message_id: int, *, send_timeout: float = SEND_TIMEOUT
) -> None:
    """Acknowledge a zone_query that could not produce a zone_update."""
    try:
        await asyncio.wait_for(
            websocket.send_text(ZoneQueryAckMessage(message_id=message_id).model_dump_json()),
            timeout=send_timeout,
        )
    except Exception:
        pass
```

- [ ] **Step 7: Add import for ZoneQueryAckMessage in common.py**

Update the import block to include `ZoneQueryAckMessage`:

```python
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    ErrorMessage,
    EventFlagAckMessage,
    PingMessage,
    ZoneQueryAckMessage,
)
```

- [ ] **Step 8: Run type check and lint**

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`
Expected: passes

- [ ] **Step 9: Commit**

```bash
git add server/speedfog_racing/websocket/schemas.py server/speedfog_racing/websocket/common.py
git commit -m "feat: add message_id to zone_update schema and zone_query_ack helper"
```

---

## Task 5: Server handlers - dedup, store message_id, and ACK early returns (race mode)

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py:781-895` (handle_zone_query)

- [ ] **Step 1: Extract message_id from parsed input**

After `zq = parse_zone_query_input(msg)` and the None check, add:

```python
    message_id = zq.message_id if zq is not None else None
```

Wait, `zq` could be None and we return. So place `message_id = zq.message_id` after the None guard. But we also need `message_id` accessible in the early return paths that happen _before_ `parse_zone_query_input`. For the `zq is None` case, extract `message_id` from `msg` directly before the parse:

```python
    raw_message_id = msg.get("message_id")
    message_id: int | None = raw_message_id if isinstance(raw_message_id, int) else None

    zq = parse_zone_query_input(msg)
    if zq is None:
        if message_id is not None:
            await send_zone_query_ack(websocket, message_id)
        return
```

- [ ] **Step 2: Add zone_query_ack on each early return path that has a message_id**

For each early return (participant not found, race not RUNNING, countdown active, not PLAYING, no seed), add before `return`:

```python
        if message_id is not None:
            await send_zone_query_ack(websocket, message_id)
```

For the `resolve_zone_query returns None` path (~line 828):

```python
        if node_id is None:
            logger.debug(
                "zone_query: unresolved (grace=%s, map=%s) for race %s",
                zq.grace_entity_id,
                zq.map_id,
                participant.race_id,
            )
            if message_id is not None:
                await send_zone_query_ack(websocket, message_id)
            return
```

- [ ] **Step 3: Add dedup check for backtrack entries**

In the `if node_id != participant.current_zone:` block, after `old_history = participant.zone_history or []`, before the history cap check:

```python
            if message_id is not None and any(
                entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                # Already processed, skip to zone_update response
                pass
            elif len(old_history) >= MAX_ZONE_HISTORY:
```

This replaces the existing `if len(old_history) >= MAX_ZONE_HISTORY:` and the `else:` block. Full replacement of the block from line 847 to 865:

```python
        if node_id != participant.current_zone:
            logger.info(
                "zone_query backtrack: %s -> %s for participant %s",
                participant.current_zone,
                node_id,
                participant_id,
            )
            igt = zq.igt_ms if zq.igt_ms is not None else participant.igt_ms
            old_history = participant.zone_history or []

            if message_id is not None and any(
                entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                pass  # Dedup: already persisted, skip to zone_update
            elif len(old_history) >= MAX_ZONE_HISTORY:
                logger.warning("zone_history cap reached for participant %s", participant_id)
            else:
                is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)

                participant.last_igt_change_at = datetime.now(UTC)
                participant.igt_ms = igt
                new_entry: dict[str, Any] = {
                    "node_id": node_id,
                    "igt_ms": igt,
                    "type": "backtrack",
                }
                if message_id is not None:
                    new_entry["message_id"] = message_id
                participant.zone_history = [*old_history, new_entry]
                history_changed = True
```

- [ ] **Step 4: Pass message_id to send_zone_update**

```python
    await send_zone_update(
        websocket,
        node_id,
        graph_json,
        participant.zone_history,
        locale,
        is_first_visit=is_first_visit,
        race_id=participant.race_id,
        participant_id=participant_id,
        message_id=message_id,
    )
```

- [ ] **Step 5: Add send_zone_query_ack import**

Add `send_zone_query_ack` to the import from `common`:

```python
from speedfog_racing.websocket.common import (
    ...
    send_zone_query_ack,
    send_zone_update,
)
```

- [ ] **Step 6: Run tests**

Run: `cd server && uv run pytest tests/test_integration.py -v -x`
Expected: all existing tests pass

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/websocket/mod.py
git commit -m "feat: add message_id dedup and ACK to race zone_query handler"
```

---

## Task 6: Server handlers - dedup, store message_id, and ACK early returns (training mode)

**Files:**

- Modify: `server/speedfog_racing/websocket/training_mod.py:546-641` (\_handle_zone_query)

- [ ] **Step 1: Apply the same pattern as Task 5 to \_handle_zone_query**

Extract message_id from msg before parse, add `send_zone_query_ack` on early returns, add dedup, store in entry, pass to send_zone_update.

Before `zq = parse_zone_query_input(msg)` (~line 555):

```python
    raw_message_id = msg.get("message_id")
    message_id: int | None = raw_message_id if isinstance(raw_message_id, int) else None
```

After `if zq is None:`:

```python
    if zq is None:
        if message_id is not None:
            await send_zone_query_ack(websocket, message_id)
        return
```

For each early return (session not found/not ACTIVE, no zone_history, no seed, resolve returns None), add:

```python
        if message_id is not None:
            await send_zone_query_ack(websocket, message_id)
```

- [ ] **Step 2: Add dedup and store message_id in backtrack entry**

Replace the block starting at `old_history = session.zone_history or []` through the end of the backtrack logic:

```python
        if node_id != session.current_zone:
            logger.info(
                "zone_query backtrack: %s -> %s for training session %s",
                session.current_zone,
                node_id,
                session_id,
            )
            igt = zq.igt_ms if zq.igt_ms is not None else session.igt_ms
            old_history = session.zone_history or []

            if message_id is not None and any(
                entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                for entry in old_history
            ):
                pass  # Dedup: already persisted, skip to zone_update
            elif len(old_history) >= MAX_ZONE_HISTORY:
                logger.warning("zone_history cap reached for training session %s", session_id)
            else:
                is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)
                session.igt_ms = igt
                new_entry: dict[str, Any] = {
                    "node_id": node_id,
                    "igt_ms": igt,
                    "type": "backtrack",
                }
                if message_id is not None:
                    new_entry["message_id"] = message_id
                session.zone_history = [*old_history, new_entry]
                history_changed = True
```

- [ ] **Step 3: Pass message_id to send_zone_update**

```python
    await send_zone_update(
        websocket,
        node_id,
        graph_json,
        session.zone_history or [],
        locale,
        is_first_visit=is_first_visit,
        message_id=message_id,
    )
```

- [ ] **Step 4: Add send_zone_query_ack import**

```python
from speedfog_racing.websocket.common import (
    ...
    send_zone_query_ack,
    send_zone_update,
)
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_training.py -v -x`
Expected: all existing tests pass

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/training_mod.py
git commit -m "feat: add message_id dedup and ACK to training zone_query handler"
```

---

## Task 7: Test helper and integration test

**Files:**

- Modify: `server/tests/test_integration.py:88-106` (ModTestClient.send_zone_query)
- Modify: `server/tests/test_integration.py` (add test)

- [ ] **Step 1: Add message_id parameter to ModTestClient.send_zone_query**

```python
    def send_zone_query(
        self,
        grace_entity_id: int | None = None,
        *,
        map_id: str | None = None,
        position: list[float] | None = None,
        play_region_id: int | None = None,
        message_id: int | None = None,
    ) -> None:
        """Send zone query (loading screen exit)."""
        payload: dict[str, Any] = {"type": "zone_query"}
        if grace_entity_id is not None:
            payload["grace_entity_id"] = grace_entity_id
        if map_id is not None:
            payload["map_id"] = map_id
        if position is not None:
            payload["position"] = position
        if play_region_id is not None:
            payload["play_region_id"] = play_region_id
        if message_id is not None:
            payload["message_id"] = message_id
        self.ws.send_json(payload)
```

- [ ] **Step 2: Write integration test for zone_query message_id dedup**

Add after `test_event_flag_replay_same_message_id_is_idempotent`:

```python
def test_zone_query_replay_same_message_id_is_idempotent(
    integration_client, race_with_participants, integration_db
):
    """Replaying the same zone_query message_id must not append twice."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # First event_flag to move to node_a
        mod0.send_event_flag(9000000, igt_ms=10000, message_id=100)
        mod0.receive_until_type("event_flag_ack")
        mod0.receive_until_type("leaderboard_update")
        mod0.receive_until_type("zone_update")

        # Backtrack via zone_query to spawn (node_spawn exists in test graph)
        mod0.send_zone_query(
            grace_entity_id=10002950,
            message_id=200,
        )
        zu = mod0.receive_until_type("zone_update")
        assert zu.get("message_id") == 200

        # Replay same zone_query (simulating reconnect)
        mod0.send_zone_query(
            grace_entity_id=10002950,
            message_id=200,
        )
        zu2 = mod0.receive_until_type("zone_update")
        assert zu2.get("message_id") == 200

    async def check_history():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_history())
    assert history is not None
    # spawn entry + fog entry (node_a) + one backtrack = 3
    backtrack_entries = [e for e in history if e.get("type") == "backtrack"]
    assert len(backtrack_entries) == 1
    assert backtrack_entries[0]["message_id"] == 200
```

- [ ] **Step 3: Write test for zone_query_ack on unresolved query**

```python
def test_zone_query_unresolved_sends_ack_with_message_id(
    integration_client, race_with_participants
):
    """An unresolved zone_query with message_id should return zone_query_ack."""
    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive_until_type("leaderboard_update")

        # Send zone_query with unknown grace (won't resolve)
        mod0.send_zone_query(grace_entity_id=99999999, message_id=300)
        ack = mod0.receive_until_type("zone_query_ack")
        assert ack["message_id"] == 300
```

- [ ] **Step 4: Run tests**

Run: `cd server && uv run pytest tests/test_integration.py::test_zone_query_replay_same_message_id_is_idempotent tests/test_integration.py::test_zone_query_unresolved_sends_ack_with_message_id -v`
Expected: both pass

Run: `cd server && uv run pytest -v -x`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_integration.py
git commit -m "test: add zone_query message_id dedup and ack integration tests"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full mod test suite**

Run: `cd mod && cargo test`
Expected: all tests pass

- [ ] **Step 2: Run full server test suite**

Run: `cd server && uv run pytest -v`
Expected: all tests pass

- [ ] **Step 3: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`
Expected: all pass

Run: `cd mod && cargo check --lib`
Expected: compiles cleanly
