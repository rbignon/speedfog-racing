# Report Buggy Seed on Re-roll

**Date:** 2026-04-01
**Status:** Approved

## Goal

Allow the race organizer to flag a seed as buggy when re-rolling, quarantining it
until an admin decides to discard or restore it.

## User Flow

1. Organizer clicks "Re-roll Seed" in race controls (SETUP status)
2. Confirmation popup shows a checkbox: "Report this seed as buggy"
3. If checked, a text field appears for an optional description (e.g. "fog gate blocked at layer 3")
4. On confirm, the re-roll executes. If the checkbox was checked, the old seed gets
   status `REPORTED` instead of returning to `AVAILABLE`

## Backend Changes

### Model: `SeedStatus` enum

Add `REPORTED = "reported"` to `SeedStatus`.

### Model: `Seed` table

Add three nullable columns:

| Column            | Type                      | Notes                |
| ----------------- | ------------------------- | -------------------- |
| `reported_by_id`  | `UUID` FK -> `users.id`   | Who reported         |
| `reported_reason` | `Text`                    | Optional description |
| `reported_at`     | `DateTime(timezone=True)` | When reported        |

### Seed service: `get_available_seed()`

Exclude `REPORTED` seeds from the available pool (same as `CONSUMED`/`DISCARDED`).

### Seed service: `reroll_seed_for_race()`

Accept optional `report_buggy: bool` and `report_reason: str | None` parameters.
When `report_buggy` is true, set the old seed's status to `REPORTED` instead of
`AVAILABLE`, and populate `reported_by_id`, `reported_reason`, `reported_at`.

### API: `POST /races/{race_id}/reroll-seed`

Accept an optional JSON body:

```json
{
  "report_buggy": true,
  "report_reason": "fog gate stuck at layer 3"
}
```

Both fields default to `false`/`null` if body is omitted (backward-compatible).

Create a Pydantic schema `RerollSeedRequest` with:

- `report_buggy: bool = False`
- `report_reason: str | None = None`

### API: `GET /api/admin/reported-seeds`

Returns list of seeds with status `REPORTED`, including:

- `seed_number`, `pool_name`, `difficulty_score`
- `reported_by` (username), `reported_reason`, `reported_at`

### API: `POST /api/admin/seeds/{seed_id}/resolve`

Body: `{ "action": "discard" | "restore" }`

- `discard`: sets status to `DISCARDED`
- `restore`: sets status to `AVAILABLE`, clears `reported_by_id`, `reported_reason`, `reported_at`

### Seed service: `discard_pool()`

Update the WHERE clause to include `REPORTED` alongside `AVAILABLE` and `CONSUMED`:

```python
Seed.status.in_([SeedStatus.AVAILABLE, SeedStatus.CONSUMED, SeedStatus.REPORTED])
```

## Deploy Script

### `deploy/deploy-seeds.sh`: `discard_seeds()`

Update the SQL WHERE clause to include `REPORTED`:

```sql
UPDATE seeds SET status = 'DISCARDED'
  WHERE status IN ('AVAILABLE', 'CONSUMED', 'REPORTED')
  AND pool_name = '$pool'
```

## Frontend Changes

### `RaceControls.svelte`

In the re-roll `ConfirmModal`:

- Add a checkbox "Report this seed as buggy" (unchecked by default)
- When checked, show a text input for description (optional, placeholder: "Describe the issue...")
- Pass `{ report_buggy, report_reason }` to `rerollSeed()`

### `api.ts`: `rerollSeed()`

Change from no-body POST to accept optional body:

```typescript
export async function rerollSeed(
  raceId: string,
  reportBuggy?: boolean,
  reportReason?: string,
): Promise<RaceDetail> {
  const body = reportBuggy
    ? { report_buggy: true, report_reason: reportReason }
    : undefined;
  const response = await fetch(`${API_BASE}/races/${raceId}/reroll-seed`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<RaceDetail>(response);
}
```

### Admin page (`admin/+page.svelte`)

Add a "Reported Seeds" section at the top of the Seeds tab:

- Table columns: Seed Number, Pool, Reporter, Reason, Date, Actions
- Actions: "Discard" button (danger), "Restore" button (secondary)
- Section hidden when no reported seeds exist

### `api.ts`: admin functions

```typescript
export async function fetchReportedSeeds(): Promise<ReportedSeed[]>;
export async function resolveReportedSeed(
  seedId: string,
  action: "discard" | "restore",
): Promise<void>;
```

## Database Migration

Alembic migration to:

1. Add `REPORTED` to `seedstatus` enum (PostgreSQL `ALTER TYPE ... ADD VALUE`)
2. Add `reported_by_id`, `reported_reason`, `reported_at` columns to `seeds` table

## Tests

- Re-roll with `report_buggy=true`: old seed becomes `REPORTED` with reason and reporter
- Re-roll with `report_buggy=false` (or no body): old seed becomes `AVAILABLE` (unchanged behavior)
- `REPORTED` seeds excluded from `get_available_seed()`
- Admin resolve discard: `REPORTED` -> `DISCARDED`
- Admin resolve restore: `REPORTED` -> `AVAILABLE`, report fields cleared
- `discard_pool()` includes `REPORTED` seeds
- Non-admin cannot access reported-seeds or resolve endpoints
