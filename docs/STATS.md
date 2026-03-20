# Stats System

ELO ratings, behavioral traits, and zone/boss analytics.

---

## ELO Ratings

### Algorithm

Pairwise ELO with margin-of-victory scoring. After each finished race, every pair of eligible participants is compared.

**Constants:**

- `K_FACTOR = 32`
- `STARTING_ELO = 1500.0`
- Minimum 3 rated races to appear on leaderboard

**Eligible participants:** FINISHED, or ABANDONED with `igt_ms > 0` (started playing but quit). Requires at least 2 eligible participants per race.

**Pairwise scoring:**

For each pair (A, B):

1. Expected score: `ea = 1 / (1 + 10^((elo_B - elo_A) / 400))`
2. Actual score depends on outcome:
   - Both finished: `0.5 +/- 0.5 * margin`, where `margin = min(|igt_A - igt_B| / ref_time, 1.0)` and `ref_time = median(finisher_igts) * 0.3`
   - One finished, one abandoned: `(1.0, 0.0)`
   - Both abandoned: `(0.5, 0.5)` (draw)
3. Delta: `K_FACTOR * (actual - expected)`, normalized by `/ (n - 1)` to avoid over-rewarding large fields

**Idempotency:** `update_elo_ratings` checks for existing `EloHistory` entries for the race before computing. No double-counting on replay.

### Leaderboard

- Users with `elo_races >= 3`, sorted by `elo_rating DESC`
- Trend delta: sum of last 3 `EloHistory.delta` per user (batch query, not N+1)
- Community stats: total finished races, 30-day active players, total deaths, total hours

### Data Model

`EloHistory` stores one entry per participant per race: `elo_before`, `elo_after`, `delta`, `race_id`. Indexed on `(user_id, created_at)`.

---

## Behavioral Traits

Seven traits scored 0-100 per player. Computed across all finished races, recomputed after each race finishes.

### Requirements

- Minimum 3 finished races (`MIN_RACES_FOR_TRAITS`)
- Each race needs at least 2 finishers to contribute
- Dominant trait set when max score >= 40 (`DOMINANT_TRAIT_THRESHOLD`)

### Trait Formulas

All rank-based traits use `_compute_ranks()` which assigns 1-indexed ranks with average rank for ties.

#### Rusher

Displayed as: "Finishes fast, takes more deaths along the way". Fast IGT rank combined with high death rank. Fires when a player is faster than their death count would suggest.

```
raw = max(0, death_rank - igt_rank) / (n - 1)    # clamped to [0, 1]
score = raw ^ 0.4
```

Where `igt_rank` = 1 for fastest, `death_rank` = 1 for fewest deaths. High score when death_rank >> igt_rank (many deaths but fast).

#### Cautious

Displayed as: "Low deaths relative to time, plays it safe". Inverse of Rusher: slow IGT rank combined with low death rank.

```
raw = max(0, igt_rank - death_rank) / (n - 1)
score = raw ^ 0.4
```

High score when igt_rank >> death_rank (slow but few deaths).

#### Explorer

Displayed as: "Visits many nodes, backtracks often". Node coverage weighted with backtracking frequency.

```
coverage = sqrt(visited_nodes / total_nodes)
backtrack_rate = revisits / len(zone_history)
score = 0.6 * coverage + 0.4 * backtrack_rate
```

#### Pathfinder

Displayed as: "Takes unique paths others avoid". Route divergence from other finishers, measured on first-visit order (revisits stripped).

```
similarities = [SequenceMatcher(player_path, other_path).ratio() for other in finishers]
avg_similarity = mean(similarities)
score = (1 - avg_similarity) ^ 0.6
```

`SequenceMatcher` compares list elements (node_ids), not characters. Measures longest common subsequence ratio.

#### Boss Slayer

Displayed as: "Fewer deaths than average on hard bosses". Rank-based scoring weighted by boss difficulty (average deaths across all players on that boss).

```
per_boss_score = (n - player_rank) / (n - 1)
weight = avg_deaths_on_boss (or 1.0 if all zero)
total = sum(per_boss_score * weight) / sum(weights)
score = total ^ 1.4
```

Bosses with < 2 encounters are skipped. Uses `BOSS_NODE_TYPES = {boss_arena, major_boss, final_boss}` (broader than the public stats page, see Zone/Boss Stats below).

#### Resilient

Displayed as: "Keeps finishing despite high death counts". Death-count based adversity combined with completion rate.

