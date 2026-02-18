/**
 * Popup data computation helpers for DAG node detail popups.
 */

import type { DagEdge, DagNode, DagNodeType } from "./types";
import type { WsParticipant } from "$lib/websocket";
import { PLAYER_COLORS } from "./constants";

// =============================================================================
// Types
// =============================================================================

export interface PopupConnection {
  nodeId: string;
  displayName: string | null; // null = undiscovered ("???")
  type: DagNodeType;
}

export interface PopupPlayer {
  displayName: string;
  color: string;
}

export interface PopupVisitor {
  displayName: string;
  color: string;
  arrivedAtMs: number;
}

export interface NodePopupData {
  nodeId: string;
  displayName: string;
  type: DagNodeType;
  tier: number;
  entrances: PopupConnection[];
  exits: PopupConnection[];
  playersHere?: PopupPlayer[];
  visitors?: PopupVisitor[];
}

// =============================================================================
// Helpers
// =============================================================================

/**
 * Compute entrances and exits for a node.
 *
 * When `discoveredIds` is provided (progressive mode), connections to
 * undiscovered-but-adjacent nodes get `displayName: null` (shown as "???"),
 * and connections to fully hidden nodes are omitted entirely.
 */
export function computeConnections(
  nodeId: string,
  edges: DagEdge[],
  nodeMap: Map<string, DagNode>,
  discoveredIds?: Set<string>,
): { entrances: PopupConnection[]; exits: PopupConnection[] } {
  const entrances: PopupConnection[] = [];
  const exits: PopupConnection[] = [];

  for (const edge of edges) {
    if (edge.to === nodeId) {
      const fromNode = nodeMap.get(edge.from);
      if (!fromNode) continue;
      if (discoveredIds && !discoveredIds.has(edge.from)) {
        entrances.push({
          nodeId: edge.from,
          displayName: null,
          type: fromNode.type,
        });
      } else {
        entrances.push({
          nodeId: edge.from,
          displayName: fromNode.displayName,
          type: fromNode.type,
        });
      }
    }
    if (edge.from === nodeId) {
      const toNode = nodeMap.get(edge.to);
      if (!toNode) continue;
      if (discoveredIds && !discoveredIds.has(edge.to)) {
        exits.push({ nodeId: edge.to, displayName: null, type: toNode.type });
      } else {
        exits.push({
          nodeId: edge.to,
          displayName: toNode.displayName,
          type: toNode.type,
        });
      }
    }
  }

  return { entrances, exits };
}

/**
 * Find players currently at a specific node.
 */
export function computePlayersAtNode(
  nodeId: string,
  participants: WsParticipant[],
): PopupPlayer[] {
  const players: PopupPlayer[] = [];
  for (const p of participants) {
    if (p.current_zone !== nodeId) continue;
    if (p.status !== "playing" && p.status !== "finished") continue;
    players.push({
      displayName: p.twitch_display_name || p.twitch_username,
      color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
    });
  }
  return players;
}

/**
 * Find all participants who visited a node (from zone_history), sorted by arrival time.
 */
export function computeVisitors(
  nodeId: string,
  participants: WsParticipant[],
): PopupVisitor[] {
  const visitors: PopupVisitor[] = [];
  for (const p of participants) {
    if (!p.zone_history) continue;
    const entry = p.zone_history.find((e) => e.node_id === nodeId);
    if (!entry) continue;
    visitors.push({
      displayName: p.twitch_display_name || p.twitch_username,
      color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
      arrivedAtMs: entry.igt_ms,
    });
  }
  visitors.sort((a, b) => a.arrivedAtMs - b.arrivedAtMs);
  return visitors;
}

/**
 * Format IGT milliseconds to human-readable string.
 */
export function formatIgt(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
