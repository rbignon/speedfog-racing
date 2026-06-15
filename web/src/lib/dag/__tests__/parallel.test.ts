import { describe, it, expect } from "vitest";
import {
  buildDirectedAdjacency,
  buildPlayerWaypoints,
  computeSlot,
  expandNodePath,
  gameplayValidBridge,
} from "../parallel";
import type { DirectedAdjacency } from "../parallel";
import type { PositionedNode, RoutedEdge } from "../types";

// =============================================================================
// Helpers
// =============================================================================

function makeNode(id: string, x: number, y: number, layer = 0): PositionedNode {
  return {
    id,
    x,
    y,
    type: "mini_dungeon",
    displayName: id,
    zones: [],
    layer,
    tier: 0,
    weight: 1,
  };
}

function makeEdge(
  fromId: string,
  toId: string,
  segments: { x1: number; y1: number; x2: number; y2: number }[],
): RoutedEdge {
  return { fromId, toId, segments };
}

function buildMaps(
  nodes: PositionedNode[],
  edges: RoutedEdge[],
): {
  nodeMap: Map<string, PositionedNode>;
  edgeMap: Map<string, RoutedEdge>;
  adjacency: DirectedAdjacency;
} {
  const nodeMap = new Map<string, PositionedNode>();
  for (const n of nodes) nodeMap.set(n.id, n);

  const edgeMap = new Map<string, RoutedEdge>();
  for (const e of edges) edgeMap.set(`${e.fromId}->${e.toId}`, e);

  const adjacency = buildDirectedAdjacency(edges);

  return { nodeMap, edgeMap, adjacency };
}

/** All node ids from every edge - convenience for "assume everything visited". */
function allVisited(edges: RoutedEdge[]): Set<string> {
  const s = new Set<string>();
  for (const e of edges) {
    s.add(e.fromId);
    s.add(e.toId);
  }
  return s;
}

// =============================================================================
// computeSlot
// =============================================================================

describe("computeSlot", () => {
  it("single player gets slot 0", () => {
    expect(computeSlot(0, 1)).toBe(0);
  });

  it("two players get -0.5 and +0.5", () => {
    expect(computeSlot(0, 2)).toBe(-0.5);
    expect(computeSlot(1, 2)).toBe(0.5);
  });

  it("three players get -1, 0, +1", () => {
    expect(computeSlot(0, 3)).toBe(-1);
    expect(computeSlot(1, 3)).toBe(0);
    expect(computeSlot(2, 3)).toBe(1);
  });

  it("four players get -1.5, -0.5, +0.5, +1.5", () => {
    expect(computeSlot(0, 4)).toBe(-1.5);
    expect(computeSlot(1, 4)).toBe(-0.5);
    expect(computeSlot(2, 4)).toBe(0.5);
    expect(computeSlot(3, 4)).toBe(1.5);
  });
});

// =============================================================================
// expandNodePath
// =============================================================================

