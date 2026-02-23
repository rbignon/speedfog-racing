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

interface NodeInfo {
  tier: number;
  layer: number;
  displayName: string;
  type: string;
}

function buildNodeInfo(
  graphJson: Record<string, unknown>,
): Map<string, NodeInfo> {
  const map = new Map<string, NodeInfo>();
  const nodes = (
    graphJson as { nodes: Record<string, Record<string, unknown>> }
  ).nodes;
  if (!nodes) return map;
  for (const [id, data] of Object.entries(nodes)) {
    map.set(id, {
      tier: (data.tier as number) ?? 1,
      layer: (data.layer as number) ?? 0,
      displayName: (data.display_name as string) ?? id,
      type: (data.type as string) ?? "mini_dungeon",
    });
  }
  return map;
}

function displayName(p: WsParticipant): string {
  return p.twitch_display_name || p.twitch_username;
}

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min >= 60) {
    const hr = Math.floor(min / 60);
    const rm = min % 60;
    return `${hr}:${String(rm).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }
  return `${min}:${String(sec).padStart(2, "0")}`;
}

function nodeName(nodeId: string, nodeInfo: Map<string, NodeInfo>): string {
  return nodeInfo.get(nodeId)?.displayName ?? nodeId;
}

// =============================================================================
// Detectors
// =============================================================================

/**
 * Speed Demon: player who cleared a zone much faster than average.
 * Looks at zones visited by 2+ players and finds the biggest speed ratio.
 */
function detectSpeedDemon(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  // Collect times per zone across all players
  const zonePlayerTimes = new Map<
    string,
    { playerId: string; timeMs: number }[]
  >();
  for (const [pid, zones] of allZoneTimes) {
    for (const zt of zones) {
      if (!zonePlayerTimes.has(zt.nodeId)) zonePlayerTimes.set(zt.nodeId, []);
      zonePlayerTimes
        .get(zt.nodeId)!
        .push({ playerId: pid, timeMs: zt.timeMs });
    }
  }

  let bestRatio = 0;
  let bestPlayerId = "";
  let bestZone = "";
  let bestTime = 0;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    // Skip start zones (tier 1, layer 0)
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    for (const t of times) {
      if (t.timeMs <= 0) continue;
      const ratio = avg / t.timeMs; // Higher = faster relative to avg
      const tierMult = info ? info.tier : 1;
      const score = ratio * tierMult;
      if (score > bestRatio) {
        bestRatio = score;
        bestPlayerId = t.playerId;
        bestZone = zoneId;
        bestTime = t.timeMs;
      }
    }
  }

  if (bestRatio < 1.5) return null; // Need at least 50% faster than average

  const p = participants.find((pp) => pp.id === bestPlayerId);
  if (!p) return null;

  return {
    type: "speed_demon",
    category: "speed",
    title: "Speed Demon",
    description: `${displayName(p)} blitzed through ${nodeName(bestZone, nodeInfo)} in ${formatTime(bestTime)}`,
    playerIds: [bestPlayerId],
    score: Math.min(100, bestRatio * 20),
  };
}

/**
 * Zone Wall: player who spent disproportionately long in a zone vs others.
 */
function detectZoneWall(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zonePlayerTimes = new Map<
    string,
    { playerId: string; timeMs: number }[]
  >();
  for (const [pid, zones] of allZoneTimes) {
    for (const zt of zones) {
      if (!zonePlayerTimes.has(zt.nodeId)) zonePlayerTimes.set(zt.nodeId, []);
      zonePlayerTimes
        .get(zt.nodeId)!
        .push({ playerId: pid, timeMs: zt.timeMs });
    }
  }

  let bestRatio = 0;
  let bestPlayerId = "";
  let bestZone = "";
  let bestTime = 0;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    for (const t of times) {
      const ratio = t.timeMs / avg; // Higher = slower relative to avg
      const tierMult = info ? info.tier : 1;
      const score = ratio * tierMult;
      if (score > bestRatio) {
        bestRatio = score;
        bestPlayerId = t.playerId;
        bestZone = zoneId;
        bestTime = t.timeMs;
      }
    }
  }

  if (bestRatio < 2.0) return null; // Need at least 2x slower than average

  const p = participants.find((pp) => pp.id === bestPlayerId);
  if (!p) return null;

  return {
    type: "zone_wall",
    category: "speed",
    title: "Zone Wall",
    description: `${nodeName(bestZone, nodeInfo)} was ${displayName(p)}'s nemesis — stuck for ${formatTime(bestTime)}`,
    playerIds: [bestPlayerId],
    score: Math.min(100, bestRatio * 15),
  };
}

