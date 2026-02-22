# Training → Solo Rename + Pool Type Refactoring

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the "training" terminology with "solo" everywhere, eliminate duplicate pool TOML configs, and add a proper `pool_type` column to the seeds table instead of relying on a `training_` naming prefix convention.

**Architecture:** The pool type (race vs solo) and pool config (standard, sprint, etc.) are orthogonal concepts currently tangled via naming conventions. This refactoring separates them: `pool_type` becomes a DB column, the filesystem uses `race/` and `solo/` subdirectories, and pool configs exist once (not duplicated per type). The "training" terminology is replaced with "solo" to better reflect actual usage.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 (async), Alembic, SvelteKit 5, Rust (serde), PostgreSQL, Bash scripts.

---

## Design decisions (brainstorming 2026-02-22)

- **All-in-one deployment** — rename + filesystem restructuring in a single migration/deploy, not phased.
- **Tests integrated per task** — each server task updates its corresponding tests (no separate "fix tests" task at the end).
- **Pool type from filesystem** — server infers `pool_type` from directory path (`race/` vs `solo/`). No `type` field in config.toml.
- **Mod config: `solo = true`** — simple boolean rename (not decomposed into `hide_leaderboard` etc.) because the 3 behaviors (WS endpoint, leaderboard, ready) are fundamentally coupled to the server-side mode.
- **API breaking change OK** — no external clients use `/api/training`, only the SvelteKit frontend.
- **Include `name` field** — add display name to pool TOMLs while we're touching them.

---

## Important context

- **No worktrees or branches** — all work on master, frequent commits.
- **Mod backward compat** — existing seed packs in the wild have `training = true` in TOML. Use serde `alias` for backward compat.
- **VPS migration** — filesystem restructuring from flat `training_standard/`, `standard/` to nested `race/standard/`, `solo/standard/`. One-time deploy step.
- **DB migration** — rename table `training_sessions` → `solo_sessions`, add `pool_type` to `seeds`, normalize `pool_name` (strip `training_` prefix), update `folder_path`.
- **Existing alembic migrations** — NEVER modify. Create new ones.

## Filesystem structure change

**Before:**

```
$SEEDS_DIR/
├── standard/          # race seeds
├── training_standard/ # solo seeds
├── sprint/
├── training_sprint/
└── ...
```

**After:**

```
$SEEDS_DIR/
├── race/
│   ├── standard/
│   │   ├── config.toml
│   │   └── seed_*.zip
│   ├── sprint/
│   └── ...
└── solo/
    ├── standard/
    ├── sprint/
    └── ...
```

---

### Task 1: Alembic migration — add pool_type, rename table, normalize data

**Files:**

- Create: `server/alembic/versions/XXXX_rename_training_to_solo.py`
- Modify: `server/speedfog_racing/models.py` (Seed model + enum rename)

#### Step 1: Create the Alembic migration

```bash
cd server && uv run alembic revision --autogenerate -m "rename training to solo and add pool_type"
```

Then edit the generated migration to include:

