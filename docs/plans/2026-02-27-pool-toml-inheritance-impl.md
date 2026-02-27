# Pool TOML Inheritance — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplication in `tools/pools/*.toml` by introducing a `_base.toml` and `extends`-based inheritance resolved at generation time.

**Architecture:** A `deep_merge` + `resolve_pool_config` function in `tools/generate_pool.py` resolves inheritance chains at generation time and writes fully-resolved TOML to `output/<pool>/config.toml`. The server is unchanged — it reads resolved files as before.

**Tech Stack:** Python 3.11+ `tomllib` (read) + `tomli_w` (write), pytest for tests.

---

## Task 1: Add `tomli_w` dependency

The script currently copies TOML files verbatim. After merging dicts, we need to serialize back to TOML. `tomli_w` is the standard write companion to `tomllib`.

**Files:**

- Modify: `tools/requirements.txt` (create if needed, or add inline dep)

### Step 1: Check if tools has a requirements file or uses inline deps

Run: `ls tools/requirements*.txt tools/pyproject.toml 2>/dev/null; head -5 tools/generate_pool.py`

If no requirements file exists, we'll use `tomli_w` as an inline script dependency via `uv`. Since `generate_pool.py` already runs under `uv`, we can add a PEP 723 script metadata block.

### Step 2: Add `tomli_w` dependency to `generate_pool.py`

Add a PEP 723 inline metadata block at the top of `tools/generate_pool.py` (after the docstring, before imports):

```python
# /// script
# dependencies = ["tomli_w"]
# ///
```

And add the import:

```python
import tomli_w
```

### Step 3: Verify the import works

Run: `cd tools && uv run python -c "import tomli_w; print('ok')"`

Expected: `ok`

### Step 4: Commit

```bash
git add tools/generate_pool.py
git commit -m "chore(tools): add tomli_w dependency for TOML serialization"
```

---

## Task 2: Implement `deep_merge` and `resolve_pool_config`

**Files:**

- Modify: `tools/generate_pool.py` (add functions after `POOLS_DIR` constant)
- Create: `tools/test_pool_inheritance.py`

### Step 1: Write failing tests for `deep_merge`

Create `tools/test_pool_inheritance.py`:

```python
"""Tests for pool TOML inheritance (deep_merge + resolve_pool_config)."""

from __future__ import annotations

import pytest

from generate_pool import deep_merge


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        assert deep_merge(base, override) == {"a": 1, "b": 3}

    def test_nested_table_merge(self):
        base = {"t": {"a": 1, "b": 2}}
        override = {"t": {"b": 3, "c": 4}}
        assert deep_merge(base, override) == {"t": {"a": 1, "b": 3, "c": 4}}

    def test_array_replacement(self):
        base = {"arr": [1, 2, 3]}
        override = {"arr": [4, 5]}
        assert deep_merge(base, override) == {"arr": [4, 5]}

    def test_new_key_in_override(self):
        base = {"a": 1}
        override = {"b": 2}
        assert deep_merge(base, override) == {"a": 1, "b": 2}

    def test_new_table_in_override(self):
        base = {"a": 1}
        override = {"t": {"x": 1}}
        assert deep_merge(base, override) == {"a": 1, "t": {"x": 1}}

    def test_does_not_mutate_base(self):
        base = {"t": {"a": 1}}
        override = {"t": {"b": 2}}
        deep_merge(base, override)
        assert base == {"t": {"a": 1}}
```

### Step 2: Run tests to verify they fail

Run: `cd tools && uv run --script generate_pool.py -- python -m pytest test_pool_inheritance.py -v 2>&1 | head -20`

Actually, since `generate_pool.py` is a script not a package, we run:

Run: `cd tools && python -m pytest test_pool_inheritance.py::TestDeepMerge -v`

Expected: ImportError — `deep_merge` not defined yet.

### Step 3: Implement `deep_merge`

Add to `tools/generate_pool.py` after the `POOLS_DIR` line:

