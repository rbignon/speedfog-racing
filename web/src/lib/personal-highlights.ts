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
    if (avgDeaths < 1) continue;

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
        segments:
          myEntry.deaths === 0
            ? [
                tSeg("You cleared "),
                zSeg(bossId, nodeInfo),
                tSeg(` deathless (average: ${Math.round(avgDeaths)} deaths)`),
              ]
            : [
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

    // Spec says ratio * 30, bumped to 40 so boss_wall wins over
    // death_spiral on the same zone via zone-reuse filtering.
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
    let otherClearedCount = 0;
    for (const [pid, zones] of allZoneTimes) {
      if (pid === myId) continue;
      const theirZt = zones.find((z) => z.nodeId === myZt.nodeId);
      if (theirZt && theirZt.outcome === "backed") backedCount++;
      else if (theirZt && theirZt.outcome === "cleared") otherClearedCount++;
    }

    // Only fire if ALL others who visited this zone backed out
    if (backedCount === 0 || otherClearedCount > 0) continue;

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

  const firstZoneId = streakZoneIds[0];
  const lastZoneId = streakZoneIds[streakZoneIds.length - 1];

  return {
    type: "clean_streak",
    category: "combat" as PersonalHighlightCategory,
    title: "Clean Streak",
    segments: [
      tSeg(`You cleared ${bestLen} zones in a row without dying, from `),
      zSeg(firstZoneId, nodeInfo),
      tSeg(" to "),
      zSeg(lastZoneId, nodeInfo),
      tSeg(`, while others lost ${othersDeaths} lives there`),
    ],
    playerIds: [myId],
    score,
  };
}

/**
 * Compute each player's rank (1-based) at each layer.
 * Rank is determined by earliest IGT to reach that layer.
 * Returns Map<layer, Map<participantId, rank>>.
 */
