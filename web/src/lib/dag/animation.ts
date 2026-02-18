/**
 * Pure animation utilities for the metro DAG hero visualization.
 * No DOM, no Svelte — fully testable.
 */

import type {
  DagLayout,
  PositionedNode,
  RoutedEdge,
  EdgeSegment,
} from "./types";
import { expandNodePath } from "./parallel";

// =============================================================================
// Types
// =============================================================================

export interface AnimationWaypoint {
  x: number;
  y: number;
  cumulativeDistance: number;
}

export interface RacerPath {
  nodeIds: string[];
  waypoints: AnimationWaypoint[];
  totalDistance: number;
}

export interface EdgeDrawTiming {
  fromId: string;
  toId: string;
  startFraction: number;
  endFraction: number;
  segments: EdgeSegment[];
}

export interface NodeAppearTiming {
  nodeId: string;
  fraction: number;
}

// =============================================================================
// Path enumeration
// =============================================================================

/**
 * DFS from start nodes (no incoming edges) to leaf nodes (no outgoing edges).
 * Returns all possible paths as arrays of node IDs.
 */
export function enumerateAllPaths(layout: DagLayout): string[][] {
  const childrenMap = new Map<string, string[]>();
  const hasIncoming = new Set<string>();

  for (const edge of layout.edges) {
    const list = childrenMap.get(edge.fromId);
    if (list) {
      list.push(edge.toId);
    } else {
      childrenMap.set(edge.fromId, [edge.toId]);
    }
    hasIncoming.add(edge.toId);
  }

  // Start nodes: no incoming edges
  const startNodes = layout.nodes.filter((n) => !hasIncoming.has(n.id));
  const allPaths: string[][] = [];

  function dfs(current: string, path: string[]): void {
    const children = childrenMap.get(current);
    if (!children || children.length === 0) {
      allPaths.push([...path]);
      return;
    }
    for (const child of children) {
      path.push(child);
      dfs(child, path);
      path.pop();
    }
  }

  for (const start of startNodes) {
    dfs(start.id, [start.id]);
  }

  return allPaths;
}

// =============================================================================
// Path selection
// =============================================================================

/**
 * Select N diverse paths for visual variety.
 * Picks paths that share the fewest nodes with already-selected paths.
 */
export function pickRacerPaths(
  allPaths: string[][],
  count: number,
): string[][] {
  if (allPaths.length <= count) return [...allPaths];
  if (allPaths.length === 0) return [];

  const selected: string[][] = [];
  const used = new Set<string>();

  // Sort by length (longer paths first for visual impact)
  const sorted = [...allPaths].sort((a, b) => b.length - a.length);

  // Greedy: pick the path with the fewest already-used nodes
  for (let i = 0; i < count; i++) {
    let bestPath = sorted[0];
    let bestOverlap = Infinity;

    for (const path of sorted) {
      if (selected.some((s) => s.join(",") === path.join(","))) continue;
      const overlap = path.filter((n) => used.has(n)).length;
      if (overlap < bestOverlap) {
        bestOverlap = overlap;
        bestPath = path;
      }
    }

    selected.push(bestPath);
    for (const nodeId of bestPath) {
      used.add(nodeId);
    }
  }

  return selected;
}

// =============================================================================
// Waypoint computation
// =============================================================================

