# Seed Pool Generation System

**Date:** 2026-02-05
**Status:** Approved

## Overview

System for generating seed pools for SpeedFog Racing by calling the external speedfog tool and merging results with the racing mod DLL.

### Components

1. **CLI Script `tools/generate_pool.py`** - Generates N seeds for a pool by calling speedfog, then adds the racing mod DLL
2. **GitHub Workflow `.github/workflows/build-mod.yml`** - Compiles the Rust mod on Windows and publishes the DLL as artifact

### Constraints

- Speedfog requires Wine on Linux (runs Windows executables internally)
- Generation happens on dev machine, seeds are manually copied to production server
- Mod DLL is pre-compiled via GitHub Actions (no local Windows build needed)

## File Structure

```
speedfog-racing/
├── tools/
│   ├── generate_pool.py          # Generation script
│   ├── assets/
│   │   └── speedfog_race_mod.dll # Pre-compiled DLL (from GitHub Actions)
│   └── pools/
│       ├── sprint/config.toml    # ~30min races
│       ├── standard/config.toml  # ~1h races
│       └── marathon/config.toml  # ~2h races
├── .github/workflows/
│   └── build-mod.yml             # Windows DLL build
└── .gitignore                    # Excludes *.dll
```

### Output Structure (on server)

```
/data/seeds/
├── sprint/
│   └── seed_123456/
├── standard/
│   └── seed_789012/
└── marathon/
    └── seed_345678/
```

Seed status (available/consumed) is tracked in the database only, no filesystem-based tracking.

## Script: generate_pool.py

### Usage

```bash
cd tools
python generate_pool.py --pool standard --count 10 --game-dir "/path/to/ELDEN RING/Game"
```

### Parameters

| Parameter         | Required | Description                                              |
| ----------------- | -------- | -------------------------------------------------------- |
| `--pool`          | Yes      | Pool name (sprint, standard, marathon)                   |
| `--count`         | Yes      | Number of seeds to generate                              |
| `--game-dir`      | Yes      | Path to Elden Ring Game directory                        |
| `--output`        | No       | Output directory (default: `./output`)                   |
| `--speedfog-path` | No       | Path to speedfog repo (default: `SPEEDFOG_PATH` env var) |

### Workflow

For each seed to generate:

1. **Call speedfog** via subprocess:

   ```python
   subprocess.run(
       [
           "uv", "run", "speedfog",
           str(pool_config.absolute()),
           "-o", str(temp_output),
           "--spoiler",
           "--game-dir", str(game_dir),
       ],
       cwd=speedfog_path,
       check=True,
   )
   ```

2. **Copy mod DLL** to `<seed>/lib/speedfog_race_mod.dll`

3. **Modify `config_speedfog.toml`** to add our DLL to ModEngine's external_dlls:

   ```toml
   [modengine]
   external_dlls = [
       "lib\\RandomizerCrashFix.dll",
       "lib\\RandomizerHelper.dll",
       "lib\\speedfog_race_mod.dll",  # Added
   ]
   ```

4. **Rename folder** to `seed_<number>` format

5. **Move to output** directory under pool name

### Error Handling

- If speedfog fails on a seed, log the error and continue with remaining seeds
- At the end, display summary: X succeeded, Y failed
- Script returns non-zero exit code if any failures

### Dependencies

- Python 3.11+ (standard library only: `argparse`, `subprocess`, `shutil`, `tomllib`, `pathlib`)
- `uv` installed (to run speedfog)
- `SPEEDFOG_PATH` environment variable or `--speedfog-path` argument
- DLL present in `tools/assets/`

## GitHub Workflow: build-mod.yml

Adapted from er-fog-vizu workflow.

### Triggers

- Push to `master` when `mod/**` changes
- Pull request to `master` when `mod/**` changes
- Manual trigger (`workflow_dispatch`)

### Jobs

1. Checkout repository
2. Setup Rust toolchain (stable, MSVC)
3. Cache cargo registry
4. Run tests: `cargo test --lib`
5. Build release: `cargo build --lib --release`
6. Upload artifact: `speedfog_race_mod.dll`

### Output

Artifact `speedfog-race-mod-vX.Y.Z` containing the DLL, downloadable from GitHub Actions.

### Developer Workflow

1. Modify Rust code in `mod/`
2. Push to GitHub → workflow builds automatically
3. Download artifact from Actions tab
4. Place in `tools/assets/speedfog_race_mod.dll`
5. Run `generate_pool.py`

## Pool Configurations

Each pool has a speedfog config with generation parameters only (no paths).

### Example: `tools/pools/sprint/config.toml`

```toml
[run]
seed = 0  # Auto-reroll until valid

[budget]
total_weight = 20
tolerance = 3

[requirements]
legacy_dungeons = 0
bosses = 3
mini_dungeons = 3

[structure]
max_parallel_paths = 2
min_layers = 4
max_layers = 6
final_tier = 20

[item_randomizer]
enabled = true
difficulty = 40
```

### Pool Characteristics

| Pool     | Duration | Weight | Layers | Bosses |
| -------- | -------- | ------ | ------ | ------ |
| sprint   | ~30min   | 20     | 4-6    | 3      |
| standard | ~1h      | 30     | 6-10   | 5      |
| marathon | ~2h      | 50     | 10-14  | 8      |

## Deployment Workflow

1. **Generate seeds** on dev machine:

   ```bash
   python tools/generate_pool.py --pool standard --count 20 --game-dir /path/to/game
   ```

2. **Copy to server**:

   ```bash
   rsync -avz output/standard/ server:/data/seeds/standard/
   ```

3. **Scan pool** via server (updates database):
   - Automatic on server startup, or
   - Manual via admin endpoint
