# Stats System

ELO ratings, behavioral traits, and zone/boss analytics.

---

## ELO Ratings

### Algorithm

Pairwise ELO with margin-of-victory scoring. After each finished race, every pair of eligible participants is compared.

**Constants:**

- `K_FACTOR = 32` (established players, >= 10 rated races)
- `K_FACTOR_PROVISIONAL = 48` (provisional players, < 10 rated races)
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
3. Delta: `K * (actual - expected)`, weighted and normalized per player (see below). K is 48 for provisional players (< 10 races) and 32 for established players, so new players' ratings converge faster.

**Provisional confidence (`PROVISIONAL_THRESHOLD = 10`):**

Players with fewer than 10 rated races have a provisional rating. The confidence of a player's rating is `min(elo_races / 10, 1.0)`.

- **Established players** (>= 10 races): pairwise delta is scaled by the opponent's confidence. Matches against provisional opponents contribute less (or nothing). Normalization divides by the sum of opponent confidences (not n-1), so provisional opponents don't dilute established matchups in large races.
- **Provisional players** (< 10 races): always receive full pairwise delta regardless of opponent confidence, enabling bootstrapping. Normalization divides by n-1.

This is asymmetric by design: an established player beating two provisionals gets ~0 delta, but the provisionals' ratings still converge based on the race result.

**Winner floor:**

After all adjustments (field strength, difficulty injection), the race winner's delta is clamped to `max(delta, 0)`. The 1st place finisher never loses ELO. This is a second intentional zero-sum break (alongside difficulty injection).

**Seed difficulty scoring:**

Each seed receives an intrinsic difficulty score at ingestion time, computed from its graph structure:

- `score = sum(type_weight * tier^1.3)` over all non-start nodes
- Type weights: `legacy_dungeon=1.0`, `mini_dungeon=0.7`, `boss_arena=1.5`, `major_boss=2.0`, `final_boss=2.5`
- Stored as `difficulty_score` on the Seed model

**Field strength weighting (post-pairwise):**

After pairwise deltas are computed, they are scaled by the average field ELO:

```
weight = avg_field_elo / 1500.0
adjusted_delta = pairwise_delta * weight
```

Races among strong players (avg ELO > 1500) amplify gains/losses. Races among weaker players dampen them.

**Difficulty injection (post-pairwise):**

A uniform bonus/penalty is added to all participants based on the race seed's difficulty relative to the global average of consumed seeds (training pool seeds are excluded):

```
difficulty_factor = seed.difficulty_score / avg(consumed_seeds.difficulty_score)
bonus = 5.0 * (difficulty_factor - 1.0)
final_delta = field_weighted_delta + bonus
```

This intentionally breaks zero-sum: harder seeds inject positive ELO into the system. Over time, players who consistently race on harder seeds drift upward, while players on easier seeds drift downward, even if the two groups never cross paths.

**Strength of Schedule (SoS):**

Available in the API as `avg_opponent_elo` on `LeaderboardPlayer`: the average `elo_before` of all opponents across all rated races for a player. Not displayed in the frontend (replaced by confidence badge).

**Idempotency:** `update_elo_ratings` checks for existing `EloHistory` entries for the race before computing. No double-counting on replay.

### Leaderboard

- Users with `elo_races >= 3`, sorted by confidence-adjusted rating: `elo_rating - 100 / sqrt(elo_races)` DESC
- Players with fewer races get a larger uncertainty penalty, preventing low-confidence ratings from outranking established players
- Confidence badge next to ELO value: green (15+ races, >= 75%), orange (8-14 races, 40-74%), gray (3-7 races, < 40%). Threshold: 20 races = 100% confidence
- Trend delta: sum of last 3 `EloHistory.delta` per user (batch query, not N+1)
- Community stats: total finished races, 30-day active players, total deaths, total hours

### Data Model

`EloHistory` stores one entry per participant per race: `elo_before`, `elo_after`, `delta`, `race_id`. Indexed on `(user_id, created_at)`.

---

## Behavioral Traits

