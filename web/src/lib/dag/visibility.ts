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
 * - Adjacent: not discovered, but reachable from a discovered node (forward exit)
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

  // Build predecessor map: for each node, track which nodes have edges pointing to it.
  // Only forward edges (discovered -> undiscovered) determine adjacency, so nodes
  // that merely lead TO discovered nodes (entrances) stay hidden.
  const predecessors = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!predecessors.has(edge.to)) predecessors.set(edge.to, new Set());
    predecessors.get(edge.to)!.add(edge.from);
  }

  // Classify each node
  for (const node of nodes) {
    if (effectiveDiscovered.has(node.id)) {
      result.set(node.id, "discovered");
      continue;
    }

    // Adjacent only if reachable from a discovered node (forward exit)
    const preds = predecessors.get(node.id);
    if (preds) {
      for (const predId of preds) {
        if (effectiveDiscovered.has(predId)) {
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
