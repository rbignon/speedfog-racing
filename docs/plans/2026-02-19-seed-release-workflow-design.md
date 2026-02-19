# Seed Release Workflow

**Date:** 2026-02-19
**Status:** Approved

## Problem

Participants can download their seed pack immediately after joining a race in SETUP. This allows:

- **Cheating:** installing the seed early and exploring the map before others
- **Spoilers:** seeing the seed layout before the race starts
- **Coordination issues:** no way to ensure everyone is ready simultaneously

## Solution: Manual Seed Release

Add a `seeds_released_at` nullable timestamp to the Race model. The organizer explicitly releases seeds before starting the race. Downloads are gated on this field.

### New Field

```
Race.seeds_released_at: Optional[datetime]  — NULL by default, set to now() on release
```

### New Endpoint

```
POST /api/races/{race_id}/release-seeds
```

Sets `seeds_released_at = now()`. Requires organizer role, race must be in SETUP, seeds must not already be released.

### Modified Behaviors

| Action        | Effect on `seeds_released_at` | Effect on Seed    |
| ------------- | ----------------------------- | ----------------- |
| Release Seeds | → `now()`                     | unchanged         |
| Reroll Seed   | → `NULL`                      | new seed assigned |
| Start Race    | unchanged                     | unchanged         |
| Reset Race    | unchanged                     | unchanged         |

**Reroll post-release** acts as an implicit un-release: the new seed hasn't been distributed, so `seeds_released_at` resets to NULL. Participants must re-download.

### Download Gating

The `GET /api/races/{race_id}/my-seed-pack` and `GET /api/races/{race_id}/download/{mod_token}` endpoints return **403** if `seeds_released_at is NULL`.

### WebSocket Notification

When seeds are released, broadcast a message to spectators/mods so the UI updates in real-time:

```json
{ "type": "seeds_released" }
```

## UX: Organizer Button States

### Before release (`seeds_released_at = NULL`, status = SETUP)

- **"Release Seeds"** — visible, active
- **"Reroll Seed"** — visible, active
- **"Start Race"** — visible, greyed out, tooltip: "Release seeds first"

### After release (`seeds_released_at != NULL`, status = SETUP)

- **"Release Seeds"** — replaced by "Seeds released ✓" indicator
- **"Reroll Seed"** — visible, active (with confirmation dialog: "Participants may have already downloaded. Rerolling will require everyone to re-download. Continue?")
- **"Start Race"** — visible, active

### Participant Experience

- **Before release:** no download button visible, status text "Waiting for seeds..."
- **After release:** download button appears, participant downloads and installs (<1 min)
- **After reroll:** download button disappears, back to "Waiting for seeds..."

## UX Flow Summary

```
SETUP (seeds locked)
  │
  ├─ Organizer: "Release Seeds"
  │
  ▼
SETUP (seeds available)
  │
  ├─ Participants download & install (<1 min)
  ├─ Mods connect → "Ready" indicator
  │
  ├─ [Optional] Organizer: "Reroll Seed" → back to seeds locked
  │
  ├─ Organizer: "Start Race"
  │
  ▼
RUNNING
```

## Scope

- `scheduled_at` remains optional (no change)
- No automatic release based on time (can be added later)
- The vocal Discord coordination is the primary synchronization mechanism
