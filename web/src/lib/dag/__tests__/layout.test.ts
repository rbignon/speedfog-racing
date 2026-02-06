import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";
import { computeLayout } from "../layout";
import { parseDagGraph } from "../types";
import type { DagGraph, DagNode } from "../types";
import {
  PADDING,
  BASE_GAP,
  WEIGHT_SCALE,
  NODE_AREA,
  LAYER_SPACING_Y,
} from "../constants";

// =============================================================================
// Helpers
// =============================================================================

function makeNode(
  id: string,
  layer: number,
  weight: number = 1,
  type: DagNode["type"] = "mini_dungeon",
): DagNode {
  return {
    id,
    type,
    displayName: id,
    zones: [id],
    layer,
    tier: layer,
    weight,
  };
}

// =============================================================================
// parseDagGraph
// =============================================================================

describe("parseDagGraph", () => {
  it("parses the sample_graph.json fixture correctly", () => {
    const raw = JSON.parse(
      readFileSync(
        resolve(
          __dirname,
          "../../../../../server/tests/fixtures/sample_graph.json",
        ),
        "utf-8",
      ),
    );
    const graph = parseDagGraph(raw);

    expect(graph.totalLayers).toBe(13);
    expect(graph.nodes).toHaveLength(16);
    expect(graph.edges).toHaveLength(17);

    // Check start node
    const start = graph.nodes.find((n) => n.id === "chapel_start_4f96");
    expect(start).toBeDefined();
    expect(start!.type).toBe("start");
    expect(start!.layer).toBe(0);
    expect(start!.weight).toBe(1);

    // Check final boss
    const final = graph.nodes.find((n) => n.id === "leyndell_erdtree_ca15");
    expect(final).toBeDefined();
    expect(final!.type).toBe("final_boss");
    expect(final!.layer).toBe(12);
  });

  it("filters edges to known nodes only", () => {
    const raw = {
      total_layers: 2,
      nodes: {
        a: {
          type: "start",
          display_name: "A",
          zones: ["a"],
          layer: 0,
          tier: 0,
          weight: 1,
        },
      },
      edges: [
        { from: "a", to: "b" }, // b doesn't exist
      ],
    };
    const graph = parseDagGraph(raw);
    expect(graph.nodes).toHaveLength(1);
    expect(graph.edges).toHaveLength(0);
  });

  it("skips nodes with unknown types", () => {
    const raw = {
      total_layers: 1,
      nodes: {
        a: {
          type: "unknown_type",
          display_name: "A",
          zones: ["a"],
          layer: 0,
          tier: 0,
          weight: 1,
        },
        b: {
          type: "start",
          display_name: "B",
          zones: ["b"],
          layer: 0,
          tier: 0,
          weight: 1,
        },
      },
      edges: [],
    };
    const graph = parseDagGraph(raw);
    expect(graph.nodes).toHaveLength(1);
    expect(graph.nodes[0].id).toBe("b");
  });
});

// =============================================================================
// Linear path
// =============================================================================

describe("computeLayout — linear path", () => {
  it("positions 3 nodes with X proportional to weight, Y centered", () => {
    const graph: DagGraph = {
      totalLayers: 3,
      nodes: [
        makeNode("a", 0, 1, "start"),
        makeNode("b", 1, 10, "legacy_dungeon"),
        makeNode("c", 2, 2, "boss_arena"),
      ],
      edges: [
        { from: "a", to: "b" },
        { from: "b", to: "c" },
      ],
    };

    const layout = computeLayout(graph);

    expect(layout.nodes).toHaveLength(3);

    const a = layout.nodes.find((n) => n.id === "a")!;
    const b = layout.nodes.find((n) => n.id === "b")!;
    const c = layout.nodes.find((n) => n.id === "c")!;

    // X positions should increase
    expect(a.x).toBeLessThan(b.x);
    expect(b.x).toBeLessThan(c.x);

    // X gap after b (weight=10) should be larger than gap after a (weight=1)
    const gapAfterA = b.x - a.x;
    const gapAfterB = c.x - b.x;
    expect(gapAfterB).toBeGreaterThan(gapAfterA);

    // Verify exact X positions
    expect(a.x).toBe(PADDING);
    expect(b.x).toBe(PADDING + NODE_AREA + BASE_GAP + 1 * WEIGHT_SCALE);
    expect(c.x).toBe(b.x + NODE_AREA + BASE_GAP + 10 * WEIGHT_SCALE);

    // All nodes at same Y (single-node layers, centered)
    expect(a.y).toBe(b.y);
    expect(b.y).toBe(c.y);
  });
});

// =============================================================================
// Split/merge
// =============================================================================

describe("computeLayout — split and merge", () => {
  it("separates nodes vertically at split and converges at merge", () => {
    const graph: DagGraph = {
      totalLayers: 3,
      nodes: [
        makeNode("start", 0, 1, "start"),
        makeNode("top", 1, 4),
        makeNode("bottom", 1, 4),
        makeNode("end", 2, 1, "final_boss"),
      ],
      edges: [
        { from: "start", to: "top" },
        { from: "start", to: "bottom" },
        { from: "top", to: "end" },
        { from: "bottom", to: "end" },
      ],
    };

    const layout = computeLayout(graph);

    const top = layout.nodes.find((n) => n.id === "top")!;
    const bottom = layout.nodes.find((n) => n.id === "bottom")!;
    const end = layout.nodes.find((n) => n.id === "end")!;

    // top and bottom should be at same X (same layer) but different Y
    expect(top.x).toBe(bottom.x);
    expect(Math.abs(top.y - bottom.y)).toBeCloseTo(LAYER_SPACING_Y);

    // end should be between top and bottom Y (barycenter)
    const midY = (top.y + bottom.y) / 2;
    expect(end.y).toBeCloseTo(midY);
  });
});

