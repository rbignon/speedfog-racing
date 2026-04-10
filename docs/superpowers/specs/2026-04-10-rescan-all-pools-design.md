# Discard + Rescan All Pools (Admin Seeds Tab)

Date: 2026-04-10

## Goal

Add a single "Discard + Rescan All Pools" button to the Seeds tab of `/admin` so that, after a SpeedFog update regenerates seed files on disk, an admin can mark all existing seeds as discarded and pick up the newly generated seeds across every pool in one click.

## Background

The Seeds tab (`web/src/routes/admin/+page.svelte:597-690`) already exposes per-pool Scan and Discard buttons that call `POST /admin/seeds/scan` and `POST /admin/seeds/discard` (`server/speedfog_racing/api/admin.py:87-127`). Both accept `{ pool_name }`.

Separately, the CLI `speedfog-scan-seeds` (`server/speedfog_racing/scan_seeds.py`) discovers pools by listing subdirectories of `settings.seeds_pool_dir` that contain a `config.toml` file, then scans each one. With no `--pool` argument it processes every discovered pool.

The new button is the UI equivalent of "rerun the full scan for every pool, after first invalidating the current contents", and it should use the same discovery mechanism as the CLI so the two stay consistent.

Scan matches seed files by the hash extracted from the filename (`seed_<hash>.zip` -> `seed_number`). Regenerated seeds have new hashes and therefore new filenames, so running discard then scan on a pool correctly: (a) flags the old seeds as `DISCARDED` in the DB, and (b) inserts rows for the new files.

## Architecture

### Shared pool discovery helper

Move `_discover_pools()` from `server/speedfog_racing/scan_seeds.py` into `server/speedfog_racing/services/seed_service.py` as a public, synchronous function `discover_pools()`. `scan_seeds.py` imports it from the service module and removes its local copy. `services/__init__.py` exports it.

Behaviour is unchanged: sorted list of subdirectory names under `settings.seeds_pool_dir` that contain a `config.toml` file; returns `[]` if the base directory does not exist.

### Backend endpoint

New route in `server/speedfog_racing/api/admin.py`:

```python
class RescanAllPoolResult(BaseModel):
    pool_name: str
    discarded: int
    added: int

class RescanAllError(BaseModel):
    pool_name: str
    error: str

class RescanAllResponse(BaseModel):
    pools: list[RescanAllPoolResult]
    errors: list[RescanAllError]
    total_discarded: int
    total_added: int

@router.post("/seeds/rescan-all", response_model=RescanAllResponse)
async def rescan_all_seeds(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RescanAllResponse: ...
```

Handler logic:

1. Call `discover_pools()`.
2. For each pool, in its own `try`/`except Exception`: call `discard_pool(db, pool)` then `scan_pool(db, pool)`, and append a `RescanAllPoolResult` to `pools`.
3. On exception: log via `logger.exception("Failed to rescan pool '%s'", pool)`, append a `RescanAllError` to `errors`, continue the loop.
4. Compute `total_discarded` and `total_added` by summing the successful entries.
5. Return the response.

No new migration. No changes to existing `scan_pool()`, `discard_pool()`, `get_pool_stats()`, or the per-pool endpoints.

Concurrency note: both `scan_pool()` and `discard_pool()` already call `db.commit()` internally, so the loop commits progressively. If the third pool raises, the first two are still persisted. This matches the CLI's behaviour (continues on per-pool errors, reports the failure at the end).

### Frontend API client

In `web/src/lib/api.ts`:

```ts
export interface AdminRescanAllResponse {
  pools: Array<{ pool_name: string; discarded: number; added: number }>;
  errors: Array<{ pool_name: string; error: string }>;
  total_discarded: number;
  total_added: number;
}

export async function adminRescanAllPools(): Promise<AdminRescanAllResponse>;
```

`POST /admin/seeds/rescan-all`, no request body. Same auth/error handling pattern as the existing `adminScanPool` / `adminDiscardPool`.

### Frontend UI

In `web/src/routes/admin/+page.svelte`, inside the "Seed Pools" section header (above the table at lines ~597-690):

- Add a single `Discard + Rescan All Pools` button.
- Add new state:

  ```ts
  let rescanAllLoading = $state(false);
  let rescanAllMessage: {
    type: "success" | "warning" | "error";
    text: string;
  } | null = $state(null);
  ```

  This mirrors the existing `recalcMessage` pattern used by `handleRecalculateStats()` (around line 288).

