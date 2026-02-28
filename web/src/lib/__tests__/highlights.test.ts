import { describe, it, expect } from "vitest";
import {
  computeZoneTimes,
  computeHighlights,
  descriptionText,
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

// Node info map factory (for computeZoneTimes)
function nodeInfoMap(
  nodes: Record<string, { layer: number }>,
): Map<
  string,
  { tier: number; layer: number; displayName: string; type: string }
> {
  const map = new Map();
  for (const [id, data] of Object.entries(nodes)) {
    map.set(id, {
      tier: 1,
      layer: data.layer,
      displayName: id,
      type: "mini_dungeon",
    });
  }
  return map;
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
    const info = nodeInfoMap({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      zone_b: { layer: 2 },
    });
    const result = computeZoneTimes(p, info);
    expect(result).toEqual([
      { nodeId: "start", timeMs: 60000, deaths: 0, outcome: "cleared" },
      { nodeId: "zone_a", timeMs: 60000, deaths: 0, outcome: "cleared" },
      { nodeId: "zone_b", timeMs: 180000, deaths: 0, outcome: "cleared" },
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
    expect(result).toEqual([
      { nodeId: "start", timeMs: 100000, deaths: 0, outcome: "cleared" },
    ]);
  });

  it("detects 'backed' outcome when next zone is on same/lower layer", () => {
    const p = participant("alice", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "zone_a", igt_ms: 0 },
        { node_id: "zone_b", igt_ms: 50000 },
        { node_id: "zone_c", igt_ms: 100000 },
      ],
    });
    const info = nodeInfoMap({
      zone_a: { layer: 0 },
      zone_b: { layer: 1 },
      zone_c: { layer: 1 },
    });
    const result = computeZoneTimes(p, info);
    expect(result[0].outcome).toBe("cleared"); // layer 0 → 1
    expect(result[1].outcome).toBe("backed"); // layer 1 → 1 (same)
  });

  it("detects 'playing' outcome for last zone when status is playing", () => {
    const p = participant("alice", {
      status: "playing",
      igt_ms: 200000,
      zone_history: [
        { node_id: "zone_a", igt_ms: 0 },
        { node_id: "zone_b", igt_ms: 50000 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result[1].outcome).toBe("playing");
  });

  it("detects 'abandoned' outcome for last zone when status is abandoned", () => {
    const p = participant("alice", {
      status: "abandoned",
      igt_ms: 200000,
      zone_history: [
        { node_id: "zone_a", igt_ms: 0 },
        { node_id: "zone_b", igt_ms: 50000 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result[1].outcome).toBe("abandoned");
  });
});

describe("computeZoneTimes with backtracking", () => {
  it("aggregates time and deaths for backtracked zones", () => {
    const p = participant("alice", {
      igt_ms: 500000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 60000, deaths: 3 },
        { node_id: "zone_b", igt_ms: 120000 },
        { node_id: "zone_a", igt_ms: 200000, deaths: 2 }, // backtrack
        { node_id: "zone_b", igt_ms: 250000 },
        { node_id: "zone_c", igt_ms: 350000 },
      ],
    });
    const info = nodeInfoMap({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      zone_b: { layer: 2 },
      zone_c: { layer: 3 },
    });
    const result = computeZoneTimes(p, info);
    // Should have 4 unique nodes, not 6 raw entries
    expect(result).toHaveLength(4);
    const zoneA = result.find((r) => r.nodeId === "zone_a");
    expect(zoneA?.timeMs).toBe(110000); // 60000 + 50000
    expect(zoneA?.deaths).toBe(5); // 3 + 2
    expect(zoneA?.outcome).toBe("cleared"); // last visit → zone_b (higher layer)
  });

  it("preserves first-visit order for aggregated zones", () => {
    const p = participant("alice", {
      igt_ms: 400000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 60000 },
        { node_id: "zone_b", igt_ms: 120000 },
        { node_id: "zone_a", igt_ms: 200000 }, // backtrack
        { node_id: "zone_c", igt_ms: 300000 },
      ],
    });
    const info = nodeInfoMap({
      start: { layer: 0 },
      zone_a: { layer: 1 },
      zone_b: { layer: 2 },
      zone_c: { layer: 3 },
    });
    const result = computeZoneTimes(p, info);
    expect(result.map((r) => r.nodeId)).toEqual([
      "start",
      "zone_a",
      "zone_b",
      "zone_c",
    ]);
  });
});

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

  it("Speed Demon: ignores backed zones", () => {
    // Alice "blitzes" zone_a but actually backed out — should not count
    const graph2 = graphJson({
      start: { tier: 1, layer: 0, type: "start" },
      zone_a: { tier: 2, layer: 1 },
      zone_b: { tier: 2, layer: 1 }, // same layer as zone_a = backed
      zone_c: { tier: 3, layer: 3, type: "final_boss" },
    });
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 }, // 10s in start
          { node_id: "zone_b", igt_ms: 15000 }, // 5s in zone_a (backed!)
          { node_id: "zone_c", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 15000 },
          { node_id: "zone_c", igt_ms: 350000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph2);
    const speedDemon = highlights.find((h) => h.type === "speed_demon");
    // Alice's zone_a time should not count since she backed out
    if (speedDemon) {
      // If a speed demon is found, it shouldn't be for zone_a with alice backing
      expect(descriptionText(speedDemon)).not.toContain("zone_a");
    }
  });

  it("Zone Wall: detects player who spent disproportionately long in a zone", () => {
    // Both players reach each layer at similar times to minimize fast_starter score,
    // but Alice spends much longer in zone_b specifically.
    const wallGraph = graphJson({
      start: { tier: 1, layer: 0, type: "start" },
      zone_a: { tier: 2, layer: 1 },
      zone_b: { tier: 3, layer: 2 },
      zone_c: { tier: 3, layer: 3, type: "final_boss" },
    });
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 400000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 10000 }, // 10s in start
          { node_id: "zone_b", igt_ms: 30000 }, // 20s in zone_a
          { node_id: "zone_c", igt_ms: 350000 }, // 320s in zone_b!
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 200000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 12000 }, // 12s in start (similar to alice)
          { node_id: "zone_b", igt_ms: 35000 }, // 23s in zone_a (similar to alice)
          { node_id: "zone_c", igt_ms: 100000 }, // 65s in zone_b
        ],
      }),
    ];
    const highlights = computeHighlights(players, wallGraph);
    const wall = highlights.find((h) => h.type === "zone_wall");
    expect(wall).toBeDefined();
    // Alice spent 320s in zone_b vs Bob's 65s — extreme zone wall
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
    expect(descriptionText(graveyard!)).toContain("zone_b");
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
    // Use similar timings across zones to minimize competing highlights
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
        igt_ms: 250000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 250000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 200000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 200000 },
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