```
death_percentile = (death_rank - 1) / (n - 1)    # 0 = fewest, 1 = most
avg_death_pct = mean(death_percentile across finished races)
completion_rate = finished_races / total_participated
score = min(avg_death_pct * completion_rate * 100, 100)
```

High score when the player consistently has more deaths than peers but keeps finishing. Distinguished from Rusher (which requires being fast) and Cautious (which requires few deaths).

#### Rage Quitter

Displayed as: "High abandon rate across races". Simple abandonment ratio. No power transform.

```
score = (abandoned_with_progress / total_participated) * 100
```

Requires `MIN_RACES_FOR_TRAITS` (3) total races, otherwise 0.

### Data Model

`PlayerTraitScores` stores all 7 scores as integers (0-100) plus `dominant_trait` (nullable string). Keyed by `user_id`. Upserted on recompute.

---

## Zone Stats

**Endpoint:** `GET /api/stats/zones?pool=<optional>`

Aggregates `zone_history` from all FINISHED participants. Only includes dungeon-type nodes.

### Node Type Filter

```python
DUNGEON_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
```

`boss_arena`, `major_boss`, `final_boss`, `start` are excluded. Deaths in boss-type nodes are tracked in Boss Stats instead.

### Display Name Resolution

Node IDs are cluster IDs from SpeedFog's `clusters.json`. Since `clusters.json` can evolve between seed generations (display_name corrections, type reclassifications), the stats code resolves each node_id's display_name and type from the **most recent seed** that contains it. The area prefix is stripped with `rsplit(" - ", 1)[-1]` (e.g., "Limgrave - Stormveil Castle" becomes "Stormveil Castle").

For boss stats specifically, the name resolution uses the `boss_name` field (canonical name from ItemRandomizer's `enemy.txt`), falling back to `randomized_boss` then `display_name` for seeds that predate the `boss_name` field. This ensures consistent naming across seeds with and without boss randomization (e.g., "Sir Gideon Ofnir, the All-Knowing" instead of "Gideon"). Resolution is per-seed (not global), so if the same node has different randomized bosses across seeds, they appear as separate entries.

### Cluster Merging

After aggregating by node_id, entries with the same display_name are merged. This handles the case where the same physical location produces different cluster_ids due to asymmetric drop connectivity in the zone graph (different entry points yield different reachable zone sets, producing different cluster hashes).

### Time Calculation

Time spent in a zone = `next_entry.igt_ms - current_entry.igt_ms`. For the last entry in zone_history, `participant.igt_ms` (final race IGT) is used as fallback.

### Panels

| Panel            | Metric                   | Sorting                             |
| ---------------- | ------------------------ | ----------------------------------- |
| Deadliest Zones  | avg. deaths per visit    | `total_deaths / visits` DESC        |
| Most Backtracked | avg. backtracks per race | `backtrack_count / race_count` DESC |
| Slowest Zones    | avg. traversal time      | `mean(times)` DESC                  |
| Fastest Zones    | avg. traversal time      | `mean(times)` ASC, min 3 visits     |

All panels show top 5. Sorting uses rate metrics (per-visit or per-race) to avoid popularity bias.

### Backtrack Detection

Per participant, a `visited_nids` set tracks already-seen node_ids. Revisiting a node_id increments that zone's backtrack count.

---

## Boss Stats

**Endpoint:** `GET /api/stats/bosses?pool=<optional>`

### Node Type Filter

```python
BOSS_NODE_TYPES = {"major_boss", "final_boss"}
```

`boss_arena` is intentionally excluded from the public stats page (minor encounters), but IS included in the trait scoring system's `BOSS_NODE_TYPES` for Boss Slayer calculations.

### Per-Participant Processing

For each participant, all visits to boss nodes are collected per node_id:

- **avg_deaths:** Average deaths across all visits, excluding 0-death backtracks (visits where the player passed through without fighting, detected when deaths = 0 and the next zone was already visited).
- **max_deaths:** Maximum deaths across all fight visits.
- **avg_time:** Time on the last visit only (last visit IGT to next entry IGT, or participant.igt_ms if last in history).
- **back_ratio:** Fraction of participants who, on their last visit to this boss, moved to a previously-visited zone afterward.
- **encounters:** Number of unique participants who visited this boss.

### Sorting

Sorted by `avg_deaths DESC`. Boss name resolution uses `boss_name` (per-seed), with merging by resolved name across participants.

---

## Recalculation

`recalculate_all_stats` (admin endpoint) clears all ELO and trait data, resets all users to 1500 ELO, then replays all finished races in chronological order (`started_at ASC`). This ensures consistency after formula changes or bug fixes.
