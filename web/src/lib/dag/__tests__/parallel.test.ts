import { describe, it, expect } from "vitest";
import { expandNodePath, buildPlayerWaypoints, computeSlot } from "../parallel";
import type { PositionedNode, RoutedEdge, DagLayout } from "../types";

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
  adjacency: Map<string, string[]>;
} {
  const nodeMap = new Map<string, PositionedNode>();
  for (const n of nodes) nodeMap.set(n.id, n);

  const edgeMap = new Map<string, RoutedEdge>();
  for (const e of edges) edgeMap.set(`${e.fromId}->${e.toId}`, e);

  const adjacency = new Map<string, string[]>();
  for (const e of edges) {
    const list = adjacency.get(e.fromId);
    if (list) list.push(e.toId);
    else adjacency.set(e.fromId, [e.toId]);
  }

  return { nodeMap, edgeMap, adjacency };
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

    expect(expandNodePath(["a", "b"], edgeMap, adjacency)).toEqual(["a", "b"]);
  });

  it("fills gap through intermediate nodes", () => {
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

    // Skip b: a -> c should expand to a -> b -> c
    expect(expandNodePath(["a", "c"], edgeMap, adjacency)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("returns empty for empty input", () => {
    const { edgeMap, adjacency } = buildMaps([], []);
    expect(expandNodePath([], edgeMap, adjacency)).toEqual([]);
  });

  it("handles single node", () => {
    const nodes = [makeNode("a", 0, 0)];
    const { edgeMap, adjacency } = buildMaps(nodes, []);
    expect(expandNodePath(["a"], edgeMap, adjacency)).toEqual(["a"]);
  });

  it("keeps target node when unreachable", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("z", 100, 0)];
    const { edgeMap, adjacency } = buildMaps(nodes, []);

    // No edges: a -> z is unreachable, but we keep z
    expect(expandNodePath(["a", "z"], edgeMap, adjacency)).toEqual(["a", "z"]);
  });
});

// =============================================================================
// buildPlayerWaypoints
// =============================================================================

describe("buildPlayerWaypoints", () => {
  it("returns node centers with no offset for single player", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 100, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 100, y2: 0 }])];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    const points = buildPlayerWaypoints(
      ["a", "b"],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );

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
    const points = buildPlayerWaypoints(
      ["a", "b", "c"],
      nodeMap,
      edgeMap,
      (key) => (key === "a->b" ? 0.5 : 0),
      (key) => (key === "a->b" ? 2 : 1),
      spacing,
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
    const points = buildPlayerWaypoints(
      ["a", "b"],
      nodeMap,
      edgeMap,
      () => 1,
      () => 3,
      5,
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
    const points = buildPlayerWaypoints(
      [],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );
    expect(points).toEqual([]);
  });

  it("returns empty when first node not in nodeMap", () => {
    const { nodeMap, edgeMap } = buildMaps([], []);
    const points = buildPlayerWaypoints(
      ["missing"],
      nodeMap,
      edgeMap,
      () => 0,
      () => 1,
      5,
    );
    expect(points).toEqual([]);
  });

  it("skips offset on very short segments", () => {
    const nodes = [makeNode("a", 0, 0), makeNode("b", 0.3, 0)];
    const edges = [makeEdge("a", "b", [{ x1: 0, y1: 0, x2: 0.3, y2: 0 }])];
    const { nodeMap, edgeMap } = buildMaps(nodes, edges);

    // Even with multiple players, short segment (len < 0.5) should not offset
    const points = buildPlayerWaypoints(
      ["a", "b"],
      nodeMap,
      edgeMap,
      () => 1,
      () => 3,
      5,
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

    const points = buildPlayerWaypoints(
      ["a", "b"],
      nodeMap,
      edgeMap,
      () => 1,
      () => 2,
      10,
    );

    // Direction (15,20), len=25, perp = (-20,15)/25 = (-0.8, 0.6)
    // offset = 1 * 10 = 10
    // mid-point: (15 + 10*(-0.8), 20 + 10*(0.6)) = (7, 26)
    expect(points[1].x).toBeCloseTo(7);
    expect(points[1].y).toBeCloseTo(26);

    // End: pinch at node b
    expect(points[2]).toEqual({ x: 30, y: 40 });
  });
});