describe("outcome-based highlights", () => {
  const graph = graphJson({
    start: { tier: 1, layer: 0, type: "start" },
    zone_a: { tier: 2, layer: 1 },
    zone_b: { tier: 2, layer: 1 },
    zone_c: { tier: 3, layer: 2 },
    final: { tier: 3, layer: 3, type: "final_boss" },
  });

  it("Hard Pass: detects zone with multiple backs", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 30000 },
          { node_id: "zone_b", igt_ms: 40000 }, // backed from zone_a (same layer)
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 40000 },
          { node_id: "zone_b", igt_ms: 50000 }, // also backed from zone_a
          { node_id: "zone_c", igt_ms: 120000 },
          { node_id: "final", igt_ms: 350000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 280000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 35000 },
          { node_id: "zone_c", igt_ms: 100000 }, // cleared zone_a normally
          { node_id: "final", igt_ms: 280000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const hardPass = highlights.find((h) => h.type === "hard_pass");
    expect(hardPass).toBeDefined();
    expect(descriptionText(hardPass!)).toContain("zone_a");
    expect(descriptionText(hardPass!)).toContain("2 players backed out");
  });

  it("Early Exit: detects earliest rage-quit", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 350000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 120000 },
          { node_id: "final", igt_ms: 350000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 50000,
        status: "abandoned",
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_a", igt_ms: 50000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const earlyExit = highlights.find((h) => h.type === "early_exit");
    expect(earlyExit).toBeDefined();
    expect(earlyExit!.playerIds).toContain("charlie");
  });

  it("Rage Inducer: detects zone that caused multiple abandonments", () => {
    const players = [
      participant("alice", {
        color_index: 0,
        igt_ms: 300000,
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 100000 },
          { node_id: "final", igt_ms: 300000 },
        ],
      }),
      participant("bob", {
        color_index: 1,
        igt_ms: 150000,
        status: "abandoned",
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 150000 },
        ],
      }),
      participant("charlie", {
        color_index: 2,
        igt_ms: 180000,
        status: "abandoned",
        zone_history: [
          { node_id: "start", igt_ms: 0 },
          { node_id: "zone_c", igt_ms: 180000 },
        ],
      }),
    ];
    const highlights = computeHighlights(players, graph);
    const rageInducer = highlights.find((h) => h.type === "rage_inducer");
    expect(rageInducer).toBeDefined();
    expect(descriptionText(rageInducer!)).toContain("zone_c");
  });
});
