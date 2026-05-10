# Item Spawner

How the racing mod injects gem (Ash of War) items into the player's inventory at runtime, and how it avoids re-spawning the same items on reconnect, save reload, or game restart.

## Why a Runtime Spawner

Most fixed items in a SpeedFog seed are granted from EMEVD via `DirectlyGivePlayerItem`. That instruction does not support the `Gem` item type (Ash of War), so any AoW listed in the seed has to be injected from outside EMEVD.

The mod uses `func_item_inject`, the same internal Elden Ring function that the [ER practice tool](https://github.com/veeenu/eldenring-practice-tool) calls when spawning items. Reusing this function keeps inventory state consistent (the item shows up like a normal pickup, no soft-locks).

## Server Contract

Two pieces arrive in `auth_ok.seed` (see `core/protocol.rs`, server side `websocket/schemas.py::extract_spawn_items`):

| Field                | Type             | Meaning                                                          |
| -------------------- | ---------------- | ---------------------------------------------------------------- |
| `spawn_items`        | `Vec<SpawnItem>` | Items to give. Each is `{ id: u32, qty: u32 (default 1) }`.      |
| `items_spawned_flag` | `Option<u32>`    | Persistent event flag in the saved range. `None` on old servers. |

`id` is the raw EquipParamGem ID (e.g. `10500`). The mod ORs it with `0x80000000` (`GEM_TYPE_FLAG`) to encode the gem type before passing it to the game. Both `spawn_items` and `items_spawned_flag` are optional; missing fields disable spawning gracefully.

## Spawn Flow

`spawn_items_blocking()` runs on a dedicated thread spawned from `RaceTracker::handle_ws_message` when an `auth_ok` carries a non-empty `spawn_items`. It blocks until the items are injected (or the guard kicks in and short-circuits).

```
auth_ok with spawn_items
  │
  ├── items_spawned (in-process)? ─── true ──→ skip (reconnect)
  │
  ├── spawner thread already running? ──── true ──→ skip
  │
  └── spawn thread:
        wait for MapItemMan != null   (player loaded into world)
        sleep 2 s                     (let game finish init)
        ├── IGT > 15 s?               → wait for MapItemMan == null
        │                               (quit to title) and retry
        ├── items_spawned_flag set?   → return (game restart, already given)
        └── call func_item_inject for each (id, qty)
            store items_spawned = true
            set items_spawned_flag (if present)
```

## Calling `func_item_inject`

Resolved through `libeldenring::pointers::Pointers::base_addresses.func_item_inject`. If the address is 0 (game version not supported), the spawner logs and returns without injecting.

The function takes a `MapItemMan*` and a `SpawnRequest` with the layout the game expects:

```rust
#[repr(C)]
struct SpawnRequest {
    one: u32,        // 1
    item_id: u32,    // GEM_TYPE_FLAG | id
    qty: u32,        // 1
    dur: i32,        // -1
    gem: i32,        // -1
}
```

The signature is `extern "system" fn(*const c_void, *mut SpawnRequest, *mut u32, u32)`. We loop `qty` times and call once per unit (the function may not respect `request.qty` reliably, single-unit calls match how the practice tool drives it).

## Three-Layer Re-Spawn Prevention

The spawner can be invoked multiple times in a session: every reconnect carries a fresh `auth_ok`. To avoid duplicating items, three guards cooperate, each catching a scenario the others can't.

### Layer 1: In-Process AtomicBool

`RaceTracker.items_spawned: Arc<AtomicBool>` is the primary guard. It's set to `true` inside `spawn_items_blocking` **after** the items have actually been injected, and checked at the start of every `auth_ok` handler.

Covers: WebSocket reconnects within the same game process (the most common case).

### Layer 2: IGT Freshness Check

After the player is loaded (`MapItemMan != null`), the spawner reads `pointers.igt`. If it's already > 15 s, this is a stale save (an existing character continued from disk), not a fresh New Game.

In that case the spawner **does not return**. It loops back: it waits for `MapItemMan` to become null again (player quit to title) and retries on the next game load. This handles the case where the player loads an old save first, gets bounced, then starts a fresh New Game without the WS connection ever dropping (which would otherwise never re-trigger spawning via `auth_ok`).

`MAX_FRESH_IGT_MS = 15_000` is the spawner's local threshold. The server-side constant in `speedfog_racing/websocket/handler.py` is `60_000` (60 s): the server gate must tolerate a transient network loss between the player starting a New Game and the first `status_update` reaching the backend, so it allows up to a minute of IGT drift. The mod check fires at game-load time and does not depend on the network, so it stays conservative. A fresh New Game reaches the first load screen at roughly 3-5 s IGT, well under both thresholds.

Covers: player picks the wrong save slot or loads a previous run.

### Layer 3: Persistent Event Flag

`items_spawned_flag` is an event flag in the saved range. SpeedFog allocates it from a persistent category dedicated to anti-replay flags (`PERSISTENT_FLAG_BASE = 1050290000` in `speedfog/output.py`, distinct from the zone-tracking category `1050294` documented in [EVENT_FLAG_TRACKING.md](EVENT_FLAG_TRACKING.md#category-1050294)). The flag ID is shipped in the seed at generation time, surfaced via `auth_ok.seed.items_spawned_flag`.

Before injecting, the spawner reads the flag through `EventFlagReader::is_flag_set`:

- `Some(true)` → items already given in a previous session, return.
- `Some(false)` → proceed.
- `None` → memory not readable (loading screen edge case), proceed anyway and rely on layers 1 + 2.

After injecting, the flag is set via `EventFlagReader::set_flag(flag_id, true)`. Because it's saved, it persists across game restarts and process kills.

Covers: full game restart on the same save (kill the process, reopen, reconnect).

### Why All Three

- Layer 1 alone misses game restarts (the AtomicBool is in-process).
- Layer 3 alone can race during the brief window between game load and the flag being set: the player could in theory reconnect twice in that window. Layer 1 closes that gap.
- Layer 2 alone is too coarse: it only distinguishes fresh saves from stale ones, not "already given" from "not yet given".

Together they cover reconnects, wrong-save selections, and process restarts without ever double-giving an item.

## Failure Modes

| Symptom                                                | Cause                                                        | Recovery                                          |
| ------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------- |
| `func_item_inject not available for this game version` | `base_addresses.func_item_inject == 0` for current ER build. | Update `libeldenring` base addresses.             |
| `Stale save detected (IGT too high), waiting...`       | Player loaded an existing save instead of New Game.          | Self-heals on quit-to-title + New Game.           |
| `Items already spawned (flag set), skipping`           | Re-running on the same save where items were already given.  | Expected; not an error.                           |
| `MapItemMan became null after delay`                   | Player quit during the 2 s init wait.                        | Race condition; next `auth_ok` retries the spawn. |
| `Cannot read items-spawned flag, proceeding anyway`    | Flag memory unreadable mid-loading-screen.                   | Layers 1 + 2 still protect against duplicate.     |

## Logging

Spawner log lines are prefixed by `[RACE]` for the dispatcher (in `tracker.rs`) and unprefixed for the spawn thread itself. A successful run prints:

```text
INFO [RACE] Spawning runtime items count=2 item_ids=[10500, 16300]
INFO Waiting to spawn items... count=2
INFO Spawned item id=10500 qty=1 encoded=0x80002904
INFO Items-spawned flag set flag=1050290000
INFO All items spawned count=2
```

A reconnect skip prints:

```text
INFO [RACE] Items already spawned this session, skipping count=2
```
