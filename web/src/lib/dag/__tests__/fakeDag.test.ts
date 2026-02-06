import { describe, it, expect } from "vitest";
import { generateFakeDag } from "../fakeDag";
import { computeLayout } from "../layout";

describe("generateFakeDag", () => {
  it("returns empty graph for zero layers", () => {
    const graph = generateFakeDag(0, 0, 0);
    expect(graph.nodes).toHaveLength(0);
    expect(graph.edges).toHaveLength(0);
    expect(graph.totalLayers).toBe(0);
  });

  it("returns a valid DagGraph with correct totalLayers", () => {
    const graph = generateFakeDag(10, 16, 4);
    expect(graph.totalLayers).toBe(10);
  });

  it("creates approximately the requested number of nodes", () => {
    const graph = generateFakeDag(10, 16, 4);
    // Should have at least totalLayers nodes (one per layer min)
    expect(graph.nodes.length).toBeGreaterThanOrEqual(10);
    // Should not wildly exceed
    expect(graph.nodes.length).toBeLessThanOrEqual(30);
  });

  it("assigns correct layer values to all nodes", () => {
    const graph = generateFakeDag(8, 12, 3);
    for (const node of graph.nodes) {
      expect(node.layer).toBeGreaterThanOrEqual(0);
      expect(node.layer).toBeLessThan(8);
    }
  });

  it("has a start node at layer 0 and final_boss at last layer", () => {
    const graph = generateFakeDag(5, 8, 2);
    const startNodes = graph.nodes.filter((n) => n.layer === 0);
    const endNodes = graph.nodes.filter((n) => n.layer === 4);
    expect(startNodes.length).toBeGreaterThanOrEqual(1);
    expect(endNodes.length).toBeGreaterThanOrEqual(1);
    expect(startNodes[0].type).toBe("start");
    expect(endNodes[0].type).toBe("final_boss");
  });

  it("produces a connected graph (all edges reference valid nodes)", () => {
    const graph = generateFakeDag(10, 16, 4);
    const nodeIds = new Set(graph.nodes.map((n) => n.id));
    for (const edge of graph.edges) {
      expect(nodeIds.has(edge.from)).toBe(true);
      expect(nodeIds.has(edge.to)).toBe(true);
    }
  });

  it("only creates edges between consecutive layers", () => {
    const graph = generateFakeDag(10, 16, 4);
    const nodeMap = new Map(graph.nodes.map((n) => [n.id, n]));
    for (const edge of graph.edges) {
      const from = nodeMap.get(edge.from)!;
      const to = nodeMap.get(edge.to)!;
      expect(to.layer - from.layer).toBe(1);
    }
  });

  it("every non-last-layer node has at least one outgoing edge", () => {
    const graph = generateFakeDag(8, 14, 3);
    const outgoing = new Set(graph.edges.map((e) => e.from));
    for (const node of graph.nodes) {
      if (node.layer < graph.totalLayers - 1) {
        expect(outgoing.has(node.id)).toBe(true);
      }
    }
  });

  it("every non-first-layer node has at least one incoming edge", () => {
    const graph = generateFakeDag(8, 14, 3);
    const incoming = new Set(graph.edges.map((e) => e.to));
    for (const node of graph.nodes) {
      if (node.layer > 0) {
        expect(incoming.has(node.id)).toBe(true);
      }
    }
  });

  it("produces a graph that computeLayout can process", () => {
    const graph = generateFakeDag(10, 16, 4);
    const layout = computeLayout(graph);
    expect(layout.nodes.length).toBe(graph.nodes.length);
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.height).toBeGreaterThan(0);
  });

  it("handles single-layer graph", () => {
    const graph = generateFakeDag(1, 1, 1);
    expect(graph.nodes).toHaveLength(1);
    expect(graph.edges).toHaveLength(0);
  });

  it("handles two-layer graph", () => {
    const graph = generateFakeDag(2, 3, 1);
    expect(graph.nodes.length).toBeGreaterThanOrEqual(2);
    expect(graph.edges.length).toBeGreaterThanOrEqual(1);
  });
});
