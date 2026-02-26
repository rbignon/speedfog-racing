# WebSocket Connection Lifecycle

Detailed connection management for mod and spectator WebSocket connections.

## Architecture Overview

```
Game (DLL)                        Server (FastAPI)              Browser
┌──────────┐   OS thread     ┌──────────────────────┐     ┌──────────┐
│ Tracker  │◄──crossbeam───►│ /ws/mod/{race_id}     │     │ Spectator│
│ (main)   │   channels      │   handle_mod_ws()     │     │ /ws/race │
│          │                 │                        │     │ /{id}/   │
│ GameState│                 │ ConnectionManager      │◄───►│ spectate │
│ EventFlag│                 │   rooms[race_id]       │     └──────────┘
│ Reader   │                 │     .mods{}            │
└──────────┘                 │     .spectators[]      │
                              └──────────────────────┘
```

## Mod Connection (Server Side)

### Connection Flow

```
Client connects
       │
       ▼
  accept TCP
       │
       ▼
  wait 5s for auth ──timeout──→ close(4001)
       │
       ▼
  authenticate_mod()
       │
       ├──invalid token──→ send auth_error + close(4003)
       ├──race finished──→ send auth_error + close(4003)
       ├──already connected──→ send auth_error + close(4003)
       │
       ▼
  send auth_ok
       │
       ▼
  send zone_update (if race RUNNING, reconnect)
       │
       ▼
  register in ConnectionManager
       │
       ▼
  broadcast leaderboard_update
       │
       ▼
  start heartbeat_loop (background task)
       │
       ▼
  enter message loop ◄───────────────────┐
       │                                  │
       ▼                                  │
  receive_text() ─────── message ─────────┘
       │
       ▼ (disconnect)
  cancel heartbeat
       │
       ▼
  disconnect_mod()
       │
       ▼
  broadcast leaderboard_update
```

### Key Mechanisms

**Auth timeout (5s)**: The server waits up to `MOD_AUTH_TIMEOUT = 5.0s` for the first `auth` message. Prevents connections that connect but never authenticate from occupying resources.

**Duplicate connection guard**: `manager.is_mod_connected(race_id, participant_id)` is checked during auth. A second connection for the same participant is rejected with code 4003. This prevents split-brain when the mod reconnects before the server detects the old connection's disconnect.

**Per-message DB sessions**: Each message handler (`handle_ready`, `handle_status_update`, `handle_event_flag`, `handle_zone_query`, `handle_finished`) opens its own `async with session_maker() as db:` block. Objects are loaded with `selectinload` for eager access. After commit, detached objects remain readable thanks to `expire_on_commit=False`. Broadcasts use these detached objects — no additional DB round-trip needed.

**Heartbeat**: A background asyncio task sends `ping` every 30s with a 5s send timeout. If the send fails (client dead), the heartbeat closes the WebSocket, which causes `receive_text()` in the main loop to raise `WebSocketDisconnect`.

**Blocked statuses**: All message handlers silently drop messages from participants in `FINISHED` or `ABANDONED` status. Additionally, `status_update` and `event_flag` send an `error` message if the race is not `RUNNING`.

---

## Mod Connection (Client Side)

### Thread Architecture

The mod runs WebSocket I/O in a dedicated OS thread. The main game thread (which also drives ImGui rendering) communicates via two bounded crossbeam channels (capacity 128 each):

```
Main thread (game loop)          WS thread
       │                              │
       ├──OutgoingMessage──►channel──►│  (Ready, StatusUpdate, EventFlag, ZoneQuery)
       │                              │
       │◄──channel◄──IncomingMessage──┤  (AuthOk, RaceStart, LeaderboardUpdate, ...)
       │                              │
```

### Reconnection Logic

```
           connect_and_auth()
                  │
          ┌───success───┐───failure───┐
          │              │             │
          ▼              │             ▼
    drain outgoing       │       log error
    channel              │             │
          │              │             ▼
          ▼              │       sleep(delay)
    StatusChanged        │       delay *= 2
    (Connected)          │       cap at 30s
          │              │             │
          ▼              │             └──→ retry
    message_loop()       │
          │              │
          ▼ (error)      │
    StatusChanged        │
    (Reconnecting)       │
          │              │
          └──────────────┘
```

**Exponential backoff**: 1s → 2s → 4s → ... → 30s cap. Reset to 1s on successful connection.

**Channel drain on reconnect**: Before sending `StatusChanged(Connected)`, the WS thread drains all pending outgoing messages:

- `EventFlag` messages are sent back as `RequeueEventFlag` to the tracker, which re-buffers them in `pending_event_flags`.
- `Shutdown` causes the thread to exit.
- All other messages (`StatusUpdate`, `Ready`, `ZoneQuery`) are silently discarded (stale data from before disconnect).