Seven traits scored 0-100 per player. Computed across all finished races, recomputed after each race finishes.

### Requirements

- Minimum 3 finished races (`MIN_RACES_FOR_TRAITS`) for all traits (including rage_quitter)
- Each race needs at least 2 finishers to contribute to per-race traits
- Dominant trait determined by percentile ranking (see Data Model below)
- API returns `finished_races` and `races_required` so the frontend can show progress
- If all scores are 0, `scores` is returned as `null` (frontend shows progress message instead of empty bars)

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

Requires `MIN_RACES_FOR_TRAITS` (3) **finished** races, same threshold as all other traits. This prevents players with few finishes but several abandons from being labeled "Rage Quitter" based on insufficient data.

### Data Model

`PlayerTraitScores` stores all 7 scores as integers (0-100) plus `dominant_trait` (nullable string) and `dominant_description` (nullable string). Keyed by `user_id`. Raw scores are upserted per-user after each race; dominant trait is resolved globally via `resolve_dominant_traits()`.

#### Dominant Trait Selection

The dominant trait is determined by **percentile ranking**, not highest raw score. For each of the 7 traits, all players are ranked by their raw score (highest = rank 1). A player's dominant trait is the trait where they rank best (lowest percentile) among all players. If two traits have the same percentile, the one with the higher raw score wins.

A minimum threshold applies: the player must be in the **top 50%** (`DOMINANT_PERCENTILE_THRESHOLD = 0.5`) on at least one trait to have a dominant trait assigned. Players below the median on all traits have no dominant trait.

`dominant_description` stores a human-readable explanation (e.g. "Top 9% among 32 players", or "#1 among 32 players" for rank 1). Displayed in the player profile alongside the trait name.

---

## Zone Stats

**Endpoint:** `GET /api/stats/zones?pool=<optional>&days=<optional>`

Aggregates `zone_history` from FINISHED participants (and ABANDONED with `igt_ms > 0`) in races started within the last `days` days (default 30). Only includes dungeon-type nodes.

### Node Type Filter

```python
DUNGEON_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
```

`boss_arena`, `major_boss`, `final_boss`, `start` are excluded. Deaths in boss-type nodes are tracked in Boss Stats instead.

### Display Name Resolution

Node IDs are cluster IDs from SpeedFog's `clusters.json`. Since `clusters.json` can evolve between seed generations (display_name corrections, type reclassifications), the stats code resolves each node_id's display_name and type from the **most recent seed** that contains it. The area prefix is stripped with `rsplit(" - ", 1)[-1]` (e.g., "Limgrave - Stormveil Castle" becomes "Stormveil Castle").