/**
 * Fast Starter: player who reached layer 2 first.
 */
function detectFastStarter(
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  let fastestTime = Infinity;
  let fastestPlayer: WsParticipant | null = null;

  for (const p of participants) {
    if (!p.zone_history) continue;
    for (const entry of p.zone_history) {
      const info = nodeInfo.get(entry.node_id);
      if (info && info.layer >= 2) {
        if (entry.igt_ms < fastestTime) {
          fastestTime = entry.igt_ms;
          fastestPlayer = p;
        }
        break;
      }
    }
  }

  if (!fastestPlayer || fastestTime === Infinity) return null;

  return {
    type: "fast_starter",
    category: "speed",
    title: "Fast Starter",
    description: `${displayName(fastestPlayer)} was first to push past tier 1 at ${formatTime(fastestTime)}`,
    playerIds: [fastestPlayer.id],
    score: 40,
  };
}

/**
 * Sprint Final: fastest time in the last tier zones.
 */
function detectSprintFinal(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const maxTier = Math.max(...[...nodeInfo.values()].map((n) => n.tier), 0);
  if (maxTier <= 1) return null;

  let bestTime = Infinity;
  let bestPlayer: WsParticipant | null = null;

  for (const p of participants) {
    const zones = allZoneTimes.get(p.id);
    if (!zones) continue;

    let totalLastTier = 0;
    let hasLastTier = false;
    for (const zt of zones) {
      const info = nodeInfo.get(zt.nodeId);
      if (info && info.tier >= maxTier) {
        totalLastTier += zt.timeMs;
        hasLastTier = true;
      }
    }

    if (hasLastTier && totalLastTier < bestTime) {
      bestTime = totalLastTier;
      bestPlayer = p;
    }
  }

  if (!bestPlayer) return null;

  return {
    type: "sprint_final",
    category: "speed",
    title: "Sprint Final",
    description: `${displayName(bestPlayer)} raced through the final tier in just ${formatTime(bestTime)}`,
    playerIds: [bestPlayer.id],
    score: 55,
  };
}

/**
 * Graveyard: zone with the most cumulative deaths across all players.
 */
function detectGraveyard(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zoneDeaths = new Map<string, number>();
  for (const [, zones] of allZoneTimes) {
    for (const zt of zones) {
      zoneDeaths.set(zt.nodeId, (zoneDeaths.get(zt.nodeId) ?? 0) + zt.deaths);
    }
  }

  let maxDeaths = 0;
  let maxZone = "";
  for (const [zoneId, deaths] of zoneDeaths) {
    if (deaths > maxDeaths) {
      maxDeaths = deaths;
      maxZone = zoneId;
    }
  }

  if (maxDeaths < 3) return null; // Need at least 3 total deaths

  return {
    type: "graveyard",
    category: "deaths",
    title: "Graveyard",
    description: `${nodeName(maxZone, nodeInfo)} claimed ${maxDeaths} deaths across all racers`,
    playerIds: [],
    score: Math.min(100, maxDeaths * 8),
  };
}

/**
 * Death Zone: most deaths by a single player in one zone.
 */