**Safety-net rescan on reconnect**: After reconnection and `ready`, the tracker re-scans all `event_ids` against live game memory. This catches flags that were set during the disconnection window and weren't captured by polling.

**Ping timeout**: The message loop monitors server pings. If no `ping` arrives within 60s, the loop exits and triggers reconnect.

**Non-blocking I/O**: The socket is set to non-blocking mode. The message loop polls both outgoing (crossbeam `try_recv`) and incoming (tungstenite `read`) in a tight loop with a 10ms sleep, avoiding blocking on either direction.

### Reconnect State Preservation

On `StatusChanged(Reconnecting)`:

- `deferred_event_flags` are moved to `pending_event_flags` (they were waiting for loading exit, now they need to wait for reconnection too).

On `StatusChanged(Connected)`:

- `ready_sent = false` → `send_ready()` fires again.
- `pending_event_flags` are drained and sent.
- Safety-net rescan runs.
- `loading_exit_time` is set to `Instant::now() - ZONE_REVEAL_DELAY` → any `zone_update` from the server is revealed immediately (no waiting for a loading cycle).

### Stale Seed Detection

`auth_ok.seed.seed_id` is compared against the config file's `seed_id`. A mismatch (organizer rerolled the seed after the player downloaded their pack) displays a red "SEED OUTDATED" banner.

---

## Spectator Connection

### Connection Flow

```
Client connects
       │
       ▼
  accept TCP
       │
       ▼
  wait 2s for optional auth
       │
       ├──auth received──→ set conn.user_id
       ├──timeout──→ anonymous (user_id=None)
       │
       ▼
  send race_state (per-connection graph gating)
       │
       ▼
  register in ConnectionManager
       │
       ▼
  start heartbeat_loop
       │
       ▼
  keep-alive loop (receive_text, discard)
       │
       ▼ (disconnect)
  cancel heartbeat + disconnect_spectator
```

### Auth Grace Period

Spectator connections wait `AUTH_GRACE_PERIOD = 2.0s` for an optional `auth` message. If received and valid, `conn.user_id` is set. This gates DAG visibility for SETUP races (only organizer/participants see the graph before the race starts). Anonymous connections always see the graph once the race is RUNNING.

### Per-Connection State

Each spectator connection carries:

- `user_id`: set from auth or None (anonymous)
- `locale`: initially from `?locale=` query param (default `"en"`), overridden by user's DB `locale` field if auth succeeds

`race_state` messages are sent individually per connection (not broadcast as a single shared message) because `graph_json` visibility and locale differ per viewer.

---

## ConnectionManager

### Room Structure

```python
rooms: dict[UUID, RaceRoom]

RaceRoom:
    mods: dict[UUID, ModConnection]         # participant_id → connection
    spectators: list[SpectatorConnection]    # ordered list
```

### Broadcast Safety

**Snapshot pattern**: Both `broadcast_to_mods()` and `broadcast_to_spectators()` take a snapshot (`dict(self.mods)` / `list(self.spectators)`) before the `asyncio.gather()`. This prevents index corruption if `connect_mod`/`disconnect_mod` modify the collection during the concurrent sends.

**Send timeout**: Each individual send is wrapped in `asyncio.wait_for(send, timeout=5.0s)`. Failed sends return the connection identity; the stale connection is then removed from the collection after the gather completes.

**Room cleanup**: Rooms are deleted from `self.rooms` when both `mods` and `spectators` are empty, preventing unbounded memory growth from abandoned races.

### Close Room

`close_room(race_id, code)` is called on race reset. It:

1. Removes the room from `self.rooms`.
2. Closes all mod and spectator WebSocket connections with the given code.
3. Mod clients detect the close and reconnect automatically.

---

## Constants Summary

| Constant             | Value | Location                  | Purpose                                     |
| -------------------- | ----- | ------------------------- | ------------------------------------------- |
| `MOD_AUTH_TIMEOUT`   | 5.0s  | `common.py`               | Max wait for mod auth message               |
| `AUTH_GRACE_PERIOD`  | 2.0s  | `spectator.py`            | Max wait for spectator optional auth        |
| `HEARTBEAT_INTERVAL` | 30.0s | `common.py`               | Server ping frequency                       |
| `SEND_TIMEOUT`       | 5.0s  | `common.py`, `manager.py` | Max time for a single send before failure   |
| Ping timeout (mod)   | 60s   | `websocket.rs`            | Client-side ping timeout before reconnect   |
| Reconnect min delay  | 1s    | `websocket.rs`            | Initial reconnect backoff                   |
| Reconnect max delay  | 30s   | `websocket.rs`            | Maximum reconnect backoff cap               |
| Channel capacity     | 128   | `websocket.rs`            | Crossbeam channel buffer for each direction |
| Message loop sleep   | 10ms  | `websocket.rs`            | Polling interval in non-blocking loop       |
