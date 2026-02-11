/**
 * Utilities for computing parallel player path offsets on shared DAG edges.
 * Pure functions — no DOM or Svelte dependencies.
 */

import { bfsShortestPath } from "./animation";
import type { PositionedNode, RoutedEdge } from "./types";

/**
 * Expand a deduplicated node path with BFS gap-filling.
 * When consecutive nodes have no direct edge, fills in
 * intermediate nodes so the path follows the graph topology.
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
    if (edgeMap.has(`${from}->${to}`)) {
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
 *
 * @param expandedNodeIds - Full expanded node sequence for this player
 * @param nodeMap - Node ID → positioned node lookup
 * @param edgeMap - "fromId->toId" → routed edge lookup
 * @param getSlot - Returns this player's centered slot for a given edge key
 * @param getCount - Returns total player count for a given edge key
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
    const key = `${fromId}->${toId}`;
    const edge = edgeMap.get(key);
    if (!edge) continue;

    const count = getCount(key);
    const slot = getSlot(key);

    for (const seg of edge.segments) {
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