- Add handler `handleRescanAll()`:
  1. Show a blocking `confirm()` dialog with the message
     `"Discard and rescan all pools? All current seeds will be marked as discarded. This cannot be undone."`.
  2. If cancelled, return.
  3. Set `rescanAllLoading = true` and `rescanAllMessage = null`; in a `try`/`catch`/`finally`:
     - `try`: call `adminRescanAllPools()`, `await loadSeedStats()`, then set `rescanAllMessage` based on the response (success/warning/empty copy below).
     - `catch`: set `rescanAllMessage = { type: 'error', text: e instanceof Error ? e.message : 'Failed to rescan pools.' }`.
     - `finally`: `rescanAllLoading = false;`.
- The button is `disabled` while `rescanAllLoading` is true **or** any per-pool `actionLoading` entry is active.
- The per-pool Scan/Discard buttons must also check `rescanAllLoading` when computing their `disabled` state, to prevent overlapping writes.
- Render `rescanAllMessage` inline near the button using the same visual styling as `recalcMessage` (a small status banner with success/warning/error variants). Add a `'warning'` variant if the existing message component only supports `'success' | 'error'` today.

Message copy:

- Success (no errors, at least one pool): `"Rescanned N pool(s): X new seeds added, Y discarded"`.
- Warning (one or more per-pool errors): `"Rescanned N pool(s): X added, Y discarded; K pool(s) failed, see server logs"`.
- Empty (no pools discovered): `"No pools found"` with `type: 'warning'`.

## Data Flow

```
User clicks "Discard + Rescan All Pools"
  -> confirm() dialog
  -> POST /admin/seeds/rescan-all
       -> discover_pools() (filesystem)
       -> for each pool (try/except):
            discard_pool(db, pool)
            scan_pool(db, pool)
       -> build RescanAllResponse
  -> frontend reloads seedStats (GET /admin/seeds/stats)
  -> inline rescanAllMessage set with totals (or warning if errors)
```

## Error Handling

| Case                                      | Behaviour                                                                            |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| Per-pool exception during discard or scan | Caught, `logger.exception`, added to `errors[]`, loop continues                      |
| `discover_pools()` returns `[]`           | 200 with empty `pools` and `errors`; frontend shows "No pools found" warning message |
| Non-admin caller                          | 403 via `require_admin` dependency                                                   |
| Network failure / 500                     | Caught in the handler's `catch`; `rescanAllMessage` set to error variant             |
| User cancels `confirm()`                  | No request sent                                                                      |
| Concurrent click while already running    | Button is disabled, so the second click is inert                                     |

## Testing

### Backend

Add tests in the existing seeds admin test module (create one if none exists):

1. **Happy path** - two pool directories with `config.toml`, each with one existing seed (available) and one new seed file on disk. Expect: response with two entries, each reporting `discarded=1, added=1`; totals match; DB reflects DISCARDED + AVAILABLE rows as expected.
2. **Empty discovery** - base `seeds_pool_dir` exists but has no subdirs with `config.toml`. Expect: 200, empty `pools`, empty `errors`, totals zero.
3. **Partial failure** - two pools; mock `scan_pool` (or make one dir's zips unreadable) so one pool raises. Expect: one entry in `pools`, one entry in `errors`, other pool's DB state is still updated.
4. **Auth** - non-admin user -> 403.

Add a unit test for `discover_pools()` in `test_seed_service.py` (create if missing): `tmp_path` with a mix of `config.toml` / non-`config.toml` subdirs and plain files; expect sorted list containing only the `config.toml` ones.

### Frontend

Thin coverage: `adminRescanAllPools()` URL, method, and response parsing in `web/src/lib/__tests__/` (same style as any existing `adminScanPool` / `adminDiscardPool` tests, if present). No Svelte component test for the handler since it is a trivial `confirm()` + fetch + toast wrapper.

## Out of Scope (YAGNI)

- No progress streaming (SSE/websocket). The operation is fast enough to block on a single request.
- No per-pool selection in the new endpoint. The existing per-pool buttons already cover targeted operations.
- No dry-run mode.
- No undo.
- No changes to the existing per-pool Scan/Discard endpoints or CLI semantics.

## Files Touched

- `server/speedfog_racing/services/seed_service.py` - add `discover_pools()`.
- `server/speedfog_racing/services/__init__.py` - export `discover_pools`.
- `server/speedfog_racing/scan_seeds.py` - import `discover_pools` from service, drop local copy.
- `server/speedfog_racing/api/admin.py` - add response schemas and `POST /admin/seeds/rescan-all` route.
- `server/tests/` - add tests for the new endpoint and for `discover_pools()`.
- `web/src/lib/api.ts` - add `AdminRescanAllResponse` interface and `adminRescanAllPools()`.
- `web/src/routes/admin/+page.svelte` - add button, state, handler in the Seed Pools section.
- `web/src/lib/__tests__/` - add thin test for the new API client function if tests for the sibling functions already exist.
