# Seed Pipeline

End-to-end flow from seed generation to player download, covering batch generation, server ingestion, on-demand pack assembly, and lifecycle management.

## Overview

```
generate_pool.py        Server startup           Player download
(batch, offline)        (scan_pool)              (on-demand)
      │                       │                        │
      ▼                       ▼                        ▼
  speedfog CLI           Read seed_*.zip          Copy base zip
      │                  Extract graph.json       Inject config TOML
      ▼                  Create Seed records      Serve FileResponse
  Post-process                                    Delete temp file
  (DLL, config, zip)
      │
      ▼
  seed_<slug>.zip
  in pool directory
```

## 1. Batch Generation (`tools/generate_pool.py`)

Offline script run on a dev machine (requires Windows game files via Wine or native).

### Usage

```bash
python tools/generate_pool.py \
    --pool standard \
    --count 10 \
    --game-dir "/path/to/ELDEN RING/Game" \
    --jobs 4
```

### Steps Per Seed

1. **Generate seed number** — `uuid4().hex[:12]` (e.g., `a1b2c3d4e5f6`). Stored as `seed_number` in the DB.

2. **Run speedfog** — subprocess call via `uv run speedfog <config> -o <temp_dir> --spoiler --game-dir <path>`. Each seed gets its own temp directory. Output is streamed to `<temp>/generation.log` (and optionally to stdout with `--verbose`).

3. **Post-process the seed directory**:
   - Copy `speedfog_race_mod.dll` from `tools/assets/` to `<seed_dir>/lib/`.
   - Inject DLL path into `config_speedfog.toml`'s `external_dlls` array via regex replacement.
   - Ensure `RandomizerHelper_config.ini` exists in `lib/` with safe racing defaults (no auto-equip, auto-upgrade enabled). This covers the case where item randomizer was disabled — the DLL is always present but may lack config.

4. **Create zip** — all files under a top-level `speedfog_<slug>/` directory. Named `seed_<slug>.zip`.

5. **Copy pool TOML** — `tools/pools/<pool>.toml` is copied to `<output>/<pool>/config.toml` for server-side metadata.

6. **Failure handling** — on generation or post-processing failure, the temp directory is preserved in `<output>/<pool>_failed/seed_<seed_number>/` for investigation.

### Pool Configuration

Pool configs live at `tools/pools/<pool>.toml`. Each TOML file contains:

- `[display]`: metadata shown in the web UI (estimated_duration, description, type, sort_order)
- `[structure]`: seed generation parameters (final_tier, min/max_layers, major_boss_ratio)
- `[requirements]`: legacy dungeon constraints
- `[care_package]`: items granted at each tier (weapons, shields, spells, etc.)
- `[item_randomizer]`: item rando settings (difficulty, nerf_gargoyles, etc.)
- `[starting_items]`: items given at start (keys, runes, tears, etc.)
- `[enemy]`: enemy randomization settings

### Parallelism

`--jobs N` uses `ThreadPoolExecutor(max_workers=N)`. Each worker is fully independent (own temp dir, own speedfog subprocess). The summary table is printed after all futures complete.

---

## 2. Server Ingestion (`services/seed_service.py`)

### Pool Scanning (`scan_pool()`)

Called during server startup (lifespan). For each pool directory configured in `SEEDS_POOL_DIR`:

1. Walk the pool directory for `seed_*.zip` files.
2. For each zip, extract `graph.json` (root-level or `*/graph.json`).
3. Parse `total_layers` from `graph_json`.
4. Check if `(seed_number, pool_name)` already exists in DB — skip if so.
5. Create `Seed` record with `status=AVAILABLE`, `folder_path` pointing to the zip.

### Seed Assignment

**`assign_seed_to_race(db, race, pool_name)`**:

- Queries all AVAILABLE seeds for the pool.
- Picks one at random (`random.choice`).
- Marks it `CONSUMED`, sets `race.seed_id`.

**`get_available_seed(db, pool_name, exclude_id?)`**:

- Returns a random AVAILABLE seed. Optional `exclude_id` for reroll (exclude the current seed).

### Seed Reroll

**`reroll_seed_for_race(db, race)`**:

- Requires `race.seed` to be eager-loaded.
- Gets a new AVAILABLE seed from the same pool, excluding the current seed ID.
- Releases old seed back to AVAILABLE (unless it was already DISCARDED from a pool retirement).
- Assigns new seed to race.

### Pool Discard

**`discard_pool(db, pool_name)`**:

