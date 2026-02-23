/**
 * Popup data computation helpers for DAG node detail popups.
 */

import type { DagEdge, DagNode, DagNodeType } from "./types";
import type { WsParticipant } from "$lib/websocket";
import { PLAYER_COLORS } from "./constants";
import { computeOutcome, type ZoneOutcome } from "$lib/highlights";

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

/** Map from nodeId → its entrances with fog gate text and source nodeId. */
export type EntranceTextMap = Map<
  string,
  { text: string; fromNodeId: string }[]
>;

export interface PopupPlayer {
  displayName: string;
  color: string;
}

export type VisitOutcome = ZoneOutcome;

export interface PopupVisitor {
  displayName: string;
  color: string;
  arrivedAtMs: number;
  timeSpentMs?: number; // duration in this zone (until next zone or race finish)
  deaths?: number;
  outcome: VisitOutcome;
}

export interface NodePopupData {
  nodeId: string;
  displayName: string;
  type: DagNodeType;
  displayType?: string;
  tier: number;
  randomizedBoss?: string;
  entrances: PopupConnection[];
  exits: PopupConnection[];
  playersHere?: PopupPlayer[];
  visitors?: PopupVisitor[];
  raceFinished?: boolean;
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
 * Parse per-node entrance texts from raw graph.json.
 * Each node may have an `entrances` array with `{ text, from (nodeId) }`.
 * Returns empty map for older graph.json files without the entrances field.
 */
export function parseEntranceTexts(
  graphJson: Record<string, unknown>,
): EntranceTextMap {
  const map: EntranceTextMap = new Map();
  const rawNodes = graphJson.nodes as
    | Record<string, Record<string, unknown>>
    | undefined;
  if (!rawNodes) return map;

  for (const [nodeId, raw] of Object.entries(rawNodes)) {
    const entrances = raw.entrances as
      | Array<{ text: string; from: string; to: string; to_text: string }>
      | undefined;
    if (!entrances || entrances.length === 0) continue;
    map.set(
      nodeId,
      entrances.map((e) => ({ text: e.text, fromNodeId: e.from })),
    );
  }
  return map;
}

/**
 * Compute entrances and exits for a node.
 *
 * When `discoveredIds` is provided (progressive mode), connections to
 * undiscovered nodes get `displayName: null` (shown as "???").
 *
 * When `exitTexts` is provided, each connection is enriched with the
 * fog gate location description from graph.json. When `entranceTexts`
 * is provided, entrance connections use the current node's entrance
 * text; no text is shown if the node has no matching entrance.
 */
export function computeConnections(
  nodeId: string,
  edges: DagEdge[],
  nodeMap: Map<string, DagNode>,
  discoveredIds?: Set<string>,
  exitTexts?: ExitTextMap,
  entranceTexts?: EntranceTextMap,
): { entrances: PopupConnection[]; exits: PopupConnection[] } {
  const entrances: PopupConnection[] = [];
  const exits: PopupConnection[] = [];

  for (const edge of edges) {
    if (edge.to === nodeId) {
      const fromNode = nodeMap.get(edge.from);
      if (!fromNode) continue;
      const isUndiscovered = discoveredIds && !discoveredIds.has(edge.from);
      // Entrance text: from current node's entrances field only.
      // Hidden for undiscovered connections (anti-spoiler).
      const text = isUndiscovered
        ? undefined
        : entranceTexts?.get(nodeId)?.find((e) => e.fromNodeId === edge.from)
            ?.text;
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
      // Exit text: describes WHERE the fog gate is in the current node.
      // Always shown — it's about the player's own zone, not the destination.
      // Assumes at most one exit per (from, to) pair in graph.json.
      const text = exitTexts
        ?.get(nodeId)
        ?.find((e) => e.toNodeId === edge.to)?.text;
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
 * Find all participants who visited a node (from zone_history).
 *
 * Computes outcome per visitor:
 * - cleared: next zone is on a higher layer
 * - backed: next zone is on same/lower layer
 * - playing: last zone + status playing
 * - abandoned: last zone + status abandoned/finished-but-stuck
 *
 * Sorted: cleared first (by time asc), then backed/playing/abandoned.
 */
export function computeVisitors(
  nodeId: string,
  participants: WsParticipant[],
  nodeLayers?: Map<string, number>,
): PopupVisitor[] {
  const visitors: PopupVisitor[] = [];
  for (const p of participants) {
    if (!p.zone_history) continue;
    const idx = p.zone_history.findIndex((e) => e.node_id === nodeId);
    if (idx === -1) continue;
    const entry = p.zone_history[idx];
    const isLast = idx >= p.zone_history.length - 1;

    let timeSpentMs: number | undefined;
    if (!isLast) {
      timeSpentMs = p.zone_history[idx + 1].igt_ms - entry.igt_ms;
    } else if (p.status === "finished" || p.status === "playing") {
      timeSpentMs = p.igt_ms - entry.igt_ms;
    }

    const nextNodeId = isLast ? undefined : p.zone_history[idx + 1].node_id;
    const outcome = computeOutcome(
      isLast,
      entry.node_id,
      nextNodeId,
      p.status,
      nodeLayers,
    );

    visitors.push({
      displayName: p.twitch_display_name || p.twitch_username,
      color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
      arrivedAtMs: entry.igt_ms,
      timeSpentMs:
        timeSpentMs != null && timeSpentMs > 0 ? timeSpentMs : undefined,
      deaths: entry.deaths && entry.deaths > 0 ? entry.deaths : undefined,
      outcome,
    });
  }
  // Cleared first (by time asc), then others
  const outcomeOrder: Record<VisitOutcome, number> = {
    cleared: 0,
    backed: 1,
    playing: 2,
    abandoned: 3,
  };
  visitors.sort(
    (a, b) =>
      outcomeOrder[a.outcome] - outcomeOrder[b.outcome] ||
      (a.timeSpentMs ?? 0) - (b.timeSpentMs ?? 0),
  );
  return visitors;
}

/**
 * Extract node layer map from raw graph.json for outcome computation.
 */
export function parseNodeLayers(
  graphJson: Record<string, unknown>,
): Map<string, number> {
  const map = new Map<string, number>();
  const rawNodes = graphJson.nodes as
    | Record<string, Record<string, unknown>>
    | undefined;
  if (!rawNodes) return map;
  for (const [nodeId, raw] of Object.entries(rawNodes)) {
    map.set(nodeId, (raw.layer as number) ?? 0);
  }
  return map;
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
