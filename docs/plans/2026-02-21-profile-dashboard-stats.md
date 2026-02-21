# Profile & Dashboard Stats Redesign

**Date:** 2026-02-21
**Status:** Approved

## Goal

Simplify and align the dashboard and profile pages by removing misleading stats (podiums, 1st places), adding per-pool performance stats, and showing a Twitch link on profiles.

## Changes Summary

1. **Stat cards**: Remove Podiums/1st Places, keep 4 cards on one line (Races, Training, Organized, Casted)
2. **Context cards**: Remove Best Recent Placement and Podium Rate from dashboard
3. **Pool stats table**: New table showing per-pool performance, separated by race/training
4. **Twitch link**: Clickable Twitch icon next to display name on profile page
5. **Same stats on both pages**: Dashboard and profile show identical stat cards + pool stats table; difference is contextual (dashboard has Active Now, profile has full Activity Timeline + Twitch link)

## Backend

### New endpoint: `GET /api/users/{username}/pool-stats`

```
PoolStatsResponse {
    pools: PoolStats[] {
        pool_name: str
        race: PoolTypeStats | null {
            runs: int
            avg_time_ms: int
            avg_deaths: float
            best_time_ms: int
        }
        training: PoolTypeStats | null {
            runs: int
            avg_time_ms: int
            avg_deaths: float
            best_time_ms: int
        }
        total_runs: int
    }
}
```

- Aggregates from `Participant` (finished races) and `TrainingSession` (finished sessions)
- Only finished runs count in all stats
- Sorted by `total_runs` descending
- Lines with 0 runs return `null` for the type stats

### Schema cleanup: `UserStatsResponse`

Remove: `podium_count`, `first_place_count`, `podium_rate`, `best_recent_placement`

Keep: `race_count`, `training_count`, `organized_count`, `casted_count`

## Frontend

### Stat Cards (dashboard + profile)

- 4 cards: Races, Training, Organized, Casted
- Grid: `repeat(4, 1fr)` desktop, `repeat(2, 1fr)` mobile
- Values in gold `#C8A44E`, labels in secondary text

### Pool Stats Table (dashboard + profile)

```
Pool              Type      Runs           Avg Time   Avg Deaths  Best
──────────────────────────────────────────────────────────────────────
Standard          Race      ██████████ 12  42:15      8.2         35:40
                  Training  ██████ 8      38:50      6.1         33:20
──────────────────────────────────────────────────────────────────────
Sprint            Race      ████ 5        18:30      4.5         15:10
                  Training  ██ 3          16:40      3.0         14:50
```

- Section heading "Pool Stats" in gold h2
- Card with surface background `#162032`
- Runs bar proportional to max runs across all rows
- Bar color: gold `#C8A44E` for Race, purple `#8B5CF6` for Training
- Times formatted as `mm:ss` (or `h:mm:ss` if > 1h)
- 0-run lines: no bar, stats shown as dashes `—`
- Always show both Race and Training lines per pool (even if empty)
- Pool name displayed once on the Race line (first row of group)
- Light separator between pool groups
- Mobile: horizontal scroll or stacked card layout

### Twitch Link (profile only)

- Twitch SVG icon (~16-18px) next to display name, between name and role badge
- Color: `#9CA3AF` default, `#8B5CF6` on hover
- Links to `https://twitch.tv/{twitch_username}`, opens in new tab
- Only on `/user/[username]`, not on dashboard
