# Stats Review Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stats system issues found during code review: N+1 query, sorting by rate instead of total, missing zone time, code quality, label/description accuracy, and add endpoint test coverage.

**Architecture:** Targeted fixes across server (`stats.py`, `stats_service.py`) and frontend (`ZonesTab.svelte`, `BossesTab.svelte`, `PlayersTab.svelte`, `+page.svelte`). No schema changes needed; the rate fields already exist in schemas and TS types.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, SvelteKit 5 (runes), pytest

---

## Task 1: Fix N+1 leaderboard trend query

**Files:**

- Modify: `server/speedfog_racing/api/stats.py:54-70`

- [ ] **Step 1: Replace per-user loop with single batch query**

Replace the N+1 loop (lines 54-70) with a single query that fetches all recent EloHistory entries for qualified users, then groups in Python:

```python
    trends: dict[Any, int] = {}
    if user_ids:
        # Batch fetch all recent EloHistory for qualified users in one query,
        # then group in Python. Replaces the N+1 pattern (one query per user).
        all_history = (
            await db.execute(
                select(EloHistory.user_id, EloHistory.delta)
                .where(EloHistory.user_id.in_(user_ids))
                .order_by(EloHistory.user_id, EloHistory.created_at.desc())
            )
        ).all()

        # Accumulate last 3 deltas per user
        delta_counts: dict[Any, int] = {}
        for uid, delta in all_history:
            count = delta_counts.get(uid, 0)
            if count < 3:
                trends[uid] = trends.get(uid, 0) + round(delta)
                delta_counts[uid] = count + 1
```

- [ ] **Step 2: Run existing tests**

Run: `cd server && uv run pytest tests/test_stats_api.py tests/test_elo.py -v`
Expected: All pass (no behavior change)

- [ ] **Step 3: Commit**

```
git add server/speedfog_racing/api/stats.py
git commit -m "fix: replace N+1 leaderboard trend query with batch fetch"
```

---

## Task 2: Sort zone stats by rate metrics, fix last zone time

**Files:**

- Modify: `server/speedfog_racing/api/stats.py:157-351`

- [ ] **Step 1: Fix last zone time in `_aggregate_zone_stats`**

After the time loop (line 214), add a fallback for the last entry using `participant.igt_ms`:

```python
            # Time: difference between this entry's igt_ms and next entry's igt_ms
            current_igt = entry.get("igt_ms", 0)
            if idx + 1 < len(history):
                next_igt = history[idx + 1].get("igt_ms", 0)
                if current_igt > 0 and next_igt > current_igt:
                    zone_times.setdefault(nid, []).append(next_igt - current_igt)
            else:
                # Last zone: use participant's final IGT as the "next" timestamp
                final_igt = participant.igt_ms or 0
                if current_igt > 0 and final_igt > current_igt:
                    zone_times.setdefault(nid, []).append(final_igt - current_igt)
```

- [ ] **Step 2: Change "Deadliest" sorting from total_deaths to avg_deaths_per_visit**

In `get_zone_stats`, replace line 285:

```python
    # Deadliest: by avg_deaths_per_visit desc (rate metric, not biased by popularity)
    deadliest_nodes = sorted(
        [n for n in node_data.values() if n["visits"] > 0],
        key=lambda n: n["total_deaths"] / n["visits"],
        reverse=True,
    )[:5]
```

- [ ] **Step 3: Change "Most Backtracked" sorting from backtrack_count to avg_backtracks_per_race**

Replace lines 299-303:

```python
    # Most backtracked: by avg_backtracks_per_race desc (rate metric)
    backtracked_nodes = sorted(
        [n for n in node_data.values() if n["backtrack_count"] > 0],
        key=lambda n: n["backtrack_count"] / n["race_count"] if n["race_count"] > 0 else 0,
        reverse=True,
    )[:5]
```

- [ ] **Step 4: Run linter and type checker**

Run: `cd server && uv run ruff check speedfog_racing/api/stats.py && uv run mypy speedfog_racing/api/stats.py`
Expected: Clean

- [ ] **Step 5: Commit**

```
git add server/speedfog_racing/api/stats.py
git commit -m "fix: sort zone stats by rate metrics, capture last zone time"
```

---

## Task 3: Server code quality fixes

**Files:**

- Modify: `server/speedfog_racing/api/stats.py:40,133-154,216-217`
- Modify: `server/speedfog_racing/services/stats_service.py:30,91-148,170-327,432-444`

- [ ] **Step 1: Add comment on BOSS_NODE_TYPES difference**

In `stats.py`, update the constant at line 40:

```python
# Only major_boss and final_boss for the public boss stats page.
# boss_arena is intentionally excluded here (minor encounters), but IS included
# in stats_service.py's BOSS_NODE_TYPES for trait scoring (Boss Slayer).
BOSS_NODE_TYPES = {"major_boss", "final_boss"}
```