```python
def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins for scalars/arrays."""
    result = {}
    for key in base.keys() | override.keys():
        if key in override and key in base:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = deep_merge(base[key], override[key])
            else:
                result[key] = override[key]
        elif key in override:
            result[key] = override[key]
        else:
            result[key] = base[key]
    return result
```

### Step 4: Run tests to verify they pass

Run: `cd tools && python -m pytest test_pool_inheritance.py::TestDeepMerge -v`

Expected: All 6 tests PASS.

### Step 5: Write failing tests for `resolve_pool_config`

Add to `tools/test_pool_inheritance.py`:

```python
import tomllib
from pathlib import Path

from generate_pool import resolve_pool_config, POOLS_DIR


class TestResolvePoolConfig:
    def test_resolves_base(self):
        """_base.toml should resolve to itself (minus extends key)."""
        resolved = resolve_pool_config("_base")
        assert "extends" not in resolved
        assert "run" in resolved

    def test_chain_standard(self):
        """standard.toml extends _base — should have all sections."""
        resolved = resolve_pool_config("standard")
        assert "extends" not in resolved
        for section in ("display", "run", "structure", "starting_items",
                        "care_package", "item_randomizer", "enemy",
                        "requirements", "budget"):
            assert section in resolved, f"missing section: {section}"

    def test_training_inherits_parent(self):
        """training_standard extends standard — should carry all values."""
        parent = resolve_pool_config("standard")
        child = resolve_pool_config("training_standard")
        # Training overrides display.type
        assert child["display"]["type"] == "training"
        # But inherits parent's starting_items
        assert child["starting_items"] == parent["starting_items"]

    def test_cycle_detection(self):
        """Circular extends should raise an error."""
        # We test this with a mock — see below
        pass  # Covered by separate test with tmp_path

    def test_all_pools_resolve(self):
        """Every non-underscore pool must resolve without error."""
        for toml_path in POOLS_DIR.glob("*.toml"):
            if toml_path.stem.startswith("_"):
                continue
            resolved = resolve_pool_config(toml_path.stem)
            assert "extends" not in resolved
            assert "display" in resolved
```

### Step 6: Implement `resolve_pool_config`

Add to `tools/generate_pool.py` after `deep_merge`:

```python
import tomllib

def resolve_pool_config(
    pool_name: str,
    *,
    _pools_dir: Path | None = None,
    _seen: frozenset[str] | None = None,
) -> dict:
    """Resolve a pool config by following the extends chain.

    Returns a fully-merged dict with no ``extends`` key.
    """
    pools_dir = _pools_dir or POOLS_DIR
    seen = _seen or frozenset()

    if pool_name in seen:
        raise ValueError(f"Circular extends detected: {' -> '.join(seen)} -> {pool_name}")
    if len(seen) >= 3:
        raise ValueError(f"Extends chain too deep (max 3): {' -> '.join(seen)} -> {pool_name}")

    toml_path = pools_dir / f"{pool_name}.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"Pool config not found: {toml_path}")

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    parent_name = data.pop("extends", None)
    if parent_name is None:
        return data

    parent = resolve_pool_config(
        parent_name,
        _pools_dir=pools_dir,
        _seen=seen | {pool_name},
    )
    return deep_merge(parent, data)
```

Note: `tomllib` is already in stdlib (Python 3.11+). Move the existing `import tomllib` to the top-level imports if it isn't there already. `generate_pool.py` currently doesn't import `tomllib` — it just copies TOML files verbatim.

### Step 7: Run all tests

Run: `cd tools && python -m pytest test_pool_inheritance.py -v`

Expected: Tests pass (except `test_all_pools_resolve` — we haven't rewritten the pool files yet, so `_base.toml` doesn't exist). That's fine, we'll fix this in Task 4.

### Step 8: Commit

```bash
git add tools/generate_pool.py tools/test_pool_inheritance.py
git commit -m "feat(tools): implement deep_merge and resolve_pool_config for TOML inheritance"
```

---

## Task 3: Create `_base.toml`

