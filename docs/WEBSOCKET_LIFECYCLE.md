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
       ├──incompatible protocol / gated version──→ send auth_error + close(4003)
       ├──invalid token──→ send auth_error + close(4003)
       ├──race finished──→ send auth_error + close(4003)
       │
       ▼
  send auth_ok
       │
       ▼
  send zone_update (if race RUNNING, reconnect)
       │
       ▼
  register in ConnectionManager
  (replaces any stale connection for the
   same participant; old socket closed 4000)
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

**Version compatibility**: the auth message may carry `protocol_version` and `mod_version`. A protocol major mismatch (absent = assumed 1.0) or a release older than the optional `MIN_MOD_VERSION` setting is rejected with `auth_error` + close 4003 before any registration. Same-major, older-minor mods are accepted silently; minor lag never produces a user-facing notice (mods ship inside seed packs, so there is no update action to prompt for). The reported version is kept on the connection and shown in the admin activity feed.

**Connection replacement**: there is no duplicate-connection rejection; last writer wins. `manager.connect_mod()` registers the new connection and, if one already existed for the same participant (typically a ghost after a network drop), closes it with code 4000 ("replaced by new connection") so the old handler's receive loop exits. `disconnect_mod()` only removes the registry entry when it still refers to the disconnecting websocket, so the old handler's cleanup cannot evict the replacement. This handles mod reconnects that happen before the server notices the old connection is dead.

**Per-message DB sessions**: Each message handler (`handle_ready`, `handle_status_update`, `handle_event_flag`, `handle_zone_query`, `handle_finished`) opens its own `async with session_maker() as db:` block. Objects are loaded with `selectinload` for eager access. After commit, detached objects remain readable thanks to `expire_on_commit=False`. Broadcasts use these detached objects, no additional DB round-trip needed.

**Heartbeat**: A background asyncio task sends `ping` every 30s with a 5s send timeout. If the send fails (client dead), the heartbeat closes the WebSocket, which causes `receive_text()` in the main loop to raise `WebSocketDisconnect`.

**Blocked statuses**: `event_flag` and `zone_query` handlers require `participant.status == PLAYING`; messages from any other status (REGISTERED, READY, FINISHED, ABANDONED) are silently dropped. `status_update` and `event_flag` send an `error` message if the race is not `RUNNING`.

**Fresh save validation**: On the first `status_update` that would trigger READY to PLAYING, the server checks `igt_ms <= MAX_FRESH_IGT_MS` (60 000ms). If the IGT exceeds this threshold (player loaded a pre-existing save), the server sends an `error` message and the participant stays READY. The mod displays this via `set_status()`. The check is self-healing: starting a New Game resets the IGT and the next `status_update` succeeds. Each rejection logs at WARNING level. Training mode applies the same check on first `zone_history` initialization (empty history + high IGT), but allows session resumption (existing history bypasses the gate). An `igt_ms` that is missing, non-int, negative, or above `MAX_IGT_MS` (the `int4` column max, ~24.85 days) is also treated as a stale save at first init: the message is silently dropped and the participant stays READY, so a save with absurd IGT cannot bypass the gate by tripping `clamp_igt`.

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

**In-flight event flags**: Once an `EventFlag` has been written to the socket, the tracker keeps it in an in-flight map (keyed by `message_id`) until the server replies with `event_flag_ack`. On reconnect, in-flight events are replayed with their **original** `message_id` so the server can deduplicate them. Events that were queued in the outgoing channel but never transmitted are removed from the in-flight map and moved to `pending_event_flags` (the server never saw them, so they get a fresh `message_id` on resend).

**Server idempotence**: Newer mods attach a `message_id` to each `event_flag`. The server stores this `message_id` in the corresponding `zone_history` entry and treats replays with the same `message_id` as already committed. This prevents duplicate `zone_history` entries when the original commit succeeded but the ACK was lost. The server also ACKs event flags sent by participants who are already finished, so the mod can clear its in-flight set after a finish event whose ACK was lost.

**Safety-net rescan on reconnect**: After reconnection and `ready`, the tracker re-scans all `event_ids` against live game memory. This catches flags that were set during the disconnection window and weren't captured by polling.

**Ping timeout**: The message loop monitors server pings. If no `ping` arrives within 60s, the loop exits and triggers reconnect.

**Non-blocking I/O**: The socket is set to non-blocking mode. The message loop polls both outgoing (crossbeam `try_recv`) and incoming (tungstenite `read`) in a tight loop with a 10ms sleep, avoiding blocking on either direction.

### Reconnect State Preservation

On `StatusChanged(Reconnecting)`:

- `deferred_event_flags` are moved to `pending_event_flags` (they were waiting for loading exit, now they need to wait for reconnection too).
- In-flight `event_flag`s remain in the in-flight map (not moved to pending). They will be replayed with their original `message_id` on reconnect.

On `StatusChanged(Connected)`:

- `ready_sent = false` → `send_ready()` fires again.
- `pending_event_flags` are drained and sent.
- Safety-net rescan runs.
- Any `zone_update` from the server goes through the usual reveal logic: loading byte clear + position readable, with the 5s defensive timeout (see EVENT_FLAG_TRACKING.md). During an in-game reconnection both conditions already hold, so the reveal fires on the next frame; a reconnection from a menu or loading screen waits for the next loading exit.

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
  wait for auth or no_auth (2s timeout)
       │
       ├──auth received──→ set conn.user_id
       ├──no_auth received──→ anonymous (user_id=None)
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