```python
def upgrade():
    # 1. Add pool_type column to seeds (nullable initially for backfill)
    op.add_column("seeds", sa.Column("pool_type", sa.String(10), nullable=True))

    # 2. Backfill pool_type from pool_name prefix
    op.execute("UPDATE seeds SET pool_type = 'solo' WHERE pool_name LIKE 'training\\_%'")
    op.execute("UPDATE seeds SET pool_type = 'race' WHERE pool_type IS NULL")

    # 3. Normalize pool_name: strip 'training_' prefix
    op.execute("UPDATE seeds SET pool_name = SUBSTRING(pool_name FROM 10) WHERE pool_name LIKE 'training\\_%'")

    # 4. Update folder_path for new directory structure
    # training_X/seed.zip → solo/X/seed.zip
    op.execute("""
        UPDATE seeds
        SET folder_path = REGEXP_REPLACE(folder_path, '/training_([^/]+)/', '/solo/\\1/')
        WHERE pool_type = 'solo'
    """)
    # race seeds: X/seed.zip → race/X/seed.zip
    op.execute("""
        UPDATE seeds
        SET folder_path = REGEXP_REPLACE(folder_path, '/([^/]+/seed_)', '/race/\\1')
        WHERE pool_type = 'race'
    """)

    # 5. Make pool_type non-nullable
    op.alter_column("seeds", "pool_type", nullable=False)

    # 6. Add index for common queries
    op.create_index("ix_seeds_pool_name_type", "seeds", ["pool_name", "pool_type"])

    # 7. Rename training_sessions table → solo_sessions
    op.rename_table("training_sessions", "solo_sessions")

    # 8. Rename PostgreSQL enum type
    op.execute("ALTER TYPE trainingsessionstatus RENAME TO solosessionstatus")

def downgrade():
    op.execute("ALTER TYPE solosessionstatus RENAME TO trainingsessionstatus")
    op.rename_table("solo_sessions", "training_sessions")
    op.drop_index("ix_seeds_pool_name_type")
    # Reverse pool_name normalization
    op.execute("UPDATE seeds SET pool_name = 'training_' || pool_name WHERE pool_type = 'solo'")
    # Reverse folder_path changes
    op.execute("""
        UPDATE seeds
        SET folder_path = REGEXP_REPLACE(folder_path, '/solo/([^/]+)/', '/training_\\1/')
        WHERE pool_type = 'solo'
    """)
    op.execute("""
        UPDATE seeds
        SET folder_path = REGEXP_REPLACE(folder_path, '/race/([^/]+/seed_)', '/\\1')
        WHERE pool_type = 'race'
    """)
    op.drop_column("seeds", "pool_type")
```

#### Step 2: Update models.py

- Rename `TrainingSessionStatus` → `SoloSessionStatus`
- Rename `TrainingSession` → `SoloSession` (set `__tablename__ = "solo_sessions"`)
- Add `pool_type` column to `Seed` model:

  ```python
  pool_type: Mapped[str] = mapped_column(String(10), nullable=False, default="race")
  ```

- Update Seed comment: `# "standard", "sprint"` (already correct without prefix)

#### Step 3: Run migration locally to verify

```bash
cd server && uv run alembic upgrade head
```

#### Step 4: Commit

```
feat(db): rename training to solo, add pool_type to seeds
```

---

### Task 2: Server services — rename training_service → solo_service, add pool_type queries

**Files:**

- Rename: `server/speedfog_racing/services/training_service.py` → `solo_service.py`
- Modify: `server/speedfog_racing/services/__init__.py`
- Modify: `server/speedfog_racing/services/seed_service.py`
- Modify: `server/speedfog_racing/services/seed_pack_service.py`

**Changes in `solo_service.py` (renamed from training_service.py):**

- `get_training_seed()` → `get_solo_seed()` — add `Seed.pool_type == "solo"` filter
- `create_training_session()` → `create_solo_session()` — use `SoloSession` model
- `get_played_seed_counts()` — add `Seed.pool_type == "solo"` filter
- All `TrainingSession` refs → `SoloSession`
- All `TrainingSessionStatus` refs → `SoloSessionStatus`

**Changes in `seed_service.py`:**

- `scan_pool()` — accept `pool_type` parameter (inferred from filesystem path by caller in `main.py`), store in Seed:

  ```python
  seed = Seed(pool_name=pool_name, pool_type=pool_type, ...)
  ```

- `get_available_seed()` — add `pool_type` parameter (default `"race"`)
- `assign_seed_to_race()` — pass `pool_type="race"` to `get_available_seed()`
- `reroll_seed_for_race()` — add `Seed.pool_type == "race"` filter
- `get_pool_stats()` — group by `(pool_name, pool_type)` instead of just `pool_name`
- `get_pool_config()` — update path resolution for new `race/X/` and `solo/X/` structure:

  ```python
  def get_pool_config(pool_name: str, pool_type: str = "race") -> dict[str, Any] | None:
      config_file = Path(settings.seeds_pool_dir) / pool_type / pool_name / "config.toml"
  ```

- `get_pool_metadata()` — update for nested directory structure

**Changes in `seed_pack_service.py`:**

- `generate_training_config()` → `generate_solo_config()` — change `training = true` to `solo = true`
- `generate_seed_pack_on_demand_training()` → `generate_seed_pack_on_demand_solo()`
- Update folder_path construction for new structure

**Changes in `__init__.py`:**

