import type { Highlight } from "$lib/highlights";
import type { CommentaryEvent, ReplayParticipant } from "./types";

/**
 * Highlight types that correspond to a specific moment (punctual).
 * Maps type -> how to compute the IGT timestamp.
 */
const FINISH_HIGHLIGHTS = new Set([
  "photo_finish",
  "sprint_final",
  "dominant",
  "early_exit",
  "comeback_kid",
]);

const ZONE_HIGHLIGHTS = new Set([
  "speed_demon",
  "zone_wall",
  "graveyard",
  "death_zone",
  "deathless",
  "hard_pass",
  "rage_inducer",
]);

const START_HIGHLIGHTS = new Set(["fast_starter"]);

/**
 * Map Phase 1 highlights to timeline events with IGT timestamps.
 *
 * Strategy:
 * - Finish-related highlights: placed at the latest involved player's totalIgt
 * - Zone-related highlights: placed at the midpoint of the relevant zone visit
 * - Start-related highlights: placed at the IGT when the player reaches layer 2
 * - Global/path highlights: placed at race midpoint
 */
export function mapHighlightsToTimeline(
  highlights: Highlight[],
  replayParticipants: ReplayParticipant[],
): CommentaryEvent[] {
  const rpMap = new Map(replayParticipants.map((rp) => [rp.id, rp]));
  const maxIgt = Math.max(...replayParticipants.map((rp) => rp.totalIgt), 0);
  if (maxIgt <= 0) return [];

  const events: CommentaryEvent[] = [];

  for (const h of highlights) {
    let igtMs: number;

    if (FINISH_HIGHLIGHTS.has(h.type)) {
      // Use latest involved player's finish time
      const finishTimes = h.playerIds
        .map((id) => rpMap.get(id)?.totalIgt ?? 0)
        .filter((t) => t > 0);
      igtMs = finishTimes.length > 0 ? Math.max(...finishTimes) : maxIgt;
    } else if (START_HIGHLIGHTS.has(h.type)) {
      // Use the earliest involved player's IGT for their second zone visit
      const startTimes = h.playerIds
        .map((id) => {
          const rp = rpMap.get(id);
          return rp && rp.zoneVisits.length > 1 ? rp.zoneVisits[1].enterIgt : 0;
        })
        .filter((t) => t > 0);
      igtMs = startTimes.length > 0 ? Math.min(...startTimes) : maxIgt * 0.1;
    } else if (ZONE_HIGHLIGHTS.has(h.type)) {
      // Find the zone mentioned in the highlight segments
      const zoneSegment = h.segments.find((s) => s.type === "zone");
      if (zoneSegment && zoneSegment.type === "zone") {
        // Find when the first involved player (or any player) was in that zone
        const zoneNodeId = zoneSegment.nodeId;
        let bestTime = maxIgt * 0.5;
        for (const rp of replayParticipants) {
          for (const visit of rp.zoneVisits) {
            if (visit.nodeId === zoneNodeId) {
              bestTime = visit.enterIgt + (visit.exitIgt - visit.enterIgt) / 2;
              break;
            }
          }
          if (bestTime !== maxIgt * 0.5) break;
        }
        igtMs = bestTime;
      } else {
        igtMs = maxIgt * 0.5;
      }
    } else {
      // Global/path highlights: midpoint
      igtMs = maxIgt / 2;
    }

    events.push({ igtMs, highlight: h });
  }

  // Sort by timestamp and space them out (min 5% gap in IGT)
  events.sort((a, b) => a.igtMs - b.igtMs);
  for (let i = 1; i < events.length; i++) {
    const minGap = maxIgt * 0.05;
    if (events[i].igtMs - events[i - 1].igtMs < minGap) {
      events[i].igtMs = events[i - 1].igtMs + minGap;
    }
  }

  return events;
}
