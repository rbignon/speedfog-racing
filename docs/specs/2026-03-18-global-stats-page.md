# Global Stats Page

Community statistics page with ELO ranking, zone/boss analytics, and behavioral player profiles.

## Overview

A public page (`/stats`) with 4 tabs: Leaderboard, Zones, Bosses, Players. Complemented by a "Play Style" section on user profile pages.

The core design challenge: seeds are all different, so absolute time comparisons across races are meaningless. All stats are either relative (comparing players within the same race) or aggregated by zone/boss identity (which is stable across seeds via `display_name`).

## ELO Rating System

### Algorithm

Multi-player ELO adaptation. After each finished race, every pair of finishers is compared. For each pair (A, B):

1. Compute expected scores:
   - `E_A = 1 / (1 + 10^((R_B - R_A) / 400))`
   - `E_B = 1 - E_A`
2. Actual scores: the player who placed higher gets `S = 1`, the other gets `S = 0`
3. Rating change: `delta = K * (S - E)` where `K` is the K-factor

Sum all pairwise deltas for each player, divide by `(N-1)` where N is the number of finishers, then apply to the rating.

### Parameters

- **Starting ELO**: 1500
- **K-factor**: 32 (standard, appropriate for small player base)
- **Eligible results**: only FINISHED participants count. ABANDONED participants are excluded (neutral, no ELO change).
- **Minimum races for display**: a player's ELO appears on the leaderboard after 3 finished races (provisional indicator for fewer).

### Precision

ELO ratings are stored as floats internally and displayed as rounded integers in the UI. The pairwise delta formula (`K * (S - E) / (N - 1)`) produces fractional values; truncating at each step would cause drift over time. `EloHistory.delta` is also stored as float to preserve precision and ensure admin recalculation is reproducible.

### Storage

New columns on the `User` model:

- `elo_rating: Mapped[float] = mapped_column(default=1500.0)` -- current ELO (displayed as int)
- `elo_races: Mapped[int] = mapped_column(default=0)` -- number of rated races

New table `EloHistory`:

- `id`: primary key
- `user_id`: FK to User, indexed with `(user_id, created_at)` for trend queries
- `race_id`: FK to Race
- `elo_before: float`
- `elo_after: float`
- `delta: float` -- signed change
- `created_at: datetime`

This table serves both the trend display (last N deltas) and full recalculation audit trail.

### Calculation Trigger

Incremental: computed when race status transitions to FINISHED. This happens in two code paths:

1. `finish_race()` in `api/races.py` (organizer force-finish)
2. `check_race_auto_finish()` in `services/race_lifecycle.py` (last player finishes or abandons)

Both paths call a new `update_elo_ratings(race_id, session)` service function. To avoid duplication, the service function is idempotent: it checks if `EloHistory` entries already exist for this race and skips if so.

### Admin Recalculation

`POST /api/admin/stats/recalculate` (admin-only): clears all ELO data and replays all finished races in chronological order (`started_at`). This covers formula changes or bug fixes.

## Behavioral Traits

### The 7 Traits

Each trait is scored 0-100 per player, based on their behavior **relative to other participants in the same race**, aggregated across all finished races.

Each per-race trait ranks players within a race. Let `N` = number of finishers, `igt_rank` = position sorted by IGT ascending (1 = fastest), `death_rank` = position sorted by deaths ascending (1 = fewest). Ranks are 1-indexed. Ties share the same rank (average rank method).

1. **Fonceur**: finishes fast relative to opponents but with more deaths.
   - Per race: `raw = max(0, death_rank - igt_rank) / (N - 1)`, clamped to [0, 1]
   - Scores high when fast (low igt_rank) but dies a lot (high death_rank)
   - Requires N >= 2

2. **Prudent**: low deaths relative to time spent.
   - Per race: `raw = max(0, igt_rank - death_rank) / (N - 1)`, clamped to [0, 1]
   - Scores high when few deaths (low death_rank) but slower (high igt_rank)
   - Requires N >= 2

3. **Coute que coute**: finishes races despite being far behind.
   - Global: `completion_rate = finished_races / total_participated_races`
   - Per finished race: `gap_ratio = (player_igt - leader_igt) / leader_igt`
   - `raw = completion_rate * avg(gap_ratio)`, normalized so that a player who finishes 100% of races with 50% avg gap scores ~0.75
   - Solo finisher (leader) has gap_ratio = 0, scoring low on this trait (correct: they were not behind)
   - Requires at least 3 finished races

4. **Rage Quitter**: high abandon rate.
   - Global: `raw = abandoned_races / total_participated_races`
   - Not per-race relative. A player who abandons 50%+ of races scores very high.