- Update all exports: `create_solo_session`, `get_solo_seed`, etc.

**Commit:**

```
refactor(server): rename training service to solo, add pool_type to seed queries
```

---

### Task 3: Server API routes — rename /api/training → /api/solo

**Files:**

- Rename: `server/speedfog_racing/api/training.py` → `solo.py`
- Modify: `server/speedfog_racing/api/__init__.py`
- Modify: `server/speedfog_racing/api/pools.py`
- Modify: `server/speedfog_racing/api/users.py`
- Modify: `server/speedfog_racing/api/admin.py`
- Modify: `server/speedfog_racing/schemas.py`
- Modify: `server/speedfog_racing/discord.py` (if exists)

**Changes in `solo.py` (renamed from training.py):**

- All function names: `create_session()`, `list_sessions()`, etc. (drop "training" prefix where present)
- All imports: `SoloSession`, `SoloSessionStatus`, `create_solo_session`, `get_solo_seed`
- Pool validation: check `type == "solo"` instead of `type == "training"`
- Error messages: "training session" → "solo session"
- Default pool*name in `CreateSoloRequest`: just `"standard"` (no `training*` prefix)

**Changes in `api/__init__.py`:**

- `training_router` → `solo_router`
- Prefix: `/training` → `/solo`
- Tag: `"training"` → `"solo"`

**Changes in `schemas.py`:**

- `CreateTrainingRequest` → `CreateSoloRequest` (default `pool_name = "standard"`)
- `TrainingSessionResponse` → `SoloSessionResponse`
- `TrainingSessionDetailResponse` → `SoloSessionDetailResponse`
- `TrainingActivity` → `SoloActivity` (type field: `"solo"`)
- `UserStatsResponse.training_count` → `solo_count`
- `UserPoolStatsEntry.training` → `solo`
- `PoolConfig.type` default stays `"race"`, valid values now `"race"` | `"solo"`
- `ActivityItem` union: replace `TrainingActivity` with `SoloActivity`

**Changes in `pools.py`:**

- Filter: `type == "solo"` instead of `type == "training"`
- Use `pool_type` column from DB stats instead of reading TOML config for type detection
- Pass `pool_type` to `get_pool_config()`

**Changes in `users.py`:**

- Variable names: `training_stats` → `solo_stats`
- Remove `.removeprefix("training_")` logic — pool_name already normalized in DB
- Filter: `Seed.pool_type == "solo"` for solo stats, `Seed.pool_type == "race"` for race stats

**Changes in `admin.py`:**

- `training_count` → `solo_count` (variable names and query aliases)

**Changes in `discord.py`:**

- `is_training` → `is_solo`
- Check `pool_type == "solo"` from context instead of `pool_name.startswith("training_")`

**Commit:**

```
refactor(server): rename training API routes to solo
```

---

### Task 4: Server WebSocket handlers — rename training WS → solo WS

**Files:**

- Rename: `server/speedfog_racing/websocket/training_manager.py` → `solo_manager.py`
- Rename: `server/speedfog_racing/websocket/training_mod.py` → `solo_mod.py`
- Rename: `server/speedfog_racing/websocket/training_spectator.py` → `solo_spectator.py`
- Modify: `server/speedfog_racing/websocket/__init__.py`
- Modify: `server/speedfog_racing/main.py`

**Changes in `solo_manager.py`:**

- `TrainingRoom` → `SoloRoom`
- `TrainingModConnection` → `SoloModConnection`
- `TrainingSpectatorConnection` → `SoloSpectatorConnection`
- `TrainingConnectionManager` → `SoloConnectionManager`
- `training_manager` → `solo_manager` (module-level instance)

**Changes in `solo_mod.py`:**

- `handle_training_mod_websocket()` → `handle_solo_mod_websocket()`
- `build_training_participant_info()` → `build_solo_participant_info()`
- `_send_training_auth_ok()` → `_send_solo_auth_ok()`
- `_broadcast_training_leaderboard()` → `_broadcast_solo_leaderboard()`
- `_broadcast_training_zone_update()` → `_broadcast_solo_zone_update()`
- Session name format: `f"Solo {format_pool_display_name(seed.pool_name)}"` (was "Training ...")
- All model refs: `SoloSession`, `SoloSessionStatus`