Extract the common values shared across all 8 pools into `_base.toml`.

**Files:**

- Create: `tools/pools/_base.toml`

### Step 1: Write `_base.toml`

Create `tools/pools/_base.toml` with values common to ALL current pools:

```toml
# SpeedFog Racing - Base Pool Defaults
# All pools inherit from this. Override any value in your pool file.

[run]
seed = 0
run_complete_message = "RUN COMPLETE GG"
chapel_grace = true

[starting_items]
academy_key = true
pureblood_medal = false
drawing_room_key = true
lantern = true
physick_flask = true
great_runes = true

# DLC key items (prevent softlocks in DLC areas)
omother = true
welldepthskey = true
gaolupperlevelkey = true
gaollowerlevelkey = true
holeladennecklace = true
messmerskindling = true

[enemy]
randomize_bosses = false

[item_randomizer]
enabled = true
remove_requirements = true
auto_upgrade_weapons = true
auto_upgrade_dropped = true
reduce_upgrade_cost = true
dlc = true
item_preset = true
```

### Step 2: Verify it parses

Run: `cd tools && python -c "import tomllib; print(tomllib.load(open('pools/_base.toml','rb')))"`

Expected: dict output, no error.

### Step 3: Commit

```bash
git add tools/pools/_base.toml
git commit -m "feat(tools): add _base.toml with shared pool defaults"
```

---

## Task 4: Rewrite pool files as override-only

Rewrite all 8 pool files to use `extends` and contain only their overrides. Do this one pair at a time, verifying each resolves correctly.

**Files:**

- Modify: all 8 files in `tools/pools/` (except `_base.toml`)

### Step 1: Save current resolved state for comparison

Run a script that captures the current full content of each pool as parsed dicts:

```bash
cd tools && python -c "
import tomllib, json
from pathlib import Path
pools = {}
for f in sorted(Path('pools').glob('*.toml')):
    if f.stem.startswith('_'):
        continue
    pools[f.stem] = tomllib.load(open(f, 'rb'))
json.dump(pools, open('/tmp/pools_before.json', 'w'), indent=2, default=str)
print('Saved', len(pools), 'pools to /tmp/pools_before.json')
"
```

### Step 2: Rewrite `standard.toml`

Replace contents with override-only version:

```toml
# SpeedFog Racing - Standard Pool Configuration
# ~1 hour races
extends = "_base"

[display]
sort_order = 1
estimated_duration = "~1h"
description = "Balanced race with legacy dungeons and bosses"

[budget]
tolerance = 5

[requirements]
legacy_dungeons = 1
bosses = 10
mini_dungeons = 5

[structure]
max_parallel_paths = 4
min_layers = 25
max_layers = 30
final_tier = 20
split_probability = 0.9
merge_probability = 0.5
max_branches = 3
first_layer_type = "legacy_dungeon"
major_boss_ratio = 0.3
final_boss_candidates = [
    # Base game remembrance bosses
    "stormveil_godrick",
    "academy_library",
    "caelid_radahn",
    "ainsel_boss",
    "leyndell_throne",
    "volcano_rykard",
    "flamepeak_firegiant",
    "mohgwyn_boss",
    "farumazula_maliketh",
    "leyndell2_throne",
    "haligtree_malenia",
    "leyndell_erdtree",
    # DLC remembrance bosses + Bayle
    "belurat_boss",
    "ensis_boss",
    "fissure_boss",
    "scaduview_gaius",
    "midramanse_boss",
    "scadutree_base",
    "storehouse_messmer",
    "rauhruins_romina",
    "fingergrounds",
    "jaggedpeak_bayle",
    "enirilim_radahn",
]

[starting_items]
whetblades = true
talisman_pouches = 3
golden_seeds = 7
sacred_tears = 4
starting_runes = 100000
larval_tears = 3
stonesword_keys = 6

[care_package]
enabled = true
weapon_upgrade = 0
weapons = 0
shields = 0
catalysts = 2
talismans = 2
sorceries = 2
incantations = 2
head_armor = 1
body_armor = 1
arm_armor = 1
leg_armor = 1
crystal_tears = 5
ashes_of_war = 3

[item_randomizer]
difficulty = 50
nerf_gargoyles = true
```

