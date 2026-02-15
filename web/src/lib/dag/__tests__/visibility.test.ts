import { describe, it, expect } from "vitest";
import { computeNodeVisibility } from "../visibility";
import type { DagNode, DagEdge } from "../types";

function makeNode(
  id: string,
  type: DagNode["type"] = "mini_dungeon",
  layer = 1,
): DagNode {
  return { id, type, displayName: id, zones: [], layer, tier: 1, weight: 1 };
}

// Simple graph: start -> A -> B, start -> C
const nodes: DagNode[] = [
  makeNode("start_node", "start", 0),
  makeNode("a"),
  makeNode("b", "mini_dungeon", 2),
  makeNode("c"),
];

const edges: DagEdge[] = [
  { from: "start_node", to: "a" },
  { from: "a", to: "b" },
  { from: "start_node", to: "c" },
];

describe("computeNodeVisibility", () => {
  it("marks start node as discovered with empty discoveredIds", () => {
    const vis = computeNodeVisibility(nodes, edges, new Set());
    expect(vis.get("start_node")).toBe("discovered");
  });

  it("marks start neighbors as adjacent with empty discoveredIds", () => {
    const vis = computeNodeVisibility(nodes, edges, new Set());
    expect(vis.get("a")).toBe("adjacent");
    expect(vis.get("c")).toBe("adjacent");
  });

  it("marks non-adjacent nodes as hidden with empty discoveredIds", () => {
    const vis = computeNodeVisibility(nodes, edges, new Set());
    expect(vis.get("b")).toBe("hidden");
  });

  it("marks explicitly discovered nodes as discovered", () => {
    const vis = computeNodeVisibility(nodes, edges, new Set(["a"]));
    expect(vis.get("a")).toBe("discovered");
    // b is now adjacent to discovered a
    expect(vis.get("b")).toBe("adjacent");
  });

  it("handles graph with no edges", () => {
    const isolated = [makeNode("start_node", "start", 0), makeNode("x")];
    const vis = computeNodeVisibility(isolated, [], new Set());
    expect(vis.get("start_node")).toBe("discovered");
    expect(vis.get("x")).toBe("hidden");
  });

  it("marks final_boss as adjacent when predecessor is discovered", () => {
    const graphWithFinal: DagNode[] = [
      makeNode("start_node", "start", 0),
      makeNode("a"),
      makeNode("boss", "final_boss", 2),
    ];
    const edgesWithFinal: DagEdge[] = [
      { from: "start_node", to: "a" },
      { from: "a", to: "boss" },
    ];
    const vis = computeNodeVisibility(
      graphWithFinal,
      edgesWithFinal,
      new Set(["a"]),
    );
    expect(vis.get("boss")).toBe("adjacent");
  });

  it("makes parent adjacent when only child is discovered", () => {
    const vis = computeNodeVisibility(nodes, edges, new Set(["b"]));
    expect(vis.get("a")).toBe("adjacent");
    expect(vis.get("b")).toBe("discovered");
  });
});