For boss stats specifically, the name resolution uses the `boss_name` field (canonical name from ItemRandomizer's `enemy.txt`), falling back to `display_name`. This ensures consistent naming across seeds with and without boss randomization (e.g., "Sir Gideon Ofnir, the All-Knowing" instead of "Gideon"). Resolution is per-seed (not global), so if the same node has different randomized bosses across seeds, they appear as separate entries.

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

---

## Race Highlights

Computed client-side in `web/src/lib/highlights.ts`. Detects race-wide moments from zone_history data and graph topology.

**Selection:** Max 6 highlights, max 2 per category, no overlapping zones between highlights. Community highlights (no specific player) get a 1.5x scoring boost for ranking.

### Speed

#### Speed Demon

Player cleared a zone much faster than the next-fastest competitor. Compared against the 2nd-fastest (not the mean) so a close runner-up prevents the highlight from firing.

- **Condition:** `second_fastest_time / fastest_time >= 1.3`, zone type is not start or final_boss, at least 2 players cleared the zone
- **Score:** `(second_fastest / fastest) * tier * 20`
- **Text:** "[Player] blitzed through [Zone] in [Time]"

#### Zone Wall

Player was stuck on a zone far longer than the next-slowest player who also cleared. Only counts cleared times: a player who backed out or abandoned isn't a "fast reference" because they chose to leave the zone, not because they breezed through it.

- **Condition:** `slowest_time / second_slowest_time >= 1.5`, zone type is not start or final_boss, at least 2 players cleared the zone
- **Score:** `(slowest / second_slowest) * tier * 15`
- **Text:** "[Zone] was [Player]'s nemesis, stuck for [Time]"

#### Sprint Final

Player defeated the final boss faster than anyone else.

- **Condition:** At least one player cleared the final_boss zone
- **Score:** `max(20, (avg_final_boss_time / best_time) * 25)`
- **Text:** "[Player] beat [FinalBoss] in [Time]"

### Deaths

#### Graveyard

A zone claimed the most total deaths across all players.

- **Condition:** `total_deaths >= 3`, zone type is not start
- **Score:** `total_deaths * 8`
- **Text:** "[Zone] claimed [N] deaths across all racers"

#### Death Zone

A single player died many times in one zone.

- **Condition:** `deaths >= 3`
- **Score:** `deaths * 10`
- **Text:** "[Player] died [N] times in [Zone]"

#### Deathless

Player cleared multiple high-tier zones without dying.

- **Condition:** Cleared zones with tier >= 3 and 0 deaths, at least 1 such zone
- **Score:** `50 + zone_count * 10`
- **Text:** "[Player] cleared [N] high-scaled zone(s) without dying"

#### Comeback Kid

Player finished well despite many deaths.

- **Condition:** Top-half finisher (by IGT) with >= 5 deaths
- **Score:** `deaths * 5 + (num_finishers - rank) * 10`
- **Text:** "[Player] died [N] times but still finished [Rank]"

#### Rage Inducer

A zone caused multiple players to abandon the race.

- **Condition:** Zone has >= 2 abandoned outcomes
- **Score:** `abandons * 40`
- **Text:** "[Zone] made [N] player(s) rage-quit"

### Path

#### Same Brain

Two players took the exact same path (first-visit order).

- **Condition:** Identical `uniqueNodePath` sequences, path length >= 2
- **Score:** `40 + path_length * 8`
- **Text:** "[Player1] and [Player2] took the exact same path"

#### Scenic Route

Player explored more zones than anyone else.

- **Condition:** `max_unique_zones >= avg * 1.3` and `>= 4`
- **Score:** `(max_nodes / avg_nodes) * 30`
- **Text:** "[Player] explored [N] zones across [M] depth levels, more than anyone else"

#### Hard Pass

Multiple players backed out of a zone.

- **Condition:** Zone has >= 2 backed outcomes
- **Score:** `backouts * tier * 15`
- **Text:** "[N] players backed out of [Zone]"

### Competitive

#### Photo Finish

Two players finished very close together.

- **Condition:** IGT gap between consecutive finishers <= 30s
- **Score:** `(30000 / max(gap_ms, 1000)) * 20`
- **Text:** "[Player1] and [Player2] finished just [Gap] apart"

#### Back and Forth

The lead changed hands multiple times.

- **Condition:** >= 2 lead changes across depth levels (different player first to reach each depth)
- **Score:** `changes * 25`
- **Text:** "The lead changed [N] times throughout the race"

#### Dominant

One player led at every single depth.

- **Condition:** Same player is first to reach every depth (>= 2 depth levels)
- **Score:** `40 + num_layers * 8`
- **Text:** "[Player] led from start to finish"

#### Early Exit

A player abandoned the race very early.

- **Condition:** Abandoned player's IGT < 80% of median finisher IGT
- **Score:** `max(20, 90 - (igt / median_igt) * 100)`
- **Text:** "[Player] rage-quit after just [Time]"

---

## Personal Highlights

Computed client-side in `web/src/lib/personal-highlights.ts`. Detects player-specific moments using direct "You..." tone.

**Selection:** Same rules as race highlights (max 6, max 2 per category, no overlapping zones).

### Combat

#### Boss Slayer

Player had far fewer deaths than average on a boss.

- **Condition:** `deaths / avg_deaths < 0.5`, at least 2 players fought the boss
- **Score:** `(1 - ratio) * 100 * tier`
- **Text:** "You cleared [Boss] deathless (average: [N] deaths)" or "You only died [N] time(s) on [Boss] (average: [M])"

#### Boss Wall

Player struggled on a boss far more than others.

- **Condition:** `deaths / avg_deaths >= 2.0`, at least 1 death
- **Score:** `ratio * 40`
- **Text:** "[Boss] gave you trouble: [N] deaths (average: [M])"

#### Stood Your Ground

Player was the only one who didn't back out of a zone; every other visitor backed.

- **Condition:** Player cleared the zone, all other visitors have outcome "backed", at least 2 total visitors
- **Score:** `backouts * 35 * tier`
- **Text:** "You're the only one who didn't turn back from [Zone]"

#### Death Spiral

Player died many times on a zone but still cleared it.

- **Condition:** `deaths >= 5`, outcome is "cleared"
- **Score:** `deaths * 15 * tier`
- **Text:** "You left [N] lives on [Zone] before finally pushing through"

#### Clean Streak

Player cleared multiple consecutive zones without dying while others struggled.

- **Condition:** >= 3 consecutive zones with 0 deaths; other players had deaths on at least one of those zones
- **Score:** `streak_length * 25 + others_total_deaths * 5`
- **Text:** "You cleared [N] zones in a row without dying, while others lost [M] lives there"

### Pathing

#### Lone Explorer

Player visited a zone nobody else visited. Picks the highest-tier solo zone (ties broken by first-visit order).

- **Score:** `num_participants * 20`
- **Text:** "You're the only one who visited [Zone]"

#### Against the Flow

Player took a unique branch at a fork that no other player took.

- **Condition:** At a graph node with 2+ children, player's next node differs from all other players' next node at the same fork
- **Score:** `others_on_different_branch * 30`
- **Text:** "At the [Fork] crossroads, you headed towards [Branch] where no one else went"

#### Smart Backtrack

Player backed out of a zone and found a better alternative, saving time.

- **Condition:** Player backed a zone, then cleared an alternative at same or higher depth; `avg_clear_time_of_backed_zone - (backed_time + alt_time) > 0`
- **Score:** `(time_saved_ms / 1000) * 2`
- **Text:** "Good call turning back from [BackedZone]: going to [AltZone] instead saved you [Time] compared to those who stayed"

### Competitive

#### Faster Than All

Player was the fastest through a zone, comfortably ahead of the runner-up.

- **Condition:** `time / runner_up_time <= 1/1.3`, player is strictly fastest, at least 2 players cleared the zone
- **Score:** `(1 - ratio) * 100 * tier`
- **Text:** "You were the fastest through [Zone]: [Time] (runner-up: [RunnerUpTime])"

#### Rough Zone (Slower Than All)

Player was the slowest through a zone, noticeably behind the next-slowest.

- **Condition:** `time / next_slowest_time >= 1.5`, player is strictly slowest, at least 2 players cleared the zone
- **Score:** `(ratio - 1) * 50`
- **Text:** "[Zone] slowed you down: last with [Time] (next: [NextTime])"

#### Lead Lost

Player was leading the race but lost the lead.

- **Condition:** Rank 1 at depth N, rank > 1 at depth N+1; fires once (first occurrence)
- **Score:** Fixed `60`
- **Text:** "You were leading the race, but lost the lead at [Zone] (depth [N])"

#### Comeback

Player gained 2+ positions between consecutive depths.

- **Condition:** `rank_before - rank_after >= 2`; picks the largest gain
- **Score:** `rank_gain * 30`
- **Text:** "You were [Rank] at depth [N], then climbed back to [Rank] place at [Zone]"

#### Lead Swap

Player and another player alternated as leader multiple times.

- **Condition:** >= 3 alternations as rank 1 between the same two players
- **Score:** `swaps * 25`
- **Text:** "You and [Player] traded the lead [N] times during the race"

#### Neck and Neck

Player stayed close to another player throughout the race.

- **Condition:** Within 1 rank for >= 70% of depths, final IGT gap < 10% of faster player's time
- **Score:** `layers_together * 10`
- **Text:** "You stayed neck and neck with [Player] throughout the race"
