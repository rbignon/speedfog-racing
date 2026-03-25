# Personal Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Your Race" tab in the highlights section showing player-specific highlights computed from zone_history data.

**Architecture:** New `personal-highlights.ts` file with 15 detectors following the same pattern as `highlights.ts`. Modifications to `RaceHighlights.svelte` to add toggle tabs and render personal highlights. One-line prop addition in `+page.svelte`.

**Tech Stack:** TypeScript, SvelteKit 5 (runes), Vitest

**Spec:** `docs/plans/2026-03-25-personal-highlights.md`

---

## Tasks

### Task 1: Export helpers from highlights.ts and widen HighlightCategory

**Files:**

- Modify: `web/src/lib/highlights.ts`
- Test: `web/src/lib/__tests__/highlights.test.ts` (existing tests must still pass)

- [ ] **Step 1: Widen HighlightCategory type**

In `web/src/lib/highlights.ts`, change line 27:

```typescript
export type HighlightCategory =
  | "speed"
  | "deaths"
  | "path"
  | "competitive"
  | "combat"
  | "pathing";
```

- [ ] **Step 2: Export helpers and NodeInfo type**

Add `export` keyword to the following functions and type in `web/src/lib/highlights.ts`:

- `interface NodeInfo` (line 113) -> `export interface NodeInfo`
- `function buildNodeInfo` (line 120) -> `export function buildNodeInfo`
- `function pSeg` (line 139) -> `export function pSeg`
- `function shortName` (line 147) -> `export function shortName`
- `function zSeg` (line 153) -> `export function zSeg`
- `function tSeg` (line 165) -> `export function tSeg`
- `function formatTime` (line 169) -> `export function formatTime`
- `function uniqueNodePath` (line 182) -> `export function uniqueNodePath`
- `function buildZonePlayerTimes` (line 223) -> `export function buildZonePlayerTimes`

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd web && npx vitest run src/lib/__tests__/highlights.test.ts`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/highlights.ts
git commit -m "refactor: export helpers from highlights.ts and widen HighlightCategory"
```

---

### Task 2: Personal highlights helpers and combat detectors

**Files:**

- Create: `web/src/lib/personal-highlights.ts`
- Create: `web/src/lib/__tests__/personal-highlights.test.ts`

- [ ] **Step 1: Write test helpers and combat detector tests**

Create `web/src/lib/__tests__/personal-highlights.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  computePersonalHighlights,
  descriptionText,
} from "$lib/personal-highlights";
import { type Highlight } from "$lib/highlights";
import type { WsParticipant } from "$lib/websocket";

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

function graphJson(
  nodes: Record<
    string,
    { tier?: number; layer?: number; type?: string; display_name?: string }
  >,
  edges: { from: string; to: string }[] = [],
) {
  const nodeEntries: Record<string, unknown> = {};
  for (const [id, data] of Object.entries(nodes)) {
    nodeEntries[id] = {
      type: data.type ?? "mini_dungeon",
      display_name: data.display_name ?? id,
      zones: [],
      layer: data.layer ?? 0,
      tier: data.tier ?? 1,
      weight: 1,
    };
  }
  return { nodes: nodeEntries, edges, total_layers: 3 };
}

function findHighlight(
  highlights: Highlight[],
  type: string,
): Highlight | undefined {
  return highlights.find((h) => h.type === type);
}

describe("computePersonalHighlights", () => {
  it("returns empty when fewer than 2 participants have zone_history", () => {
    const me = participant("me", {
      zone_history: [{ node_id: "start", igt_ms: 0 }],
    });
    const other = participant("other");
    const graph = graphJson({ start: { layer: 0 } });
    expect(computePersonalHighlights("me", [me, other], graph)).toEqual([]);
  });

  it("returns at most 6 highlights", () => {
    // Build a scenario with many zone_history entries to trigger many detectors
    const me = participant("me", {
      igt_ms: 600000,
      death_count: 20,
      zone_history: [
        { node_id: "start", igt_ms: 0, deaths: 0 },
        { node_id: "a", igt_ms: 10000, deaths: 0 },
        { node_id: "b", igt_ms: 30000, deaths: 0 },
        { node_id: "c", igt_ms: 60000, deaths: 0 },
        { node_id: "d", igt_ms: 100000, deaths: 6 },
        { node_id: "e", igt_ms: 200000, deaths: 0 },
        { node_id: "f", igt_ms: 250000, deaths: 5 },
        { node_id: "boss", igt_ms: 400000, deaths: 1 },
      ],
    });
    const other = participant("other", {
      igt_ms: 500000,
      death_count: 15,
      zone_history: [
        { node_id: "start", igt_ms: 0, deaths: 0 },
        { node_id: "a", igt_ms: 50000, deaths: 3 },
        { node_id: "b", igt_ms: 100000, deaths: 2 },
        { node_id: "c", igt_ms: 150000, deaths: 1 },
        { node_id: "d", igt_ms: 200000, deaths: 2 },
        { node_id: "e", igt_ms: 300000, deaths: 0 },
        { node_id: "f", igt_ms: 350000, deaths: 0 },
        { node_id: "boss", igt_ms: 450000, deaths: 7 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      a: { layer: 1 },
      b: { layer: 2 },
      c: { layer: 3 },
      d: { layer: 4 },
      e: { layer: 5 },
      f: { layer: 6 },
      boss: { layer: 7, type: "boss" },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    expect(result.length).toBeLessThanOrEqual(6);
  });
});

describe("combat detectors", () => {
  it("detects boss_slayer when player has fewer deaths than average on a boss", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 100000, deaths: 1 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 200000, deaths: 8 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 350000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 150000, deaths: 6 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      boss: { layer: 1, type: "boss" },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "boss_slayer");
    expect(h).toBeDefined();
    expect(h!.category).toBe("combat");
    expect(descriptionText(h!)).toContain("1");
  });

  it("detects boss_wall when player has many more deaths than average on a boss", () => {
    const me = participant("me", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 200000, deaths: 10 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 150000, deaths: 2 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 350000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 180000, deaths: 3 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      boss: { layer: 1, type: "boss" },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "boss_wall");
    expect(h).toBeDefined();
    expect(h!.category).toBe("combat");
  });

  it("detects stood_your_ground when player clears a zone others backed from", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "hard_zone", igt_ms: 50000, deaths: 2 },
        { node_id: "next", igt_ms: 150000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "hard_zone", igt_ms: 50000, deaths: 3 },
        { node_id: "start", igt_ms: 100000 },
        { node_id: "alt", igt_ms: 150000 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "hard_zone", igt_ms: 60000, deaths: 4 },
        { node_id: "start", igt_ms: 120000 },
        { node_id: "alt", igt_ms: 180000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      hard_zone: { layer: 1 },
      next: { layer: 2 },
      alt: { layer: 1 },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "stood_your_ground");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("hard_zone");
  });

  it("detects death_spiral when player dies 5+ times but clears the zone", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "brutal", igt_ms: 50000, deaths: 7 },
        { node_id: "next", igt_ms: 200000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "brutal", igt_ms: 50000, deaths: 2 },
        { node_id: "next", igt_ms: 150000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      brutal: { layer: 1, tier: 2 },
      next: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "death_spiral");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("7");
  });

  it("detects clean_streak when player clears 3+ zones without dying", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "a", igt_ms: 0, deaths: 0 },
        { node_id: "b", igt_ms: 50000, deaths: 0 },
        { node_id: "c", igt_ms: 100000, deaths: 0 },
        { node_id: "d", igt_ms: 150000, deaths: 0 },
      ],
    });
    const other = participant("other", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "a", igt_ms: 0, deaths: 2 },
        { node_id: "b", igt_ms: 60000, deaths: 3 },
        { node_id: "c", igt_ms: 130000, deaths: 1 },
        { node_id: "d", igt_ms: 200000, deaths: 0 },
      ],
    });
    const graph = graphJson({
      a: { layer: 0 },
      b: { layer: 1 },
      c: { layer: 2 },
      d: { layer: 3 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "clean_streak");
    expect(h).toBeDefined();
    expect(h!.category).toBe("combat");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Create personal-highlights.ts with helpers and combat detectors**

Create `web/src/lib/personal-highlights.ts`:

```typescript
/**
 * Personal highlights computation.
 *
 * Pure functions that compute player-specific highlights from
 * zone_history data and graph_json topology. Uses direct tone ("You...").
 */