function detectDeathZone(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  let maxDeaths = 0;
  let maxPlayerId = "";
  let maxZone = "";

  for (const [pid, zones] of allZoneTimes) {
    for (const zt of zones) {
      if (zt.deaths > maxDeaths) {
        maxDeaths = zt.deaths;
        maxPlayerId = pid;
        maxZone = zt.nodeId;
      }
    }
  }

  if (maxDeaths < 3) return null;

  const p = participants.find((pp) => pp.id === maxPlayerId);
  if (!p) return null;

  return {
    type: "death_zone",
    category: "deaths",
    title: "Death Zone",
    description: `${displayName(p)} died ${maxDeaths} times in ${nodeName(maxZone, nodeInfo)}`,
    playerIds: [maxPlayerId],
    score: Math.min(100, maxDeaths * 10),
  };
}

/**
 * Deathless: player with 0 deaths in a tier 3+ zone.
 */
function detectDeathless(
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  for (const p of participants) {
    const zones = allZoneTimes.get(p.id);
    if (!zones) continue;

    const highTierZones = zones.filter((zt) => {
      const info = nodeInfo.get(zt.nodeId);
      return info && info.tier >= 3;
    });

    if (
      highTierZones.length > 0 &&
      highTierZones.every((zt) => zt.deaths === 0)
    ) {
      return {
        type: "deathless",
        category: "deaths",
        title: "Deathless",
        description: `${displayName(p)} cleared all high-tier zones without dying`,
        playerIds: [p.id],
        score: 70,
      };
    }
  }

  return null;
}

/**
 * Comeback Kid: player with the most deaths who still finished well.
 */
function detectComebackKid(participants: WsParticipant[]): Highlight | null {
  const finishers = participants
    .filter((p) => p.status === "finished")
    .sort((a, b) => a.igt_ms - b.igt_ms);

  if (finishers.length < 2) return null;

  // Find player with most deaths among finishers who finished in top half
  const topHalf = finishers.slice(0, Math.ceil(finishers.length / 2));
  let maxDeaths = 0;
  let maxPlayer: WsParticipant | null = null;

  for (const p of topHalf) {
    if (p.death_count > maxDeaths) {
      maxDeaths = p.death_count;
      maxPlayer = p;
    }
  }

  if (!maxPlayer || maxDeaths < 5) return null;

  const rank = finishers.indexOf(maxPlayer) + 1;
  const suffix =
    rank === 1 ? "st" : rank === 2 ? "nd" : rank === 3 ? "rd" : "th";

  return {
    type: "comeback_kid",
    category: "deaths",
    title: "Comeback Kid",
    description: `${displayName(maxPlayer)} died ${maxDeaths} times but still finished ${rank}${suffix}`,
    playerIds: [maxPlayer.id],
    score: Math.min(100, maxDeaths * 5 + (finishers.length - rank) * 10),
  };
}

/**
 * Road Less Traveled: player with the most unique path (fewest nodes in common with others).
 */
function detectRoadLessTraveled(
  participants: WsParticipant[],
): Highlight | null {
  if (participants.length < 3) return null;

  const paths = participants.map((p) => ({
    player: p,
    nodes: new Set(p.zone_history?.map((z) => z.node_id) ?? []),
  }));

  let bestUniqueness = 0;
  let bestPlayer: WsParticipant | null = null;

  for (let i = 0; i < paths.length; i++) {
    const myNodes = paths[i].nodes;
    if (myNodes.size < 2) continue;

    // Average overlap with other players
    let totalOverlap = 0;
    for (let j = 0; j < paths.length; j++) {
      if (i === j) continue;
      let shared = 0;
      for (const n of myNodes) {
        if (paths[j].nodes.has(n)) shared++;
      }
      totalOverlap += shared / myNodes.size;
    }
    const avgOverlap = totalOverlap / (paths.length - 1);
    const uniqueness = 1 - avgOverlap;

    if (uniqueness > bestUniqueness) {
      bestUniqueness = uniqueness;
      bestPlayer = paths[i].player;
    }
  }

  if (!bestPlayer || bestUniqueness < 0.3) return null;

  return {
    type: "road_less_traveled",
    category: "path",
    title: "Road Less Traveled",
    description: `${displayName(bestPlayer)} forged a unique path through the fog`,
    playerIds: [bestPlayer.id],
    score: Math.min(100, bestUniqueness * 80),
  };
}

