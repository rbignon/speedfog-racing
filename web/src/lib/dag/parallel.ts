/**
 * Utilities for computing parallel player path offsets on shared DAG edges.
 * Pure functions. No DOM or Svelte dependencies.
 */

import type { PositionedNode, RoutedEdge } from "./types";

/**
 * Directed adjacency split by edge orientation.
 *
 * `forward` maps each node to its original-DAG successors (fog-gate traversal
 * direction). `reverse` maps each node to its original-DAG predecessors
 * (backtrack direction). The split is required to enforce the gameplay rule
 * that reverse edges are only walkable between already-visited nodes.
 */
export interface DirectedAdjacency {
  forward: Map<string, string[]>;
  reverse: Map<string, string[]>;
}

/**
 * Build a DirectedAdjacency from a list of edges.
 */
export function buildDirectedAdjacency(
  edges: readonly { fromId: string; toId: string }[],
): DirectedAdjacency {
  const forward = new Map<string, string[]>();
  const reverse = new Map<string, string[]>();
  for (const edge of edges) {
    const fwd = forward.get(edge.fromId);
    if (fwd) fwd.push(edge.toId);
    else forward.set(edge.fromId, [edge.toId]);
    const rev = reverse.get(edge.toId);
    if (rev) rev.push(edge.fromId);
    else reverse.set(edge.toId, [edge.fromId]);
  }
  return { forward, reverse };
}

/**
 * Return the canonical (forward) edge key for a pair of nodes.
 * Forward and reverse traversals of the same physical edge share one key
 * so they end up in the same slot pool for parallel offset.
 */
export function canonicalEdgeKey(
  fromId: string,
  toId: string,
  edgeMap: Map<string, RoutedEdge>,
): string {
  const fwd = `${fromId}->${toId}`;
  if (edgeMap.has(fwd)) return fwd;
  const rev = `${toId}->${fromId}`;
  if (edgeMap.has(rev)) return rev;
  return fwd;
}

/**
 * Find a gameplay-valid bridge between two nodes that have no direct edge.
 *
 * Models Elden Ring traversal rules to infer plausible paths when the player
 * zone_history misses intermediate fog gates:
 *   - Forward edges (fog-gate traversals) are always allowed. They may cross
 *     non-visited nodes, representing the fog gates that were missed.
 *   - Reverse edges (backtracks) are only allowed between two already-visited
 *     nodes, because you can only walk back through terrain you've actually
 *     seen.
 *
 * BFS on this restricted subgraph yields the shortest gameplay-valid bridge.
 * Ties between equally-short bridges are broken by edge-insertion order
 * (the order in which forward adjacencies were built). Returns null if no
 * such bridge exists (caller should treat as a teleport gap).
 */
export function gameplayValidBridge(
  from: string,
  to: string,
  adj: DirectedAdjacency,
  visited: Set<string>,
): string[] | null {
  if (from === to) return [from];

  const parent = new Map<string, string | null>([[from, null]]);
  const queue: string[] = [from];

  while (queue.length > 0) {
    const cur = queue.shift()!;

    // Forward edges: always allowed (even into non-visited nodes).
    for (const next of adj.forward.get(cur) ?? []) {
      if (parent.has(next)) continue;
      parent.set(next, cur);
      if (next === to) return reconstructPath(parent, to);
      queue.push(next);
    }

    // Reverse edges: only between visited nodes.
    if (visited.has(cur)) {
      for (const prev of adj.reverse.get(cur) ?? []) {
        if (!visited.has(prev) || parent.has(prev)) continue;
        parent.set(prev, cur);
        if (prev === to) return reconstructPath(parent, to);
        queue.push(prev);
      }
    }
  }
  return null;
}

function reconstructPath(
  parent: Map<string, string | null>,
  to: string,
): string[] {
  const path: string[] = [to];
  let node: string = to;
  for (;;) {
    const prev: string | null = parent.get(node) ?? null;
    if (prev === null) break;
    path.unshift(prev);
    node = prev;
  }
  return path;
}

/**
 * Expand a deduplicated node path with gameplay-valid gap-filling.
 *
 * When consecutive nodes have no direct edge, fills in intermediate nodes
 * via `gameplayValidBridge` (forward edges free, reverse edges restricted
 * to visited-to-visited). Non-fog entries (backtrack, spawn) with no direct
 * edge are treated as teleports and left as gaps.
 */
