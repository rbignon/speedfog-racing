import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";
import { parseDagGraph } from "../types";
import { computeLayout } from "../layout";
import {
  enumerateAllPaths,
  pickRacerPaths,
  bfsShortestPath,
  pathToWaypoints,
  buildRacerPath,
  computeEdgeDrawTimings,
  computeNodeAppearTimings,
  interpolatePosition,
} from "../animation";
import type { DagLayout } from "../types";

// =============================================================================
// Helpers
// =============================================================================

function loadHeroSeed(): DagLayout {
  const raw = JSON.parse(
    readFileSync(resolve(__dirname, "../../data/hero-seed.json"), "utf-8"),
  );
  const graph = parseDagGraph(raw);
  return computeLayout(graph);
}

// =============================================================================
// enumerateAllPaths
// =============================================================================

describe("enumerateAllPaths", () => {
  it("finds all paths in the hero seed graph", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);

    // The hero seed has 9 total_paths according to the JSON
    expect(paths.length).toBeGreaterThanOrEqual(5);

    // All paths should start from the start node
    for (const path of paths) {
      expect(path[0]).toBe("chapel_start_4f96");
    }

    // All paths should end at the final boss (Loretta)
    for (const path of paths) {
      expect(path[path.length - 1]).toBe("haligtree_loretta_19ab");
    }
  });

  it("each path is a valid sequence of connected nodes", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);

    const edgeSet = new Set(layout.edges.map((e) => `${e.fromId}->${e.toId}`));

    for (const path of paths) {
      for (let i = 0; i < path.length - 1; i++) {
        expect(edgeSet.has(`${path[i]}->${path[i + 1]}`)).toBe(true);
      }
    }
  });

  it("handles a simple linear graph", () => {
    const layout: DagLayout = {
      nodes: [
        {
          id: "a",
          x: 0,
          y: 0,
          type: "start",
          displayName: "A",
          zones: [],
          layer: 0,
          tier: 0,
          weight: 1,
        },
        {
          id: "b",
          x: 100,
          y: 0,
          type: "mini_dungeon",
          displayName: "B",
          zones: [],
          layer: 1,
          tier: 1,
          weight: 1,
        },
      ],
      edges: [
        {
          fromId: "a",
          toId: "b",
          segments: [{ x1: 0, y1: 0, x2: 100, y2: 0 }],
        },
      ],
      width: 200,
      height: 100,
    };

    const paths = enumerateAllPaths(layout);
    expect(paths).toHaveLength(1);
    expect(paths[0]).toEqual(["a", "b"]);
  });
});

// =============================================================================
// pickRacerPaths
// =============================================================================

describe("pickRacerPaths", () => {
  it("selects the requested number of paths", () => {
    const layout = loadHeroSeed();
    const allPaths = enumerateAllPaths(layout);
    const selected = pickRacerPaths(allPaths, 4);

    expect(selected).toHaveLength(4);
  });

  it("returns all paths when count >= total", () => {
    const paths = [
      ["a", "b"],
      ["a", "c"],
    ];
    const selected = pickRacerPaths(paths, 5);
    expect(selected).toHaveLength(2);
  });

  it("picks diverse paths (not all identical)", () => {
    const layout = loadHeroSeed();
    const allPaths = enumerateAllPaths(layout);
    const selected = pickRacerPaths(allPaths, 4);

    // At least some paths should differ
    const unique = new Set(selected.map((p) => p.join(",")));
    expect(unique.size).toBeGreaterThan(1);
  });
});

// =============================================================================
// bfsShortestPath
// =============================================================================

describe("bfsShortestPath", () => {
  it("returns single-element path when from === to", () => {
    const adj = new Map([["a", ["b"]]]);
    expect(bfsShortestPath("a", "a", adj)).toEqual(["a"]);
  });

  it("finds direct neighbor", () => {
    const adj = new Map([["a", ["b"]]]);
    expect(bfsShortestPath("a", "b", adj)).toEqual(["a", "b"]);
  });

  it("finds shortest path through intermediates", () => {
    // a → b → c → d
    const adj = new Map([
      ["a", ["b"]],
      ["b", ["c"]],
      ["c", ["d"]],
    ]);
    expect(bfsShortestPath("a", "d", adj)).toEqual(["a", "b", "c", "d"]);
  });

  it("picks shortest when multiple paths exist", () => {
    // a → b → d (length 2)
    // a → b → c → d (length 3)
    const adj = new Map([
      ["a", ["b"]],
      ["b", ["c", "d"]],
      ["c", ["d"]],
    ]);
    expect(bfsShortestPath("a", "d", adj)).toEqual(["a", "b", "d"]);
  });

  it("returns null when unreachable", () => {
    const adj = new Map([["a", ["b"]]]);
    expect(bfsShortestPath("a", "z", adj)).toBeNull();
  });

  it("returns null with empty adjacency", () => {
    expect(bfsShortestPath("a", "b", new Map())).toBeNull();
  });
});

