# Equipped Weapons Tracking

How the mod reads the player's currently-equipped weapons from Elden Ring's memory and how the server filters, persists and exposes them per zone.

## Overview

At each periodic `status_update` (1 Hz, see `mod/src/dll/tracker.rs`), the mod reads the active loadout slot of each hand and the weapon ID stored in that slot, sending the pair as `weapons: [Option<i32>; 2]` on the WebSocket. The server resolves each ID against a static catalogue, drops weapons whose `wep_type` is in the excluded set (staves, seals, shields, torches), and counts how many ticks each unique combo is held.

Storage uses raw runtime IDs (`param_row_id + affinity * 100 + upgrade_level`, e.g. `2000025` = Longsword +25, `23150925` = Rotten Greataxe Cold +25). The catalogue maps the base param row to a name and a type at read time, which keeps the database resilient to renames and language changes.

The field is per-zone, with storage as a list of per-tick combo counters. Each tick-update normalizes the equipped weapons into a canonical combo key (see "Canonicalisation" below), then either increments that combo's tick counter or appends a new entry. A tick that resolves to `[None, None]` after filtering is skipped, not written, so loading screens and stretches where the player only holds filtered types do not reset the accumulation for earlier observed combos.

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

`EquipParamWeapon` rows are pre-spaced on multiples of 1000. The low three digits of a runtime id encode two distinct things: the affinity in the hundreds digit (0 Standard, 1 Heavy, 2 Keen, 3 Quality, 4 Fire, 5 Flame Art, 6 Lightning, 7 Sacred, 8 Magic, 9 Cold, A Poison, B Blood, C Occult), and the upgrade level in the tens and units (0..25). A Cold Rotten Greataxe +25 reads as `23150925` = `23150000` (base row) + `9 * 100` (Cold affinity) + `25` (upgrade level).

Catalogue resolution strips the low three digits to recover the base row. The runtime id including affinity and upgrade is preserved both on the wire and in storage, so two combos differing only by affinity remain distinct in the per-zone counter.

Three sentinel values map to `None` during filtering:

- `110000`: Unarmed (the game writes this in any hand without an equipped weapon).
- `0` and `-1`: unset / transient state during weapon swaps. Defensive.

### `read_equipped_weapons`

Defined on `GameState` (`mod/src/eldenring/game_state.rs`). For each hand:

1. Read the per-hand slot offset (`i32` in `[0..3)`). If the chain is unreadable, the hand resolves to `None`.
2. Index into the per-hand `[PointerChain<i32>; 3]` array at that slot, read the `i32`. Out-of-range slot, non-positive value, or the Unarmed sentinel resolve to `None`.
3. Otherwise return the raw `i32` with affinity and upgrade level preserved.

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

`zone_history` entries grow an optional `weapons` key containing a list of per-tick combo counters:

```json
{
  "node_id": "stormveil_godrick",
  "igt_ms": 234567,
  "weapons": [
    { "ids": [2000025], "ticks": 18 },
    { "ids": [3070000, 2000025], "ticks": 5 }
  ]
}
```

Each entry in the `weapons` list is a combo counter with `ids` (the canonical weapon list) and `ticks` (count of update ticks held in this zone). The list is ordered by first observation.

Entries that pre-date the feature, or zones the player stayed in without ever wielding a tracked weapon, simply have no `weapons` key. Readers should treat the key's absence as "unknown".

### Aggregation by base weapon id

Aggregation across zones and across participants merges combos by their base row id: each id is stripped via `% 1000` (affinity and upgrade-level digits) when computing the aggregation key. Storage stays raw, so a future feature that wants to expose affinity or upgrade can read it from `zone_history.weapons` directly.

### Canonicalisation

The `ids` key normalizes the observed left and right hands into a canonical form (Option B from the design spec):

- **Single weapon:** if only one of left or right is a tracked ID, the key is `[X]` (a single-element list). Both `(None, X)` and `(X, None)` increment the same single-weapon counter, as hand information is intentionally dropped.
- **Dual wield:** if both are tracked IDs, the key is `[left, right]` in mod-reported order (left, right). The combo `[X, Y]` is distinct from `[Y, X]`, preserving laterality for dual-wield weapon pairs.
- **No tracked weapons:** a tick with `(None, None)` after filtering produces no write (the combo counter is not incremented and no new entry is created).