export function expandNodePath(
  nodeIds: string[],
  edgeMap: Map<string, RoutedEdge>,
  adj: DirectedAdjacency,
  visited: Set<string>,
  entryTypes?: (string | undefined)[],
): string[] {
  if (nodeIds.length === 0) return [];
  const expanded: string[] = [nodeIds[0]];
  for (let i = 0; i < nodeIds.length - 1; i++) {
    const from = nodeIds[i];
    const to = nodeIds[i + 1];
    // Entry type of the destination node (undefined treated as "fog").
    const toType = entryTypes?.[i + 1];
    const isFog = toType === undefined || toType === "fog";

    if (edgeMap.has(`${from}->${to}`) || edgeMap.has(`${to}->${from}`)) {
      expanded.push(to);
    } else if (isFog) {
      const bridge = gameplayValidBridge(from, to, adj, visited);
      if (bridge) {
        for (let j = 1; j < bridge.length; j++) {
          expanded.push(bridge[j]);
        }
      } else {
        expanded.push(to);
      }
    } else {
      // Non-fog entry (backtrack/spawn) with no direct edge = teleport gap.
      expanded.push(to);
    }
  }
  return expanded;
}

/**
 * Build waypoints with perpendicular offset on shared edges.
 * Pinches at node centers (no offset) for a natural "station" effect.
 * Handles both forward and reverse (backtracking) edge traversals.
 *
 * @param expandedNodeIds - Full expanded node sequence for this player
 * @param nodeMap - Node ID → positioned node lookup
 * @param edgeMap - "fromId->toId" → routed edge lookup
 * @param getSlot - Returns this player's centered slot for a given canonical edge key
 * @param getCount - Returns total player count for a given canonical edge key
 * @param spacing - Perpendicular spacing in px between parallel lines
 */
export function buildPlayerWaypoints(
  expandedNodeIds: string[],
  nodeMap: Map<string, PositionedNode>,
  edgeMap: Map<string, RoutedEdge>,
  getSlot: (edgeKey: string) => number,
  getCount: (edgeKey: string) => number,
  spacing: number,
): { x: number; y: number }[][] {
  if (expandedNodeIds.length === 0) return [];

  const firstNode = nodeMap.get(expandedNodeIds[0]);
  if (!firstNode) return [];

  const segments: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [
    { x: firstNode.x, y: firstNode.y },
  ];

  for (let i = 0; i < expandedNodeIds.length - 1; i++) {
    const fromId = expandedNodeIds[i];
    const toId = expandedNodeIds[i + 1];
    const fwdEdge = edgeMap.get(`${fromId}->${toId}`);
    const revEdge = !fwdEdge ? edgeMap.get(`${toId}->${fromId}`) : undefined;
    const edge = fwdEdge ?? revEdge;

    if (!edge) {
      // No edge = teleport gap. End current segment and start a new one
      if (current.length > 0) segments.push(current);
      const gapNode = nodeMap.get(toId);
      current = gapNode ? [{ x: gapNode.x, y: gapNode.y }] : [];
      continue;
    }

    const cKey = canonicalEdgeKey(fromId, toId, edgeMap);
    const count = getCount(cKey);
    const slot = getSlot(cKey);

    if (fwdEdge) {
      for (const seg of fwdEdge.segments) {
        const dx = seg.x2 - seg.x1;
        const dy = seg.y2 - seg.y1;
        const len = Math.sqrt(dx * dx + dy * dy);

        if (count <= 1 || len < 0.5) {
          current.push({ x: seg.x2, y: seg.y2 });
        } else {
          // Perpendicular normal: (-dy, dx) / len
          const nx = -dy / len;
          const ny = dx / len;
          const offset = slot * spacing;
          current.push({
            x: seg.x2 + offset * nx,
            y: seg.y2 + offset * ny,
          });
        }
      }
    } else {
      // Reverse edge: traverse segments backward, using (x1, y1)
      for (let s = edge.segments.length - 1; s >= 0; s--) {
        const seg = edge.segments[s];
        const dx = seg.x1 - seg.x2;
        const dy = seg.y1 - seg.y2;
        const len = Math.sqrt(dx * dx + dy * dy);

        if (count <= 1 || len < 0.5) {
          current.push({ x: seg.x1, y: seg.y1 });
        } else {
          const nx = -dy / len;
          const ny = dx / len;
          const offset = slot * spacing;
          current.push({
            x: seg.x1 + offset * nx,
            y: seg.y1 + offset * ny,
          });
        }
      }
    }

    // Pinch at destination node center
    const destNode = nodeMap.get(toId);
    if (destNode) {
      current[current.length - 1] = { x: destNode.x, y: destNode.y };
    }
  }

  if (current.length > 0) segments.push(current);
  return segments;
}

/**
 * Compute centered slot index for player at given position among N players.
 * 1 player: 0, 2 players: -0.5/+0.5, 3 players: -1/0/+1, etc.
 */
export function computeSlot(playerIndex: number, totalPlayers: number): number {
  return playerIndex - (totalPlayers - 1) / 2;
}
