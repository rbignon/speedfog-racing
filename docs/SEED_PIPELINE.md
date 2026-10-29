# Seed Pipeline

End-to-end flow from seed generation to player download, covering batch generation, server ingestion, on-demand pack assembly, and lifecycle management.

## Overview

```
generate_pool.py        speedfog-scan-seeds      Player download
(batch, offline)        (CLI or admin API)       (on-demand)
      │                       │                        │
      ▼                       ▼                        ▼
  speedfog CLI           Read seed_*.zip          Stream base zip
      │                  Extract graph.json       Drop graph.json
      ▼                  Create Seed records      Inject config TOML
                                                  Append current DLL
  Post-process                                    Rewrite central dir
  (config, zip)
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

1. **Generate seed number**: `uuid4().hex[:12]` (e.g., `a1b2c3d4e5f6`). Stored as `seed_number` in the DB.

2. **Run speedfog**: subprocess call via `uv run speedfog <config> -o <temp_dir> --logs --game-dir <path>`. Each seed gets its own temp directory. Output is streamed to `<temp>/generation.log` (and optionally to stdout with `--verbose`).

3. **Post-process the seed directory**:
   - Register the racing mod in `modengine2/config_speedfog.toml`'s `external_dlls` array (`"..\\lib\\speedfog_racing.dll"`). The path is resolved by ModEngine 2 against the config's directory, so the `..\` prefix walks back up to the seed root. The zip does not carry the DLL itself: the server appends its current build to every seed pack at download (see section 3), so a mod release needs no pool regeneration.
   - Ensure `RandomizerHelper_config.ini` exists in `lib/` with safe racing defaults (no auto-equip, auto-upgrade enabled). This covers the case where item randomizer was disabled, as the DLL is always present but may lack config.

4. **Create zip**: all files under a top-level `speedfog_<slug>/` directory. Named `seed_<slug>.zip`.

5. **Copy pool TOML**: `tools/pools/<pool>.toml` is copied to `<output>/<pool>/config.toml` for server-side metadata.

6. **Failure handling**: on generation or post-processing failure, the temp directory is preserved in `<output>/<pool>_failed/seed_<seed_number>/` for investigation.

### Pool Configuration

Pool configs live at `tools/pools/<pool>.toml`. Each TOML file contains:

- `[display]`: metadata shown in the web UI (estimated_duration, description, type, sort_order, rules, archived_layers). `archived_layers` is an optional list of older layer counts that keep a retired speedrun board (see `docs/SPEEDRUN.md`); racing-only, never read by the generator. `rules` is an optional multi-line string; each non-empty line becomes a "Mode Rules" bullet, shown in the rules card above the DAG on `/race/[id]` and `/daily/[date]`, in the download modal, and in the pool settings card's "Mode Rules" popover.
- `[structure]`: seed generation parameters (final_tier, layers_count)
- `[requirements]`: zone constraints (legacy_dungeons, bosses, mini_dungeons, major_bosses)
- `[care_package]`: items granted at each tier (weapons, shields, spells, etc.)
- `[item_randomizer]`: item rando settings (difficulty, nerf_gargoyles, etc.)
- `[starting_items]`: items given at start (keys, runes, tears, etc.)
- `[enemy]`: enemy randomization settings

### Parallelism

`--jobs N` uses `ThreadPoolExecutor(max_workers=N)`. Each worker is fully independent (own temp dir, own speedfog subprocess). The summary table is printed after all futures complete.

---

## 2. Server Ingestion (`services/seed_service.py`)

### Pool Scanning (`scan_pool()`)

Called via the `speedfog-scan-seeds` CLI (or `POST /api/admin/seeds/scan`). For each pool directory configured in `SEEDS_POOL_DIR`:

1. Load `<pool>/config.toml`, normalize it via `_normalize_pool_config()`, and upsert the `Pool` row (`config`, `last_scanned_at` refreshed; `enabled` preserved so admin toggles survive rescans).
2. Walk the pool directory for `seed_*.zip` files.
3. For each zip, extract `graph.json` (root-level or `*/graph.json`).
4. Parse `total_layers` from `graph_json`.
5. Check if `(seed_number, pool_name)` already exists in DB, skip if so.
6. Create `Seed` record with `status=AVAILABLE`, `folder_path` pointing to the zip, FK `pool_name` referencing the `Pool` row.

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

Pools live in the `pools` table (see section 5 below). The on-disk
`config.toml` is the source of truth at scan time, but runtime reads go
through the DB:

**`get_pool_config(db, pool_name)`** (async) returns the normalized
config dict cached on `Pool.config` (human-readable settings:
estimated_duration, starting_items, care_package_items, difficulty
labels, etc.). Returns `None` if the pool does not exist or was
backfilled without a rescan.

**`pool_service.list_pools(db, *, include_disabled=False)`** returns
`Pool` rows, by default filtering out disabled pools. Used by
`/api/pools` (public) and `/api/admin/pools` (admin, with
`include_disabled=True`).

**`pool_service.set_pool_enabled(db, name, enabled)`** flips the admin
toggle; rescans never touch `enabled`.

Response builders that need the display name read from the eager
`seed.pool` relationship (`Seed.pool` uses `lazy="joined"`), so no
extra DB round-trips are needed to render pool names in race / training
responses, the admin reported-seeds list, and the admin pools list
(which reads the display name straight off each `Pool` row). All of
these resolve names via `format_pool_display_name`, which prefers the
config name and falls back to title-casing the normalized name. The
admin pools list also exposes each pool's `type` (`race` / `training`,
read from `Pool.config`) so the admin UI can suffix training pools with
" (Solo)".

Training seeds are never consumed: `get_training_seed` only skips the
seeds the requesting user already opened a session on, and once they have
played every available seed it picks among all of them again (repeats).
To show when a solo pool needs more seeds, the admin pools list carries a
`solo` object per played training pool, from
`training_service.get_pool_play_progress`: `max_played` (most distinct
available seeds played by one user), `top_players` (everyone tied at that
count) and `exhausted_users` (users who played them all). It counts the
same way as `get_played_seed_counts`, so a regenerated pool starts back at
zero; it is `null` for race pools and for training pools whose current
seeds nobody has played.
The Seeds tab shows it in the Consumed cell of solo pools as
`max_played/available`, plus `· N done` in the warning color once someone
has run out.

---

## 3. On-Demand Seed Pack Generation (`services/seed_pack_service.py`)

When a participant downloads their seed pack (`GET /races/{id}/my-seed-pack`), the server assembles a personalized zip on-the-fly.

The web client first mints a short-lived signed ticket (`/seed-pack-ticket` for races, `/pack-ticket` for training), then lets the browser download the zip natively via a `?t=` query param instead of buffering the whole response in JS. This gives native download progress, ETA, and resume.

The ticket endpoints run the same gating as the download endpoints, including checking that the seed zip still exists on disk (410 Gone when it was cleaned up), so failures surface in the web UI via the XHR instead of a broken native download. The download endpoints keep the same checks as a backstop.

### Steps

`stream_seed_pack_with_config(seed_zip_path, config_content, mod_dll_path)` never copies the pool zip: it parses the central directory once, then streams the original local records in 64 KB chunks and appends a rewritten central directory.

1. **Parse the central directory**: locate the EOCD record (ZIP64 is rejected), read the entries, and detect the common top-level directory (e.g., `speedfog_a1b2c3/`).

2. **Drop `graph.json`**: the seed's own DAG file (root-level or directly under the top dir, the same rule the pool scan uses to ingest it) is excluded from the download. Its local record is skipped in the byte stream, its central directory entry is removed, and the local header offsets of the entries stored after it are shifted back. The mod reads nothing from it (`event_ids`, `finish_event`, `spawn_items`, `phantom_skins` all arrive in `auth_ok`, see [PROTOCOL.md](PROTOCOL.md)) and it is a full-route spoiler in plain text; the pool zip on disk keeps it as the ingestion contract for `scan_pool()`.

3. **Drop the bundled mod DLL**: a `lib/speedfog_racing.dll` at the root or directly under the top dir (where ModEngine loads it, see `external_dlls`) is skipped the same way. Pool zips generated before the server started appending the DLL carry the build of their generation day there.

4. **Generate TOML config**: `generate_player_config(participant, race)` produces:

   ```toml
   [server]
   url = "<websocket_url>"
   mod_token = "<participant.mod_token>"
   race_id = "<race.id>"
   seed_id = "<race.seed_id>"

   [overlay]
   enabled = true
   anchor = "top-right"
   font_path = ""
   font_size = <user's preference or 20.0>
   leaderboard_mode = <user's preference or "centered">
   background_color = "#0F1923"
   background_opacity = 0.55
   text_color = "#E8E6E1"
   text_disabled_color = "#96A0AD"
   show_border = false
   border_color = "#253550"

   [keybindings]
   toggle_ui = "f9"
   toggle_leaderboard = "f10"
   ```

5. **Inject config and the current DLL**: appends a stored (uncompressed) `<top_dir>/lib/speedfog_racing.toml` entry right after the surviving local records, then the server's current DLL as a stored `<top_dir>/lib/speedfog_racing.dll`, followed by the rewritten central directory and a new EOCD. The DLL comes from `MOD_DLL_PATH` (default `/opt/speedfog-racing/mod/speedfog_racing.dll`, shipped by `deploy/deploy.sh`): `load_mod_dll` reads it once and keeps it in memory until the file changes, so concurrent downloads share one copy, and a pack streams the build it started with even if a deploy replaces the file meanwhile. Every pack therefore carries the current mod, whatever its seed's generation date; a player who keeps an older pack keeps its older DLL. When the file is missing, the ticket and download endpoints answer 503 (not the 410 of a purged seed zip).

6. **Serve response**: FastAPI `StreamingResponse` with the exact `Content-Length` computed up front (original size, minus the dropped `graph.json` and DLL records, plus the config and DLL entries). No temp file is written. The download is named `speedfog_<username>_<slug>.zip`, `<slug>` being the seed's `seed_number` (the slug shown as "Seed <slug>" on the race, daily and training pages); both parts are sanitized to `[a-zA-Z0-9_]`.

### Training Mode Variant

`GET /api/training/{id}/pack` streams through the same function with `generate_training_config(session)`, which:

- Sets `training = true` in the `[server]` section.
- Uses the training session's `mod_token` and `id` (as `race_id`).
- Omits `seed_id`, since training sessions don't use stale seed detection.
- Names the download `speedfog_training_<username>_<slug>.zip`.

### Stale Seed Detection

The `seed_id` in the TOML config enables client-side detection of outdated seed packs (race mode only). On `auth_ok`, the mod compares `config.server.seed_id` against `auth_ok.seed.seed_id`. A mismatch (organizer rerolled after download) displays a red banner prompting the player to re-download.

---

## 4. Pool Table

Each pool directory on disk is mirrored by a row in the `pools` table.
The row carries the runtime state that does not belong in the
filesystem:

| Column            | Purpose                                                                                                                 |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `name`            | Functional key (unique). Matches the directory name and `seeds.pool_name`.                                              |
| `enabled`         | Admin-managed visibility flag. Disabled pools are hidden from `/api/pools` and training creation rejects them with 400. |
| `config`          | Normalized snapshot of `config.toml` (`_normalize_pool_config()` output). Refreshed on every scan.                      |
| `last_scanned_at` | Populated by `scan_pool()`.                                                                                             |

`seeds.pool_name` is a foreign key referencing `pools.name`. A migration
backfills one row per distinct `seed.pool_name` with `enabled=True` and
an empty `config`. Operators are expected to run `speedfog-scan-seeds`
right after the migration to populate `config` / `last_scanned_at`.

Disabling a pool does not alter its seeds. Existing races keep playing
and existing training sessions remain valid; the toggle only hides the
pool from new selection UIs and blocks training creation.

---

## 5. Seed Status Lifecycle

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
- Seeds released via `POST /races/{id}/release-seeds` sets `seeds_released_at`, and participants can then download. The seed itself stays CONSUMED.
- Reroll is only allowed in SETUP status and when seeds have NOT been released.
- Discarded seeds are permanently retired; the guard in `reroll_seed_for_race` prevents them from returning to AVAILABLE.

### Retention of DISCARDED zips

A DISCARDED seed's zip is kept while any of these holds, so a played seed stays replayable on Set Seed:

- it is one of the `SET_SEED_KEPT_TOP_SEEDS` (10) best seeds of its category's Set Seed board;
- a player protected it (`seed_protections`, at most `SEED_PROTECTION_LIMIT` seeds each, no expiry);
- its last race or solo session is less than `SEED_PURGE_GRACE_DAYS` (30) days old (a race counts from its finish, else its start, else its creation; a session from its finish, else its creation).

A seed built before `SET_SEED_MIN_SEED_DATE` is purgeable whatever its reasons. Seeds that are not DISCARDED are never purged. `services/set_seed_service.py::purgeable_seeds` applies the rules; the CLI `speedfog-purgeable-seeds [--pool P] [--older-than DAYS]` prints one `folder_path` per line (logs on stderr). `deploy/cleanup-seeds.sh` runs it on the VPS and deletes only the listed zips (dry-run unless `--execute`); its second phase, which deletes DISCARDED rows no race or session references, also skips protected seeds. Settings are described in `docs/SPEEDRUN.md`.

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
│   └── speedfog_racing.dll
└── generate_pool.py
```