/**
 * Same Brain: two players with identical zone path.
 */
function detectSameBrain(participants: WsParticipant[]): Highlight | null {
  for (let i = 0; i < participants.length; i++) {
    const pathA = participants[i].zone_history?.map((z) => z.node_id);
    if (!pathA || pathA.length < 2) continue;
    const keyA = pathA.join(",");

    for (let j = i + 1; j < participants.length; j++) {
      const pathB = participants[j].zone_history?.map((z) => z.node_id);
      if (!pathB) continue;
      if (pathB.join(",") === keyA) {
        return {
          type: "same_brain",
          category: "path",
          title: "Same Brain",
          description: `${displayName(participants[i])} and ${displayName(participants[j])} took the exact same path`,
          playerIds: [participants[i].id, participants[j].id],
          score: 65,
        };
      }
    }
  }

  return null;
}

/**
 * Detour: player who visited the most nodes.
 */
function detectDetour(participants: WsParticipant[]): Highlight | null {
  let maxNodes = 0;
  let maxPlayer: WsParticipant | null = null;
  let avgNodes = 0;

  for (const p of participants) {
    const count = p.zone_history?.length ?? 0;
    avgNodes += count;
    if (count > maxNodes) {
      maxNodes = count;
      maxPlayer = p;
    }
  }

  avgNodes /= participants.length;

  if (!maxPlayer || maxNodes <= avgNodes * 1.3 || maxNodes < 4) return null;

  return {
    type: "detour",
    category: "path",
    title: "Scenic Route",
    description: `${displayName(maxPlayer)} explored ${maxNodes} zones — more than anyone else`,
    playerIds: [maxPlayer.id],
    score: Math.min(100, (maxNodes / avgNodes) * 30),
  };
}

/**
 * Photo Finish: closest IGT gap between consecutive finishers.
 */
function detectPhotoFinish(participants: WsParticipant[]): Highlight | null {
  const finishers = participants
    .filter((p) => p.status === "finished")
    .sort((a, b) => a.igt_ms - b.igt_ms);

  if (finishers.length < 2) return null;

  let minGap = Infinity;
  let player1: WsParticipant | null = null;
  let player2: WsParticipant | null = null;

  for (let i = 0; i < finishers.length - 1; i++) {
    const gap = finishers[i + 1].igt_ms - finishers[i].igt_ms;
    if (gap < minGap) {
      minGap = gap;
      player1 = finishers[i];
      player2 = finishers[i + 1];
    }
  }

  if (!player1 || !player2 || minGap > 30000) return null; // Must be within 30s

  return {
    type: "photo_finish",
    category: "competitive",
    title: "Photo Finish",
    description: `${displayName(player1)} and ${displayName(player2)} finished just ${formatTime(minGap)} apart`,
    playerIds: [player1.id, player2.id],
    score: Math.min(100, (30000 / Math.max(minGap, 1000)) * 20),
  };
}

/**
 * Lead Changes: counts how many times the leader changed across layers.
 */