Spectator connections wait `AUTH_GRACE_PERIOD = 2.0s` for an `auth` or `no_auth` message. If `auth` is received and valid, `conn.user_id` is set. If `no_auth` is received (or any non-auth message), the server proceeds immediately as anonymous. The timeout is a fallback for clients that send neither message. This gates DAG visibility for SETUP races (only organizer/participants see the graph before the race starts). Anonymous connections always see the graph once the race is RUNNING.

### Per-Connection State

Each spectator connection carries:

- `user_id`: set from auth or None (anonymous)
- `locale`: initially from `?locale=` query param (default `"en"`), overridden by user's DB `locale` field if auth succeeds
- `role`: race role for this user (`"organizer"`, `"admin"`, `"caster"`, `"participant"`, or `None`), resolved at auth via `services/chat_access.race_role`
- `participant_id`: set when `role == "participant"`
- `participant_status`: cached `ParticipantStatus` of the user in this race, used by the chat-access helpers to evaluate broadcasts without re-iterating `race.participants`. Set at auth, refreshed by `RaceRoom.set_participant_status` on race start (`mark_participants_playing`) and on per-user finish/abandon transitions, and lazily refreshed from DB inside `_handle_request_chat_history` for the public channel.

`race_state` messages are sent individually per connection (not broadcast as a single shared message) because `graph_json` visibility and locale differ per viewer.

### Chat Access

Chat send, history load, and per-message broadcast all flow through the same `services/chat_access` predicates (`can_read_participants_chat`, `can_read_public_chat`, `can_write_public_chat`) so the three paths cannot drift. The server is authoritative; the frontend mirrors the same matrix locally to drive its UI but cannot grant access the server denies.

Public-chat unlocks during a race (late-join window closing for a spectator, participant finishing or abandoning, race transitioning to FINISHED) are detected by the client from data it already receives: the registration deadline travels in `race_info`, participant status updates ride on `player_update`/`leaderboard_update`, and the race status flip rides on `race_status_change`. When the locally-computed access flips from locked to readable, the client sends a `request_chat_history` (see `docs/PROTOCOL.md`); the server revalidates and replies with a `chat_history` for the requested channel, or silently drops the request. No server-initiated push or scheduled task is involved, which keeps the lifecycle robust to server restart and avoids divergence between the broadcast filter and any out-of-band history-push code path.

The frontend mirror of the access matrix lives in `web/src/lib/public-chat-access.ts` (`computePublicAccess`, `computePublicLockedReason`); the locked-pane UX and the `showPublicOnly` Daily-Seeds variant live in `web/src/lib/components/ChatSidebar.svelte` and `web/src/lib/chat-sidebar-layout.ts`.

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

## Scaling

The `ConnectionManager` (`websocket/race/manager.py`, plus the parallel `websocket/training/manager.py` for training sessions) is a **single-process, in-memory singleton**. `manager.rooms: dict[uuid.UUID, RaceRoom]` holds every active connection for the entire server.

**Implications:**

- The server currently runs as a **single uvicorn worker**. Adding `--workers N` will break broadcasts: a status update arriving on worker A will only reach spectators whose WebSockets landed on worker A.
- Horizontal scaling (multiple server instances behind a load balancer) has the same constraint, amplified.
- In-process rate limits (`rate_limit.py`) have the same property.

**Path forward when horizontal scaling becomes necessary:**

1. Introduce Redis pub/sub. Connections stay local to each worker; broadcasts are published to a Redis channel keyed by `race_id`, and each worker subscribes and forwards to its local sockets.
2. Move rate limit state to a Redis-backed token bucket.
3. Keep the existing `ConnectionManager` API surface: the Redis layer sits between `broadcast_*` methods and the socket sends.

Not worth doing before the platform actually needs it: single-worker uvicorn can handle thousands of WebSocket connections, and we are nowhere near that.

---

## Constants Summary

| Constant             | Value | Location                                               | Purpose                                     |
| -------------------- | ----- | ------------------------------------------------------ | ------------------------------------------- |
| `MOD_AUTH_TIMEOUT`   | 5.0s  | `handler.py`                                           | Max wait for mod auth message               |
| `AUTH_GRACE_PERIOD`  | 2.0s  | `race/spectator.py`                                    | Max wait for spectator optional auth        |
| `HEARTBEAT_INTERVAL` | 30.0s | `handler.py`                                           | Server ping frequency                       |
| `SEND_TIMEOUT`       | 5.0s  | `handler.py`, `race/manager.py`, `training/manager.py` | Max time for a single send before failure   |
| Ping timeout (mod)   | 60s   | `websocket.rs`                                         | Client-side ping timeout before reconnect   |
| Reconnect min delay  | 1s    | `websocket.rs`                                         | Initial reconnect backoff                   |
| Reconnect max delay  | 30s   | `websocket.rs`                                         | Maximum reconnect backoff cap               |
| Channel capacity     | 128   | `websocket.rs`                                         | Crossbeam channel buffer for each direction |
| Message loop sleep   | 10ms  | `websocket.rs`                                         | Polling interval in non-blocking loop       |