5. **Explorateur**: visits many nodes, high backtrack rate.
   - Per race: `coverage = unique_nodes_visited / total_nodes_in_seed`
   - Per race: `backtrack_rate = backtrack_entries / total_zone_history_entries` (where a backtrack entry is a revisit of a previously visited node)
   - `raw = 0.6 * coverage + 0.4 * backtrack_rate`

6. **Routard**: takes unusual paths compared to other players on the same race.
   - Per race: `others_nodes = union of all other finishers' visited node sets`
   - `unique_nodes = player_nodes - others_nodes` (nodes only this player visited)
   - `raw = |unique_nodes| / |player_nodes|` (proportion of unique routing)
   - Requires N >= 2

7. **Boss Slayer**: fewer deaths than average on hard bosses.
   - Per boss encounter in a race: compute `avg_deaths_on_boss` across all finishers who visited that boss
   - Player's score for that boss: `max(0, 1 - player_deaths / avg_deaths)` (scores 1.0 if zero deaths, 0.0 if at average)
   - Weight each boss by its global difficulty (average deaths across all races for that boss)
   - Per race raw = weighted average of per-boss scores
   - Only counts `boss_arena`, `major_boss`, `final_boss` node types (each has its own `node_id` in graph_json)

### Scoring Method

For per-race traits (1, 2, 5, 6, 7):

1. Compute a raw score per race (0-1 scale)
2. Average across all finished races (minimum 3 races for trait to be scored)
3. Normalize to 0-100

For global traits (3, 4):

1. Compute directly from aggregate stats across all races
2. Normalize to 0-100

The **dominant trait** is the trait with the highest score (minimum threshold of 40 to qualify; if no trait reaches 40, no dominant trait is assigned).

### Storage

New table `PlayerTraitScores` (upsert on each recalculation via `merge()`):

- `user_id`: FK to User (primary key)
- `dominant_trait: str | None` -- enum name of highest trait, or null
- `fonceur: int` -- 0-100
- `prudent: int`
- `coute_que_coute: int`
- `rage_quitter: int`
- `explorateur: int`
- `routard: int`
- `boss_slayer: int`
- `updated_at: datetime`

### Calculation Trigger

Recalculated alongside ELO at race finish: `update_player_traits(race_id, session)`. Only recalculates traits for participants of the just-finished race (not all players).

The admin recalculate endpoint also recomputes all traits.

## Zone & Boss Stats

### Data Source

Aggregated on the fly from `Participant.zone_history` and `Seed.graph_json`. No pre-computed tables.

Each entry in `zone_history` has `node_id` and `igt_ms`. The `node_id` maps to a node in `graph_json.nodes[node_id]` which has `type`, `display_name`, and `layer`.

Deaths per zone are derived from `Participant.death_count` attribution in `handle_status_update` (deaths attributed to the last matching zone_history entry).

### Zone Tab

Aggregates nodes where `type` is `legacy_dungeon` or `mini_dungeon`:

- **Deadliest zones**: sorted by total deaths across all races, grouped by `display_name`
- **Most visited zones**: sorted by visit frequency (number of races where at least one player visited the zone / total races), grouped by `display_name`

Each zone shows its type badge (Legacy / Mini).

### Bosses Tab

Aggregates nodes where `type` is `boss_arena`, `major_boss`, or `final_boss`:

- **Columns**: boss name (`display_name`), type badge, encounter count, average deaths per encounter, max deaths in a single encounter, average time spent
- **Default sort**: by average deaths descending (deadliest first)

### Query Strategy

Since zone_history is a JSON column, aggregation requires iterating through all finished participants' zone_history entries. With ~20 players and 5-7 races/week, this is a few hundred records at most.

The API endpoints:

- `GET /api/stats/zones` -- returns aggregated zone stats
- `GET /api/stats/bosses` -- returns aggregated boss stats

Both query all participants where `status = FINISHED`, join with their race's seed to get `graph_json`, then aggregate in Python (not SQL, since the data is in JSON columns).

Optional query parameter: `pool` to filter by seed pool name.

At current scale (~100-200 finished participant records), no caching is needed. If the dataset grows significantly, add a TTL cache (invalidated on race finish) to avoid re-scanning all zone_history JSON on every request.

## API Endpoints

### Public Stats