- Single UPDATE: marks both AVAILABLE and CONSUMED seeds as DISCARDED.
- CONSUMED seeds are included to prevent them from leaking back to AVAILABLE via reroll after the pool is retired.

### Pool Metadata

**`get_pool_config(pool_name)`** reads `$SEEDS_POOL_DIR/<pool>/config.toml` and returns a dict of human-readable settings (estimated_duration, starting_items, care_package_items, difficulty labels, etc.).

**`get_pool_metadata(seeds_pool_dir)`** scans all pool subdirectories for `config.toml` files and extracts the `[display]` section.

---

## 3. On-Demand Seed Pack Generation (`services/seed_pack_service.py`)

When a participant downloads their seed pack (`GET /races/{id}/my-seed-pack`), the server assembles a personalized zip on-the-fly.

### Steps

1. **Copy base zip** to a temp file (`tempfile.mkstemp(suffix=".zip")`).

2. **Detect top-level directory** — `_get_top_dir()` finds the common top-level directory inside the zip (e.g., `speedfog_a1b2c3/`).

3. **Generate TOML config** — `generate_player_config(participant, race)` produces:

   ```toml
   [server]
   url = "<websocket_url>"
   mod_token = "<participant.mod_token>"
   race_id = "<race.id>"
   seed_id = "<race.seed_id>"

   [overlay]
   enabled = true
   font_path = ""
   font_size = <user's preference or 18.0>
   background_color = "#141414"
   background_opacity = 0.3
   text_color = "#FFFFFF"
   text_disabled_color = "#808080"
   show_border = false
   border_color = "#404040"

   [keybindings]
   toggle_ui = "f9"
   ```

4. **Inject config** — writes `speedfog_race.toml` into `<top_dir>/lib/speedfog_race.toml` within the zip.

5. **Serve response** — FastAPI `FileResponse` streams the temp file. A `BackgroundTask` deletes the temp file after the response completes.

### Training Mode Variant

`generate_seed_pack_on_demand_training(session)` is similar but:

- Sets `training = true` in the `[server]` section.
- Uses the training session's `mod_token` and `id` (as `race_id`).
- Omits `seed_id` — training sessions don't use stale seed detection.

### Stale Seed Detection

The `seed_id` in the TOML config enables client-side detection of outdated seed packs (race mode only). On `auth_ok`, the mod compares `config.server.seed_id` against `auth_ok.seed.seed_id`. A mismatch (organizer rerolled after download) displays a red banner prompting the player to re-download.

---

## 4. Seed Status Lifecycle

```
AVAILABLE ──assign_seed_to_race──→ CONSUMED
    ↑                                  │
    └────reroll_seed_for_race──────────┘

AVAILABLE ──┐
             ├──discard_pool──→ DISCARDED
CONSUMED  ──┘

DISCARDED ──reroll──→ stays DISCARDED (never released back)
```

### Key Invariants

- A race always has exactly one seed assigned (set at creation, changeable via reroll during SETUP).
- Seeds released via `POST /races/{id}/release-seeds` sets `seeds_released_at` — participants can then download. The seed itself stays CONSUMED.
- Reroll is only allowed in SETUP status and when seeds have NOT been released.
- Discarded seeds are permanently retired — the guard in `reroll_seed_for_race` prevents them from returning to AVAILABLE.

---

## Directory Layout

```
$SEEDS_POOL_DIR/
├── standard/
│   ├── config.toml          # Copy of tools/pools/standard.toml
│   ├── seed_a1b2c3d4e5f6.zip
│   ├── seed_b2c3d4e5f6a1.zip
│   └── ...
├── sprint/
│   ├── config.toml
│   └── seed_*.zip
└── training/
    ├── config.toml
    └── seed_*.zip

tools/
├── pools/
│   ├── standard.toml        # Pool config templates
│   ├── sprint.toml
│   └── training.toml
├── assets/
│   └── speedfog_race_mod.dll
└── generate_pool.py
```

## Zip Internal Structure

```
seed_a1b2c3d4e5f6.zip
└── speedfog_a1b2c3d4e5f6/
    ├── graph.json               # DAG definition (nodes, edges, event_map, ...)
    ├── config_speedfog.toml     # ModEngine config (includes racing DLL)
    ├── regulation.bin           # Game data overrides
    ├── lib/
    │   ├── speedfog_race_mod.dll    # Racing overlay mod
    │   ├── RandomizerHelper.dll     # Item rando helper
    │   ├── RandomizerHelper_config.ini
    │   └── speedfog_race.toml       # ← injected per-participant at download time
    └── event/                   # EMEVD scripts with custom event flags
```