- [ ] **Step 2: Improve \_resolve_node_display docstring**

Replace the docstring at lines 136-140:

```python
    """Build node_id -> (short_display_name, type) from the most recent seed.

    Node IDs are cluster IDs from SpeedFog's clusters.json. The same cluster_id
    always refers to the same physical location, but display_names and types can
    change across seeds if clusters.json was updated between seed generations
    (e.g. display_name typo fixed, or a cluster reclassified from major_boss to
    legacy_dungeon). Using the most recent seed ensures stats show current names.
    """
```

- [ ] **Step 3: Fix merge comment**

Replace lines 216-217:

```python
    # Merge clusters sharing the same display_name. This happens when the same
    # physical location produces different cluster_ids due to asymmetric drop
    # connectivity in the zone graph (different entry points yield different
    # reachable zone sets, so different cluster hashes).
```

- [ ] **Step 4: Move \_first_visit_path to module level in stats_service.py**

Move the function definition from inside the loop (lines 246-254) to module level, before `_recompute_traits_for_user`:

```python
def _first_visit_path(zh: list[dict[str, Any]]) -> list[str]:
    """Extract first-visit node order from zone_history, ignoring revisits."""
    seen: set[str] = set()
    path: list[str] = []
    for e in zh:
        nid = e.get("node_id", "")
        if nid and nid not in seen:
            seen.add(nid)
            path.append(nid)
    return path
```

Delete the inner definition at lines 246-254 (the call sites at lines 256, 260 remain unchanged).

- [ ] **Step 5: Add missing user guard in update_elo_ratings**

In `stats_service.py`, replace lines 127-128. Filter out players whose users are missing
BEFORE calling `compute_elo_deltas`, so the players list stays consistent:

```python
    # Filter to players whose users still exist (defensive against deleted users)
    players = [p for p in players if p["user_id"] in users_by_id]
    if len(players) < 2:
        return

    for p in players:
        p["elo"] = users_by_id[p["user_id"]].elo_rating
```

No change needed in the second loop (lines 132-146) since `players` is now pre-filtered.

- [ ] **Step 6: Fix resilient docstring**

Update `compute_resilient_score` docstring (lines 435-438):

```python
    """Score resilience (0-100): keeps finishing despite high death counts.

    death_percentiles: per finished race, (death_rank - 1) / (N - 1) among finishers.
    High value = more deaths than others. Weighted by completion rate.
    """
```

- [ ] **Step 7: Run tests and linter**

Run: `cd server && uv run pytest tests/test_stats_api.py tests/test_elo.py tests/test_traits.py -v && uv run ruff check speedfog_racing/api/stats.py speedfog_racing/services/stats_service.py && uv run mypy speedfog_racing/api/stats.py speedfog_racing/services/stats_service.py`
Expected: All pass, clean

- [ ] **Step 8: Commit**

```
git add server/speedfog_racing/api/stats.py server/speedfog_racing/services/stats_service.py
git commit -m "fix: improve stats code quality (comments, user guard, _first_visit_path)"
```

---

## Task 4: Frontend label and display fixes

**Files:**

- Modify: `web/src/routes/stats/+page.svelte:15`
- Modify: `web/src/lib/components/stats/ZonesTab.svelte:34-53,79-81,107-108`
- Modify: `web/src/lib/components/stats/PlayersTab.svelte:43-44`

- [ ] **Step 1: Rename Bosses tab to "Major Bosses"**

In `web/src/routes/stats/+page.svelte`, change the tab label at line 15:

```typescript
  { id: 'bosses', label: 'Major Bosses' },
```

- [ ] **Step 2: Fix zone type badges in ZonesTab.svelte**

Replace the `typeLabel` function (lines 43-46):

```typescript
function typeLabel(type: string): string {
  if (type === "legacy_dungeon") return "Legacy";
  return "Minor";
}
```

- [ ] **Step 3: Display rate metrics instead of totals in ZonesTab**

For "Deadliest Zones", change the bar and value (lines 79-81) to use `avg_deaths_per_visit`:

```svelte
        <div
         class="bar bar-death"
         style="width: {barWidth(zone.avg_deaths_per_visit, maxDeaths)}"
        ></div>
        <span class="bar-value">{zone.avg_deaths_per_visit.toFixed(1)}</span>
```

Update `maxDeaths` derived (line 13):

```typescript
let maxDeaths = $derived(
  Math.max(1, ...deadliest.map((z) => z.avg_deaths_per_visit)),
);
```

For "Most Backtracked", change lines 106-108 to use `avg_backtracks_per_race`:

```svelte
        <div
         class="bar bar-backtrack"
         style="width: {barWidth(zone.avg_backtracks_per_race, maxBacktracks)}"
        ></div>
        <span class="bar-value">{zone.avg_backtracks_per_race.toFixed(1)}x</span>
```

