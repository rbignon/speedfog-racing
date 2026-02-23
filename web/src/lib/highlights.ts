/**
 * Race highlights computation.
 *
 * Pure functions that compute interesting race highlights from
 * zone_history data and graph_json topology.
 */

import type { WsParticipant } from "$lib/websocket";

// =============================================================================
// Types
// =============================================================================

export interface ZoneTime {
  nodeId: string;
  timeMs: number;
  deaths: number;
}

export type HighlightCategory = "speed" | "deaths" | "path" | "competitive";

export interface Highlight {
  type: string;
  category: HighlightCategory;
  title: string;
  description: string;
  /** Participant ID(s) involved */
  playerIds: string[];
  /** Internal score for ranking (higher = more interesting) */
  score: number;
}

// =============================================================================
// Helpers
// =============================================================================

/**
 * Compute time spent in each zone for a participant.
 * Time in zone N = entry time of zone N+1 - entry time of zone N.
 * For the last zone, uses participant's final igt_ms.
 */
export function computeZoneTimes(p: WsParticipant): ZoneTime[] {
  if (!p.zone_history || p.zone_history.length === 0) return [];

  return p.zone_history.map((entry, i) => {
    const nextIgt =
      i < p.zone_history!.length - 1 ? p.zone_history![i + 1].igt_ms : p.igt_ms;
    return {
      nodeId: entry.node_id,
      timeMs: Math.max(0, nextIgt - entry.igt_ms),
      deaths: entry.deaths ?? 0,
    };
  });
}
