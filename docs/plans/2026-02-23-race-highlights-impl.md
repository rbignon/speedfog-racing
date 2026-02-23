# Race Highlights Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Display a curated list of 5-6 fun race highlights on the race detail page for finished races.

**Architecture:** Frontend-only. Pure TypeScript computation from existing `zone_history` (participant data) and `graph_json` (seed topology). New `<RaceHighlights>` Svelte component placed after `<RaceStats>` in the FINISHED state. Tests use Vitest.

**Tech Stack:** TypeScript, SvelteKit 5 (runes), Vitest

---

## Task 1: Core types and per-zone time helper

**Files:**

- Create: `web/src/lib/highlights.ts`
- Test: `web/src/lib/__tests__/highlights.test.ts`

### Step 1: Write the failing tests

Create `web/src/lib/__tests__/highlights.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { computeZoneTimes, type ZoneTime } from "$lib/highlights";
import type { WsParticipant } from "$lib/websocket";

// Minimal participant factory
function participant(
  id: string,
  overrides: Partial<WsParticipant> = {},
): WsParticipant {
  return {
    id,
    twitch_username: id,
    twitch_display_name: id.charAt(0).toUpperCase() + id.slice(1),
    status: "finished",
    current_zone: null,
    current_layer: 3,
    igt_ms: 300000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...overrides,
  };
}

describe("computeZoneTimes", () => {
  it("computes time spent in each zone from zone_history", () => {
    const p = participant("alice", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 60000 },
        { node_id: "zone_b", igt_ms: 120000 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result).toEqual([
      { nodeId: "start", timeMs: 60000, deaths: 0 },
      { nodeId: "zone_a", timeMs: 60000, deaths: 0 },
      { nodeId: "zone_b", timeMs: 180000, deaths: 0 },
    ]);
  });

  it("includes deaths from zone_history entries", () => {
    const p = participant("alice", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 50000, deaths: 3 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result[1].deaths).toBe(3);
  });

  it("returns empty array when zone_history is null", () => {
    const p = participant("alice", { zone_history: null });
    expect(computeZoneTimes(p)).toEqual([]);
  });

  it("handles single-entry zone_history", () => {
    const p = participant("alice", {
      igt_ms: 100000,
      zone_history: [{ node_id: "start", igt_ms: 0 }],
    });
    const result = computeZoneTimes(p);
    expect(result).toEqual([{ nodeId: "start", timeMs: 100000, deaths: 0 }]);
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/__tests__/highlights.test.ts`

Expected: FAIL — module `$lib/highlights` not found

### Step 3: Write minimal implementation

Create `web/src/lib/highlights.ts`:

```typescript
/**
 * Race highlights computation.
 *
 * Pure functions that compute interesting race highlights from
 * zone_history data and graph_json topology.
 */

import type { WsParticipant } from "$lib/websocket";

// =============================================================================
// Types
// =============================================================================

export interface ZoneTime {
  nodeId: string;
  timeMs: number;
  deaths: number;
}

export type HighlightCategory = "speed" | "deaths" | "path" | "competitive";

export interface Highlight {
  type: string;
  category: HighlightCategory;
  title: string;
  description: string;
  /** Participant ID(s) involved */
  playerIds: string[];
  /** Internal score for ranking (higher = more interesting) */
  score: number;
}

// =============================================================================
// Helpers
// =============================================================================

/**
 * Compute time spent in each zone for a participant.
 * Time in zone N = entry time of zone N+1 - entry time of zone N.
 * For the last zone, uses participant's final igt_ms.
 */
export function computeZoneTimes(p: WsParticipant): ZoneTime[] {
  if (!p.zone_history || p.zone_history.length === 0) return [];

  return p.zone_history.map((entry, i) => {
    const nextIgt =
      i < p.zone_history!.length - 1 ? p.zone_history![i + 1].igt_ms : p.igt_ms;
    return {
      nodeId: entry.node_id,
      timeMs: Math.max(0, nextIgt - entry.igt_ms),
      deaths: entry.deaths ?? 0,
    };
  });
}
```

### Step 4: Run test to verify it passes

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/__tests__/highlights.test.ts`

Expected: PASS (4 tests)

### Step 5: Commit

```bash
git add web/src/lib/highlights.ts web/src/lib/__tests__/highlights.test.ts
git commit -m "feat(web): add highlight types and computeZoneTimes helper"
```

---

## Task 2: Speed & time highlights (Speed Demon, Zone Wall, Fast Starter, Sprint Final)

**Files:**

- Modify: `web/src/lib/highlights.ts`
- Modify: `web/src/lib/__tests__/highlights.test.ts`

### Step 1: Write the failing tests

Append to `highlights.test.ts`:

```typescript
import { computeHighlights, type Highlight } from "$lib/highlights";

