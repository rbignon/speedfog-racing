/**
 * Personal highlights computation.
 *
 * Pure functions that compute player-specific highlights from
 * zone_history data and graph_json topology. Uses direct tone ("You...").
 */

import type { WsParticipant } from "$lib/websocket";
import {
  type Highlight,
  type DescriptionSegment,
  type ZoneTime,
  type NodeInfo,
  computeZoneTimes,
  buildNodeInfo,
  pSeg,
  zSeg,
  tSeg,
  formatTime,
  uniqueNodePath,
  buildZonePlayerTimes,
} from "$lib/highlights";

// =============================================================================
// Types
// =============================================================================

type PersonalHighlightCategory = "combat" | "pathing" | "competitive";

// =============================================================================
// Helpers
// =============================================================================

/** Flatten segments into a plain description string (for tests). */
export function descriptionText(h: Highlight): string {
  return h.segments.map((s) => (s.type === "text" ? s.value : s.name)).join("");
}

/**
 * Build a map of zoneId -> list of { playerId, deaths } for boss nodes.
 */
function buildBossDeaths(
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Map<string, { playerId: string; deaths: number }[]> {
  const map = new Map<string, { playerId: string; deaths: number }[]>();
  for (const [pid, zones] of allZoneTimes) {
    for (const zt of zones) {
      const info = nodeInfo.get(zt.nodeId);
      if (!info || (info.type !== "boss" && info.type !== "final_boss"))
        continue;
      if (!map.has(zt.nodeId)) map.set(zt.nodeId, []);
      map.get(zt.nodeId)!.push({ playerId: pid, deaths: zt.deaths });
    }
  }
  return map;
}

// =============================================================================
// Combat Detectors
// =============================================================================

function detectBossSlayer(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const bossDeaths = buildBossDeaths(allZoneTimes, nodeInfo);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [bossId, entries] of bossDeaths) {
    if (entries.length < 2) continue;
    const myEntry = entries.find((e) => e.playerId === myId);
    if (!myEntry) continue;

    const othersDeaths = entries.filter((e) => e.playerId !== myId);
    const avgDeaths =
      othersDeaths.reduce((s, e) => s + e.deaths, 0) / othersDeaths.length;
    if (avgDeaths <= 0) continue;

    const ratio = myEntry.deaths / avgDeaths;
    if (ratio >= 0.5) continue;

    const info = nodeInfo.get(bossId);
    const tierMult = info?.tier ?? 1;
    const score = (1 - ratio) * 100 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "boss_slayer",
        category: "combat" as PersonalHighlightCategory,
        title: "Boss Slayer",
        segments: [
          tSeg(
            `You only died ${myEntry.deaths} time${myEntry.deaths !== 1 ? "s" : ""} on `,
          ),
          zSeg(bossId, nodeInfo),
          tSeg(` (average: ${Math.round(avgDeaths)})`),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectBossWall(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const bossDeaths = buildBossDeaths(allZoneTimes, nodeInfo);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [bossId, entries] of bossDeaths) {
    if (entries.length < 2) continue;
    const myEntry = entries.find((e) => e.playerId === myId);
    if (!myEntry || myEntry.deaths === 0) continue;

    const othersDeaths = entries.filter((e) => e.playerId !== myId);
    const avgDeaths =
      othersDeaths.reduce((s, e) => s + e.deaths, 0) / othersDeaths.length;
    if (avgDeaths <= 0) continue;

    const ratio = myEntry.deaths / avgDeaths;
    if (ratio <= 2) continue;

    const score = ratio * 40;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "boss_wall",
        category: "combat" as PersonalHighlightCategory,
        title: "Boss Wall",
        segments: [
          zSeg(bossId, nodeInfo),
          tSeg(
            ` gave you trouble: ${myEntry.deaths} deaths (average: ${Math.round(avgDeaths)})`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectStoodYourGround(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const myZt of myZones) {
    if (myZt.outcome !== "cleared") continue;

    let backedCount = 0;
    for (const [pid, zones] of allZoneTimes) {
      if (pid === myId) continue;
      const theirZt = zones.find((z) => z.nodeId === myZt.nodeId);
      if (theirZt && theirZt.outcome === "backed") backedCount++;
    }

    if (backedCount === 0) continue;

    const info = nodeInfo.get(myZt.nodeId);
    const tierMult = info?.tier ?? 1;
    const score = backedCount * 35 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "stood_your_ground",
        category: "combat" as PersonalHighlightCategory,
        title: "Stood Your Ground",
        segments: [
          tSeg("You're the only one who didn't turn back from "),
          zSeg(myZt.nodeId, nodeInfo),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectDeathSpiral(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const zt of myZones) {
    if (zt.outcome !== "cleared" || zt.deaths < 5) continue;

    const info = nodeInfo.get(zt.nodeId);
    const tierMult = info?.tier ?? 1;
    const score = zt.deaths * 15 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "death_spiral",
        category: "combat" as PersonalHighlightCategory,
        title: "Death Spiral",
        segments: [
          tSeg(`You left ${zt.deaths} lives on `),
          zSeg(zt.nodeId, nodeInfo),
          tSeg(" before finally pushing through"),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectCleanStreak(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  // Find longest consecutive streak of 0-death zones
  let bestStart = 0;
  let bestLen = 0;
  let curStart = 0;
  let curLen = 0;

  for (let i = 0; i < myZones.length; i++) {
    if (myZones[i].deaths === 0) {
      if (curLen === 0) curStart = i;
      curLen++;
      if (curLen > bestLen) {
        bestLen = curLen;
        bestStart = curStart;
      }
    } else {
      curLen = 0;
    }
  }

  if (bestLen < 3) return null;

  // Count others' total deaths across those same zones
  const streakZoneIds = myZones
    .slice(bestStart, bestStart + bestLen)
    .map((z) => z.nodeId);
  let othersDeaths = 0;
  for (const [pid, zones] of allZoneTimes) {
    if (pid === myId) continue;
    for (const zt of zones) {
      if (streakZoneIds.includes(zt.nodeId)) othersDeaths += zt.deaths;
    }
  }

  if (othersDeaths === 0) return null;

  const score = bestLen * 25 + othersDeaths * 5;

  return {
    type: "clean_streak",
    category: "combat" as PersonalHighlightCategory,
    title: "Clean Streak",
    segments: [
      tSeg(
        `You cleared ${bestLen} zones in a row without dying, while others lost ${othersDeaths} lives there`,
      ),
    ],
    playerIds: [myId],
    score,
  };
}

// =============================================================================
// Orchestrator (partial - combat only for now)
// =============================================================================

export function computePersonalHighlights(
  myParticipantId: string,
  participants: WsParticipant[],
  graphJson: Record<string, unknown>,
): Highlight[] {
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );
  if (eligible.length < 2) return [];
  if (!eligible.find((p) => p.id === myParticipantId)) return [];

  const nodeInfo = buildNodeInfo(graphJson);
  const allZoneTimes = new Map(
    eligible.map((p) => [p.id, computeZoneTimes(p, nodeInfo)]),
  );

  const candidates: Highlight[] = [];
  const push = (h: Highlight | null) => {
    if (h) candidates.push(h);
  };

  // Combat detectors
  push(detectBossSlayer(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(detectBossWall(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(
    detectStoodYourGround(myParticipantId, eligible, allZoneTimes, nodeInfo),
  );
  push(detectDeathSpiral(myParticipantId, allZoneTimes, nodeInfo));
  push(detectCleanStreak(myParticipantId, eligible, allZoneTimes, nodeInfo));

  // Selection
  candidates.sort((a, b) => b.score - a.score);

  const categoryCounts = new Map<string, number>();
  const usedZones = new Set<string>();
  const selected: Highlight[] = [];
  for (const h of candidates) {
    const count = categoryCounts.get(h.category) ?? 0;
    if (count >= 2) continue;
    const zones = h.segments
      .filter(
        (s): s is Extract<DescriptionSegment, { type: "zone" }> =>
          s.type === "zone",
      )
      .map((s) => s.nodeId);
    if (zones.length > 0 && zones.some((z) => usedZones.has(z))) continue;
    categoryCounts.set(h.category, count + 1);
    zones.forEach((z) => usedZones.add(z));
    selected.push(h);
    if (selected.length >= 6) break;
  }

  return selected;
}