function detectLeadChanges(
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const maxLayer = Math.max(...[...nodeInfo.values()].map((n) => n.layer), 0);
  if (maxLayer < 2) return null;

  // For each layer, find who arrived at that layer first
  const leaders: string[] = [];
  for (let layer = 1; layer <= maxLayer; layer++) {
    let earliest = Infinity;
    let leaderId = "";
    for (const p of participants) {
      if (!p.zone_history) continue;
      for (const entry of p.zone_history) {
        const info = nodeInfo.get(entry.node_id);
        if (info && info.layer >= layer && entry.igt_ms < earliest) {
          earliest = entry.igt_ms;
          leaderId = p.id;
          break;
        }
      }
    }
    if (leaderId) leaders.push(leaderId);
  }

  let changes = 0;
  for (let i = 1; i < leaders.length; i++) {
    if (leaders[i] !== leaders[i - 1]) changes++;
  }

  if (changes < 2) return null;

  return {
    type: "lead_changes",
    category: "competitive",
    title: "Back and Forth",
    description: `The lead changed ${changes} times throughout the race`,
    playerIds: [...new Set(leaders)],
    score: Math.min(100, changes * 25),
  };
}

/**
 * Dominant: player who led at every layer checkpoint.
 */
function detectDominant(
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const maxLayer = Math.max(...[...nodeInfo.values()].map((n) => n.layer), 0);
  if (maxLayer < 2) return null;

  const leaders: string[] = [];
  for (let layer = 1; layer <= maxLayer; layer++) {
    let earliest = Infinity;
    let leaderId = "";
    for (const p of participants) {
      if (!p.zone_history) continue;
      for (const entry of p.zone_history) {
        const info = nodeInfo.get(entry.node_id);
        if (info && info.layer >= layer && entry.igt_ms < earliest) {
          earliest = entry.igt_ms;
          leaderId = p.id;
          break;
        }
      }
    }
    if (leaderId) leaders.push(leaderId);
  }

  const uniqueLeaders = new Set(leaders);
  if (uniqueLeaders.size !== 1 || leaders.length < 2) return null;

  const dominantId = leaders[0];
  const p = participants.find((pp) => pp.id === dominantId);
  if (!p) return null;

  return {
    type: "dominant",
    category: "competitive",
    title: "Dominant",
    description: `${displayName(p)} led from start to finish`,
    playerIds: [dominantId],
    score: 60,
  };
}

// =============================================================================
// Orchestrator
// =============================================================================

export function computeHighlights(
  participants: WsParticipant[],
  graphJson: Record<string, unknown>,
): Highlight[] {
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );
  if (eligible.length < 2) return [];

  const nodeInfo = buildNodeInfo(graphJson);
  const allZoneTimes = new Map(
    eligible.map((p) => [p.id, computeZoneTimes(p)]),
  );

  const candidates: Highlight[] = [];
  const push = (h: Highlight | null) => {
    if (h) candidates.push(h);
  };

  push(detectSpeedDemon(eligible, allZoneTimes, nodeInfo));
  push(detectZoneWall(eligible, allZoneTimes, nodeInfo));
  push(detectFastStarter(eligible, nodeInfo));
  push(detectSprintFinal(eligible, allZoneTimes, nodeInfo));
  push(detectGraveyard(eligible, allZoneTimes, nodeInfo));
  push(detectDeathZone(eligible, allZoneTimes, nodeInfo));
  push(detectDeathless(eligible, allZoneTimes, nodeInfo));
  push(detectComebackKid(eligible));
  push(detectRoadLessTraveled(eligible));
  push(detectSameBrain(eligible));
  push(detectDetour(eligible));
  push(detectPhotoFinish(eligible));
  push(detectLeadChanges(eligible, nodeInfo));
  push(detectDominant(eligible, nodeInfo));

  // Sort by score descending
  candidates.sort((a, b) => b.score - a.score);

  // Diversity filter: max 2 per category
  const categoryCounts = new Map<string, number>();
  const selected: Highlight[] = [];
  for (const h of candidates) {
    const count = categoryCounts.get(h.category) ?? 0;
    if (count >= 2) continue;
    categoryCounts.set(h.category, count + 1);
    selected.push(h);
    if (selected.length >= 6) break;
  }

  return selected;
}