// =============================================================================
// Edge routing
// =============================================================================

describe("edge routing", () => {
  it("uses single horizontal segment when dy == 0", () => {
    const graph: DagGraph = {
      totalLayers: 2,
      nodes: [makeNode("a", 0, 1), makeNode("b", 1, 1)],
      edges: [{ from: "a", to: "b" }],
    };

    const layout = computeLayout(graph);
    expect(layout.edges).toHaveLength(1);

    const edge = layout.edges[0];
    expect(edge.segments).toHaveLength(1);

    const seg = edge.segments[0];
    expect(seg.y1).toBe(seg.y2); // horizontal
  });

  it("uses 3 segments with 45-degree diagonal when dy != 0", () => {
    const graph: DagGraph = {
      totalLayers: 3,
      nodes: [
        makeNode("start", 0, 1, "start"),
        makeNode("top", 1, 4),
        makeNode("bottom", 1, 4),
        makeNode("end", 2, 1, "final_boss"),
      ],
      edges: [
        { from: "start", to: "top" },
        { from: "start", to: "bottom" },
        { from: "top", to: "end" },
        { from: "bottom", to: "end" },
      ],
    };

    const layout = computeLayout(graph);

    // Find an edge that has a vertical component
    const diagonalEdge = layout.edges.find((e) => e.segments.length === 3);
    expect(diagonalEdge).toBeDefined();

    if (diagonalEdge) {
      const [horiz1, diag, horiz2] = diagonalEdge.segments;

      // First segment is horizontal
      expect(horiz1.y1).toBe(horiz1.y2);

      // Diagonal: |dx| should equal |dy| (45-degree)
      const diagDx = Math.abs(diag.x2 - diag.x1);
      const diagDy = Math.abs(diag.y2 - diag.y1);
      expect(diagDx).toBeCloseTo(diagDy);

      // Last segment is horizontal
      expect(horiz2.y1).toBe(horiz2.y2);
    }
  });
});

// =============================================================================
// Full sample graph
// =============================================================================

describe("computeLayout — full sample_graph.json", () => {
  let layout: ReturnType<typeof computeLayout>;

  it("loads and lays out the full 16-node graph", () => {
    const raw = JSON.parse(
      readFileSync(
        resolve(
          __dirname,
          "../../../../../server/tests/fixtures/sample_graph.json",
        ),
        "utf-8",
      ),
    );
    const graph = parseDagGraph(raw);
    layout = computeLayout(graph);

    expect(layout.nodes).toHaveLength(16);
    expect(layout.edges).toHaveLength(17);
  });

  it("has reasonable dimensions", () => {
    expect(layout.width).toBeGreaterThan(200);
    expect(layout.height).toBeGreaterThan(100);
    expect(layout.width).toBeLessThan(5000);
    expect(layout.height).toBeLessThan(2000);
  });

  it("has all positive coordinates", () => {
    for (const node of layout.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeGreaterThanOrEqual(0);
    }
  });

  it("has no node overlaps", () => {
    for (let i = 0; i < layout.nodes.length; i++) {
      for (let j = i + 1; j < layout.nodes.length; j++) {
        const a = layout.nodes[i];
        const b = layout.nodes[j];
        const dist = Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
        // Nodes should be at least 10px apart
        expect(dist).toBeGreaterThan(10);
      }
    }
  });

  it("maintains layer ordering on X axis", () => {
    const nodesByLayer = new Map<number, typeof layout.nodes>();
    for (const node of layout.nodes) {
      const list = nodesByLayer.get(node.layer) ?? [];
      list.push(node);
      nodesByLayer.set(node.layer, list);
    }

    const layers = Array.from(nodesByLayer.keys()).sort((a, b) => a - b);
    for (let i = 1; i < layers.length; i++) {
      const prevNodes = nodesByLayer.get(layers[i - 1])!;
      const currNodes = nodesByLayer.get(layers[i])!;
      const maxPrevX = Math.max(...prevNodes.map((n) => n.x));
      const minCurrX = Math.min(...currNodes.map((n) => n.x));
      expect(minCurrX).toBeGreaterThan(maxPrevX);
    }
  });

  it("routes all edges correctly", () => {
    for (const edge of layout.edges) {
      expect(edge.segments.length).toBeGreaterThanOrEqual(1);
      expect(edge.segments.length).toBeLessThanOrEqual(3);

      // Edge should connect from source to target
      const from = layout.nodes.find((n) => n.id === edge.fromId)!;
      const to = layout.nodes.find((n) => n.id === edge.toId)!;
      expect(from).toBeDefined();
      expect(to).toBeDefined();

      // First segment starts at source
      expect(edge.segments[0].x1).toBe(from.x);
      expect(edge.segments[0].y1).toBe(from.y);

      // Last segment ends at target (both X and Y)
      const last = edge.segments[edge.segments.length - 1];
      expect(last.x2).toBe(to.x);
      expect(last.y2).toBe(to.y);
    }
  });
});

// =============================================================================
// Edge cases
// =============================================================================

describe("computeLayout — edge cases", () => {
  it("handles empty graph", () => {
    const layout = computeLayout({
      nodes: [],
      edges: [],
      totalLayers: 0,
    });
    expect(layout.nodes).toHaveLength(0);
    expect(layout.edges).toHaveLength(0);
    expect(layout.width).toBe(0);
    expect(layout.height).toBe(0);
  });

  it("handles single node", () => {
    const layout = computeLayout({
      nodes: [makeNode("solo", 0, 1, "start")],
      edges: [],
      totalLayers: 1,
    });
    expect(layout.nodes).toHaveLength(1);
    expect(layout.nodes[0].x).toBe(PADDING);
    expect(layout.width).toBe(PADDING * 2);
  });
});