- `GET /api/stats/leaderboard` -- ELO leaderboard
  - Response: `{ players: [{ user, elo_rating, elo_races, wins, losses, trend_delta, provisional }], community: { total_races, active_players, total_deaths, hours_raced } }`
  - `trend_delta`: sum of last 3 ELO deltas from `EloHistory`
  - `wins`: count of 1st place finishes (lowest `igt_ms` among FINISHED participants; ties broken by fewer deaths)
  - `losses`: finished races minus wins
  - Both computed on the fly by scanning Participant records (no denormalized columns needed at current scale)
  - Players sorted by `elo_rating` descending
  - `provisional: true` for players with `elo_races < 3`
  - Community stats definitions:
    - `total_races`: count of races with status FINISHED
    - `active_players`: users with at least 1 finished race in the last 30 days
    - `total_deaths`: sum of `death_count` across all FINISHED participants
    - `hours_raced`: sum of `igt_ms` across all FINISHED participants, converted to hours

- `GET /api/stats/zones` -- zone analytics
  - Response: `{ deadliest: [{ display_name, type, total_deaths, avg_deaths_per_visit }], most_visited: [{ display_name, type, visit_rate, total_visits }] }`
  - Optional query param: `?pool=standard`

- `GET /api/stats/bosses` -- boss analytics
  - Response: `{ bosses: [{ display_name, type, encounters, avg_deaths, max_deaths, avg_time_ms }] }`
  - Default sort: `avg_deaths` descending
  - Optional query param: `?pool=standard`

- `GET /api/stats/players` -- player profiles by trait
  - Response: `{ profiles: { fonceur: [{ user, score, elo_rating }], prudent: [...], ... } }`
  - Each trait list sorted by score descending, limited to top 10
  - Players appear only under their dominant trait
  - Players with no dominant trait (no score >= 40) do not appear in this tab; they are still visible via their profile page and the Leaderboard tab

### User Profile Extension

- `GET /api/users/{username}/traits` -- player's trait scores
  - Response: `{ dominant_trait, scores: { fonceur, prudent, coute_que_coute, rage_quitter, explorateur, routard, boss_slayer }, elo_rating, elo_rank, elo_trend_delta }`
  - Returns null scores if fewer than 3 finished races

### Admin

- `POST /api/admin/stats/recalculate` -- full recalculation of ELO + traits for all players

## Frontend

### New Route: `/stats`

Public page, no authentication required. Four tabs implemented as URL query parameter (`?tab=leaderboard`).

**Leaderboard tab**:

- Ranking table: #, player (avatar + name, clickable to profile), ELO, W/L, races, trend
- Sidebar: community stats card + "How ELO works" explainer card

**Zones tab**:

- Two panels side by side: "Deadliest Zones" and "Most Visited Zones"
- Horizontal bar charts with zone type badges (Legacy / Mini)

**Bosses tab**:

- Table: boss name + type badge, encounters, avg deaths, max deaths, avg time
- Sortable columns

**Players tab**:

- Grouped by dominant trait (7 sections)
- Each section: category header (icon, name, description, player count) + player rows
- Top 3 shown by default, "Show all (N)" button to expand
- Columns: rank within category, player, trait score, ELO, trait strength bar

### Profile Page Extension

New "Play Style" section between the existing stats grid and Pool Stats section:

- Card with: dominant trait (icon + color + description) + ELO (rank + value + trend)
- All 7 trait scores as horizontal bars, sorted by score descending
- Hidden if player has fewer than 3 finished races

### Navigation

Add "Stats" link to the navbar (visible to all, between Discord icon and Help).

## Design

Follows the existing graphic charter.

### Trait Names

Trait names use French for flavor (matching the community's usage): Fonceur, Prudent, Coute que coute, Explorateur, Routard. Boss Slayer and Rage Quitter use English as the community already uses these terms. This is a deliberate design choice; the UI is otherwise English.

### Color Assignments

| Trait           | Color    | Hex       |
| --------------- | -------- | --------- |
| Fonceur         | Red      | `#EF4444` |
| Prudent         | Emerald  | `#10B981` |
| Coute que coute | Gold     | `#C8A44E` |
| Rage Quitter    | Dark red | `#DC2626` |
| Explorateur     | Blue     | `#3B82F6` |
| Routard         | Purple   | `#A78BFA` |
| Boss Slayer     | Amber    | `#FBBF24` |

ELO ranking #1 uses gold (`#C8A44E`), others use secondary text (`#9CA3AF`), consistent with existing leaderboard style.

## Scope Boundaries

**In scope:**

- Stats page with 4 tabs
- ELO system (incremental + admin recalc)
- 7 behavioral traits
- Profile page Play Style section
- Navbar link

**Out of scope (future):**

- ELO split by pool (evaluate after community growth)
- Seasonal rankings / time-windowed leaderboards
- Head-to-head comparison view
- ELO history graph over time
- Training sessions in trait calculation (races only)
