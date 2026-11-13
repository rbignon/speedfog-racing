# Item Spawner

How the racing mod injects gem (Ash of War) items into the player's inventory at runtime, and how it avoids re-spawning the same items on reconnect, save reload, or game restart. The same injection gives race item goods, with their own guard (see [Race Item Goods](#race-item-goods)).

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
    item_id: u32,    // type flag | id (GEM_TYPE_FLAG, or 0x40000000 for goods)
    qty: u32,        // 1
    dur: i32,        // -1
    gem: i32,        // -1
}
```

The signature is `extern "system" fn(*const c_void, *mut SpawnRequest, *mut u32, u32)`. `item_spawner::inject_one(encoded_id)` is the only call into it: it reads `MapItemMan` and injects a single unit, or returns false without calling when the function's or `MapItemMan`'s address is 0 or `MapItemMan` is null (player not in the game world). After a call it logs the word the function wrote to its output (`func_item_inject called`, with `encoded` and `output`), which nothing reads: a called function counts as an injection, and the log lets an in-game check tell what a given item and a refused one write there. The gem path calls it `qty` times, once per unit (the function may not respect `request.qty` reliably, single-unit calls match how the practice tool drives it).

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

## Race Item Goods

In a race with items (see `RACE_ITEMS.md`), `item_grant` names a catalog item, and the mod gives its goods through the same `inject_one` with the goods type flag (`race_items::spawn_goods`, `0x40000000 | goods_id`, one unit). None of the gem layers apply:

- **No fresh-save gate and no wait.** Grants arrive mid-race. The race machine holds a grant until the player is loaded on the race save (position readable, no wrong save, seed pack up to date), then the tracker spawns it on the main loop, not on a spawner thread.
- **The inventory is the guard.** Before spawning, the tracker reads how many of the goods the player holds (`race_items::goods_quantity`). Goods already held skip the spawn: that is a game restart, where the server sends again a grant it never saw acknowledged. Within one process, the machine also remembers the grants whose goods reached the inventory and only acknowledges one sent again.
- **`item_received` and the banner follow a spawn or goods already held.** The tracker hands the outcome back to the machine (`grant_spawn_result`); only then is the grant handled and its gold banner shown. A spawn that injected nothing (`MapItemMan` null, or its address unknown for this game version) or an unreadable inventory sends nothing and is logged: the grant waits for the next game load or reconnection and is tried again then, not on every frame. Meanwhile the server's copy of the grant, sent again at the next auth, finds it waiting and is neither acknowledged nor queued twice.
- **Prewarm.** At the `auth_ok` of a race with items, the tracker resolves the SpEffect apply function (`sp_effect_apply::prewarm`, a pattern scan of the whole game image) and indexes the game's params (`race_items::prewarm_params`, for the Hammer's equip load) on background threads, once per process, so the first item effect does not pay either on the render thread.

### Reading the inventory

`goods_quantity` follows `GameDataMan -> +0x8 (PlayerGameData)`, then reads the head of the held inventory's `InventoryItemsData`, inline at PlayerGameData + 0x410:

| Offset | Field                       |
| ------ | --------------------------- |
| +0x04  | normal items capacity (u32) |
| +0x08  | normal items list (pointer) |
| +0x10  | normal items in use (u32)   |
| +0x14  | key items capacity (u32)    |
| +0x18  | key items list (pointer)    |
| +0x20  | key items in use (u32)      |

Each list is an array of 0x18-byte entries: item id (type flag | param id) at +0x4, quantity at +0x8. The tracker copies a list's whole capacity out in one read (a removed item leaves a gap, so items need not sit below the in-use count) and sums the quantity of the matching entries (`core::item_inventory`), over both lists. A null pointer, or a header that no longer looks like this layout (nothing allocated, more in use than allocated, or more than 0x2000 entries), makes the read `None` rather than a guess: zeroed memory must not pass for an empty inventory, which a report would turn into every item lost. Both lists empty make it `None` too: a loaded character always holds its flasks, so those are lists allocated but not filled yet. Every read logs the two headers (capacity and in-use count of each list), at info level, for the in-game check of this layout. The storage chest is not read: goods put in the chest count as not held. The offsets come from fromsoftware-rs `cs/player_game_data.rs` and agree with the TGA Cheat Engine table v1.17.0 inventory script; this mod has not verified them in game yet.

The `item_inventory` report, sent once per game load and once per reconnection, reads the inventory once (`race_items::HeldInventory`) and lists the catalog keys whose goods are held. An unreadable inventory skips the report (logged), since a partial or empty one would read as items lost.

## Failure Modes

| Symptom                                                | Cause                                                                            | Recovery                                                                                 |
| ------------------------------------------------------ | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `func_item_inject not available for this game version` | `base_addresses.func_item_inject == 0` for current ER build.                     | Update `libeldenring` base addresses.                                                    |
| `Stale save detected (IGT too high), waiting...`       | Player loaded an existing save instead of New Game.                              | Self-heals on quit-to-title + New Game.                                                  |
| `Items already spawned (flag set), skipping`           | Re-running on the same save where items were already given.                      | Expected; not an error.                                                                  |
| `MapItemMan became null after delay`                   | Player quit during the 2 s init wait.                                            | Race condition; next `auth_ok` retries the spawn.                                        |
| `Cannot read items-spawned flag, proceeding anyway`    | Flag memory unreadable mid-loading-screen.                                       | Layers 1 + 2 still protect against duplicate.                                            |
| `Item unit not injected`                               | Gems: `MapItemMan` became null between units (player quit).                      | Logged; the gem guards still mark the items given, so the missing units are not retried. |
| `[ITEMS] Goods spawn failed`                           | Race goods: `func_item_inject` unknown or `MapItemMan` null.                     | Grant tried again at the next load or reconnection.                                      |
| `[ITEMS] Inventory unreadable, spawn skipped`          | Race goods: inventory pointer null, list header implausible or both lists empty. | Grant tried again at the next load or reconnection; check the inventory offsets.         |
| `[ITEMS] Inventory unreadable, report skipped`         | Same, at a game load or reconnection.                                            | No report this time; the next load or reconnection sends one.                            |
| `[ITEMS] Goods already held, spawn skipped`            | A game restart: the server sent again a grant it never saw acknowledged.         | Expected; `item_received` sent.                                                          |

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