import type { WsParticipant } from "$lib/websocket";
import {
  type Highlight,
  type DescriptionSegment,
  type ZoneTime,
  type NodeInfo,
  computeZoneTimes,
  buildNodeInfo,
  pSeg,
  zSeg,
  tSeg,
  formatTime,
  uniqueNodePath,
  buildZonePlayerTimes,
} from "$lib/highlights";

// =============================================================================
// Types
// =============================================================================

type PersonalHighlightCategory = "combat" | "pathing" | "competitive";

// =============================================================================
// Helpers
// =============================================================================

/** Flatten segments into a plain description string (for tests). */
export function descriptionText(h: Highlight): string {
  return h.segments.map((s) => (s.type === "text" ? s.value : s.name)).join("");
}

/**
 * Build a map of zoneId -> list of { playerId, deaths } for boss nodes.
 */
function buildBossDeaths(
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Map<string, { playerId: string; deaths: number }[]> {
  const map = new Map<string, { playerId: string; deaths: number }[]>();
  for (const [pid, zones] of allZoneTimes) {
    for (const zt of zones) {
      const info = nodeInfo.get(zt.nodeId);
      if (!info || (info.type !== "boss" && info.type !== "final_boss"))
        continue;
      if (!map.has(zt.nodeId)) map.set(zt.nodeId, []);
      map.get(zt.nodeId)!.push({ playerId: pid, deaths: zt.deaths });
    }
  }
  return map;
}

// =============================================================================
// Combat Detectors
// =============================================================================

function detectBossSlayer(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const bossDeaths = buildBossDeaths(allZoneTimes, nodeInfo);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [bossId, entries] of bossDeaths) {
    if (entries.length < 2) continue;
    const myEntry = entries.find((e) => e.playerId === myId);
    if (!myEntry) continue;

    const othersDeaths = entries.filter((e) => e.playerId !== myId);
    const avgDeaths =
      othersDeaths.reduce((s, e) => s + e.deaths, 0) / othersDeaths.length;
    if (avgDeaths <= 0) continue;

    const ratio = myEntry.deaths / avgDeaths;
    if (ratio >= 0.5) continue;

    const info = nodeInfo.get(bossId);
    const tierMult = info?.tier ?? 1;
    const score = (1 - ratio) * 100 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "boss_slayer",
        category: "combat" as PersonalHighlightCategory,
        title: "Boss Slayer",
        segments: [
          tSeg(
            `You only died ${myEntry.deaths} time${myEntry.deaths !== 1 ? "s" : ""} on `,
          ),
          zSeg(bossId, nodeInfo),
          tSeg(` (average: ${Math.round(avgDeaths)})`),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectBossWall(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const bossDeaths = buildBossDeaths(allZoneTimes, nodeInfo);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [bossId, entries] of bossDeaths) {
    if (entries.length < 2) continue;
    const myEntry = entries.find((e) => e.playerId === myId);
    if (!myEntry || myEntry.deaths === 0) continue;

    const othersDeaths = entries.filter((e) => e.playerId !== myId);
    const avgDeaths =
      othersDeaths.reduce((s, e) => s + e.deaths, 0) / othersDeaths.length;
    if (avgDeaths <= 0) continue;

    const ratio = myEntry.deaths / avgDeaths;
    if (ratio <= 2) continue;

    const score = ratio * 30;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "boss_wall",
        category: "combat" as PersonalHighlightCategory,
        title: "Boss Wall",
        segments: [
          zSeg(bossId, nodeInfo),
          tSeg(
            ` gave you trouble: ${myEntry.deaths} deaths (average: ${Math.round(avgDeaths)})`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectStoodYourGround(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const myZt of myZones) {
    if (myZt.outcome !== "cleared") continue;

    let backedCount = 0;
    for (const [pid, zones] of allZoneTimes) {
      if (pid === myId) continue;
      const theirZt = zones.find((z) => z.nodeId === myZt.nodeId);
      if (theirZt && theirZt.outcome === "backed") backedCount++;
    }

    if (backedCount === 0) continue;

    const info = nodeInfo.get(myZt.nodeId);
    const tierMult = info?.tier ?? 1;
    const score = backedCount * 35 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "stood_your_ground",
        category: "combat" as PersonalHighlightCategory,
        title: "Stood Your Ground",
        segments: [
          tSeg("You're the only one who didn't turn back from "),
          zSeg(myZt.nodeId, nodeInfo),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectDeathSpiral(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const zt of myZones) {
    if (zt.outcome !== "cleared" || zt.deaths < 5) continue;

    const info = nodeInfo.get(zt.nodeId);
    const tierMult = info?.tier ?? 1;
    const score = zt.deaths * 15 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "death_spiral",
        category: "combat" as PersonalHighlightCategory,
        title: "Death Spiral",
        segments: [
          tSeg(`You left ${zt.deaths} lives on `),
          zSeg(zt.nodeId, nodeInfo),
          tSeg(" before finally pushing through"),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectCleanStreak(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  // Find longest consecutive streak of 0-death zones
  let bestStart = 0;
  let bestLen = 0;
  let curStart = 0;
  let curLen = 0;

  for (let i = 0; i < myZones.length; i++) {
    if (myZones[i].deaths === 0) {
      if (curLen === 0) curStart = i;
      curLen++;
      if (curLen > bestLen) {
        bestLen = curLen;
        bestStart = curStart;
      }
    } else {
      curLen = 0;
    }
  }

  if (bestLen < 3) return null;

  // Count others' total deaths across those same zones
  const streakZoneIds = myZones
    .slice(bestStart, bestStart + bestLen)
    .map((z) => z.nodeId);
  let othersDeaths = 0;
  for (const [pid, zones] of allZoneTimes) {
    if (pid === myId) continue;
    for (const zt of zones) {
      if (streakZoneIds.includes(zt.nodeId)) othersDeaths += zt.deaths;
    }
  }

  if (othersDeaths === 0) return null;

  const score = bestLen * 25 + othersDeaths * 5;

  return {
    type: "clean_streak",
    category: "combat" as PersonalHighlightCategory,
    title: "Clean Streak",
    segments: [
      tSeg(
        `You cleared ${bestLen} zones in a row without dying, while others lost ${othersDeaths} lives there`,
      ),
    ],
    playerIds: [myId],
    score,
  };
}

// =============================================================================
// Orchestrator (partial - combat only for now)
// =============================================================================

export function computePersonalHighlights(
  myParticipantId: string,
  participants: WsParticipant[],
  graphJson: Record<string, unknown>,
): Highlight[] {
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );
  if (eligible.length < 2) return [];
  if (!eligible.find((p) => p.id === myParticipantId)) return [];

  const nodeInfo = buildNodeInfo(graphJson);
  const allZoneTimes = new Map(
    eligible.map((p) => [p.id, computeZoneTimes(p, nodeInfo)]),
  );

  const candidates: Highlight[] = [];
  const push = (h: Highlight | null) => {
    if (h) candidates.push(h);
  };

  // Combat detectors
  push(detectBossSlayer(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(detectBossWall(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(
    detectStoodYourGround(myParticipantId, eligible, allZoneTimes, nodeInfo),
  );
  push(detectDeathSpiral(myParticipantId, allZoneTimes, nodeInfo));
  push(detectCleanStreak(myParticipantId, eligible, allZoneTimes, nodeInfo));

  // Selection
  candidates.sort((a, b) => b.score - a.score);

  const categoryCounts = new Map<string, number>();
  const usedZones = new Set<string>();
  const selected: Highlight[] = [];
  for (const h of candidates) {
    const count = categoryCounts.get(h.category) ?? 0;
    if (count >= 2) continue;
    const zones = h.segments
      .filter(
        (s): s is Extract<DescriptionSegment, { type: "zone" }> =>
          s.type === "zone",
      )
      .map((s) => s.nodeId);
    if (zones.length > 0 && zones.some((z) => usedZones.has(z))) continue;
    categoryCounts.set(h.category, count + 1);
    zones.forEach((z) => usedZones.add(z));
    selected.push(h);
    if (selected.length >= 6) break;
  }

  return selected;
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/personal-highlights.ts web/src/lib/__tests__/personal-highlights.test.ts
git commit -m "feat: add personal highlights with combat detectors (5/15)"
```

---

### Task 3: Pathing detectors

**Files:**

- Modify: `web/src/lib/personal-highlights.ts`
- Modify: `web/src/lib/__tests__/personal-highlights.test.ts`

- [ ] **Step 1: Write pathing detector tests**

Append to `web/src/lib/__tests__/personal-highlights.test.ts`:

```typescript
describe("pathing detectors", () => {
  it("detects lone_explorer when player visits a zone nobody else visited", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "secret", igt_ms: 50000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "normal", igt_ms: 50000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      secret: { layer: 1 },
      normal: { layer: 1 },
      end: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "lone_explorer");
    expect(h).toBeDefined();
    expect(h!.category).toBe("pathing");
    expect(descriptionText(h!)).toContain("secret");
  });

  it("detects against_the_flow at a fork where player took a unique branch", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "fork", igt_ms: 0 },
        { node_id: "branch_b", igt_ms: 50000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "fork", igt_ms: 0 },
        { node_id: "branch_a", igt_ms: 60000 },
        { node_id: "end", igt_ms: 250000 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "fork", igt_ms: 0 },
        { node_id: "branch_a", igt_ms: 70000 },
        { node_id: "end", igt_ms: 220000 },
      ],
    });
    const graph = graphJson(
      {
        fork: { layer: 0 },
        branch_a: { layer: 1 },
        branch_b: { layer: 1 },
        end: { layer: 2 },
      },
      [
        { from: "fork", to: "branch_a" },
        { from: "fork", to: "branch_b" },
        { from: "branch_a", to: "end" },
        { from: "branch_b", to: "end" },
      ],
    );
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "against_the_flow");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("fork");
  });

  it("detects smart_backtrack when backing out saved time", () => {
    const me = participant("me", {
      igt_ms: 250000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "hard", igt_ms: 30000, deaths: 1 },
        { node_id: "start", igt_ms: 50000 },
        { node_id: "easy", igt_ms: 60000 },
        { node_id: "end", igt_ms: 150000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "hard", igt_ms: 30000, deaths: 5 },
        { node_id: "end", igt_ms: 300000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      hard: { layer: 1 },
      easy: { layer: 1 },
      end: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "smart_backtrack");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("hard");
  });

  it("detects costly_detour when visiting a zone that top finishers skipped", () => {
    const me = participant("me", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "detour", igt_ms: 50000 },
        { node_id: "main", igt_ms: 200000 },
        { node_id: "end", igt_ms: 350000 },
      ],
    });
    const winner = participant("winner", {
      igt_ms: 250000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "main", igt_ms: 50000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      detour: { layer: 1 },
      main: { layer: 1 },
      end: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, winner], graph);
    const h = findHighlight(result, "costly_detour");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("detour");
  });
});
```

- [ ] **Step 2: Run tests to verify pathing tests fail**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: FAIL on pathing tests (detectors not found)

- [ ] **Step 3: Implement pathing detectors**

Add the following detector functions to `web/src/lib/personal-highlights.ts` before the orchestrator:

```typescript
// =============================================================================
// Pathing Detectors
// =============================================================================

function detectLoneExplorer(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  const othersZoneIds = new Set<string>();
  for (const [pid, zones] of allZoneTimes) {
    if (pid === myId) continue;
    for (const zt of zones) othersZoneIds.add(zt.nodeId);
  }

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const zt of myZones) {
    if (othersZoneIds.has(zt.nodeId)) continue;

    const score = participants.length * 20;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "lone_explorer",
        category: "pathing" as PersonalHighlightCategory,
        title: "Lone Explorer",
        segments: [
          tSeg("You're the only one who visited "),
          zSeg(zt.nodeId, nodeInfo),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

/**
 * Build a map of parentId -> [childId, ...] from graph_json edges.
 */
function buildChildrenMap(
  graphJson: Record<string, unknown>,
): Map<string, string[]> {
  const edges = (graphJson as { edges: { from: string; to: string }[] }).edges;
  const map = new Map<string, string[]>();
  if (!edges) return map;
  for (const e of edges) {
    if (!map.has(e.from)) map.set(e.from, []);
    map.get(e.from)!.push(e.to);
  }
  return map;
}

function detectAgainstTheFlow(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
  graphJson: Record<string, unknown>,
): Highlight | null {
  const childrenMap = buildChildrenMap(graphJson);
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );

  // For each player, build their unique node path
  const playerPaths = new Map<string, string[]>();
  for (const p of eligible) {
    playerPaths.set(p.id, uniqueNodePath(p.zone_history!));
  }

  const myPath = playerPaths.get(myId);
  if (!myPath) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (let i = 0; i < myPath.length; i++) {
    const forkNode = myPath[i];
    const children = childrenMap.get(forkNode);
    if (!children || children.length < 2) continue;

    // Find my first child after this fork
    const myNextInPath = myPath[i + 1];
    if (!myNextInPath || !children.includes(myNextInPath)) continue;

    // Check what branches others took
    let othersOnDifferentBranch = 0;
    let anyoneOnMyBranch = false;

    for (const [pid, path] of playerPaths) {
      if (pid === myId) continue;
      const forkIdx = path.indexOf(forkNode);
      if (forkIdx < 0 || forkIdx >= path.length - 1) continue;
      const theirNext = path[forkIdx + 1];
      if (!children.includes(theirNext)) continue;
      if (theirNext === myNextInPath) {
        anyoneOnMyBranch = true;
      } else {
        othersOnDifferentBranch++;
      }
    }

    if (anyoneOnMyBranch || othersOnDifferentBranch === 0) continue;

    const score = othersOnDifferentBranch * 30;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "against_the_flow",
        category: "pathing" as PersonalHighlightCategory,
        title: "Against the Flow",
        segments: [
          tSeg("At the "),
          zSeg(forkNode, nodeInfo),
          tSeg(" crossroads, you took a path no one else did"),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectSmartBacktrack(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const myZt of myZones) {
    if (myZt.outcome !== "backed") continue;

    // Find others who cleared this zone and how long it took them
    const othersClearTimes: number[] = [];
    for (const [pid, zones] of allZoneTimes) {
      if (pid === myId) continue;
      const theirZt = zones.find((z) => z.nodeId === myZt.nodeId);
      if (theirZt && theirZt.outcome === "cleared") {
        othersClearTimes.push(theirZt.timeMs);
      }
    }

    if (othersClearTimes.length === 0) continue;

    const avgClearTime =
      othersClearTimes.reduce((s, t) => s + t, 0) / othersClearTimes.length;
    const timeSavedMs = avgClearTime - myZt.timeMs;
    if (timeSavedMs <= 0) continue;

    const score = (timeSavedMs / 1000) * 2;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "smart_backtrack",
        category: "pathing" as PersonalHighlightCategory,
        title: "Smart Backtrack",
        segments: [
          tSeg("Good call turning back from "),
          zSeg(myZt.nodeId, nodeInfo),
          tSeg(
            `: those who stayed spent ${formatTime(avgClearTime - myZt.timeMs)} longer on average`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectCostlyDetour(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  // Find better-ranked finishers
  const me = participants.find((p) => p.id === myId);
  if (!me) return null;

  const betterFinishers = participants.filter(
    (p) =>
      p.id !== myId &&
      p.status === "finished" &&
      p.igt_ms < (me.igt_ms || Infinity),
  );
  if (betterFinishers.length === 0) return null;

  // Zones visited by better finishers
  const betterZoneIds = new Set<string>();
  for (const p of betterFinishers) {
    const zones = allZoneTimes.get(p.id);
    if (zones) {
      for (const zt of zones) betterZoneIds.add(zt.nodeId);
    }
  }

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const myZt of myZones) {
    if (betterZoneIds.has(myZt.nodeId)) continue;
    if (myZt.timeMs <= 0) continue;

    const score = (myZt.timeMs / 1000) * 1.5;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "costly_detour",
        category: "pathing" as PersonalHighlightCategory,
        title: "Costly Detour",
        segments: [
          tSeg("Your detour through "),
          zSeg(myZt.nodeId, nodeInfo),
          tSeg(
            ` cost you ${formatTime(myZt.timeMs)} compared to those who skipped it`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}
```

Then add these detector calls to the orchestrator, after the combat detectors:

```typescript
// Pathing detectors
push(detectLoneExplorer(myParticipantId, eligible, allZoneTimes, nodeInfo));
push(detectAgainstTheFlow(myParticipantId, eligible, nodeInfo, graphJson));
push(detectSmartBacktrack(myParticipantId, allZoneTimes, nodeInfo));
push(detectCostlyDetour(myParticipantId, eligible, allZoneTimes, nodeInfo));
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/personal-highlights.ts web/src/lib/__tests__/personal-highlights.test.ts
git commit -m "feat: add pathing detectors for personal highlights (9/15)"
```

---

### Task 4: Competitive detectors

**Files:**

- Modify: `web/src/lib/personal-highlights.ts`
- Modify: `web/src/lib/__tests__/personal-highlights.test.ts`

- [ ] **Step 1: Write competitive detector tests**

Append to `web/src/lib/__tests__/personal-highlights.test.ts`:

```typescript
describe("competitive detectors", () => {
  it("detects faster_than_all when player is fastest on a zone", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 10000 },
        { node_id: "end", igt_ms: 100000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 50000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 60000 },
        { node_id: "end", igt_ms: 250000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      end: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "faster_than_all");
    expect(h).toBeDefined();
    expect(h!.category).toBe("competitive");
  });

  it("detects lead_lost when player was leading then lost the lead", () => {
    // me leads at layer 1 (arrives first), p2 leads at layer 2 (arrives first)
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 30000 },
        { node_id: "zone_b", igt_ms: 200000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 250000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 50000 },
        { node_id: "zone_b", igt_ms: 100000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      zone_b: { layer: 2 },
    });
    const result = computePersonalHighlights("me", [me, p2], graph);
    const h = findHighlight(result, "lead_lost");
    expect(h).toBeDefined();
  });

  it("detects comeback when player improves rank by 2+ positions", () => {
    // 3 players: me starts last at layer 1, then finishes first at layer 3
    const me = participant("me", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 80000 },
        { node_id: "l2", igt_ms: 120000 },
        { node_id: "l3", igt_ms: 150000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 250000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 30000 },
        { node_id: "l2", igt_ms: 140000 },
        { node_id: "l3", igt_ms: 200000 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 40000 },
        { node_id: "l2", igt_ms: 160000 },
        { node_id: "l3", igt_ms: 250000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      l1: { layer: 1 },
      l2: { layer: 2 },
      l3: { layer: 3 },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "comeback");
    expect(h).toBeDefined();
    expect(h!.category).toBe("competitive");
  });

  it("detects lead_swap when two players alternate as leader", () => {
    // me and p2 alternate leads across 4 layers
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 20000 },
        { node_id: "l2", igt_ms: 90000 },
        { node_id: "l3", igt_ms: 120000 },
        { node_id: "l4", igt_ms: 250000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 280000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 40000 },
        { node_id: "l2", igt_ms: 60000 },
        { node_id: "l3", igt_ms: 150000 },
        { node_id: "l4", igt_ms: 200000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      l1: { layer: 1 },
      l2: { layer: 2 },
      l3: { layer: 3 },
      l4: { layer: 4 },
    });
    const result = computePersonalHighlights("me", [me, p2], graph);
    const h = findHighlight(result, "lead_swap");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("P2");
  });

  it("detects neck_and_neck when two players stay close throughout", () => {
    // me and p2 within 1 rank at every layer, final times close
    const me = participant("me", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 30000 },
        { node_id: "l2", igt_ms: 80000 },
        { node_id: "l3", igt_ms: 130000 },
        { node_id: "l4", igt_ms: 170000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 210000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 35000 },
        { node_id: "l2", igt_ms: 75000 },
        { node_id: "l3", igt_ms: 135000 },
        { node_id: "l4", igt_ms: 175000 },
      ],
    });
    // Add a 3rd player far behind so rank differences are meaningful
    const p3 = participant("p3", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 100000 },
        { node_id: "l2", igt_ms: 200000 },
        { node_id: "l3", igt_ms: 300000 },
        { node_id: "l4", igt_ms: 350000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      l1: { layer: 1 },
      l2: { layer: 2 },
      l3: { layer: 3 },
      l4: { layer: 4 },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "neck_and_neck");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("P2");
  });
});
```

- [ ] **Step 2: Run tests to verify competitive tests fail**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: FAIL on competitive tests

- [ ] **Step 3: Implement computeRanksPerLayer helper and competitive detectors**

Add to `web/src/lib/personal-highlights.ts`, in the helpers section:

```typescript
/**
 * Compute each player's rank (1-based) at each layer.
 * Rank is determined by earliest IGT to reach that layer.
 * Returns Map<layer, Map<participantId, rank>>.
 */
function computeRanksPerLayer(
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Map<number, Map<string, number>> {
  const maxLayer = Math.max(...[...nodeInfo.values()].map((n) => n.layer), 0);
  const ranks = new Map<number, Map<string, number>>();

  for (let layer = 1; layer <= maxLayer; layer++) {
    const arrivals: { id: string; igt: number }[] = [];
    for (const p of participants) {
      if (!p.zone_history) continue;
      for (const entry of p.zone_history) {
        const info = nodeInfo.get(entry.node_id);
        if (info && info.layer >= layer) {
          arrivals.push({ id: p.id, igt: entry.igt_ms });
          break;
        }
      }
    }
    arrivals.sort((a, b) => a.igt - b.igt);
    const layerRanks = new Map<string, number>();
    arrivals.forEach((a, i) => layerRanks.set(a.id, i + 1));
    ranks.set(layer, layerRanks);
  }

  return ranks;
}
```

Then add the competitive detectors before the orchestrator:

```typescript
// =============================================================================
// Competitive Detectors
// =============================================================================

function detectFasterThanAll(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zonePlayerTimes = buildZonePlayerTimes(allZoneTimes, true);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const myTime = times.find((t) => t.playerId === myId);
    if (!myTime || myTime.timeMs <= 0) continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    const ratio = myTime.timeMs / avg;
    if (ratio >= 0.6) continue;

    // Check we're actually the fastest
    const isFastest = times.every(
      (t) => t.playerId === myId || t.timeMs >= myTime.timeMs,
    );
    if (!isFastest) continue;

    const tierMult = info?.tier ?? 1;
    const score = (1 - ratio) * 100 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "faster_than_all",
        category: "competitive" as PersonalHighlightCategory,
        title: "Fastest Through",
        segments: [
          tSeg("You were the fastest through "),
          zSeg(zoneId, nodeInfo),
          tSeg(`: ${formatTime(myTime.timeMs)} (average: ${formatTime(avg)})`),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectSlowerThanAll(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zonePlayerTimes = buildZonePlayerTimes(allZoneTimes, true);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const myTime = times.find((t) => t.playerId === myId);
    if (!myTime || myTime.timeMs <= 0) continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    const ratio = myTime.timeMs / avg;
    if (ratio <= 1.5) continue;

    // Check we're actually the slowest
    const isSlowest = times.every(
      (t) => t.playerId === myId || t.timeMs <= myTime.timeMs,
    );
    if (!isSlowest) continue;

    const score = (ratio - 1) * 50;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "slower_than_all",
        category: "competitive" as PersonalHighlightCategory,
        title: "Rough Zone",
        segments: [
          zSeg(zoneId, nodeInfo),
          tSeg(
            ` slowed you down: last with ${formatTime(myTime.timeMs)} (average: ${formatTime(avg)})`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectLeadLost(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  for (let i = 0; i < layers.length - 1; i++) {
    const curRanks = ranks.get(layers[i]);
    const nextRanks = ranks.get(layers[i + 1]);
    if (!curRanks || !nextRanks) continue;

    const myRankNow = curRanks.get(myId);
    const myRankNext = nextRanks.get(myId);

    if (myRankNow === 1 && myRankNext !== undefined && myRankNext > 1) {
      return {
        type: "lead_lost",
        category: "competitive" as PersonalHighlightCategory,
        title: "Lead Lost",
        segments: [
          tSeg(
            `You were leading the race, but lost the lead at layer ${layers[i + 1]}`,
          ),
        ],
        playerIds: [myId],
        score: 60,
      };
    }
  }

  return null;
}

function detectComeback(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  let bestGain = 0;
  let bestHighlight: Highlight | null = null;

  for (let i = 0; i < layers.length - 1; i++) {
    const curRanks = ranks.get(layers[i]);
    const nextRanks = ranks.get(layers[i + 1]);
    if (!curRanks || !nextRanks) continue;

    const rankBefore = curRanks.get(myId);
    const rankAfter = nextRanks.get(myId);
    if (rankBefore === undefined || rankAfter === undefined) continue;

    const gain = rankBefore - rankAfter;
    if (gain >= 2 && gain > bestGain) {
      bestGain = gain;
      bestHighlight = {
        type: "comeback",
        category: "competitive" as PersonalHighlightCategory,
        title: "Comeback",
        segments: [
          tSeg(
            `You were ${ordinal(rankBefore)} at layer ${layers[i]} before climbing back to ${ordinal(rankAfter)} place`,
          ),
        ],
        playerIds: [myId],
        score: gain * 30,
      };
    }
  }

  return bestHighlight;
}

function detectLeadSwap(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  // Count how many times me and each other player alternated as rank 1
  const swapCounts = new Map<string, number>();

  for (let i = 1; i < layers.length; i++) {
    const prevRanks = ranks.get(layers[i - 1]);
    const curRanks = ranks.get(layers[i]);
    if (!prevRanks || !curRanks) continue;

    const prevLeader = [...prevRanks.entries()].find(([, r]) => r === 1)?.[0];
    const curLeader = [...curRanks.entries()].find(([, r]) => r === 1)?.[0];

    if (!prevLeader || !curLeader || prevLeader === curLeader) continue;

    // Only count swaps involving me
    if (prevLeader !== myId && curLeader !== myId) continue;
    const other = prevLeader === myId ? curLeader : prevLeader;
    swapCounts.set(other, (swapCounts.get(other) ?? 0) + 1);
  }

  let bestOther = "";
  let bestSwaps = 0;
  for (const [otherId, count] of swapCounts) {
    if (count > bestSwaps) {
      bestSwaps = count;
      bestOther = otherId;
    }
  }

  if (bestSwaps < 3) return null;

  const otherP = participants.find((p) => p.id === bestOther);
  if (!otherP) return null;

  return {
    type: "lead_swap",
    category: "competitive" as PersonalHighlightCategory,
    title: "Lead Swap",
    segments: [
      tSeg("You and "),
      pSeg(otherP),
      tSeg(` traded the lead ${bestSwaps} times during the race`),
    ],
    playerIds: [myId, bestOther],
    score: bestSwaps * 25,
  };
}

function detectNeckAndNeck(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);
  if (layers.length < 3) return null;

  const me = participants.find((p) => p.id === myId);
  if (!me) return null;

  let bestHighlight: Highlight | null = null;
  let bestScore = 0;

  for (const other of participants) {
    if (other.id === myId) continue;

    let layersTogether = 0;
    for (const layer of layers) {
      const layerRanks = ranks.get(layer);
      if (!layerRanks) continue;
      const myRank = layerRanks.get(myId);
      const theirRank = layerRanks.get(other.id);
      if (myRank !== undefined && theirRank !== undefined) {
        if (Math.abs(myRank - theirRank) <= 1) layersTogether++;
      }
    }

    const ratio = layersTogether / layers.length;
    if (ratio < 0.7) continue;

    // Check final IGT gap < 10% of faster player's time
    const fasterIgt = Math.min(me.igt_ms, other.igt_ms);
    if (fasterIgt <= 0) continue;
    const gap = Math.abs(me.igt_ms - other.igt_ms);
    if (gap / fasterIgt >= 0.1) continue;

    const score = layersTogether * 10;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "neck_and_neck",
        category: "competitive" as PersonalHighlightCategory,
        title: "Neck and Neck",
        segments: [
          tSeg("You stayed neck and neck with "),
          pSeg(other),
          tSeg(" throughout the race"),
        ],
        playerIds: [myId, other.id],
        score,
      };
    }
  }

  return bestHighlight;
}

/** Format number as ordinal: 1 -> "1st", 2 -> "2nd", etc. */
function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
```

Then add these detector calls to the orchestrator:

```typescript
// Competitive detectors
push(detectFasterThanAll(myParticipantId, allZoneTimes, nodeInfo));
push(detectSlowerThanAll(myParticipantId, allZoneTimes, nodeInfo));
push(detectLeadLost(myParticipantId, eligible, nodeInfo));
push(detectComeback(myParticipantId, eligible, nodeInfo));
push(detectLeadSwap(myParticipantId, eligible, nodeInfo));
push(detectNeckAndNeck(myParticipantId, eligible, nodeInfo));
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/__tests__/personal-highlights.test.ts`
Expected: All tests PASS

- [ ] **Step 5: Run all web tests to check for regressions**

Run: `cd web && npx vitest run`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/personal-highlights.ts web/src/lib/__tests__/personal-highlights.test.ts
git commit -m "feat: add competitive detectors for personal highlights (15/15)"
```

---

### Task 5: Add tabs to RaceHighlights component

**Files:**

- Modify: `web/src/lib/components/RaceHighlights.svelte`
- Modify: `web/src/routes/race/[id]/+page.svelte`

- [ ] **Step 1: Add myParticipantId prop and tab logic to RaceHighlights.svelte**

Replace the full content of `web/src/lib/components/RaceHighlights.svelte` with:

```svelte
<script lang="ts">
 import type { WsParticipant } from '$lib/websocket';
 import { computeHighlights, type Highlight } from '$lib/highlights';
 import { computePersonalHighlights } from '$lib/personal-highlights';
 import { PLAYER_COLORS } from '$lib/dag/constants';

 interface Props {
  participants: WsParticipant[];
  graphJson: Record<string, unknown>;
  myParticipantId?: string;
  onzoneclick?: (nodeId: string) => void;
 }

 let { participants, graphJson, myParticipantId, onzoneclick }: Props = $props();

 let highlights = $derived(computeHighlights(participants, graphJson));
 let personalHighlights = $derived(
  myParticipantId
   ? computePersonalHighlights(myParticipantId, participants, graphJson)
   : [],
 );

 let showTabs = $derived(!!myParticipantId);
 let activeTab: 'race' | 'personal' = $state('race');
 let displayedHighlights: Highlight[] = $derived(
  activeTab === 'personal' ? personalHighlights : highlights,
 );

 function playerColor(playerId: string): string {
  const p = participants.find((pp) => pp.id === playerId);
  return p ? PLAYER_COLORS[p.color_index % PLAYER_COLORS.length] : '#9CA3AF';
 }
</script>

{#if highlights.length > 0 || personalHighlights.length > 0}
 <div class="race-highlights">
  <h2>Highlights</h2>

  {#if showTabs}
   <div class="highlight-tabs">
    <button
     class="tab-btn"
     class:active={activeTab === 'race'}
     onclick={() => (activeTab = 'race')}
    >
     Race
    </button>
    <button
     class="tab-btn"
     class:active={activeTab === 'personal'}
     onclick={() => (activeTab = 'personal')}
    >
     Your Race
    </button>
   </div>
  {/if}

  {#if displayedHighlights.length > 0}
   <ul class="highlight-list">
    {#each displayedHighlights as highlight}
     <li class="highlight-item">
      <span class="highlight-title">{highlight.title}</span>
      <span class="highlight-desc">
       {#each highlight.segments as seg}
        {#if seg.type === 'text'}
         {seg.value}
        {:else if seg.type === 'player'}
         <span class="player-link" style="color: {playerColor(seg.playerId)}"
          >{seg.name}</span
         >
        {:else if seg.type === 'zone'}
         <button
          class="zone-link"
          onclick={() => onzoneclick?.(seg.nodeId)}
         >
          {seg.name}
         </button>
        {/if}
       {/each}
      </span>
     </li>
    {/each}
   </ul>
  {:else if activeTab === 'personal'}
   <p class="no-highlights">No personal highlights for this race.</p>
  {/if}
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

 .highlight-tabs {
  display: flex;
  gap: 0.25rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 0.25rem;
  width: fit-content;
  margin-bottom: 1rem;
 }

 .tab-btn {
  all: unset;
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  color: var(--color-text-disabled);
  padding: 0.35rem 0.9rem;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition);
 }

 .tab-btn:hover {
  color: var(--color-text-secondary);
 }

 .tab-btn.active {
  background: var(--color-border);
  color: var(--color-text);
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

 .player-link {
  font-weight: 600;
 }

 .zone-link {
  all: unset;
  color: var(--color-purple);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
  text-decoration-color: transparent;
  transition: text-decoration-color var(--transition);
 }

 .zone-link:hover {
  text-decoration-color: var(--color-purple);
 }

 .no-highlights {
  color: var(--color-text-disabled);
  font-size: var(--font-size-sm);
  margin: 0;
 }
</style>
```

- [ ] **Step 2: Pass myParticipantId in +page.svelte**

In `web/src/routes/race/[id]/+page.svelte`, change line 735 from:

```svelte
<RaceHighlights participants={raceStore.leaderboard} graphJson={liveSeed.graph_json} onzoneclick={handleHighlightZoneClick} />
```

to:

```svelte
<RaceHighlights participants={raceStore.leaderboard} graphJson={liveSeed.graph_json} myParticipantId={myWsParticipant?.id} onzoneclick={handleHighlightZoneClick} />
```

- [ ] **Step 3: Run linting and type check**

Run: `cd web && npm run check && npm run lint`
Expected: PASS (no type errors, no lint errors)

- [ ] **Step 4: Run all tests**

Run: `cd web && npx vitest run`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/RaceHighlights.svelte web/src/routes/race/[id]/+page.svelte
git commit -m "feat: add Race/Your Race tabs to highlights section"
```

---

### Task 6: Final review and cleanup

- [ ] **Step 1: Run full test suite**

Run: `cd web && npx vitest run`
Expected: All tests PASS

- [ ] **Step 2: Run type checking**

Run: `cd web && npm run check`
Expected: PASS

- [ ] **Step 3: Run linting and formatting**

Run: `cd web && npm run lint && npm run format`
Expected: PASS

- [ ] **Step 4: Launch code review agent**

Dispatch `superpowers:code-reviewer` agent to review the full implementation against the spec.