// Minimal graph_json factory
function graphJson(
  nodes: Record<string, { tier?: number; layer?: number; type?: string }>,
) {
  const nodeEntries: Record<string, unknown> = {};
  for (const [id, data] of Object.entries(nodes)) {
    nodeEntries[id] = {
      type: data.type ?? "mini_dungeon",
      display_name: id,
      zones: [],
      layer: data.layer ?? 0,
      tier: data.tier ?? 1,
      weight: 1,
    };
  }
  return { nodes: nodeEntries, edges: [], total_layers: 3 };
}

describe("speed highlights", () => {
  const graph = graphJson({
    start: { tier: 1, layer: 0, type: "start" },
    zone_a: { tier: 2, layer: 1 },
    zone_b: { tier: 3, layer: 2 },
    zone_c: { tier: 3, layer: 3, type: "final_boss" },
  });

  it("Speed Demon: detects player who cleared a zone much faster than average", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 }, // 10s in start
          { node_id: "zone_b", igt_ms: 30000 }, // 20s in zone_a
          { node_id: "zone_c", igt_ms: 100000 }, // 70s in zone_b
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 15000 }, // 15s in start
          { node_id: "zone_b", igt_ms: 90000 }, // 75s in zone_a
          { node_id: "zone_c", igt_ms: 200000 }, // 110s in zone_b
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const speedDemon = highlights.find((h) => h.type === "speed_demon");
    expect(speedDemon).toBeDefined();
    // Alice cleared zone_a in 20s vs Bob's 75s — Alice is the speed demon
    expect(speedDemon!.playerIds).toContain("alice");
  });

  it("Zone Wall: detects player who spent disproportionately long in a zone", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 },
          { node_id: "zone_b", igt_ms: 250000 }, // 240s in zone_a!
          { node_id: "zone_c", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 200000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 },
          { node_id: "zone_b", igt_ms: 30000 }, // 20s in zone_a
          { node_id: "zone_c", igt_ms: 200000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const wall = highlights.find((h) => h.type === "zone_wall");
    expect(wall).toBeDefined();
    expect(wall!.playerIds).toContain("alice");
  });

  it("Photo Finish: detects close finish between two players", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 302000, // 2 second difference
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 302000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const photo = highlights.find((h) => h.type === "photo_finish");
    expect(photo).toBeDefined();
    expect(photo!.playerIds).toContain("alice");
    expect(photo!.playerIds).toContain("bob");
  });

  it("returns empty array with fewer than 2 participants with zone_history", () => {
    const players = [
      participant("alice", {
        zone_history: [{ node_id: "start", igt_ms: 0 }],
      }),
    ];
    expect(computeHighlights(players, graph)).toEqual([]);
  });
});
```

### Step 2: Run test to verify it fails

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/__tests__/highlights.test.ts`

Expected: FAIL — `computeHighlights` not exported

### Step 3: Implement all highlight detectors and the scoring/selection logic

Add to `web/src/lib/highlights.ts` the following functions:

- `detectSpeedDemon(allZoneTimes, nodeInfo)` — finds the zone where a player's time ratio vs average is lowest
- `detectZoneWall(allZoneTimes, nodeInfo)` — finds the zone where a player's time ratio vs average is highest
- `detectFastStarter(participants, nodeInfo)` — player reaching layer 2 first
- `detectSprintFinal(allZoneTimes, nodeInfo, participants)` — fastest in last tier
- `detectGraveyard(allZoneTimes, nodeInfo)` — zone with most cumulative deaths
- `detectDeathZone(allZoneTimes, nodeInfo)` — most deaths by a single player in one zone
- `detectDeathless(allZoneTimes, nodeInfo)` — player with 0 deaths in a tier 3+ zone
- `detectComebackKid(participants)` — most deaths but still finished well
- `detectRoadLessTraveled(participants)` — most unique path
- `detectSameBrain(participants)` — two players with identical path
- `detectDetour(participants)` — most nodes visited
- `detectPhotoFinish(participants)` — closest IGT gap between finishers
- `detectLeadChanges(participants, nodeInfo)` — leader changes across layers
- `detectDominant(participants, nodeInfo)` — player leading at every layer
- `computeHighlights(participants, graphJson)` — orchestrator: calls all detectors, scores, diversifies, returns top 5-6

The `nodeInfo` is a Map built from `graphJson` nodes (nodeId → { tier, layer, displayName, type }).

**Implementation details for `computeHighlights`:**