describe("expandNodePath", () => {
  it("returns path unchanged when all edges are direct", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 100, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }])];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    expect(
      expandNodePath(["a", "b"], edgeMap, adjacency, allVisited(edges)),
    ).toEqual(["a", "b"]);
  });

  it("fills gap through intermediate nodes (forward chain)", () => {
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    // a → c expands to a → b → c via the forward chain. Intermediate `b` can
    // be non-visited (inferred fog gate).
    const visited = new Set(["a", "c"]);
    expect(expandNodePath(["a", "c"], edgeMap, adjacency, visited)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("returns empty for empty input", () => {
    const { edgeMap, adjacency } = buildMaps([], []);
    expect(expandNodePath([], edgeMap, adjacency, new Set())).toEqual([]);
  });

  it("handles single node", () => {
    const nodes = [makeNode("a", 0, 0)];
    const { edgeMap, adjacency } = buildMaps(nodes, []);
    expect(expandNodePath(["a"], edgeMap, adjacency, new Set(["a"]))).toEqual([
      "a",
    ]);
  });

  it("keeps target node when unreachable", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("z", 100, 0)];
    const { edgeMap, adjacency } = buildMaps(nodes, []);

    // No edges: a -> z is unreachable, but we keep z
    expect(
      expandNodePath(["a", "z"], edgeMap, adjacency, new Set(["a", "z"])),
    ).toEqual(["a", "z"]);
  });

  it("recognizes reverse (backtrack) edge as direct connection", () => {
    // Edge goes a→b in graph, but player backtracks b→a
    const nodes = [makeNode("a", 0, 0), makeNode("b", 100, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }])];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    expect(
      expandNodePath(["b", "a"], edgeMap, adjacency, new Set(["a", "b"])),
    ).toEqual(["b", "a"]);
  });

  it("skips BFS for backtrack entry type (fast-travel)", () => {
    // Graph: a→b→c→d→e. Player at e fast-travels to a (backtrack),
    // then fog-traverses to b.
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
      makeNode("d", 300, 0),
      makeNode("e", 400, 0),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
      makeEdge("c", "d", [{ x1: 200, y1: 0, x2: 300, y2: 0 }]),
      makeEdge("d", "e", [{ x1: 300, y1: 0, x2: 400, y2: 0 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);
    const visited = allVisited(edges);

    // Without entry types: e→a fills via reverse chain through visited nodes,
    // then a→b via direct forward edge.
    const defaultTypes = expandNodePath(
      ["e", "a", "b"],
      edgeMap,
      adjacency,
      visited,
    );
    expect(defaultTypes).toEqual(["e", "d", "c", "b", "a", "b"]);

    // With entry types: "a" is a backtrack (fast-travel, teleport gap),
    // "b" is fog traversal with direct edge.
    const withTypes = expandNodePath(
      ["e", "a", "b"],
      edgeMap,
      adjacency,
      visited,
      [undefined, "backtrack", "fog"],
    );
    expect(withTypes).toEqual(["e", "a", "b"]);
  });

  it("treats undefined entry types as fog", () => {
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    // No entryTypes param: gap filled by forward chain through unvisited b.
    const result = expandNodePath(
      ["a", "c"],
      edgeMap,
      adjacency,
      new Set(["a", "c"]),
    );
    expect(result).toEqual(["a", "b", "c"]);
  });

  it("fills a full backtracking path when all nodes visited", () => {
    // Graph: a→b→c, a→d. Player goes a→b→c then backtracks to a→d
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
      makeNode("d", 100, 50),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
      makeEdge("a", "d", [{ x1: 0, y1: 0, x2: 100, y2: 50 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    // Zone history: a, b, c, d. c→d bridges via reverse through visited
    // nodes (c→b→a→d).
    const result = expandNodePath(
      ["a", "b", "c", "d"],
      edgeMap,
      adjacency,
      allVisited(edges),
    );
    expect(result).toEqual(["a", "b", "c", "b", "a", "d"]);
  });

  it("gameplay-valid bridge mixes reverse-through-visited + forward", () => {
    // Layered DAG:
    //   a (L0) → b (L1) → c (L2)
    //   a (L0) → d (L1) → e (L2)
    // Zone history: a, b, e. Player went a→b, then somehow reached e.
    // Reverse b→a allowed (both visited); forward a→d→e allowed (d/e can
    // be non-visited since they're discovered via forward edges).
    const nodes = [
      makeNode("a", 0, 0, 0),
      makeNode("b", 100, 0, 1),
      makeNode("c", 200, 0, 2),
      makeNode("d", 100, 50, 1),
      makeNode("e", 200, 50, 2),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
      makeEdge("a", "d", [{ x1: 0, y1: 0, x2: 100, y2: 50 }]),
      makeEdge("d", "e", [{ x1: 100, y1: 50, x2: 200, y2: 50 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    // Only a, b, e visited. d is not visited but can be inferred via
    // forward edges (missed fog gate).
    const visited = new Set(["a", "b", "e"]);
    const result = expandNodePath(
      ["a", "b", "e"],
      edgeMap,
      adjacency,
      visited,
      ["spawn", "fog", "fog"],
    );
    expect(result).toEqual(["a", "b", "a", "d", "e"]);
  });

  it("does not walk reverse through non-visited nodes", () => {
    // Layered DAG: a (L0) → b (L1) → c (L2), a (L0) → d (L1) → c (L2).
    // Zone history: a, c. b and d both unvisited.
    // There is no valid forward-only chain a→c (a→b→c or a→d→c would
    // require traversing through a layer-1 node, which is fine — they
    // are forward transitions). Both paths are equally short; BFS picks
    // whichever it finds first, but both are gameplay-valid because the
    // intermediate is reached via forward edges.
    const nodes = [
      makeNode("a", 0, 0, 0),
      makeNode("b", 100, 0, 1),
      makeNode("c", 200, 0, 2),
      makeNode("d", 100, 50, 1),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
      makeEdge("a", "d", [{ x1: 0, y1: 0, x2: 100, y2: 50 }]),
      makeEdge("d", "c", [{ x1: 100, y1: 50, x2: 200, y2: 0 }]),
    ];
    const { edgeMap, adjacency } = buildMaps(nodes, edges);

    const visited = new Set(["a", "c"]);
    const result = expandNodePath(["a", "c"], edgeMap, adjacency, visited, [
      "spawn",
      "fog",
    ]);
    // Either a→b→c or a→d→c is gameplay-valid. BFS deterministic on
    // edge insertion order ⇒ a→b→c (b enqueued first).
    expect(result).toEqual(["a", "b", "c"]);
  });
});

// =============================================================================
// gameplayValidBridge
// =============================================================================

describe("gameplayValidBridge", () => {
  function adjFromEdges(
    edges: { fromId: string; toId: string }[],
  ): DirectedAdjacency {
    return buildDirectedAdjacency(edges);
  }

  it("returns [from] when from === to", () => {
    const adj = adjFromEdges([]);
    expect(gameplayValidBridge("a", "a", adj, new Set(["a"]))).toEqual(["a"]);
  });

  it("walks a forward edge to a non-visited node", () => {
    const adj = adjFromEdges([{ fromId: "a", toId: "b" }]);
    expect(gameplayValidBridge("a", "b", adj, new Set(["a"]))).toEqual([
      "a",
      "b",
    ]);
  });

  it("walks a forward chain through non-visited intermediates", () => {
    const adj = adjFromEdges([
      { fromId: "a", toId: "b" },
      { fromId: "b", toId: "c" },
    ]);
    // b is not visited, but allowed because we reach it by a forward edge.
    expect(gameplayValidBridge("a", "c", adj, new Set(["a", "c"]))).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("walks a reverse edge between two visited nodes", () => {
    const adj = adjFromEdges([{ fromId: "a", toId: "b" }]);
    expect(gameplayValidBridge("b", "a", adj, new Set(["a", "b"]))).toEqual([
      "b",
      "a",
    ]);
  });

  it("blocks reverse edge when neighbor is not visited", () => {
    // a → b, a → c. from=c (visited), to=b (NOT visited).
    // Reverse c→a would require a visited (ok), then a→b forward allowed.
    // So path c→a→b (length 2) should exist.
    const adj = adjFromEdges([
      { fromId: "a", toId: "b" },
      { fromId: "a", toId: "c" },
    ]);
    expect(gameplayValidBridge("c", "b", adj, new Set(["a", "c"]))).toEqual([
      "c",
      "a",
      "b",
    ]);
  });

  it("blocks reverse edge when *from* is not visited (hypothetical)", () => {
    // a → b. from=b not visited. Can't reverse b→a.
    // But forward from b to ... nothing.
    const adj = adjFromEdges([{ fromId: "a", toId: "b" }]);
    expect(gameplayValidBridge("b", "a", adj, new Set(["a"]))).toBeNull();
  });

  it("mixes reverse-through-visited + forward chain (Roger's scenario)", () => {
    // Mimics Roger's scenario:
    //   - Visited: chapel, cemetery, royal, death_knight, fissure.
    //   - Dragon Temple Lift (lift) is NOT visited.
    //   - The only forward path reaching fissure goes through lift.
    //   - death_knight has NO forward-only path to fissure (its only
    //     downstream chain reaches godskinduo via belurat).
    //
    // Expected bridge: death_knight → (reverse) cemetery → (forward)
    // royal → (forward) lift → (forward) fissure. lift is non-visited
    // but walked via forward edges (inferred missed fog gate).
    const adj = adjFromEdges([
      // L0 → L1
      { fromId: "chapel", toId: "cemetery" },
      { fromId: "chapel", toId: "redmane" },
      // L1 → L2
      { fromId: "cemetery", toId: "royal" },
      { fromId: "cemetery", toId: "death_knight" },
      { fromId: "redmane", toId: "leyndell" },
      // L2 → L3
      { fromId: "royal", toId: "lift" },
      { fromId: "death_knight", toId: "belurat" },
      { fromId: "leyndell", toId: "belurat" },
      // L3 → L4
      { fromId: "lift", toId: "fissure" },
      { fromId: "belurat", toId: "godskinduo" },
    ]);
    const visited = new Set([
      "chapel",
      "cemetery",
      "royal",
      "death_knight",
      "fissure",
    ]);

    const bridge = gameplayValidBridge("death_knight", "fissure", adj, visited);

    expect(bridge).toEqual([
      "death_knight",
      "cemetery",
      "royal",
      "lift",
      "fissure",
    ]);
    // leyndell (Ashen Leyndell analogue) must NOT appear: reverse edges
    // into it are blocked because it's not visited.
    expect(bridge).not.toContain("leyndell");
  });

  it("returns null when no gameplay-valid bridge exists", () => {
    // a → b (visited), c → d (isolated). from=b, to=d, nothing connects.
    const adj = adjFromEdges([
      { fromId: "a", toId: "b" },
      { fromId: "c", toId: "d" },
    ]);
    expect(
      gameplayValidBridge("b", "d", adj, new Set(["a", "b", "d"])),
    ).toBeNull();
  });
});

// =============================================================================
// buildPlayerWaypoints
// =============================================================================

describe("buildPlayerWaypoints", () => {
  // Helper: flatten segments to flat points array (for tests with no gaps)
  function flat(
    segments: { x: number; y: number }[][],
  ): { x: number; y: number }[] {
    return segments.flat();
  }

  it("returns node centers with no offset for single player", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 100, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }])];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const segments = buildPlayerWaypoints(
      ["a", "b"],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );

    expect(segments).toHaveLength(1);
    const points = flat(segments);
    expect(points).toHaveLength(2);
    expect(points[0]).toEqual({ x: 0, y: 0 });
    expect(points[1]).toEqual({ x: 100, y: 0 }); // pinch at node
  });

  it("applies perpendicular offset on shared horizontal edge", () => {
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
    ];
    // Edge a->b has a mid-segment so there's an intermediate point to offset
    const edges = [
      makeEdge("a", "b", [
        { x1: 0, y1: 0, x2: 50, y2: 0 },
        { x1: 50, y1: 0, x2: 100, y2: 0 },
      ]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const spacing = 5;

    // Player with slot +0.5 on edge a->b (2 players sharing it)
    const points = flat(
      buildPlayerWaypoints(
        ["a", "b", "c"],
        nodeMap,
        edgeMap,
        (key) => (key === "a->b" ? 0.5 : 0),
        (key) => (key === "a->b" ? 2 : 1),
        spacing,
      ),
    );

    expect(points).toHaveLength(4); // a, mid(offset), b(pinch), c

    // Start: pinch at node a
    expect(points[0]).toEqual({ x: 0, y: 0 });

    // Mid-point: horizontal edge goes right, perpendicular is up (-dy,dx)/len = (0,1) for rightward
    // Wait: direction is (50,0), perp is (0,50)/50 = (0,1)
    // offset = 0.5 * 5 = 2.5
    // So mid-point should be (50, 0 + 2.5) = (50, 2.5)
    expect(points[1].x).toBeCloseTo(50);
    expect(points[1].y).toBeCloseTo(2.5);

    // End of edge a->b: pinch at node b
    expect(points[2]).toEqual({ x: 100, y: 0 });

    // End of edge b->c: pinch at node c (single player, no offset)
    expect(points[3]).toEqual({ x: 200, y: 0 });
  });

  it("offsets perpendicular to vertical edges", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 0, 100)];
    // Multi-segment vertical edge so there's an intermediate point
    const edges = [
      makeEdge("a", "b", [
        { x1: 0, y1: 0, x2: 0, y2: 50 },
        { x1: 0, y1: 50, x2: 0, y2: 100 },
      ]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    // Player with slot +1 (3 players, index 2)
    const points = flat(
      buildPlayerWaypoints(
        ["a", "b"],
        nodeMap,
        edgeMap,
        () => 1,
        () => 3,
        5,
      ),
    );

    expect(points).toHaveLength(3); // a, mid(offset), b(pinch)

    // Vertical edge going down: direction (0,50), perp = (-50,0)/50 = (-1,0)
    // offset = 1 * 5 = 5
    // mid-point: (0 + 5*(-1), 50 + 5*0) = (-5, 50)
    expect(points[1].x).toBeCloseTo(-5);
    expect(points[1].y).toBeCloseTo(50);

    // End: pinch at node b
    expect(points[2]).toEqual({ x: 0, y: 100 });
  });

  it("returns empty for empty node list", () => {
    const { nodeMap, edgeMap } = buildMaps([], []);
    const segments = buildPlayerWaypoints(
      [],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );
    expect(segments).toEqual([]);
  });

  it("returns empty when first node not in nodeMap", () => {
    const { nodeMap, edgeMap } = buildMaps([], []);
    const segments = buildPlayerWaypoints(
      ["missing"],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );
    expect(segments).toEqual([]);
  });

  it("skips offset on very short segments", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 0.3, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 0.3, y2: 0 }])];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    // Even with multiple players, short segment (len < 0.5) should not offset
    const points = flat(
      buildPlayerWaypoints(
        ["a", "b"],
        nodeMap,
        edgeMap,
        () => 1,
        () => 3,
        5,
      ),
    );

    expect(points).toHaveLength(2);
    // Pinch at node b replaces the endpoint anyway
    expect(points[1]).toEqual({ x: 0.3, y: 0 });
  });

  it("handles diagonal edge offset correctly", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 30, 40)];
    // Two segments so we get an intermediate offset point
    const edges = [
      makeEdge("a", "b", [
        { x1: 0, y1: 0, x2: 15, y2: 20 },
        { x1: 15, y1: 20, x2: 30, y2: 40 },
      ]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const points = flat(
      buildPlayerWaypoints(
        ["a", "b"],
        nodeMap,
        edgeMap,
        () => 1,
        () => 2,
        10,
      ),
    );

    // Direction (15,20), len=25, perp = (-20,15)/25 = (-0.8, 0.6)
    // offset = 1 * 10 = 10
    // mid-point: (15 + 10*(-0.8), 20 + 10*(0.6)) = (7, 26)
    expect(points[1].x).toBeCloseTo(7);
    expect(points[1].y).toBeCloseTo(26);

    // End: pinch at node b
    expect(points[2]).toEqual({ x: 30, y: 40 });
  });

  it("traverses reverse edge when backtracking", () => {
    // Edge is a→b in graph, but player goes b→a (backtrack)
    const nodes = [makeNode("a", 0, 0), makeNode("b", 100, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }])];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const points = flat(
      buildPlayerWaypoints(
        ["b", "a"],
        nodeMap,
        edgeMap,
        () => 0,
        () => 1,
        5,
      ),
    );

    expect(points).toHaveLength(2);
    expect(points[0]).toEqual({ x: 100, y: 0 }); // start at b
    expect(points[1]).toEqual({ x: 0, y: 0 }); // pinch at a
  });

  it("traverses reverse edge segments in correct order", () => {
    // Edge a→b has 3 segments (metro style). Reverse traversal should follow them backward.
    const nodes = [makeNode("a", 0, 0), makeNode("b", 200, 50)];
    const edges = [
      makeEdge("a", "b", [
        { x1: 0, y1: 0, x2: 50, y2: 0 },
        { x1: 50, y1: 0, x2: 150, y2: 50 },
        { x1: 150, y1: 50, x2: 200, y2: 50 },
      ]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const points = flat(
      buildPlayerWaypoints(
        ["b", "a"],
        nodeMap,
        edgeMap,
        () => 0,
        () => 1,
        5,
      ),
    );

    // Start at b(200,50), then reversed segments:
    // seg3 reversed: x1=150,y1=50 → waypoint (150,50)
    // seg2 reversed: x1=50,y1=0 → waypoint (50,0)
    // seg1 reversed: x1=0,y1=0 → pinch at a(0,0)
    expect(points).toHaveLength(4);
    expect(points[0]).toEqual({ x: 200, y: 50 }); // start at b
    expect(points[1]).toEqual({ x: 150, y: 50 }); // reversed seg3
    expect(points[2]).toEqual({ x: 50, y: 0 }); // reversed seg2
    expect(points[3]).toEqual({ x: 0, y: 0 }); // pinch at a
  });

  it("handles full backtracking path with forward and reverse edges", () => {
    // Graph: a→b→c. Player goes a→b→c then backtracks to a: expanded = [a,b,c,b,a]
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 200, 0),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("b", "c", [{ x1: 100, y1: 0, x2: 200, y2: 0 }]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const points = flat(
      buildPlayerWaypoints(
        ["a", "b", "c", "b", "a"],
        nodeMap,
        edgeMap,
        () => 0,
        () => 1,
        5,
      ),
    );

    expect(points).toHaveLength(5);
    expect(points[0]).toEqual({ x: 0, y: 0 }); // a
    expect(points[1]).toEqual({ x: 100, y: 0 }); // b (forward a→b)
    expect(points[2]).toEqual({ x: 200, y: 0 }); // c (forward b→c)
    expect(points[3]).toEqual({ x: 100, y: 0 }); // b (reverse c→b)
    expect(points[4]).toEqual({ x: 0, y: 0 }); // a (reverse b→a)
  });

  it("splits into separate segments at teleport gaps", () => {
    // Graph: a->b, c->d (no edge between b and c, teleport gap)
    const nodes = [
      makeNode("a", 0, 0),
      makeNode("b", 100, 0),
      makeNode("c", 300, 0),
      makeNode("d", 400, 0),
    ];
    const edges = [
      makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }]),
      makeEdge("c", "d", [{ x1: 300, y1: 0, x2: 400, y2: 0 }]),
    ];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const segments = buildPlayerWaypoints(
      ["a", "b", "c", "d"],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );

    // Should produce 2 segments: [a,b] and [c,d]
    expect(segments).toHaveLength(2);
    expect(segments[0]).toHaveLength(2);
    expect(segments[0][0]).toEqual({ x: 0, y: 0 }); // a
    expect(segments[0][1]).toEqual({ x: 100, y: 0 }); // b
    expect(segments[1]).toHaveLength(2);
    expect(segments[1][0]).toEqual({ x: 300, y: 0 }); // c
    expect(segments[1][1]).toEqual({ x: 400, y: 0 }); // d
  });
});