**Changes in `solo_spectator.py`:**

- `handle_training_spectator_websocket()` → `handle_solo_spectator_websocket()`
- Import updates

**Changes in `__init__.py`:**

- Update all imports and `__all__` exports

**Changes in `main.py`:**

- Routes: `/ws/training/{session_id}` → `/ws/solo/{session_id}`
- Routes: `/ws/training/{session_id}/spectate` → `/ws/solo/{session_id}/spectate`
- Import updates
- Update `scan_pool` startup to scan nested structure (`race/*/`, `solo/*/`):

  ```python
  pool_base = Path(settings.seeds_pool_dir)
  for pool_type_dir in ["race", "solo"]:
      type_dir = pool_base / pool_type_dir
      if not type_dir.exists():
          continue
      for subdir in sorted(type_dir.iterdir()):
          if subdir.is_dir() and (subdir / "config.toml").exists():
              added = await scan_pool(db, subdir.name, pool_type=pool_type_dir)
  ```

**Commit:**

```
refactor(server): rename training WebSocket handlers to solo
```

---

### Task 5: Pool TOML configs — delete duplicates, add name field

**Files:**

- Delete: `tools/pools/training_standard.toml`
- Delete: `tools/pools/training_sprint.toml`
- Delete: `tools/pools/training_boss_shuffle.toml`
- Delete: `tools/pools/training_hardcore.toml`
- Modify: `tools/pools/standard.toml` — add `name = "Standard"`
- Modify: `tools/pools/sprint.toml` — add `name = "Sprint"`
- Modify: `tools/pools/boss_shuffle.toml` — add `name = "Boss Shuffle"`
- Modify: `tools/pools/hardcore.toml` — add `name = "Hardcore"`

**Add `name` field to `[display]` in each pool config:**

```toml
[display]
name = "Standard"
sort_order = 1
estimated_duration = "~1h"
description = "Balanced race with legacy dungeons and bosses"
```

**Update `PoolConfig` schema** in `schemas.py` to include `name`:

```python
class PoolConfig(BaseModel):
    name: str | None = None
    type: str = "race"
    ...
```

**Update `get_pool_config()`** in `seed_service.py` to return `name`:

```python
return {
    "name": display.get("name"),
    "type": display.get("type", "race"),
    ...
}
```

**Commit:**

```
refactor(tools): delete duplicate training pool configs, add display name
```

---

### Task 6: Update generate_pool.py — add --solo flag

**Files:**

- Modify: `tools/generate_pool.py`

**Changes:**

