# Equipped Weapons Tracking

How the mod reads the player's currently-equipped weapons from Elden Ring's memory and how the server filters, persists and exposes them per zone.

## Overview

At each periodic `status_update` (1 Hz, see `mod/src/dll/tracker.rs`), the mod reads the active loadout slot of each hand and the weapon ID stored in that slot, sending the pair as `weapons: [Option<i32>; 2]` on the WebSocket. The server resolves each ID against a static catalogue, drops weapons whose `wep_type` is in the excluded set (staves, seals, shields, torches), and writes the surviving raw IDs onto the participant's current `zone_history` entry under the `weapons` key.

Storage uses raw runtime IDs (`param_row_id + upgrade_level`, e.g. `2000025` = Longsword +25). The catalogue maps the base param row to a name and a type at read time, which keeps the database resilient to renames and language changes.

The field is intentionally per-zone with last-write-wins semantics: only weapon swaps the player keeps long enough to outlive the rest of their stay in the zone end up persisted. A tick that resolves to `[None, None]` after filtering is skipped, not written, so loading screens and stretches where the player only holds filtered types do not overwrite earlier meaningful captures.

## Mod-side: ChrAsm memory layout

The currently-equipped weapons live in the `ChrAsm` sub-structure of `PlayerGameData`, reached through `GameDataMan -> +0x8 (PlayerGameData)`. `GameDataMan.Base` is stable from patch 2.4.0 through current 2.6.1.

The v5.0 Hexinton CE table is the only public layout source for ChrAsm, but it is incorrect on patch 2.6.1. Two issues:

1. **Layout shift.** CE lists five accessory slots starting at `0x388` and then begins the weapon block at `0x39C`. In 2.6.1 there are only four accessory slots (`0x388..0x394`), and the weapon block begins one slot earlier at `0x398`. Every field in CE is therefore four bytes too late in memory.
2. **Hand label inversion.** CE labels these fields "Left/Right" matching the equipment screen's columns, where the _left_ column displays the _right_ hand's equipment. The constants below use in-game hand semantics.

Verified by equipping known weapons in each loadout slot of each hand on 2.6.1 and matching the in-memory values against ground truth.

All offsets are relative to the `PlayerGameData` pointer (the second hop):

| Offset  | Type | Field                                                 |
| ------- | ---- | ----------------------------------------------------- |
| `0x328` | i32  | LEFT slot offset (0=Primary, 1=Secondary, 2=Tertiary) |
| `0x32C` | i32  | RIGHT slot offset                                     |
| `0x398` | i32  | LEFT primary weapon ID                                |
| `0x39C` | i32  | RIGHT primary weapon ID                               |
| `0x3A0` | i32  | LEFT secondary                                        |
| `0x3A4` | i32  | RIGHT secondary                                       |
| `0x3A8` | i32  | LEFT tertiary                                         |
| `0x3AC` | i32  | RIGHT tertiary                                        |

Reads use `libeldenring::memedit::PointerChain::<i32>::new(&[game_data_man, 0x8, <offset>])`, matching the existing pattern used for player stats (`pointer_chain!(game_data_man, 0x8, 0x3C)` for Vigor, etc.).

### Runtime weapon ID encoding

`EquipParamWeapon` rows are pre-spaced so that the upgrade level fits in the low two digits of the row ID: a Longsword +0 reads as `2000000`, +25 as `2000025`, Mace +0 as `11000000`. Each affinity variant is its own row (Heavy Longsword, Keen Longsword, etc.), so an affinity change shows up as a different base ID rather than a flag overlay.

Three sentinel values map to `None`:

- `110000`: Unarmed (the game writes this in any hand without an equipped weapon).
- `0` and `-1`: unset / transient state during weapon swaps. Defensive.

### `read_equipped_weapons`

Defined on `GameState` (`mod/src/eldenring/game_state.rs`). For each hand:

1. Read the per-hand slot offset (`i32` in `[0..3)`). If the chain is unreadable, the hand resolves to `None`.
2. Index into the per-hand `[PointerChain<i32>; 3]` array at that slot, read the `i32`. Out-of-range slot, non-positive value, or the Unarmed sentinel resolve to `None`.
3. Otherwise return the raw `i32` with the upgrade-level suffix preserved.

The function is called once per `status_update`, not per frame, so it does not need a `FrameSnapshot` slot. The chains themselves are constructed once in `GameState::new`.

In the `status_update` branch in `tracker.rs`, `read_equipped_weapons` is skipped in favour of `[None, None]` when `is_in_loading_screen()` reports `Some(true)`: during loading screens ChrAsm may hold stale or in-flight values.

### Two-handing (not detected)

The byte at `0x328` that CE labels "ArmStyle" is in fact the LEFT slot offset (the layout-shift issue again); the actual ArmStyle field has not been located on 2.6.1. Without it the mod cannot tell when the player is two-handing one of their weapons, and the inactive hand is over-reported. In practice the off-hand during two-handing typically holds a shield, staff or seal: all are stripped by the server's `wep_type` filter, so the over-report rarely reaches the database. Revisit if a UX requirement later demands accuracy.