function computeRanksPerLayer(
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Map<number, Map<string, number>> {
  const maxLayer = Math.max(...[...nodeInfo.values()].map((n) => n.layer), 0);
  const ranks = new Map<number, Map<string, number>>();

  for (let layer = 1; layer <= maxLayer; layer++) {
    const arrivals: { id: string; igt: number }[] = [];
    for (const p of participants) {
      if (!p.zone_history) continue;
      for (const entry of p.zone_history) {
        const info = nodeInfo.get(entry.node_id);
        if (info && info.layer >= layer) {
          arrivals.push({ id: p.id, igt: entry.igt_ms });
          break;
        }
      }
    }
    arrivals.sort((a, b) => a.igt - b.igt);
    const layerRanks = new Map<string, number>();
    arrivals.forEach((a, i) => layerRanks.set(a.id, i + 1));
    ranks.set(layer, layerRanks);
  }

  return ranks;
}

/** Find the first zone a player reaches at a given layer. */
function firstZoneAtLayer(
  participant: WsParticipant,
  layer: number,
  nodeInfo: Map<string, NodeInfo>,
): string | null {
  if (!participant.zone_history) return null;
  for (const entry of participant.zone_history) {
    const info = nodeInfo.get(entry.node_id);
    if (info && info.layer === layer) return entry.node_id;
  }
  return null;
}

/** Format number as ordinal: 1 -> "1st", 2 -> "2nd", etc. */
function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// =============================================================================
// Pathing Detectors
// =============================================================================

function detectLoneExplorer(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  const othersZoneIds = new Set<string>();
  for (const [pid, zones] of allZoneTimes) {
    if (pid === myId) continue;
    for (const zt of zones) othersZoneIds.add(zt.nodeId);
  }

  // Pick the solo zone with the highest tier (ties broken by first-visit order)
  let bestTier = -1;
  let bestZoneId: string | null = null;

  for (const zt of myZones) {
    if (othersZoneIds.has(zt.nodeId)) continue;
    const tier = nodeInfo.get(zt.nodeId)?.tier ?? 1;
    if (tier > bestTier) {
      bestTier = tier;
      bestZoneId = zt.nodeId;
    }
  }

  if (!bestZoneId) return null;

  return {
    type: "lone_explorer",
    category: "pathing" as PersonalHighlightCategory,
    title: "Lone Explorer",
    segments: [
      tSeg("You're the only one who visited "),
      zSeg(bestZoneId, nodeInfo),
    ],
    playerIds: [myId],
    score: participants.length * 20,
  };
}

/**
 * Build a map of parentId -> [childId, ...] from graph_json edges.
 */
function buildChildrenMap(
  graphJson: Record<string, unknown>,
): Map<string, string[]> {
  const edges = (graphJson as { edges: { from: string; to: string }[] }).edges;
  const map = new Map<string, string[]>();
  if (!edges) return map;
  for (const e of edges) {
    if (!map.has(e.from)) map.set(e.from, []);
    map.get(e.from)!.push(e.to);
  }
  return map;
}

function detectAgainstTheFlow(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
  graphJson: Record<string, unknown>,
): Highlight | null {
  const childrenMap = buildChildrenMap(graphJson);
  const eligible = participants.filter(
    (p) => p.zone_history && p.zone_history.length > 0,
  );

  // For each player, build their unique node path
  const playerPaths = new Map<string, string[]>();
  for (const p of eligible) {
    playerPaths.set(p.id, uniqueNodePath(p.zone_history!));
  }

  const myPath = playerPaths.get(myId);
  if (!myPath) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (let i = 0; i < myPath.length; i++) {
    const forkNode = myPath[i];
    const children = childrenMap.get(forkNode);
    if (!children || children.length < 2) continue;

    // Find my first child after this fork
    const myNextInPath = myPath[i + 1];
    if (!myNextInPath || !children.includes(myNextInPath)) continue;

    // Check what branches others took
    let othersOnDifferentBranch = 0;
    let anyoneOnMyBranch = false;

    for (const [pid, path] of playerPaths) {
      if (pid === myId) continue;
      const forkIdx = path.indexOf(forkNode);
      if (forkIdx < 0 || forkIdx >= path.length - 1) continue;
      const theirNext = path[forkIdx + 1];
      if (!children.includes(theirNext)) continue;
      if (theirNext === myNextInPath) {
        anyoneOnMyBranch = true;
      } else {
        othersOnDifferentBranch++;
      }
    }

    if (anyoneOnMyBranch || othersOnDifferentBranch === 0) continue;

    const score = othersOnDifferentBranch * 30;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "against_the_flow",
        category: "pathing" as PersonalHighlightCategory,
        title: "Against the Flow",
        segments: [
          tSeg("At the "),
          zSeg(forkNode, nodeInfo),
          tSeg(" crossroads, you headed towards "),
          zSeg(myNextInPath, nodeInfo),
          tSeg(" where no one else went"),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectSmartBacktrack(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  const me = participants.find((p) => p.id === myId);
  if (!me?.zone_history) return null;

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const myZt of myZones) {
    if (myZt.outcome !== "backed") continue;

    const backedInfo = nodeInfo.get(myZt.nodeId);
    if (!backedInfo) continue;
    const backedLayer = backedInfo.layer;

    // Find the last visit to this zone in raw zone_history (matches aggregated outcome)
    let entryIdx = -1;
    for (let i = me.zone_history.length - 1; i >= 0; i--) {
      if (me.zone_history[i].node_id === myZt.nodeId) {
        entryIdx = i;
        break;
      }
    }
    if (entryIdx < 0) continue;

    // Find the alternative zone: next zone at same or higher layer that was cleared
    let altZoneId: string | null = null;
    for (let i = entryIdx + 1; i < me.zone_history.length; i++) {
      const entryNodeId = me.zone_history[i].node_id;
      const info = nodeInfo.get(entryNodeId);
      if (!info || info.layer < backedLayer) continue;
      const zt = myZones.find((z) => z.nodeId === entryNodeId);
      if (zt && zt.outcome === "cleared") {
        altZoneId = entryNodeId;
        break;
      }
    }
    if (!altZoneId) continue;

    const altZone = myZones.find((z) => z.nodeId === altZoneId)!;

    // My cost: time wasted in backed zone + time in alternative zone
    const myCost = myZt.timeMs + altZone.timeMs;

    // Others who cleared the backed zone
    const othersClearTimes: number[] = [];
    for (const [pid, zones] of allZoneTimes) {
      if (pid === myId) continue;
      const theirZt = zones.find((z) => z.nodeId === myZt.nodeId);
      if (theirZt && theirZt.outcome === "cleared") {
        othersClearTimes.push(theirZt.timeMs);
      }
    }

    if (othersClearTimes.length === 0) continue;

    const avgClearTime =
      othersClearTimes.reduce((s, t) => s + t, 0) / othersClearTimes.length;
    const timeSavedMs = avgClearTime - myCost;
    if (timeSavedMs <= 0) continue;

    const score = (timeSavedMs / 1000) * 2;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "smart_backtrack",
        category: "pathing" as PersonalHighlightCategory,
        title: "Smart Backtrack",
        segments: [
          tSeg("Good call turning back from "),
          zSeg(myZt.nodeId, nodeInfo),
          tSeg(": going to "),
          zSeg(altZoneId, nodeInfo),
          tSeg(
            ` instead saved you ${formatTime(timeSavedMs)} compared to those who stayed`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectCostlyDetour(
  myId: string,
  participants: WsParticipant[],
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const myZones = allZoneTimes.get(myId);
  if (!myZones) return null;

  const me = participants.find((p) => p.id === myId);
  if (!me?.zone_history) return null;

  const betterFinishers = participants.filter(
    (p) =>
      p.id !== myId &&
      p.status === "finished" &&
      p.igt_ms < (me.igt_ms || Infinity),
  );
  if (betterFinishers.length === 0) return null;

  const betterZoneIds = new Set<string>();
  for (const p of betterFinishers) {
    const zones = allZoneTimes.get(p.id);
    if (zones) {
      for (const zt of zones) betterZoneIds.add(zt.nodeId);
    }
  }

  // Build nodeId -> ZoneTime map for quick lookup
  const myZoneMap = new Map<string, ZoneTime>();
  for (const zt of myZones) {
    myZoneMap.set(zt.nodeId, zt);
  }

  // Walk unique path, group contiguous zones not visited by better finishers
  // into branches. A multi-zone branch means the player was committed to a
  // path after a fork, so individual zones downstream weren't choices.
  const path = uniqueNodePath(me.zone_history);

  interface Branch {
    zones: ZoneTime[];
    totalTimeMs: number;
    costliestZone: ZoneTime;
  }

  const branches: Branch[] = [];
  let curZones: ZoneTime[] = [];
  let curTime = 0;
  let curCostliest: ZoneTime | null = null;

  const flushBranch = () => {
    if (curZones.length > 0 && curCostliest) {
      branches.push({
        zones: [...curZones],
        totalTimeMs: curTime,
        costliestZone: curCostliest,
      });
    }
    curZones = [];
    curTime = 0;
    curCostliest = null;
  };

  for (const nodeId of path) {
    if (betterZoneIds.has(nodeId)) {
      flushBranch();
    } else {
      const zt = myZoneMap.get(nodeId);
      if (zt && zt.timeMs > 0) {
        curZones.push(zt);
        curTime += zt.timeMs;
        if (!curCostliest || zt.timeMs > curCostliest.timeMs) {
          curCostliest = zt;
        }
      }
    }
  }
  flushBranch();

  if (branches.length === 0) return null;

  // Pick costliest branch
  branches.sort((a, b) => b.totalTimeMs - a.totalTimeMs);
  const best = branches[0];

  const score = (best.totalTimeMs / 1000) * 1.5;

  if (best.zones.length === 1) {
    return {
      type: "costly_detour",
      category: "pathing" as PersonalHighlightCategory,
      title: "Costly Detour",
      segments: [
        tSeg("Your detour through "),
        zSeg(best.costliestZone.nodeId, nodeInfo),
        tSeg(
          ` cost you ${formatTime(best.totalTimeMs)} compared to those who skipped it`,
        ),
      ],
      playerIds: [myId],
      score,
    };
  }

  // Multi-zone branch: the individual zone wasn't a choice, the branch was
  return {
    type: "costly_detour",
    category: "pathing" as PersonalHighlightCategory,
    title: "Costly Detour",
    segments: [
      tSeg("Your path from "),
      zSeg(best.zones[0].nodeId, nodeInfo),
      tSeg(" to "),
      zSeg(best.zones[best.zones.length - 1].nodeId, nodeInfo),
      tSeg(
        ` cost you ${formatTime(best.totalTimeMs)} compared to those who took a different route`,
      ),
    ],
    playerIds: [myId],
    score,
  };
}

// =============================================================================
// Competitive Detectors
// =============================================================================

function detectFasterThanAll(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zonePlayerTimes = buildZonePlayerTimes(allZoneTimes, true);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const myTime = times.find((t) => t.playerId === myId);
    if (!myTime || myTime.timeMs <= 0) continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    const ratio = myTime.timeMs / avg;
    if (ratio >= 0.6) continue;

    // Check we're actually the fastest
    const isFastest = times.every(
      (t) => t.playerId === myId || t.timeMs >= myTime.timeMs,
    );
    if (!isFastest) continue;

    const tierMult = info?.tier ?? 1;
    const score = (1 - ratio) * 100 * tierMult;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "faster_than_all",
        category: "competitive" as PersonalHighlightCategory,
        title: "Fastest Through",
        segments: [
          tSeg("You were the fastest through "),
          zSeg(zoneId, nodeInfo),
          tSeg(`: ${formatTime(myTime.timeMs)} (average: ${formatTime(avg)})`),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectSlowerThanAll(
  myId: string,
  allZoneTimes: Map<string, ZoneTime[]>,
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const zonePlayerTimes = buildZonePlayerTimes(allZoneTimes, true);

  let bestScore = 0;
  let bestHighlight: Highlight | null = null;

  for (const [zoneId, times] of zonePlayerTimes) {
    if (times.length < 2) continue;
    const info = nodeInfo.get(zoneId);
    if (info?.type === "start") continue;

    const myTime = times.find((t) => t.playerId === myId);
    if (!myTime || myTime.timeMs <= 0) continue;

    const avg = times.reduce((s, t) => s + t.timeMs, 0) / times.length;
    if (avg <= 0) continue;

    const ratio = myTime.timeMs / avg;
    if (ratio <= 1.5) continue;

    // Check we're actually the slowest
    const isSlowest = times.every(
      (t) => t.playerId === myId || t.timeMs <= myTime.timeMs,
    );
    if (!isSlowest) continue;

    const score = (ratio - 1) * 50;

    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "slower_than_all",
        category: "competitive" as PersonalHighlightCategory,
        title: "Rough Zone",
        segments: [
          zSeg(zoneId, nodeInfo),
          tSeg(
            ` slowed you down: last with ${formatTime(myTime.timeMs)} (average: ${formatTime(avg)})`,
          ),
        ],
        playerIds: [myId],
        score,
      };
    }
  }

  return bestHighlight;
}

function detectLeadLost(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  for (let i = 0; i < layers.length - 1; i++) {
    const curRanks = ranks.get(layers[i]);
    const nextRanks = ranks.get(layers[i + 1]);
    if (!curRanks || !nextRanks) continue;

    const myRankNow = curRanks.get(myId);
    const myRankNext = nextRanks.get(myId);

    if (
      myRankNow === 1 &&
      myRankNext !== undefined &&
      myRankNext > 1 &&
      layers[i] >= 2
    ) {
      const me = participants.find((p) => p.id === myId);
      const zoneId = me ? firstZoneAtLayer(me, layers[i + 1], nodeInfo) : null;
      const segments: DescriptionSegment[] = zoneId
        ? [
            tSeg("You were leading the race, but lost the lead at "),
            zSeg(zoneId, nodeInfo),
            tSeg(` (layer ${layers[i + 1]})`),
          ]
        : [
            tSeg(
              `You were leading the race, but lost the lead at layer ${layers[i + 1]}`,
            ),
          ];
      return {
        type: "lead_lost",
        category: "competitive" as PersonalHighlightCategory,
        title: "Lead Lost",
        segments,
        playerIds: [myId],
        score: 60,
      };
    }
  }

  return null;
}

function detectComeback(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  let bestGain = 0;
  let bestHighlight: Highlight | null = null;

  for (let i = 0; i < layers.length - 1; i++) {
    const curRanks = ranks.get(layers[i]);
    const nextRanks = ranks.get(layers[i + 1]);
    if (!curRanks || !nextRanks) continue;

    const rankBefore = curRanks.get(myId);
    const rankAfter = nextRanks.get(myId);
    if (rankBefore === undefined || rankAfter === undefined) continue;

    const gain = rankBefore - rankAfter;
    if (gain >= 2 && gain > bestGain) {
      bestGain = gain;
      const me = participants.find((p) => p.id === myId);
      const zoneId = me ? firstZoneAtLayer(me, layers[i + 1], nodeInfo) : null;
      const segments: DescriptionSegment[] = zoneId
        ? [
            tSeg(
              `You were ${ordinal(rankBefore)} at layer ${layers[i]}, then climbed back to ${ordinal(rankAfter)} place at `,
            ),
            zSeg(zoneId, nodeInfo),
          ]
        : [
            tSeg(
              `You were ${ordinal(rankBefore)} at layer ${layers[i]} before climbing back to ${ordinal(rankAfter)} place`,
            ),
          ];
      bestHighlight = {
        type: "comeback",
        category: "competitive" as PersonalHighlightCategory,
        title: "Comeback",
        segments,
        playerIds: [myId],
        score: gain * 30,
      };
    }
  }

  return bestHighlight;
}

function detectLeadSwap(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);

  // Count how many times me and each other player alternated as rank 1
  const swapCounts = new Map<string, number>();

  for (let i = 1; i < layers.length; i++) {
    const prevRanks = ranks.get(layers[i - 1]);
    const curRanks = ranks.get(layers[i]);
    if (!prevRanks || !curRanks) continue;

    const prevLeader = [...prevRanks.entries()].find(([, r]) => r === 1)?.[0];
    const curLeader = [...curRanks.entries()].find(([, r]) => r === 1)?.[0];

    if (!prevLeader || !curLeader || prevLeader === curLeader) continue;

    // Only count swaps involving me
    if (prevLeader !== myId && curLeader !== myId) continue;
    const other = prevLeader === myId ? curLeader : prevLeader;
    swapCounts.set(other, (swapCounts.get(other) ?? 0) + 1);
  }

  let bestOther = "";
  let bestSwaps = 0;
  for (const [otherId, count] of swapCounts) {
    if (count > bestSwaps) {
      bestSwaps = count;
      bestOther = otherId;
    }
  }

  if (bestSwaps < 3) return null;

  const otherP = participants.find((p) => p.id === bestOther);
  if (!otherP) return null;

  return {
    type: "lead_swap",
    category: "competitive" as PersonalHighlightCategory,
    title: "Lead Swap",
    segments: [
      tSeg("You and "),
      pSeg(otherP),
      tSeg(` traded the lead ${bestSwaps} times during the race`),
    ],
    playerIds: [myId, bestOther],
    score: bestSwaps * 25,
  };
}

function detectNeckAndNeck(
  myId: string,
  participants: WsParticipant[],
  nodeInfo: Map<string, NodeInfo>,
): Highlight | null {
  const ranks = computeRanksPerLayer(participants, nodeInfo);
  const layers = [...ranks.keys()].sort((a, b) => a - b);
  if (layers.length < 3) return null;

  const me = participants.find((p) => p.id === myId);
  if (!me) return null;

  let bestHighlight: Highlight | null = null;
  let bestScore = 0;

  for (const other of participants) {
    if (other.id === myId) continue;

    let layersTogether = 0;
    for (const layer of layers) {
      const layerRanks = ranks.get(layer);
      if (!layerRanks) continue;
      const myRank = layerRanks.get(myId);
      const theirRank = layerRanks.get(other.id);
      if (myRank !== undefined && theirRank !== undefined) {
        if (Math.abs(myRank - theirRank) <= 1) layersTogether++;
      }
    }

    const ratio = layersTogether / layers.length;
    if (ratio < 0.7) continue;

    // Check final IGT gap < 10% of faster player's time
    const fasterIgt = Math.min(me.igt_ms, other.igt_ms);
    if (fasterIgt <= 0) continue;
    const gap = Math.abs(me.igt_ms - other.igt_ms);
    if (gap / fasterIgt >= 0.1) continue;

    const score = layersTogether * 10;
    if (score > bestScore) {
      bestScore = score;
      bestHighlight = {
        type: "neck_and_neck",
        category: "competitive" as PersonalHighlightCategory,
        title: "Neck and Neck",
        segments: [
          tSeg("You stayed neck and neck with "),
          pSeg(other),
          tSeg(" throughout the race"),
        ],
        playerIds: [myId, other.id],
        score,
      };
    }
  }

  return bestHighlight;
}

// =============================================================================
// Orchestrator (combat + pathing)
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

  // Pathing detectors
  push(detectLoneExplorer(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(detectAgainstTheFlow(myParticipantId, eligible, nodeInfo, graphJson));
  push(detectSmartBacktrack(myParticipantId, eligible, allZoneTimes, nodeInfo));
  push(detectCostlyDetour(myParticipantId, eligible, allZoneTimes, nodeInfo));

  // Competitive detectors
  push(detectFasterThanAll(myParticipantId, allZoneTimes, nodeInfo));
  push(detectSlowerThanAll(myParticipantId, allZoneTimes, nodeInfo));
  push(detectLeadLost(myParticipantId, eligible, nodeInfo));
  push(detectComeback(myParticipantId, eligible, nodeInfo));
  push(detectLeadSwap(myParticipantId, eligible, nodeInfo));
  push(detectNeckAndNeck(myParticipantId, eligible, nodeInfo));

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