- Add `--solo` flag to argparse
- When `--solo`: output to `output/solo/{pool_name}/`, inject `type = "solo"` into config.toml
- When not `--solo`: output to `output/race/{pool_name}/`
- Pool discovery: only list base configs (no `training_*` since they're deleted)
- Config.toml written to output: copy pool TOML, set `[display] type` based on --solo flag

**Key changes in `main()`:**

```python
# Output directory structure: output/race/standard/ or output/solo/standard/
pool_type = "solo" if args.solo else "race"
output_pool_dir = args.output / pool_type / args.pool
output_pool_dir.mkdir(parents=True, exist_ok=True)

# Copy pool TOML as config.toml, inject type
import tomllib, tomli_w  # or manual string manipulation
config_content = pool_config.read_text()
# Inject/replace type field in [display] section
shutil.copy2(pool_config, output_pool_dir / "config.toml")
# Then patch the type field in the copied config.toml
```

Note: Since we don't want to add `tomli_w` as a dependency, use string manipulation to inject `type = "solo"` into the copied config.toml (or just let the config have no `type` field and rely on directory structure).

**Simpler approach:** The config.toml doesn't need a `type` field at all — the server infers pool_type from the directory structure (`race/` vs `solo/`). Just copy the same TOML to both locations.

**Commit:**

```
feat(tools): add --solo flag to generate_pool.py
```

---

### Task 7: Update deploy-seeds.sh — support --solo flag and new directory structure

**Files:**

- Modify: `deploy/deploy-seeds.sh`

**Changes:**

- Add `--solo` flag
- Generation: pass `--solo` to `generate_pool.py` when set
- Output structure: `output/race/standard/` or `output/solo/standard/`
- Upload: tar now includes `race/` and/or `solo/` parent directories
- Discard SQL: include `pool_type` in WHERE clause:

  ```sql
  UPDATE seeds SET status = 'DISCARDED'
  WHERE status IN ('AVAILABLE', 'CONSUMED')
  AND pool_name = '$pool' AND pool_type = '$type'
  ```

- Pool discovery: generate for `race` by default, `solo` with `--solo`, or both with `--all-types`

**Commit:**

```
feat(deploy): update deploy-seeds.sh for pool_type structure
```

---

### Task 8: Frontend — rename training → solo (API client + types)

**Files:**

- Modify: `web/src/lib/api.ts`
- Rename: `web/src/lib/utils/training.ts` → `solo.ts`
- Modify: `web/src/lib/format.ts` (if needed)

**Changes in `api.ts`:**

- Interfaces: `TrainingSession` → `SoloSession`, `TrainingSessionDetail` → `SoloSessionDetail`, `TrainingActivityItem` → `SoloActivityItem`
- Functions: `fetchTrainingPools()` → `fetchSoloPools()`, `createTrainingSession()` → `createSoloSession()`, `fetchTrainingSessions()` → `fetchSoloSessions()`, `fetchTrainingSession()` → `fetchSoloSession()`, `abandonTrainingSession()` → `abandonSoloSession()`, `downloadTrainingPack()` → `downloadSoloPack()`
- API base path: `/training` → `/solo`
- Query param: `?type=training` → `?type=solo`
- Fields: `training_count` → `solo_count`
- Download filename: `speedfog_solo_${sessionId}.zip`

**Changes in `solo.ts` (renamed from training.ts):**

- `displayPoolName()` — remove `.replace(/^training_/, "")` (pool*name is already clean from API), or replace with `.replace(/^solo*/, "")` for safety
- Since pool_name from API is now just "standard", this function can simplify to just `formatPoolName(poolName)`

**Commit:**

```
refactor(web): rename training API client to solo
```

---

### Task 9: Frontend — rename routes, stores, components

**Files:**

- Rename directory: `web/src/routes/training/` → `web/src/routes/solo/`
- Rename: `web/src/lib/stores/training.svelte.ts` → `solo.svelte.ts`
- Rename: `web/src/lib/components/TrainingSessionCard.svelte` → `SoloSessionCard.svelte`
- Modify: `web/src/routes/+layout.svelte` (nav links)
- Modify: `web/src/routes/+page.svelte` (homepage links)
- Modify: `web/src/routes/dashboard/+page.svelte`
- Modify: `web/src/routes/user/[username]/+page.svelte`
- Modify: `web/src/routes/admin/+page.svelte`
- Modify: `web/src/routes/help/+page.svelte`
- Modify: `web/src/lib/components/PoolStatsTable.svelte`

**Changes in store (`solo.svelte.ts`):**

- `TrainingStore` → `SoloStore`
- `trainingStore` → `soloStore`
- WS URL: `/ws/training/{id}/spectate` → `/ws/solo/{id}/spectate`
- Console log prefix: `[SoloWS]`

**Changes in routes:**

- `training/+page.svelte` → `solo/+page.svelte`: title, CSS classes, imports
- `training/[id]/+page.svelte` → `solo/[id]/+page.svelte`: imports, navigation, back link text "← Solo"
- All `goto('/training/...')` → `goto('/solo/...')`

**Changes in layout:**

- Nav link: `/training` → `/solo`, label "Solo" (was "Training")

**Changes in dashboard/profile pages:**

- `training` field refs → `solo`
- Labels: "Training" → "Solo"

**Commit:**

```
refactor(web): rename training routes and components to solo
```

---

### Task 10: Mod — rename training field with backward compat

**Files:**

- Modify: `mod/src/dll/config.rs`
- Modify: `mod/src/dll/websocket.rs`
- Modify: `mod/src/dll/tracker.rs`
- Modify: `mod/src/dll/ui.rs`

**Changes in `config.rs`:**

```rust
/// Solo mode — hides leaderboard, uses /ws/solo/ endpoint
#[serde(default, alias = "training")]
pub solo: bool,
```

The `alias = "training"` ensures existing seed packs with `training = true` still work.

**Changes in `websocket.rs`:**

```rust
let endpoint = if settings.solo { "solo" } else { "mod" };
```

**Changes in `tracker.rs`:**

```rust
if !self.config.server.solo {
    self.ws_client.send_ready();
}
```

**Changes in `ui.rs`:**

```rust
if !self.config.server.solo && self.show_leaderboard {
```

**Commit:**

```
refactor(mod): rename training to solo with backward compat alias
```

---

### ~~Task 11: Server tests~~ — MERGED into tasks 2-4

> **Design decision:** Tests are updated alongside each server component, not in a separate task.
>
> - Task 2: updates `test_solo.py` (renamed from `test_training.py`), `conftest.py` fixtures
> - Task 3: updates `test_admin.py`, `test_pool_stats.py`, `test_user_profile.py`, `test_discord.py`
> - Task 4: updates WS-related test assertions
> - Each task runs `uv run pytest -x -v` to verify before committing.

---

### Task 11: VPS deployment migration

**This task is a one-time deploy operation, not code.**

**Script to run on VPS (or add to deploy.sh as a migration step):**

Create `deploy/migrate-pool-dirs.sh`:

```bash
#!/usr/bin/env bash
# One-time migration: restructure seed pool directories
set -euo pipefail
SEEDS_DIR="${SEEDS_DIR:-/data/SpeedFog/racing/seeds}"

echo "Creating new directory structure..."
sudo -u speedfog mkdir -p "$SEEDS_DIR/race" "$SEEDS_DIR/solo"

echo "Moving race pools..."
for pool in standard sprint boss_shuffle hardcore; do
    if [ -d "$SEEDS_DIR/$pool" ]; then
        sudo -u speedfog mv "$SEEDS_DIR/$pool" "$SEEDS_DIR/race/$pool"
        echo "  $pool → race/$pool"
    fi
done

echo "Moving solo pools..."
for pool in training_standard training_sprint training_boss_shuffle training_hardcore; do
    base="${pool#training_}"
    if [ -d "$SEEDS_DIR/$pool" ]; then
        sudo -u speedfog mv "$SEEDS_DIR/$pool" "$SEEDS_DIR/solo/$base"
        echo "  $pool → solo/$base"
    fi
done

echo "Done! Run alembic upgrade head to update DB paths."
```

**Deploy order:**

1. Run `migrate-pool-dirs.sh` on VPS (moves directories)
2. Deploy code (new server + frontend)
3. Alembic migration runs automatically (updates DB pool_name, pool_type, folder_path)
4. Service restart picks up new pool structure

**Commit:**

```
feat(deploy): add one-time pool directory migration script
```

---

### Task 12: Update CLAUDE.md and documentation

**Files:**

- Modify: `CLAUDE.md` — update all training references to solo
- Modify: `docs/PROTOCOL.md` — update WS endpoint paths
- Modify: `CHANGELOG.md` — add entry under [Unreleased]

**CHANGELOG entry:**

```markdown
### Changed

- Renamed "Training" mode to "Solo" — better reflects actual usage
- Pool directory structure reorganized (`race/` and `solo/` subdirectories)
```

**Commit:**

```
docs: update documentation for training → solo rename
```

---

## Verification

After all tasks are complete:

**Server tests:**

```bash
cd server && uv run pytest -x -v
```

**Server linting:**

```bash
cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/
```

**Frontend checks:**

```bash
cd web && npm run check && npm run lint
```

**Mod check:**

```bash
cd mod && cargo check --lib && cargo test
```

**Grep for leftover "training" references (should only be in alembic migrations and docs/plans/):**

```bash
grep -ri "training" --include="*.py" --include="*.ts" --include="*.svelte" --include="*.rs" --include="*.toml" \
  --exclude-dir=alembic --exclude-dir=plans --exclude-dir=node_modules --exclude-dir=.venv
```

**Manual smoke test:**

1. Start server: `cd server && uv run speedfog-racing`
2. Start frontend: `cd web && npm run dev`
3. Verify `/solo` page loads
4. Verify `/api/pools?type=solo` returns pools
5. Verify pool names show correctly (no `training_` prefix anywhere)
