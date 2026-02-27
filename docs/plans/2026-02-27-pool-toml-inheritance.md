# Pool TOML Inheritance

Reduce duplication across `tools/pools/*.toml` by introducing a `_base.toml` and
an `extends` mechanism resolved at generation time.

## Problem

8 pool files with massive duplication:

- 4 race/training pairs that differ by ~3-5 lines each
- Cross-pool duplication: `[run]`, DLC starting items, `[item_randomizer]` defaults

This leads to inconsistencies (e.g. `max_branches` 3 vs 4, `crosslinks` present in
training_standard but not standard) and makes bulk changes error-prone.

## Design

### File Structure

```
tools/pools/
  _base.toml                  # Global defaults (run, DLC items, item_randomizer)
  standard.toml               # extends = "_base"
  training_standard.toml      # extends = "standard"
  sprint.toml                 # extends = "_base"
  training_sprint.toml        # extends = "sprint"
  hardcore.toml               # extends = "_base"
  training_hardcore.toml      # extends = "hardcore"
  boss_shuffle.toml           # extends = "standard" (differs only in [enemy])
  training_boss_shuffle.toml  # extends = "boss_shuffle"
```

Files starting with `_` are not pools (not copied to output, not listed).

### `_base.toml` Contents

- `[run]`: seed=0, run_complete_message, chapel_grace
- `[starting_items]`: DLC key items (omother, welldepthskey, etc.) + common items
  (academy_key, pureblood_medal=false, drawing_room_key, lantern, physick_flask,
  great_runes)
- `[item_randomizer]`: common values (enabled, remove_requirements,
  auto_upgrade_weapons, auto_upgrade_dropped, reduce_upgrade_cost, dlc, item_preset)
- `[enemy]`: randomize_bosses=false

Each pool file declares only its overrides.

### Merge Mechanics

Resolution in `generate_pool.py` via `resolve_pool_config(pool_name)`:

1. Read the pool's TOML
2. If `extends` is present, recursively resolve the parent
3. Deep-merge: parent -> child (child wins)
4. Remove the `extends` key from the resolved result
5. Write resolved TOML to `output/<pool>/config.toml`

Merge rules:

- **Tables** (dicts): recursive key-by-key merge
- **Scalars and arrays**: full replacement (no array append)
- **Key absent in child**: keep parent value
- **Key present in child**: take child value

Guards:

- Cycle detection -> explicit error
- Max depth = 3
- Missing parent -> error

### Server Impact

None. The server reads fully resolved `config.toml` files. No changes to
`seed_service.py`, `schemas.py`, or the API.

### Validation

- After resolution, verify all required sections are present: `[display]`,
  `[structure]`, `[starting_items]`, `[care_package]`, `[item_randomizer]`,
  `[enemy]`, `[requirements]`, `[budget]`, `[run]`
- Warning on unexpected keys (typo detection)
- `--dump <pool>` flag to print resolved TOML without writing (debug aid)

### Tests

- Unit test `deep_merge(base, override)`: scalar, nested table, array replacement
- Unit test `resolve_pool_config`: chain `_base -> standard -> training_standard`
- Cycle detection test
- All pools resolve without error (loop over `discover_pools()`)

### Migration

- Create `_base.toml`
- Rewrite 8 existing files as override-only
- Verify resolved output matches original files (parsed dict comparison)