## Zip Internal Structure

Layout of the pack a player downloads. It differs from the pool zip on disk in three entries (see section 3): `graph.json` is dropped, `lib/speedfog_racing.toml` is added, and `lib/speedfog_racing.dll` is the server's current build (pool zips generated since the server appends it carry none; older ones carry the build of their generation day, which is dropped).

```
seed_a1b2c3d4e5f6.zip
└── speedfog_a1b2c3d4e5f6/
    ├── graph.json               # DAG definition (nodes, edges, event_map, ...); pool zip only, never shipped to players
    ├── regulation.bin           # Game data overrides
    ├── modengine2/
    │   ├── config_speedfog.toml   # ModEngine 2 config (includes racing DLL in external_dlls)
    │   ├── modengine2_launcher.exe
    │   └── modengine2/            # ModEngine 2 runtime (nested same-named dir, from upstream)
    │       ├── bin/
    │       ├── crashpad/
    │       └── tools/
    ├── launch_speedfog.bat        # Windows launcher
    ├── lib/
    │   ├── speedfog_racing.dll    # Racing overlay mod, appended at download (server's current build)
    │   ├── MenuInputDelayFix.dll  # Menu input-delay fix (from the speedfog base package)
    │   ├── RandomizerHelper.dll     # Item rando helper
    │   ├── RandomizerHelper_config.ini
    │   └── speedfog_racing.toml       # ← injected per-participant at download time
    └── event/                   # EMEVD scripts with custom event flags
```
