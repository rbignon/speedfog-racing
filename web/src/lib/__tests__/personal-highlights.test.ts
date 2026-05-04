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

  it("does not detect boss_slayer when average deaths rounds to zero", () => {
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 100000, deaths: 0 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 200000, deaths: 0 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 350000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "boss", igt_ms: 150000, deaths: 0 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      boss: { layer: 1, type: "boss" },
    });
    const result = computePersonalHighlights("me", [me, p2, p3], graph);
    const h = findHighlight(result, "boss_slayer");
    expect(h).toBeUndefined();
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
      a: { layer: 0, display_name: "Zone A" },
      b: { layer: 1, display_name: "Zone B" },
      c: { layer: 2, display_name: "Zone C" },
      d: { layer: 3, display_name: "Zone D" },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "clean_streak");
    expect(h).toBeDefined();
    expect(h!.category).toBe("combat");
    const text = descriptionText(h!);
    expect(text).toContain("Zone A");
    expect(text).toContain("Zone D");
  });
});

describe("pathing detectors", () => {
  it("detects solo_explorer with one zone nobody else visited", () => {
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
    const h = findHighlight(result, "solo_explorer");
    expect(h).toBeDefined();
    expect(h!.category).toBe("pathing");
    expect(descriptionText(h!)).toBe("You were the only racer to visit secret");
  });

  it("solo_explorer joins two solo zones with 'and'", () => {
    const me = participant("me", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "solo_low", igt_ms: 50000 },
        { node_id: "solo_high", igt_ms: 150000 },
        { node_id: "end", igt_ms: 300000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "shared", igt_ms: 50000 },
        { node_id: "end", igt_ms: 300000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      solo_low: { layer: 1, tier: 1, display_name: "Low Tier" },
      solo_high: { layer: 2, tier: 5, display_name: "High Tier" },
      shared: { layer: 1 },
      end: { layer: 3 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "solo_explorer");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toBe(
      "You were the only racer to visit High Tier and Low Tier",
    );
  });

  it("solo_explorer lists multiple solo zones sorted by tier desc", () => {
    // 3 solo zones: all named, highest tier first
    const me = participant("me", {
      igt_ms: 500000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "low_tier_solo", igt_ms: 50000 },
        { node_id: "mid_tier_solo", igt_ms: 100000 },
        { node_id: "high_tier_solo", igt_ms: 200000 },
        { node_id: "end", igt_ms: 400000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "shared", igt_ms: 50000 },
        { node_id: "end", igt_ms: 300000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      low_tier_solo: { layer: 1, tier: 1, display_name: "Low Tier" },
      mid_tier_solo: { layer: 2, tier: 3, display_name: "Mid Tier" },
      high_tier_solo: { layer: 3, tier: 6, display_name: "High Tier Boss" },
      shared: { layer: 1 },
      end: { layer: 4 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "solo_explorer");
    expect(h).toBeDefined();
    const text = descriptionText(h!);
    // High-tier zone appears before low-tier zone
    expect(text.indexOf("High Tier Boss")).toBeLessThan(
      text.indexOf("Mid Tier"),
    );
    expect(text.indexOf("Mid Tier")).toBeLessThan(text.indexOf("Low Tier"));
  });

  it("solo_explorer collapses to a count when 4+ solo zones", () => {
    const me = participant("me", {
      igt_ms: 600000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "solo_1", igt_ms: 50000 },
        { node_id: "solo_2", igt_ms: 100000 },
        { node_id: "solo_3", igt_ms: 150000 },
        { node_id: "solo_4", igt_ms: 200000 },
        { node_id: "end", igt_ms: 500000 },
      ],
    });
    const other = participant("other", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "shared", igt_ms: 50000 },
        { node_id: "end", igt_ms: 300000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      solo_1: { layer: 1 },
      solo_2: { layer: 2 },
      solo_3: { layer: 3 },
      solo_4: { layer: 4 },
      shared: { layer: 1 },
      end: { layer: 5 },
    });
    const result = computePersonalHighlights("me", [me, other], graph);
    const h = findHighlight(result, "solo_explorer");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toBe(
      "You visited 4 zones no one else discovered",
    );
  });

  it("detects against_the_flow at a fork where player took a unique branch", () => {
    // p4 visits branch_b (not via fork) so it's not a solo_explorer zone,
    // but at the fork only me takes branch_b while p2/p3 take branch_a.
    // Similar finish times avoid triggering competitive highlights.
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
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const p3 = participant("p3", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "fork", igt_ms: 0 },
        { node_id: "branch_a", igt_ms: 70000 },
        { node_id: "end", igt_ms: 200000 },
      ],
    });
    const p4 = participant("p4", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "branch_b", igt_ms: 0 },
        { node_id: "end", igt_ms: 200000 },
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
    const result = computePersonalHighlights("me", [me, p2, p3, p4], graph);
    const h = findHighlight(result, "against_the_flow");
    expect(h).toBeDefined();
    expect(descriptionText(h!)).toContain("fork");
    expect(descriptionText(h!)).toContain("branch_b");
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
    expect(descriptionText(h!)).toContain("easy");
    expect(descriptionText(h!)).toContain("instead saved you");
  });
});

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
    // me leads at layer 2 (arrives first), p2 overtakes at layer 3
    const me = participant("me", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 30000 },
        { node_id: "zone_b", igt_ms: 60000 },
        { node_id: "zone_c", igt_ms: 200000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 250000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 50000 },
        { node_id: "zone_b", igt_ms: 80000 },
        { node_id: "zone_c", igt_ms: 100000 },
      ],
    });
    const graph = graphJson({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      zone_b: { layer: 2 },
      zone_c: { layer: 3 },
    });
    const result = computePersonalHighlights("me", [me, p2], graph);
    const h = findHighlight(result, "lead_lost");
    expect(h).toBeDefined();
    const text = descriptionText(h!);
    expect(text).toContain("zone_c");
    expect(text).toContain("depth 3");
  });

  it("does not detect lead_lost when lead was only at the starting layer", () => {
    // me leads at layer 1 but loses at layer 2, not meaningful
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
    expect(h).toBeUndefined();
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
    const text = descriptionText(h!);
    // Should mention the zone where the comeback happened
    expect(text).toContain("l2");
    // And keep the depth info
    expect(text).toContain("depth 1");
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
    // p2 leads at every layer, me is always rank 2. p3 is far behind.
    // Final times are within 5% of each other to satisfy the IGT gap check.
    // me never leads, so lead_lost cannot fire for me.
    // Zone times similar across all shared zones to avoid faster_than_all.
    const me = participant("me", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 32000 },
        { node_id: "l2", igt_ms: 82000 },
        { node_id: "l3", igt_ms: 132000 },
        { node_id: "l4", igt_ms: 172000 },
      ],
    });
    const p2 = participant("p2", {
      igt_ms: 205000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "l1", igt_ms: 30000 },
        { node_id: "l2", igt_ms: 80000 },
        { node_id: "l3", igt_ms: 130000 },
        { node_id: "l4", igt_ms: 170000 },
      ],
    });
    // p3 far behind so rank differences between me and p2 are clear
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