### Step 3: Rewrite `training_standard.toml`

```toml
# SpeedFog Racing - Training Standard Pool Configuration
# ~1 hour solo runs
extends = "standard"

[display]
type = "training"
description = "Balanced solo run with legacy dungeons and bosses"

[structure]
crosslinks = true
min_branch_age = 3
max_branches = 4
```

### Step 4: Rewrite `sprint.toml`

```toml
# SpeedFog Racing - Sprint Pool Configuration
# ~30 minute races
extends = "_base"

[display]
sort_order = 2
estimated_duration = "~30min"
description = "Fast-paced race with minimal exploration"

[budget]
tolerance = 3

[requirements]
legacy_dungeons = 1
bosses = 5
mini_dungeons = 3

[structure]
max_parallel_paths = 4
min_layers = 10
max_layers = 15
final_tier = 12
split_probability = 0.9
merge_probability = 0.5
max_branches = 3
major_boss_ratio = 0.3
final_boss_candidates = ["all"]

[starting_items]
whetblades = true
talisman_pouches = 3
golden_seeds = 5
sacred_tears = 4
starting_runes = 100000
larval_tears = 1
stonesword_keys = 6

[care_package]
enabled = true
weapon_upgrade = 0
weapons = 5
shields = 2
catalysts = 2
talismans = 4
sorceries = 5
incantations = 5
head_armor = 2
body_armor = 2
arm_armor = 2
leg_armor = 2
crystal_tears = 5
ashes_of_war = 3

[item_randomizer]
difficulty = 40
nerf_gargoyles = true
```

### Step 5: Rewrite `training_sprint.toml`

```toml
# SpeedFog Racing - Training Sprint Pool Configuration
# ~30 minute solo runs
extends = "sprint"

[display]
type = "training"
description = "Quick solo run — minimal exploration"

[structure]
max_branches = 4
```

### Step 6: Rewrite `hardcore.toml`

```toml
# SpeedFog Racing - Hardcore Pool Configuration
# ~1 hour races, reduced resources and harder loot
extends = "_base"

[display]
sort_order = 3
estimated_duration = "~1h"
description = "Punishing race with scarce resources and tougher encounters"

[budget]
tolerance = 5

[requirements]
legacy_dungeons = 1
bosses = 10
mini_dungeons = 5

[structure]
max_parallel_paths = 4
min_layers = 25
max_layers = 30
final_tier = 28
split_probability = 0.9
merge_probability = 0.5
max_branches = 3
first_layer_type = "legacy_dungeon"
major_boss_ratio = 0.5
final_boss_candidates = [
    # Base game remembrance bosses
    "stormveil_godrick",
    "academy_library",
    "caelid_radahn",
    "ainsel_boss",
    "leyndell_throne",
    "volcano_rykard",
    "flamepeak_firegiant",
    "mohgwyn_boss",
    "farumazula_maliketh",
    "leyndell2_throne",
    "haligtree_malenia",
    "leyndell_erdtree",
    # DLC remembrance bosses + Bayle
    "belurat_boss",
    "ensis_boss",
    "fissure_boss",
    "scaduview_gaius",
    "midramanse_boss",
    "scadutree_base",
    "storehouse_messmer",
    "rauhruins_romina",
    "fingergrounds",
    "jaggedpeak_bayle",
    "enirilim_radahn",
]

[starting_items]
whetblades = false
talisman_pouches = 2
golden_seeds = 3
sacred_tears = 2
starting_runes = 50000
larval_tears = 2
stonesword_keys = 3

[care_package]
enabled = true
weapon_upgrade = 0
weapons = 0
shields = 0
catalysts = 0
talismans = 0
sorceries = 0
incantations = 0
head_armor = 1
body_armor = 1
arm_armor = 1
leg_armor = 1
crystal_tears = 2
ashes_of_war = 1

[item_randomizer]
difficulty = 75
nerf_gargoyles = false
```