## Wire format

The mod's `ClientMessage::StatusUpdate` carries the field, the server consumes it via `StatusUpdateMessage`:

```json
{
  "type": "status_update",
  "igt_ms": 123456,
  "death_count": 5,
  "weapons": [null, 2000025]
}
```

`weapons[0]` is the LEFT hand, `weapons[1]` is the RIGHT hand. The field is optional; older mod builds that predate the feature simply omit it.

`zone_history` entries grow an optional `weapons` key with the same shape:

```json
{
  "node_id": "stormveil_godrick",
  "igt_ms": 234567,
  "weapons": [null, 2000025]
}
```

Entries that pre-date the feature, or zones the player stayed in without ever wielding a tracked weapon, simply have no `weapons` key. Readers should treat the key's absence as "unknown".

## Server-side

### Lookup catalogue

`server/data/weapons.csv` is the static name/type table, sourced from TarnishedTool's `Properties/Resources.resx` (the `Weapons` block). One row per affinity variant:

```
id,name,wep_type,gem_mount_type,upgrade_type
3070000,Alabaster Lord's Sword,5,0,1
33200000,Academy Glintstone Staff,57,2,0
```

`id` is the base `EquipParamWeapon` row ID; the runtime ID at any upgrade is `id + upgrade_level`. 478 rows at time of writing.

`speedfog_racing/services/weapons.py` loads the CSV at import time into a frozen `dict[int, WeaponInfo]` keyed by base id. The trailing two columns (`gem_mount_type`, `upgrade_type`) are ignored: not needed for tracking.

### Excluded types

Weapons whose `wep_type` is in this set are dropped (the field never reaches `zone_history`):

| Value | Category         |
| ----- | ---------------- |
| 57    | Staff            |
| 61    | Sacred Seal      |
| 65    | Small Shield     |
| 67    | Medium Shield    |
| 69    | Greatshield      |
| 87    | Torch            |
| 90    | Thrusting Shield |

Ammo `wep_type` values (81 Arrow, 83 Greatarrow, 85 Bolt, 86 BallistaBolt) are absent from the CSV: arrows and bolts live in dedicated ChrAsm slots that the mod does not read, so they cannot reach the filter and there is no need to list them explicitly.

### Filter

`filter_equipped(raw_id)` in `services/weapons.py`:

1. Strips the upgrade suffix via `base_id = raw_id - (raw_id % 100)`.
2. Looks up `base_id` in the catalogue.
3. Returns the raw id (upgrade preserved) if found and `wep_type` is tracked, otherwise `None`. Also returns `None` for `None`, `0`, negative values.

### Handler write

`_handle_status_update` in `websocket/handler.py`:

```python
raw_weapons = msg.get("weapons")
if isinstance(raw_weapons, list) and len(raw_weapons) == 2 and entity.zone_history:
    left = filter_equipped(raw_weapons[0] if isinstance(raw_weapons[0], int) else None)
    right = filter_equipped(raw_weapons[1] if isinstance(raw_weapons[1], int) else None)
    if left is not None or right is not None:
        new_history = [dict(e) for e in entity.zone_history]
        new_history[-1]["weapons"] = [left, right]
        entity.zone_history = new_history
        history_changed = True
```

The skip on `(None, None)` is load-bearing. The mod sends that payload during loading screens, the filter produces it whenever every slot holds an excluded type, and ChrAsm reads can fail transiently. Treating any of these as a write would erase the last meaningful weapons captured for the current zone. Semantically the field stores "last tracked weapons observed in this zone", not "weapons at the last tick".

The `[dict(e) for e in entity.zone_history]` copy is the same pattern used by `attribute_deaths` (`handler.py:586`) to force SQLAlchemy to detect the JSON column mutation.

The write only happens after `entity.zone_history` is non-empty, which is guaranteed once the start-node bootstrap has run earlier in `_handle_status_update`.

## Refreshing the catalogue on a patch

When a patch adds new weapons (typically a DLC), the catalogue needs a refresh. The procedure:

1. Pull the latest `Weapons` block from upstream TarnishedTool's `Properties/Resources.resx`. The block is a `<data name="Weapons">` element containing the CSV inline.
2. Replace `server/data/weapons.csv` with the new content. Preserve the leading header comment lines.
3. If new `wep_type` values appear and any should be excluded (a new shield type, etc.), update `EXCLUDED_WEP_TYPES` in `services/weapons.py` and add a row in the [Excluded types](#excluded-types) table above.
4. Run `tests/test_weapons.py`. The `test_filter_rejects_shield_and_torch` test enumerates every excluded `wep_type` against the CSV and fails if a category becomes unrepresented in the snapshot.

No code change is needed for new weapons in already-tracked categories: they are picked up automatically.