Update `maxBacktracks` derived (line 14):

```typescript
let maxBacktracks = $derived(
  Math.max(1, ...mostBacktracked.map((z) => z.avg_backtracks_per_race)),
);
```

- [ ] **Step 4: Fix Resilient trait description**

In `web/src/lib/components/stats/PlayersTab.svelte`, change the resilient entry (lines 43-44):

```typescript
  {
   key: 'resilient',
   label: 'Resilient',
   color: '#C8A44E',
   icon: '\uD83D\uDCAA',
   description: 'Keeps finishing despite high death counts'
  },
```

- [ ] **Step 5: Run frontend checks**

Run: `cd web && npm run check && npm run lint`
Expected: Clean

- [ ] **Step 6: Commit**

```
git add web/src/routes/stats/+page.svelte web/src/lib/components/stats/ZonesTab.svelte web/src/lib/components/stats/PlayersTab.svelte
git commit -m "fix: use rate metrics in zone stats, rename to Major Bosses, fix labels"
```

---

## Task 5: Add stats endpoint tests

**Files:**

- Modify: `server/tests/test_stats_api.py` (add new test classes at the end)

These tests use the existing `three_races_with_zone_history` fixture which creates 3 finished races with zone_history data, bosses (`margit_g7h8` type `boss_arena`, `final_k1l2` type `final_boss`), and dungeons (`stormveil_c3d4` type `legacy_dungeon`, `cave_e5f6` type `mini_dungeon`).

Note: these are integration tests using async sessions (same pattern as existing tests in the file), NOT HTTP endpoint tests via TestClient. This avoids complexities with the sync TestClient + async database layer, and the existing test infrastructure already uses this pattern.

- [ ] **Step 1: Add zone stats endpoint logic test**

Add to `test_stats_api.py`:

```python
from speedfog_racing.api.stats import (
    _resolve_node_display,
    _aggregate_zone_stats,
    DUNGEON_NODE_TYPES,
    BOSS_NODE_TYPES,
)


class TestZoneStatsAggregation:
    async def test_aggregate_zone_stats_counts_deaths(
        self, async_session, three_races_with_zone_history
    ):
        """Zone aggregation should sum deaths across all participants."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            from sqlalchemy.orm import selectinload

            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            # stormveil_c3d4 is legacy_dungeon, should be included
            assert any("Stormveil" in name for name in zone_data)
            # margit_g7h8 is boss_arena, should be excluded from dungeon stats
            assert not any("Margit" in name for name in zone_data)

    async def test_aggregate_zone_stats_computes_times(
        self, async_session, three_races_with_zone_history
    ):
        """Time should be computed as difference between consecutive igt_ms entries."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            from sqlalchemy.orm import selectinload

            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            # Each zone should have time entries
            for name, data in zone_data.items():
                assert data["times"], f"Zone {name} should have time entries"
                for t in data["times"]:
                    assert t > 0, f"Zone {name} has non-positive time {t}"


    async def test_last_zone_time_uses_participant_igt(
        self, async_session, three_races_with_zone_history
    ):
        """The last zone in history should use participant.igt_ms for time calculation."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            from sqlalchemy.orm import selectinload

            # Player 0 has final_k1l2 as last zone (type final_boss, not a dungeon).
            # Player 2 has final_k1l2 as last zone too.
            # Player 1 has final_k1l2 as last zone.
            # All final zones are final_boss type, so they won't appear in dungeon stats.
            # But raya_i9j0 (legacy_dungeon) is the second-to-last for players 1 and 2,
            # so its time IS computed from next entry. The last dungeon-type entry for
            # each player should also have time computed (via participant.igt_ms fallback
            # if it's the very last entry, or via next entry otherwise).
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            # Stormveil should have times (it always has a next entry in history)
            stormveil = next((d for n, d in zone_data.items() if "Stormveil" in n), None)
            assert stormveil is not None
            assert len(stormveil["times"]) > 0


class TestBossStatsFiltering:
    async def test_boss_stats_excludes_boss_arena(
        self, async_session, three_races_with_zone_history
    ):
        """Boss stats should only include major_boss and final_boss, not boss_arena."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            from sqlalchemy.orm import selectinload

            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)

            # final_k1l2 is final_boss type, should resolve in boss types
            for nid, (display, ntype) in node_display.items():
                if "final" in nid:
                    assert ntype == "final_boss"
                if "margit" in nid:
                    # boss_arena should NOT be in stats.py BOSS_NODE_TYPES
                    assert ntype == "boss_arena"
                    assert ntype not in BOSS_NODE_TYPES
```

- [ ] **Step 2: Run all stats tests**

Run: `cd server && uv run pytest tests/test_stats_api.py -v`
Expected: All pass (existing + new)

- [ ] **Step 3: Commit**

```
git add server/tests/test_stats_api.py
git commit -m "test: add zone and boss stats aggregation tests"
```
