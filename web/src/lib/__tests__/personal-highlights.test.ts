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