// =============================================================================
// pathToWaypoints
// =============================================================================

describe("pathToWaypoints", () => {
  it("creates waypoints following edge segments", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const waypoints = pathToWaypoints(paths[0], layout);

    // Should have waypoints
    expect(waypoints.length).toBeGreaterThan(0);

    // First waypoint should be at start node position
    const startNode = layout.nodes.find((n) => n.id === paths[0][0])!;
    expect(waypoints[0].x).toBe(startNode.x);
    expect(waypoints[0].y).toBe(startNode.y);

    // Cumulative distance should be monotonically increasing
    for (let i = 1; i < waypoints.length; i++) {
      expect(waypoints[i].cumulativeDistance).toBeGreaterThanOrEqual(
        waypoints[i - 1].cumulativeDistance,
      );
    }
  });

  it("ends at the last node position", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const waypoints = pathToWaypoints(paths[0], layout);
    const lastNode = layout.nodes.find(
      (n) => n.id === paths[0][paths[0].length - 1],
    )!;
    const lastWp = waypoints[waypoints.length - 1];

    expect(lastWp.x).toBe(lastNode.x);
    expect(lastWp.y).toBe(lastNode.y);
  });

  it("fills gap through intermediate nodes when skipping", () => {
    // Graph: a -> b -> c -> d (linear chain)
    const layout: DagLayout = {
      nodes: [
        {
          id: "a",
          x: 0,
          y: 0,
          type: "start",
          displayName: "A",
          zones: [],
          layer: 0,
          tier: 0,
          weight: 1,
        },
        {
          id: "b",
          x: 100,
          y: 0,
          type: "mini_dungeon",
          displayName: "B",
          zones: [],
          layer: 1,
          tier: 1,
          weight: 1,
        },
        {
          id: "c",
          x: 200,
          y: 0,
          type: "mini_dungeon",
          displayName: "C",
          zones: [],
          layer: 2,
          tier: 2,
          weight: 1,
        },
        {
          id: "d",
          x: 300,
          y: 0,
          type: "final_boss",
          displayName: "D",
          zones: [],
          layer: 3,
          tier: 3,
          weight: 1,
        },
      ],
      edges: [
        {
          fromId: "a",
          toId: "b",
          segments: [{ x1: 0, y1: 0, x2: 100, y2: 0 }],
        },
        {
          fromId: "b",
          toId: "c",
          segments: [{ x1: 100, y1: 0, x2: 200, y2: 0 }],
        },
        {
          fromId: "c",
          toId: "d",
          segments: [{ x1: 200, y1: 0, x2: 300, y2: 0 }],
        },
      ],
      width: 400,
      height: 100,
    };

    // Player visited a and d, skipping b and c
    const waypoints = pathToWaypoints(["a", "d"], layout);

    // Should pass through all intermediate nodes
    expect(waypoints).toHaveLength(4); // a, b, c, d
    expect(waypoints[0]).toMatchObject({ x: 0, y: 0 });
    expect(waypoints[1]).toMatchObject({ x: 100, y: 0 });
    expect(waypoints[2]).toMatchObject({ x: 200, y: 0 });
    expect(waypoints[3]).toMatchObject({ x: 300, y: 0 });
  });

  it("fills gap on the hero seed graph", () => {
    const layout = loadHeroSeed();

    // altus_sagescave -> stormveil_margit requires going through graveyard_cave
    // (altus_sagescave -> graveyard_cave -> stormveil_margit)
    const waypoints = pathToWaypoints(
      ["altus_sagescave_1646", "stormveil_margit_9a63"],
      layout,
    );

    // Should have more than 2 waypoints (start + intermediate edges + end)
    expect(waypoints.length).toBeGreaterThan(2);

    // Should start at altus_sagescave
    const startNode = layout.nodes.find(
      (n) => n.id === "altus_sagescave_1646",
    )!;
    expect(waypoints[0].x).toBe(startNode.x);
    expect(waypoints[0].y).toBe(startNode.y);

    // Should end at stormveil_margit
    const endNode = layout.nodes.find((n) => n.id === "stormveil_margit_9a63")!;
    const lastWp = waypoints[waypoints.length - 1];
    expect(lastWp.x).toBe(endNode.x);
    expect(lastWp.y).toBe(endNode.y);
  });
});

// =============================================================================
// buildRacerPath
// =============================================================================

describe("buildRacerPath", () => {
  it("builds a valid racer path with total distance", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const racerPath = buildRacerPath(paths[0], layout);

    expect(racerPath.nodeIds).toEqual(paths[0]);
    expect(racerPath.waypoints.length).toBeGreaterThan(0);
    expect(racerPath.totalDistance).toBeGreaterThan(0);
  });
});

// =============================================================================
// computeEdgeDrawTimings
// =============================================================================

