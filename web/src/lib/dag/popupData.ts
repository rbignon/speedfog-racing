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
  text?: string; // fog gate location description (e.g. "before Grafted Scion's arena")
}

/** Map from nodeId → its exits with fog gate text and destination nodeId. */
export type ExitTextMap = Map<string, { text: string; toNodeId: string }[]>;

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
 * Parse per-node exit texts from raw graph.json.
 * Each node may have an `exits` array with `{ text, to (nodeId) }`.
 */
export function parseExitTexts(
  graphJson: Record<string, unknown>,
): ExitTextMap {
  const map: ExitTextMap = new Map();
  const rawNodes = graphJson.nodes as
    | Record<string, Record<string, unknown>>
    | undefined;
  if (!rawNodes) return map;

  for (const [nodeId, raw] of Object.entries(rawNodes)) {
    const exits = raw.exits as
      | Array<{ fog_id: string; text: string; from: string; to: string }>
      | undefined;
    if (!exits || exits.length === 0) continue;
    map.set(
      nodeId,
      exits.map((e) => ({ text: e.text, toNodeId: e.to })),
    );
  }
  return map;
}

/**
 * Compute entrances and exits for a node.
 *
 * When `discoveredIds` is provided (progressive mode), connections to
 * undiscovered-but-adjacent nodes get `displayName: null` (shown as "???"),
 * and connections to fully hidden nodes are omitted entirely.
 *
 * When `exitTexts` is provided, each connection is enriched with the
 * fog gate location description from graph.json.
 */
export function computeConnections(
  nodeId: string,
  edges: DagEdge[],
  nodeMap: Map<string, DagNode>,
  discoveredIds?: Set<string>,
  exitTexts?: ExitTextMap,
): { entrances: PopupConnection[]; exits: PopupConnection[] } {
  const entrances: PopupConnection[] = [];
  const exits: PopupConnection[] = [];

  for (const edge of edges) {
    if (edge.to === nodeId) {
      const fromNode = nodeMap.get(edge.from);
      if (!fromNode) continue;
      const isUndiscovered = discoveredIds && !discoveredIds.has(edge.from);
      // Entrance text: the source node's exit pointing to us.
      // Hidden for undiscovered connections (anti-spoiler).
      // Assumes at most one exit per (from, to) pair in graph.json.
      const text = isUndiscovered
        ? undefined
        : exitTexts?.get(edge.from)?.find((e) => e.toNodeId === nodeId)?.text;
      entrances.push({
        nodeId: edge.from,
        displayName: isUndiscovered ? null : fromNode.displayName,
        type: fromNode.type,
        text,
      });
    }
    if (edge.from === nodeId) {
      const toNode = nodeMap.get(edge.to);
      if (!toNode) continue;
      const isUndiscovered = discoveredIds && !discoveredIds.has(edge.to);
      // Exit text: our own exit pointing to the destination.
      // Hidden for undiscovered connections (anti-spoiler).
      // Assumes at most one exit per (from, to) pair in graph.json.
      const text = isUndiscovered
        ? undefined
        : exitTexts?.get(nodeId)?.find((e) => e.toNodeId === edge.to)?.text;
      exits.push({
        nodeId: edge.to,
        displayName: isUndiscovered ? null : toNode.displayName,
        type: toNode.type,
        text,
      });
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
