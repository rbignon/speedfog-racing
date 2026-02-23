import { describe, it, expect } from "vitest";
import {
  computeZoneTimes,
  computeHighlights,
  type ZoneTime,
  type Highlight,
} from "$lib/highlights";
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
    // Use custom graph where zone_a is high-tier so Alice's wall there dominates
    const wallGraph = graphJson({
      start: { tier: 1, layer: 0, type: "start" },
      zone_a: { tier: 3, layer: 1 },
      zone_b: { tier: 3, layer: 2 },
      zone_c: { tier: 3, layer: 3, type: "final_boss" },
    });
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 400000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 },
          { node_id: "zone_b", igt_ms: 300000 }, // 290s in zone_a!
          { node_id: "zone_c", igt_ms: 350000 }, // 50s in zone_b
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 200000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 },
          { node_id: "zone_b", igt_ms: 40000 }, // 30s in zone_a
          { node_id: "zone_c", igt_ms: 100000 }, // 60s in zone_b
        ],
      }),
    ];
    const highlights = computeHighlights(players, wallGraph);
    const wall = highlights.find((h) => h.type === "zone_wall");
    expect(wall).toBeDefined();
    // Alice spent 290s in zone_a vs Bob's 30s — extreme zone wall
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