describe("computeEdgeDrawTimings", () => {
  it("produces timings for all edges", () => {
    const layout = loadHeroSeed();
    const timings = computeEdgeDrawTimings(layout);

    expect(timings).toHaveLength(layout.edges.length);
  });

  it("timings are within [0, 1] range", () => {
    const layout = loadHeroSeed();
    const timings = computeEdgeDrawTimings(layout);

    for (const t of timings) {
      expect(t.startFraction).toBeGreaterThanOrEqual(0);
      expect(t.endFraction).toBeLessThanOrEqual(1.001); // small float tolerance
      expect(t.endFraction).toBeGreaterThan(t.startFraction);
    }
  });

  it("edges from earlier layers start before later layers", () => {
    const layout = loadHeroSeed();
    const timings = computeEdgeDrawTimings(layout);

    const nodeMap = new Map(layout.nodes.map((n) => [n.id, n]));

    // Group timings by source layer
    const byLayer = new Map<number, number[]>();
    for (const t of timings) {
      const layer = nodeMap.get(t.fromId)?.layer ?? 0;
      const list = byLayer.get(layer);
      if (list) list.push(t.startFraction);
      else byLayer.set(layer, [t.startFraction]);
    }

    const layers = Array.from(byLayer.keys()).sort((a, b) => a - b);
    for (let i = 1; i < layers.length; i++) {
      const prevStarts = byLayer.get(layers[i - 1])!;
      const currStarts = byLayer.get(layers[i])!;
      const maxPrev = Math.max(...prevStarts);
      const minCurr = Math.min(...currStarts);
      expect(minCurr).toBeGreaterThanOrEqual(maxPrev - 0.001);
    }
  });
});

// =============================================================================
// computeNodeAppearTimings
// =============================================================================

describe("computeNodeAppearTimings", () => {
  it("start nodes appear at fraction 0", () => {
    const layout = loadHeroSeed();
    const edgeTimings = computeEdgeDrawTimings(layout);
    const nodeTimings = computeNodeAppearTimings(layout, edgeTimings);

    const startTiming = nodeTimings.find(
      (t) => t.nodeId === "chapel_start_4f96",
    );
    expect(startTiming).toBeDefined();
    expect(startTiming!.fraction).toBe(0);
  });

  it("all nodes have timings", () => {
    const layout = loadHeroSeed();
    const edgeTimings = computeEdgeDrawTimings(layout);
    const nodeTimings = computeNodeAppearTimings(layout, edgeTimings);

    expect(nodeTimings).toHaveLength(layout.nodes.length);
  });

  it("fractions are in [0, 1] range", () => {
    const layout = loadHeroSeed();
    const edgeTimings = computeEdgeDrawTimings(layout);
    const nodeTimings = computeNodeAppearTimings(layout, edgeTimings);

    for (const t of nodeTimings) {
      expect(t.fraction).toBeGreaterThanOrEqual(0);
      expect(t.fraction).toBeLessThanOrEqual(1.001);
    }
  });
});

// =============================================================================
// interpolatePosition
// =============================================================================

describe("interpolatePosition", () => {
  it("returns start position at progress 0", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const racerPath = buildRacerPath(paths[0], layout);

    const pos = interpolatePosition(racerPath, 0);
    expect(pos.x).toBe(racerPath.waypoints[0].x);
    expect(pos.y).toBe(racerPath.waypoints[0].y);
  });

  it("returns end position at progress 1", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const racerPath = buildRacerPath(paths[0], layout);

    const pos = interpolatePosition(racerPath, 1);
    const lastWp = racerPath.waypoints[racerPath.waypoints.length - 1];
    expect(pos.x).toBeCloseTo(lastWp.x);
    expect(pos.y).toBeCloseTo(lastWp.y);
  });

  it("returns intermediate position at progress 0.5", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const racerPath = buildRacerPath(paths[0], layout);

    const pos = interpolatePosition(racerPath, 0.5);
    const first = racerPath.waypoints[0];
    const last = racerPath.waypoints[racerPath.waypoints.length - 1];

    // Position should be somewhere between start and end
    expect(pos.x).toBeGreaterThanOrEqual(Math.min(first.x, last.x));
    expect(pos.x).toBeLessThanOrEqual(Math.max(first.x, last.x));
  });

  it("clamps progress to [0, 1]", () => {
    const layout = loadHeroSeed();
    const paths = enumerateAllPaths(layout);
    const racerPath = buildRacerPath(paths[0], layout);

    const below = interpolatePosition(racerPath, -0.5);
    const atZero = interpolatePosition(racerPath, 0);
    expect(below.x).toBe(atZero.x);
    expect(below.y).toBe(atZero.y);

    const above = interpolatePosition(racerPath, 1.5);
    const atOne = interpolatePosition(racerPath, 1);
    expect(above.x).toBeCloseTo(atOne.x);
    expect(above.y).toBeCloseTo(atOne.y);
  });

  it("handles empty path", () => {
    const pos = interpolatePosition(
      { nodeIds: [], waypoints: [], totalDistance: 0 },
      0.5,
    );
    expect(pos.x).toBe(0);
    expect(pos.y).toBe(0);
  });
});