### Step 7: Rewrite `training_hardcore.toml`

```toml
# SpeedFog Racing - Training Hardcore Pool Configuration
# ~1 hour solo runs, reduced resources and harder loot
extends = "hardcore"

[display]
type = "training"
description = "Punishing solo run with scarce resources and tougher encounters"
```

### Step 8: Rewrite `boss_shuffle.toml`

This one extends `standard` since it shares almost everything, overriding only `[enemy]` and `final_boss_candidates`:

```toml
# SpeedFog Racing - Boss Shuffle Pool Configuration
# ~1 hour races with randomized boss encounters
extends = "standard"

[display]
sort_order = 4
description = "Standard race with randomized boss encounters"

[structure]
final_boss_candidates = ["all"]

[enemy]
randomize_bosses = true
lock_final_boss = true
```

### Step 9: Rewrite `training_boss_shuffle.toml`

```toml
# SpeedFog Racing - Training Boss Shuffle Pool Configuration
# ~1 hour solo runs with randomized boss encounters
extends = "boss_shuffle"

[display]
type = "training"
description = "Solo run with randomized boss encounters"
```

### Step 10: Verify resolved output matches originals

Run a verification script:

```bash
cd tools && python -c "
import tomllib, json
from generate_pool import resolve_pool_config

before = json.load(open('/tmp/pools_before.json'))
mismatches = []
for name, expected in before.items():
    resolved = resolve_pool_config(name)
    if resolved != expected:
        mismatches.append(name)
        # Show diff
        for section in set(list(expected.keys()) + list(resolved.keys())):
            if expected.get(section) != resolved.get(section):
                print(f'{name}[{section}]:')
                print(f'  expected: {expected.get(section)}')
                print(f'  resolved: {resolved.get(section)}')
if mismatches:
    print(f'MISMATCH in: {mismatches}')
else:
    print('All pools match their original values.')
"
```

Expected: `All pools match their original values.`

If mismatches exist, fix the override files until they match.

### Step 11: Run the test suite

Run: `cd tools && python -m pytest test_pool_inheritance.py -v`

Expected: All tests pass (including `test_all_pools_resolve`).

### Step 12: Commit

```bash
git add tools/pools/
git commit -m "refactor(tools): rewrite pool configs to use extends inheritance

All 8 pool files now use extends to inherit from _base.toml or their
race parent. Training pools are reduced to 3-10 lines of overrides.
boss_shuffle extends standard, overriding only [enemy]."
```

---

## Task 5: Wire `resolve_pool_config` into `generate_pool.py` main flow

Replace the `shutil.copy2` with resolution + `tomli_w` serialization.

**Files:**

- Modify: `tools/generate_pool.py` (main function + discover_pools)

### Step 1: Update `discover_pools` to skip `_` prefixed files

In `tools/generate_pool.py`, modify `discover_pools`:

```python
def discover_pools() -> list[str]:
    """Discover available pool names from TOML files in the pools directory."""
    if not POOLS_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in POOLS_DIR.glob("*.toml")
        if not p.stem.startswith("_")
    )
```

### Step 2: Replace `shutil.copy2` with resolved TOML write

In the `main()` function, replace line 446:

```python
# OLD:
shutil.copy2(pool_config, output_pool_dir / "config.toml")

# NEW:
resolved = resolve_pool_config(args.pool)
config_out = output_pool_dir / "config.toml"
with open(config_out, "wb") as f:
    tomli_w.dump(resolved, f)
```

### Step 3: Add a `--dump` flag for debugging

In `parse_args`, add:

```python
parser.add_argument(
    "--dump",
    action="store_true",
    help="Resolve and print the pool config TOML, then exit (no generation)",
)
```

In `main()`, after resolving speedfog_path but before pool_config validation, add:

```python
if args.dump:
    resolved = resolve_pool_config(args.pool)
    sys.stdout.buffer.write(tomli_w.dumps(resolved).encode())
    return 0
```