export function segmentLength(seg: EdgeSegment): number {
  const dx = seg.x2 - seg.x1;
  const dy = seg.y2 - seg.y1;
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * BFS shortest path between two nodes in the DAG.
 * Returns the full path including start and end, or null if unreachable.
 */
export function bfsShortestPath(
  from: string,
  to: string,
  adjacency: Map<string, string[]>,
): string[] | null {
  if (from === to) return [from];

  const visited = new Set<string>([from]);
  const parent = new Map<string, string>();
  const queue: string[] = [from];

  while (queue.length > 0) {
    const current = queue.shift()!;
    const neighbors = adjacency.get(current);
    if (!neighbors) continue;

    for (const neighbor of neighbors) {
      if (visited.has(neighbor)) continue;
      visited.add(neighbor);
      parent.set(neighbor, current);

      if (neighbor === to) {
        const path: string[] = [to];
        let node = to;
        while (node !== from) {
          node = parent.get(node)!;
          path.unshift(node);
        }
        return path;
      }

      queue.push(neighbor);
    }
  }

  return null;
}

/**
 * Convert a node path to waypoints following edge segments.
 * When consecutive visited nodes have no direct edge, BFS fills in
 * intermediate nodes so the path follows the graph topology.
 */
export function pathToWaypoints(
  nodeIds: string[],
  layout: DagLayout,
): AnimationWaypoint[] {
  if (nodeIds.length === 0) return [];

  const nodeMap = new Map<string, PositionedNode>();
  for (const node of layout.nodes) {
    nodeMap.set(node.id, node);
  }

  // Build edge lookup: "fromId->toId" -> RoutedEdge
  const edgeMap = new Map<string, RoutedEdge>();
  for (const edge of layout.edges) {
    edgeMap.set(`${edge.fromId}->${edge.toId}`, edge);
  }

  // Build bidirectional adjacency list for BFS gap-filling
  // (bidirectional so expandNodePath can handle backtracking paths)
  const adjacency = new Map<string, string[]>();
  for (const edge of layout.edges) {
    const fwd = adjacency.get(edge.fromId);
    if (fwd) fwd.push(edge.toId);
    else adjacency.set(edge.fromId, [edge.toId]);
    const rev = adjacency.get(edge.toId);
    if (rev) rev.push(edge.fromId);
    else adjacency.set(edge.toId, [edge.fromId]);
  }

  // Expand path: fill gaps between non-adjacent nodes with BFS
  const expanded = expandNodePath(nodeIds, edgeMap, adjacency);

  const waypoints: AnimationWaypoint[] = [];
  let cumDist = 0;

  // Start at first node
  const firstNode = nodeMap.get(expanded[0]);
  if (!firstNode) return [];
  waypoints.push({ x: firstNode.x, y: firstNode.y, cumulativeDistance: 0 });

  // Follow edges between consecutive expanded nodes
  for (let i = 0; i < expanded.length - 1; i++) {
    const edge = edgeMap.get(`${expanded[i]}->${expanded[i + 1]}`);
    if (!edge) continue;

    for (const seg of edge.segments) {
      const len = segmentLength(seg);
      cumDist += len;
      waypoints.push({ x: seg.x2, y: seg.y2, cumulativeDistance: cumDist });
    }
  }

  return waypoints;
}

/**
 * Build a complete RacerPath from a node ID path and layout.
 */
export function buildRacerPath(
  nodeIds: string[],
  layout: DagLayout,
): RacerPath {
  const waypoints = pathToWaypoints(nodeIds, layout);
  return {
    nodeIds,
    waypoints,
    totalDistance:
      waypoints.length > 0
        ? waypoints[waypoints.length - 1].cumulativeDistance
        : 0,
  };
}

// =============================================================================
// Edge draw timings
// =============================================================================

/**
 * Compute per-edge timing for the draw phase.
 * Edges are ordered by source node layer (left-to-right).
 * Each edge's draw fraction is proportional to its total segment length.
 */
export function computeEdgeDrawTimings(layout: DagLayout): EdgeDrawTiming[] {
  const nodeMap = new Map<string, PositionedNode>();
  for (const node of layout.nodes) {
    nodeMap.set(node.id, node);
  }

  // Sort edges by source node layer, then by source node Y
  const sorted = [...layout.edges].sort((a, b) => {
    const aFrom = nodeMap.get(a.fromId);
    const bFrom = nodeMap.get(b.fromId);
    const layerDiff = (aFrom?.layer ?? 0) - (bFrom?.layer ?? 0);
    if (layerDiff !== 0) return layerDiff;
    return (aFrom?.y ?? 0) - (bFrom?.y ?? 0);
  });

  // Calculate total edge length across all edges
  let totalLength = 0;
  const edgeLengths: number[] = [];
  for (const edge of sorted) {
    let edgeLen = 0;
    for (const seg of edge.segments) {
      edgeLen += segmentLength(seg);
    }
    edgeLengths.push(edgeLen);
    totalLength += edgeLen;
  }

  if (totalLength === 0) return [];

  // Assign timings: edges draw in layer order, each taking proportional time
  // But edges from the same layer draw simultaneously
  const layerGroups = new Map<number, number[]>();
  for (let i = 0; i < sorted.length; i++) {
    const fromNode = nodeMap.get(sorted[i].fromId);
    const layer = fromNode?.layer ?? 0;
    const list = layerGroups.get(layer);
    if (list) list.push(i);
    else layerGroups.set(layer, [i]);
  }

  const layers = Array.from(layerGroups.keys()).sort((a, b) => a - b);
  const timings: EdgeDrawTiming[] = [];

  // Each layer group gets a fraction proportional to its total length
  let layerLengths: { layer: number; length: number; indices: number[] }[] = [];
  let allLayerLength = 0;
  for (const layer of layers) {
    const indices = layerGroups.get(layer)!;
    let groupLen = 0;
    for (const idx of indices) {
      groupLen += edgeLengths[idx];
    }
    layerLengths.push({ layer, length: groupLen, indices });
    allLayerLength += groupLen;
  }

  let currentFraction = 0;
  for (const group of layerLengths) {
    const groupFraction =
      allLayerLength > 0 ? group.length / allLayerLength : 0;
    // All edges in this layer draw simultaneously
    for (const idx of group.indices) {
      timings.push({
        fromId: sorted[idx].fromId,
        toId: sorted[idx].toId,
        startFraction: currentFraction,
        endFraction: currentFraction + groupFraction,
        segments: sorted[idx].segments,
      });
    }
    currentFraction += groupFraction;
  }

  return timings;
}

// =============================================================================
// Node appear timings
// =============================================================================

/**
 * Compute when each node should appear (fade in).
 * A node appears when the first incoming edge finishes drawing.
 * Start nodes appear at fraction 0.
 */
export function computeNodeAppearTimings(
  layout: DagLayout,
  edgeTimings: EdgeDrawTiming[],
): NodeAppearTiming[] {
  const hasIncoming = new Set<string>();
  for (const edge of layout.edges) {
    hasIncoming.add(edge.toId);
  }

  const nodeTimings: NodeAppearTiming[] = [];

  for (const node of layout.nodes) {
    if (!hasIncoming.has(node.id)) {
      // Start node: appears immediately
      nodeTimings.push({ nodeId: node.id, fraction: 0 });
      continue;
    }

    // Find the earliest-finishing incoming edge
    let earliestEnd = 1;
    for (const timing of edgeTimings) {
      if (timing.toId === node.id) {
        earliestEnd = Math.min(earliestEnd, timing.endFraction);
      }
    }
    nodeTimings.push({ nodeId: node.id, fraction: earliestEnd });
  }

  return nodeTimings;
}

// =============================================================================
// Position interpolation
// =============================================================================

/**
 * Interpolate position along a racer path at fractional progress [0, 1].
 * Returns {x, y} for smooth constant-speed movement.
 */
export function interpolatePosition(
  racerPath: RacerPath,
  progress: number,
): { x: number; y: number } {
  const { waypoints, totalDistance } = racerPath;
  if (waypoints.length === 0) return { x: 0, y: 0 };
  if (waypoints.length === 1) return { x: waypoints[0].x, y: waypoints[0].y };

  const clampedProgress = Math.max(0, Math.min(1, progress));
  const targetDist = clampedProgress * totalDistance;

  // Find the segment containing the target distance
  for (let i = 1; i < waypoints.length; i++) {
    if (waypoints[i].cumulativeDistance >= targetDist) {
      const prev = waypoints[i - 1];
      const curr = waypoints[i];
      const segLen = curr.cumulativeDistance - prev.cumulativeDistance;
      if (segLen === 0) return { x: curr.x, y: curr.y };

      const t = (targetDist - prev.cumulativeDistance) / segLen;
      return {
        x: prev.x + (curr.x - prev.x) * t,
        y: prev.y + (curr.y - prev.y) * t,
      };
    }
  }

  // At the end
  const last = waypoints[waypoints.length - 1];
  return { x: last.x, y: last.y };
}
