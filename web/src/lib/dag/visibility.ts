/**
 * Progressive DAG visibility logic.
 *
 * Computes which nodes and edges are visible based on discovered node IDs.
 * Three states: discovered (full), adjacent (dim placeholder), hidden (not rendered).
 */

import type { DagNode, DagEdge, PositionedNode, RoutedEdge } from "./types";
import { ADJACENT_EDGE_OPACITY } from "./constants";

export type NodeVisibility = "discovered" | "adjacent" | "hidden";

/**
 * Compute visibility for each node in the graph.
 *
 * - Discovered: node.id is in discoveredIds
 * - Adjacent: not discovered, but shares an edge with a discovered node
 * - Hidden: everything else
 * - The "start" node is always discovered
 */
export function computeNodeVisibility(
  nodes: DagNode[],
  edges: DagEdge[],
  discoveredIds: Set<string>,
): Map<string, NodeVisibility> {
  const result = new Map<string, NodeVisibility>();

  // Always include start node as discovered
  const effectiveDiscovered = new Set(discoveredIds);
  for (const node of nodes) {
    if (node.type === "start") {
      effectiveDiscovered.add(node.id);
    }
  }

  // Build adjacency from edges
  const neighbors = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!neighbors.has(edge.from)) neighbors.set(edge.from, new Set());
    if (!neighbors.has(edge.to)) neighbors.set(edge.to, new Set());
    neighbors.get(edge.from)!.add(edge.to);
    neighbors.get(edge.to)!.add(edge.from);
  }

  // Classify each node
  for (const node of nodes) {
    if (effectiveDiscovered.has(node.id)) {
      result.set(node.id, "discovered");
      continue;
    }

    // Check if any neighbor is discovered
    const nodeNeighbors = neighbors.get(node.id);
    if (nodeNeighbors) {
      for (const neighborId of nodeNeighbors) {
        if (effectiveDiscovered.has(neighborId)) {
          result.set(node.id, "adjacent");
          break;
        }
      }
    }

    if (!result.has(node.id)) {
      result.set(node.id, "hidden");
    }
  }

  return result;
}

/**
 * Filter positioned nodes to only those that are visible (discovered or adjacent).
 */
export function filterVisibleNodes(
  nodes: PositionedNode[],
  visibility: Map<string, NodeVisibility>,
): PositionedNode[] {
  return nodes.filter((n) => {
    const v = visibility.get(n.id);
    return v === "discovered" || v === "adjacent";
  });
}

/**
 * Filter edges to only those where both endpoints are visible.
 */
export function filterVisibleEdges(
  edges: RoutedEdge[],
  visibility: Map<string, NodeVisibility>,
): RoutedEdge[] {
  return edges.filter((e) => {
    const fromVis = visibility.get(e.fromId);
    const toVis = visibility.get(e.toId);
    return (
      (fromVis === "discovered" || fromVis === "adjacent") &&
      (toVis === "discovered" || toVis === "adjacent")
    );
  });
}

/**
 * Compute edge opacity based on endpoint visibility.
 * Both discovered: normal opacity. Any adjacent: dim.
 */
export function edgeOpacity(
  edge: RoutedEdge,
  visibility: Map<string, NodeVisibility>,
  normalOpacity: number,
): number {
  const fromVis = visibility.get(edge.fromId);
  const toVis = visibility.get(edge.toId);
  if (fromVis === "discovered" && toVis === "discovered") return normalOpacity;
  return ADJACENT_EDGE_OPACITY;
}

/**
 * Extract discovered node IDs from a participant's zone_history.
 */
export function extractDiscoveredIds(
  zoneHistory: { node_id: string; igt_ms: number }[] | null,
  currentZone: string | null,
): Set<string> {
  const ids = new Set<string>();
  if (zoneHistory) {
    for (const entry of zoneHistory) {
      ids.add(entry.node_id);
    }
  }
  if (currentZone) {
    ids.add(currentZone);
  }
  return ids;
}