Note: with `--dump`, we can skip the `--game-dir` and `--count` requirements. Adjust `parse_args` so `--game-dir` and `--count` are only required when not using `--dump`. The simplest way: make them not required in argparse and validate manually in `main()`.

### Step 4: Verify dump works

Run: `cd tools && python generate_pool.py --pool standard --dump | head -20`

Expected: Resolved TOML output with all sections.

### Step 5: Commit

```bash
git add tools/generate_pool.py
git commit -m "feat(tools): wire pool inheritance into generate_pool.py

- resolve_pool_config replaces shutil.copy2 for config.toml output
- discover_pools skips _-prefixed files
- --dump flag prints resolved TOML without generating seeds"
```

---

## Task 6: Add section validation

After resolution, warn if expected sections are missing.

**Files:**

- Modify: `tools/generate_pool.py`
- Modify: `tools/test_pool_inheritance.py`

### Step 1: Write failing test

Add to `tools/test_pool_inheritance.py`:

```python
from generate_pool import validate_pool_config


class TestValidation:
    def test_complete_config_passes(self):
        resolved = resolve_pool_config("standard")
        errors = validate_pool_config(resolved, "standard")
        assert errors == []

    def test_missing_section_reports_error(self):
        config = {"display": {"sort_order": 1}}
        errors = validate_pool_config(config, "test")
        assert len(errors) > 0
        assert any("structure" in e for e in errors)
```

### Step 2: Run test to verify it fails

Run: `cd tools && python -m pytest test_pool_inheritance.py::TestValidation -v`

Expected: ImportError — `validate_pool_config` not defined.

### Step 3: Implement `validate_pool_config`

Add to `tools/generate_pool.py`:

```python
REQUIRED_SECTIONS = (
    "display", "run", "structure", "starting_items",
    "care_package", "item_randomizer", "enemy",
    "requirements", "budget",
)


def validate_pool_config(config: dict, pool_name: str) -> list[str]:
    """Validate a resolved pool config. Returns list of error messages."""
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in config:
            errors.append(f"{pool_name}: missing required section [{section}]")
    return errors
```

### Step 4: Wire validation into main flow

After `resolved = resolve_pool_config(args.pool)` in `main()`, add:

```python
errors = validate_pool_config(resolved, args.pool)
for err in errors:
    print(f"Warning: {err}")
```

### Step 5: Run tests

Run: `cd tools && python -m pytest test_pool_inheritance.py -v`

Expected: All pass.

### Step 6: Commit

```bash
git add tools/generate_pool.py tools/test_pool_inheritance.py
git commit -m "feat(tools): add section validation for resolved pool configs"
```

---

## Task 7: Final verification and cleanup

### Step 1: Run the full test suite

Run: `cd tools && python -m pytest test_pool_inheritance.py -v`

Expected: All tests pass.

### Step 2: Verify every pool resolves and validates

Run:

```bash
cd tools && python -c "
from generate_pool import resolve_pool_config, validate_pool_config, discover_pools
for name in discover_pools():
    resolved = resolve_pool_config(name)
    errors = validate_pool_config(resolved, name)
    status = 'OK' if not errors else f'ERRORS: {errors}'
    print(f'{name:30s} {status}')
"
```

Expected: All pools show `OK`.

### Step 3: Verify `--dump` produces valid output for all pools

Run:

```bash
cd tools && for pool in $(python -c "from generate_pool import discover_pools; print(' '.join(discover_pools()))"); do
    echo "=== $pool ==="
    python generate_pool.py --pool "$pool" --dump > /dev/null && echo "OK" || echo "FAIL"
done
```

Expected: All `OK`.

### Step 4: Run server tests to confirm nothing broke

Run: `cd ../server && uv run pytest -x -q`

Expected: All pass (server doesn't read source TOML files, only resolved `config.toml`).

### Step 5: Commit if any final tweaks were needed

```bash
git add -A
git commit -m "chore(tools): final cleanup for pool TOML inheritance"
```