## Server-side

### Lookup catalogue

`server/data/weapons.json` is the static name/type table, sourced from TarnishedTool's `Properties/Resources.resx` (the `Weapons` block). Keyed by base `EquipParamWeapon` row ID:

```json
{
  "3070000": { "name": "Alabaster Lord's Sword", "wep_type": 5 },
  "33200000": { "name": "Academy Glintstone Staff", "wep_type": 57 }
}
```

The runtime ID at any affinity and upgrade is `base_id + affinity * 100 + upgrade_level`. 478 rows at time of writing.

`speedfog_racing/services/weapons.py` loads the JSON at import time into a frozen `dict[int, WeaponInfo]` keyed by base id.

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

Ammo `wep_type` values (81 Arrow, 83 Greatarrow, 85 Bolt, 86 BallistaBolt) are absent from the JSON catalogue: arrows and bolts live in dedicated ChrAsm slots that the mod does not read, so they cannot reach the filter and there is no need to list them explicitly.

### Filter

`filter_equipped(raw_id)` in `services/weapons.py`:

1. Strips the low three digits (affinity and upgrade) via `base_id = raw_id - (raw_id % 1000)`.
2. Looks up `base_id` in the catalogue.
3. Returns the raw id (affinity and upgrade preserved) if found and `wep_type` is tracked, otherwise `None`. Also returns `None` for `None`, `0`, negative values.

### Handler write

`_handle_status_update` in `websocket/handler.py` processes each incoming weapons pair:

```python
raw_weapons = msg.get("weapons")
if isinstance(raw_weapons, list) and len(raw_weapons) == 2 and entity.zone_history:
    left = filter_equipped(raw_weapons[0] if isinstance(raw_weapons[0], int) else None)
    right = filter_equipped(raw_weapons[1] if isinstance(raw_weapons[1], int) else None)
    if left is not None or right is not None:
        current = entity.zone_history[-1].get("weapons", []) or []
        new_weapons = bump_combo(current, left, right)
        new_history = [dict(e) for e in entity.zone_history]
        new_history[-1]["weapons"] = new_weapons
        entity.zone_history = new_history
        history_changed = True
```

The skip on `(None, None)` is load-bearing. The mod sends that payload during loading screens, the filter produces it whenever every slot holds an excluded type, and ChrAsm reads can fail transiently. Skipping the write preserves the accumulated tick counter for any previously-observed combo in the current zone. Semantically the field stores "combos observed and duration-spent-holding each", not "weapons at the current tick".

The `bump_combo` helper (in `services/weapons.py`) handles the canonicalisation and counter increment: it finds the matching combo in the current list (by its canonical `ids` key), increments its `ticks` counter, or appends a new entry if the combo is new.

The `[dict(e) for e in entity.zone_history]` copy is the same pattern used by `attribute_deaths` (`handler.py:586`) to force SQLAlchemy to detect the JSON column mutation.

The write only happens after `entity.zone_history` is non-empty, which is guaranteed once the start-node bootstrap has run earlier in `_handle_status_update`.

## Refreshing the catalogue on a patch

When a patch adds new weapons (typically a DLC), the catalogue needs a refresh. The procedure:

1. Pull the latest `Weapons` block from upstream TarnishedTool's `Properties/Resources.resx`. The block is a `<data name="Weapons">` element containing the CSV inline.

2. Run a Python script to parse the CSV and emit JSON. A minimal conversion script:

   ```python
   import csv
   import json

   with open('weapons.csv', 'r') as f:
       reader = csv.DictReader(f)
       weapons = {}
       for row in reader:
           weapons[row['id']] = {
               'name': row['name'],
               'wep_type': int(row['wep_type'])
           }

   with open('server/data/weapons.json', 'w') as f:
       json.dump(weapons, f, indent=2)
   ```

3. If new `wep_type` values appear and any should be excluded (a new shield type, etc.), update `EXCLUDED_WEP_TYPES` in `services/weapons.py` and add a row in the [Excluded types](#excluded-types) table above.

4. Run `tests/test_weapons.py`. The `test_filter_rejects_shield_and_torch` test enumerates every excluded `wep_type` against the JSON and fails if a category becomes unrepresented in the snapshot.

No code change is needed for new weapons in already-tracked categories: they are picked up automatically.
