/**
 * Utilities for computing parallel player path offsets on shared DAG edges.
 * Pure functions — no DOM or Svelte dependencies.
 */

import { bfsShortestPath } from "./animation";
import type { PositionedNode, RoutedEdge } from "./types";

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
 * Expand a deduplicated node path with BFS gap-filling.
 * When consecutive nodes have no direct edge, fills in
 * intermediate nodes so the path follows the graph topology.
 * Supports backtracking: reverse edges (to→from) are treated
 * as valid direct connections. Pass a bidirectional adjacency
 * map so BFS can find backtracking routes.
 */
export function expandNodePath(
  nodeIds: string[],
  edgeMap: Map<string, RoutedEdge>,
  adjacency: Map<string, string[]>,
): string[] {
  if (nodeIds.length === 0) return [];
  const expanded: string[] = [nodeIds[0]];
  for (let i = 0; i < nodeIds.length - 1; i++) {
    const from = nodeIds[i];
    const to = nodeIds[i + 1];
    if (edgeMap.has(`${from}->${to}`) || edgeMap.has(`${to}->${from}`)) {
      expanded.push(to);
    } else {
      const bridge = bfsShortestPath(from, to, adjacency);
      if (bridge) {
        for (let j = 1; j < bridge.length; j++) {
          expanded.push(bridge[j]);
        }
      } else {
        expanded.push(to);
      }
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
): { x: number; y: number }[] {
  if (expandedNodeIds.length === 0) return [];

  const points: { x: number; y: number }[] = [];

  const firstNode = nodeMap.get(expandedNodeIds[0]);
  if (!firstNode) return [];
  points.push({ x: firstNode.x, y: firstNode.y });

  for (let i = 0; i < expandedNodeIds.length - 1; i++) {
    const fromId = expandedNodeIds[i];
    const toId = expandedNodeIds[i + 1];
    const fwdEdge = edgeMap.get(`${fromId}->${toId}`);
    const revEdge = !fwdEdge ? edgeMap.get(`${toId}->${fromId}`) : undefined;
    const edge = fwdEdge ?? revEdge;

    if (!edge) continue;

    const cKey = canonicalEdgeKey(fromId, toId, edgeMap);
    const count = getCount(cKey);
    const slot = getSlot(cKey);

    if (fwdEdge) {
      for (const seg of fwdEdge.segments) {
        const dx = seg.x2 - seg.x1;
        const dy = seg.y2 - seg.y1;
        const len = Math.sqrt(dx * dx + dy * dy);

        if (count <= 1 || len < 0.5) {
          points.push({ x: seg.x2, y: seg.y2 });
        } else {
          // Perpendicular normal: (-dy, dx) / len
          const nx = -dy / len;
          const ny = dx / len;
          const offset = slot * spacing;
          points.push({
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
          points.push({ x: seg.x1, y: seg.y1 });
        } else {
          const nx = -dy / len;
          const ny = dx / len;
          const offset = slot * spacing;
          points.push({
            x: seg.x1 + offset * nx,
            y: seg.y1 + offset * ny,
          });
        }
      }
    }

    // Pinch at destination node center
    const destNode = nodeMap.get(toId);
    if (destNode) {
      points[points.length - 1] = { x: destNode.x, y: destNode.y };
    }
  }

  return points;
}

/**
 * Compute centered slot index for player at given position among N players.
 * 1 player: 0, 2 players: -0.5/+0.5, 3 players: -1/0/+1, etc.
 */
export function computeSlot(playerIndex: number, totalPlayers: number): number {
  return playerIndex - (totalPlayers - 1) / 2;
}