```typescript
export function computeHighlights(
  participants: WsParticipant[],
  graphJson: Record<string, unknown>,
): Highlight[] {
  // Need at least 2 participants with zone_history for meaningful comparisons
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );
  if (eligible.length < 2) return [];

  // Build node info map from graph_json
  const nodeInfo = buildNodeInfo(graphJson);

  // Compute per-participant zone times
  const allZoneTimes = new Map(
    eligible.map((p) => [p.id, computeZoneTimes(p)]),
  );

  // Collect all candidates
  const candidates: Highlight[] = [];
  const push = (h: Highlight | null) => {
    if (h) candidates.push(h);
  };

  push(detectSpeedDemon(eligible, allZoneTimes, nodeInfo));
  push(detectZoneWall(eligible, allZoneTimes, nodeInfo));
  push(detectFastStarter(eligible, nodeInfo));
  push(detectSprintFinal(eligible, allZoneTimes, nodeInfo));
  push(detectGraveyard(eligible, allZoneTimes, nodeInfo));
  push(detectDeathZone(eligible, allZoneTimes, nodeInfo));
  push(detectDeathless(eligible, allZoneTimes, nodeInfo));
  push(detectComebackKid(eligible));
  push(detectRoadLessTraveled(eligible));
  push(detectSameBrain(eligible));
  push(detectDetour(eligible));
  push(detectPhotoFinish(eligible));
  push(detectLeadChanges(eligible, nodeInfo));
  push(detectDominant(eligible, nodeInfo));

  // Sort by score descending
  candidates.sort((a, b) => b.score - a.score);

  // Diversity filter: max 2 per category
  const categoryCounts = new Map<string, number>();
  const selected: Highlight[] = [];
  for (const h of candidates) {
    const count = categoryCounts.get(h.category) ?? 0;
    if (count >= 2) continue;
    categoryCounts.set(h.category, count + 1);
    selected.push(h);
    if (selected.length >= 6) break;
  }

  return selected;
}
```

Each detector function returns `Highlight | null`. Scoring uses:

- Base score from the metric amplitude (e.g., time ratio for Speed Demon)
- Tier multiplier (higher tier zones score higher)
- Normalized to 0-100 range for comparability

### Step 4: Run tests

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/__tests__/highlights.test.ts`

Expected: All PASS

### Step 5: Commit

```bash
git add web/src/lib/highlights.ts web/src/lib/__tests__/highlights.test.ts
git commit -m "feat(web): implement all highlight detectors with scoring and selection"
```

---

## Task 3: Death and path highlight tests

**Files:**

- Modify: `web/src/lib/__tests__/highlights.test.ts`

### Step 1: Add tests for remaining highlight types

Append to `highlights.test.ts`:

```typescript
describe("death highlights", () => {
  const graph = graphJson({
    start: { tier: 1, layer: 0, type: "start" },
    zone_a: { tier: 2, layer: 1 },
    zone_b: { tier: 3, layer: 2 },
    zone_c: { tier: 3, layer: 3, type: "final_boss" },
  });

  it("Graveyard: detects zone with most cumulative deaths", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        death_count: 8,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_b", igt_ms: 100000, deaths: 5 },
          { node_id: "zone_c", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        death_count: 6,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_b", igt_ms: 120000, deaths: 4 },
          { node_id: "zone_c", igt_ms: 350000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const graveyard = highlights.find((h) => h.type === "graveyard");
    expect(graveyard).toBeDefined();
    // zone_b has 5+4=9 total deaths
    expect(graveyard!.description).toContain("zone_b");
  });

  it("Comeback Kid: player with most deaths who finished well", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 310000,
        death_count: 15,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 310000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 300000,
        death_count: 2,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 300000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 350000,
        death_count: 20,
        status: "abandoned",
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 350000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const comeback = highlights.find((h) => h.type === "comeback_kid");
    // Alice has most deaths among finishers and still finished 2nd
    if (comeback) {
      expect(comeback.playerIds).toContain("alice");
    }
  });
});

describe("path highlights", () => {
  const graph = graphJson({
    start: { tier: 1, layer: 0, type: "start" },
    zone_a: { tier: 2, layer: 1 },
    zone_b: { tier: 2, layer: 1 },
    zone_c: { tier: 3, layer: 2 },
    zone_d: { tier: 3, layer: 2 },
    final: { tier: 3, layer: 3, type: "final_boss" },
  });

  it("Same Brain: detects two players with identical path", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 60000 },
          { node_id: "zone_c", igt_ms: 120000 },
          { node_id: "final", igt_ms: 350000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 400000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_b", igt_ms: 70000 },
          { node_id: "zone_d", igt_ms: 140000 },
          { node_id: "final", igt_ms: 400000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const sameBrain = highlights.find((h) => h.type === "same_brain");
    expect(sameBrain).toBeDefined();
    expect(sameBrain!.playerIds).toContain("alice");
    expect(sameBrain!.playerIds).toContain("bob");
  });

  it("Road Less Traveled: detects player with most unique path", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_b", igt_ms: 50000 },
          { node_id: "zone_d", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const road = highlights.find((h) => h.type === "road_less_traveled");
    expect(road).toBeDefined();
    // Alice took zone_b + zone_d while others took zone_a + zone_c
    expect(road!.playerIds).toContain("alice");
  });
});
```

### Step 2: Run tests

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/__tests__/highlights.test.ts`

Expected: All PASS (tests exercise detectors implemented in Task 2)

### Step 3: Commit

```bash
git add web/src/lib/__tests__/highlights.test.ts
git commit -m "test(web): add death and path highlight tests"
```

---

## Task 4: RaceHighlights Svelte component

**Files:**

- Create: `web/src/lib/components/RaceHighlights.svelte`

### Step 1: Create the component

```svelte
<script lang="ts">
 import type { WsParticipant } from '$lib/websocket';
 import { computeHighlights, type Highlight } from '$lib/highlights';
 import { PLAYER_COLORS } from '$lib/dag/constants';

 interface Props {
  participants: WsParticipant[];
  graphJson: Record<string, unknown>;
 }

 let { participants, graphJson }: Props = $props();

 let highlights = $derived(computeHighlights(participants, graphJson));

 function playerColor(highlight: Highlight): string[] {
  return highlight.playerIds.map((id) => {
   const p = participants.find((pp) => pp.id === id);
   return p ? PLAYER_COLORS[p.color_index % PLAYER_COLORS.length] : '#9CA3AF';
  });
 }

 function playerNames(highlight: Highlight): string[] {
  return highlight.playerIds.map((id) => {
   const p = participants.find((pp) => pp.id === id);
   return p?.twitch_display_name || p?.twitch_username || '???';
  });
 }
</script>

{#if highlights.length > 0}
 <div class="race-highlights">
  <h2>Highlights</h2>
  <ul class="highlight-list">
   {#each highlights as highlight}
    <li class="highlight-item">
     <span class="highlight-title">{highlight.title}</span>
     <span class="highlight-desc">{highlight.description}</span>
    </li>
   {/each}
  </ul>
 </div>
{/if}

<style>
 .race-highlights {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
 }

 h2 {
  color: var(--color-gold);
  margin: 0 0 1rem 0;
  font-size: var(--font-size-lg);
  font-weight: 600;
 }

 .highlight-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
 }

 .highlight-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border);
 }

 .highlight-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
 }

 .highlight-title {
  font-weight: 600;
  font-size: var(--font-size-base);
  color: var(--color-text);
 }

 .highlight-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
 }
</style>
```

### Step 2: Commit

```bash
git add web/src/lib/components/RaceHighlights.svelte
git commit -m "feat(web): add RaceHighlights display component"
```

---

## Task 5: Integrate into race detail page

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

### Step 1: Add import and render component

In `+page.svelte`, add the import at the top of the `<script>` block (around line 18, after the RaceStats import):

```typescript
import RaceHighlights from "$lib/components/RaceHighlights.svelte";
```

In the template, add the component right after `<RaceStats>` (around line 573):

```svelte
 {:else if liveSeed?.graph_json && raceStatus === 'finished'}
  <Podium participants={raceStore.leaderboard} />
  <MetroDagFull
   graphJson={liveSeed.graph_json}
   participants={raceStore.leaderboard}
   highlightIds={selectedParticipantIds}
  />
  <RaceStats participants={raceStore.leaderboard} />
  <RaceHighlights participants={raceStore.leaderboard} graphJson={liveSeed.graph_json} />
```

### Step 2: Run type check

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`

Expected: No errors

### Step 3: Run all tests

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm test`

Expected: All PASS

### Step 4: Commit

```bash
git add web/src/routes/race/[id]/+page.svelte
git commit -m "feat(web): integrate RaceHighlights into race detail page"
```

---

## Task 6: Manual verification and polish

### Step 1: Start dev server and verify visually

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run dev`

Open a finished race in the browser. Verify:

- Highlights section appears after RaceStats
- 5-6 highlights displayed with titles and descriptions
- Section hidden when race has < 2 participants with zone_history
- Section hidden when race is not FINISHED

### Step 2: Adjust description text to include player-colored names

Update `RaceHighlights.svelte` to use `{@html}` for player-colored names in descriptions if needed, or build description as structured data with player references. The exact approach depends on how the descriptions are formatted in the highlight detectors.

### Step 3: Final commit

```bash
git add -u
git commit -m "fix(web): polish highlight descriptions and styling"
```

---

## Summary

| Task | Description                                      | Files                  |
| ---- | ------------------------------------------------ | ---------------------- |
| 1    | Core types + `computeZoneTimes` helper           | `highlights.ts`, tests |
| 2    | All 14 highlight detectors + `computeHighlights` | `highlights.ts`, tests |
| 3    | Additional death/path highlight tests            | tests                  |
| 4    | `RaceHighlights.svelte` component                | component              |
| 5    | Integration in race detail page                  | `+page.svelte`         |
| 6    | Manual verification + polish                     | various                |
