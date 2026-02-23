import type { WsParticipant } from "$lib/websocket";
import type {
  ReplayParticipant,
  ReplayZoneVisit,
  PlayerSnapshot,
  SkullEvent,
} from "./types";
import { REPLAY_DEFAULTS } from "./types";
import { PLAYER_COLORS } from "$lib/dag/constants";

interface NodeInfo {
  layer: number;
  type: string;
}

function parseNodeInfo(
  graphJson: Record<string, unknown>,
): Map<string, NodeInfo> {
  const map = new Map<string, NodeInfo>();
  const nodes = (
    graphJson as { nodes: Record<string, Record<string, unknown>> }
  ).nodes;
  if (!nodes) return map;
  for (const [id, data] of Object.entries(nodes)) {
    map.set(id, {
      layer: (data.layer as number) ?? 0,
      type: (data.type as string) ?? "mini_dungeon",
    });
  }
  return map;
}

/**
 * Build pre-computed replay data for all eligible participants.
 * Deaths are distributed uniformly across zone time.
 */
export function buildReplayParticipants(
  participants: WsParticipant[],
  graphJson: Record<string, unknown>,
): ReplayParticipant[] {
  const nodeInfo = parseNodeInfo(graphJson);

  return participants
    .filter((p) => p.zone_history && p.zone_history.length > 0)
    .map((p) => {
      const history = p.zone_history!;
      const zoneVisits: ReplayZoneVisit[] = history.map((entry, i) => {
        const isLast = i >= history.length - 1;
        const exitIgt = isLast ? p.igt_ms : history[i + 1].igt_ms;
        const enterIgt = entry.igt_ms;
        const deaths = entry.deaths ?? 0;
        const zoneDuration = exitIgt - enterIgt;

        // Distribute deaths uniformly: death_i = enter + duration * (i+1) / (deaths+1)
        const deathTimestamps: number[] = [];
        for (let d = 0; d < deaths; d++) {
          deathTimestamps.push(
            Math.round(enterIgt + (zoneDuration * (d + 1)) / (deaths + 1)),
          );
        }

        return {
          nodeId: entry.node_id,
          enterIgt,
          exitIgt,
          deaths,
          deathTimestamps,
          isLast,
        };
      });

      // Detect if player reached final_boss
      let finalBossNodeId: string | null = null;
      if (p.status === "finished") {
        for (const visit of zoneVisits) {
          if (nodeInfo.get(visit.nodeId)?.type === "final_boss") {
            finalBossNodeId = visit.nodeId;
          }
        }
      }

      return {
        id: p.id,
        displayName: p.twitch_display_name || p.twitch_username,
        color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
        colorIndex: p.color_index,
        zoneVisits,
        totalIgt: p.igt_ms,
        finished: p.status === "finished",
        finalBossNodeId,
      };
    });
}

/**
 * Linear mapping from race IGT to replay wall-clock time.
 */
export function igtToReplayMs(
  igtMs: number,
  maxIgt: number,
  durationMs: number = REPLAY_DEFAULTS.DURATION_MS,
): number {
  if (maxIgt <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, igtMs / maxIgt));
  return ratio * durationMs;
}

/**
 * Inverse: replay wall-clock time to race IGT.
 */
export function replayMsToIgt(
  replayMs: number,
  maxIgt: number,
  durationMs: number = REPLAY_DEFAULTS.DURATION_MS,
): number {
  if (durationMs <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, replayMs / durationMs));
  return ratio * maxIgt;
}

/**
 * Find which zone visit a player is in at a given IGT.
 * Returns the index into zoneVisits, or -1 if before their first entry.
 */
export function findCurrentZone(rp: ReplayParticipant, igtMs: number): number {
  for (let i = rp.zoneVisits.length - 1; i >= 0; i--) {
    if (igtMs >= rp.zoneVisits[i].enterIgt) return i;
  }
  return -1;
}

/**
 * Compute the position of a player at a given IGT.
 * Returns x, y in SVG coordinates using the node positions.
 *
 * Position logic per zone visit:
 * - First EDGE_TRANSIT_FRACTION of the zone time: glide from previous node to this node
 * - Remaining time: orbit around the node center
 */
export function computePlayerPosition(
  rp: ReplayParticipant,
  igtMs: number,
  nodePositions: Map<string, { x: number; y: number }>,
  nodeInfo: Map<string, NodeInfo>,
  orbitPhaseOffset: number,
  replayElapsedMs: number,
): PlayerSnapshot | null {
  // Finished players: park to the right of their last node, static
  if (rp.finished && igtMs >= rp.totalIgt && rp.zoneVisits.length > 0) {
    const lastVisit = rp.zoneVisits[rp.zoneVisits.length - 1];
    const lastPos = nodePositions.get(lastVisit.nodeId);
    if (lastPos) {
      const layer = nodeInfo.get(lastVisit.nodeId)?.layer ?? 0;
      const ySpread = orbitPhaseOffset / (Math.PI * 2) - 0.5;
      return {
        participantId: rp.id,
        x: lastPos.x + REPLAY_DEFAULTS.FINISHED_X_OFFSET,
        y: lastPos.y + ySpread * 16,
        currentNodeId: lastVisit.nodeId,
        inTransit: false,
        layer,
      };
    }
  }

  const zoneIdx = findCurrentZone(rp, igtMs);
  if (zoneIdx < 0) return null;

  const visit = rp.zoneVisits[zoneIdx];
  const nodePos = nodePositions.get(visit.nodeId);
  if (!nodePos) return null;

  const zoneDuration = visit.exitIgt - visit.enterIgt;
  const timeInZone = igtMs - visit.enterIgt;
  const layer = nodeInfo.get(visit.nodeId)?.layer ?? 0;

  // Compute transit duration (fraction of zone time, but at least MIN_TRANSIT_MS worth of IGT)
  const transitIgt = Math.max(
    zoneDuration * REPLAY_DEFAULTS.EDGE_TRANSIT_FRACTION,
    zoneDuration > 0
      ? Math.min(REPLAY_DEFAULTS.MIN_TRANSIT_MS, zoneDuration * 0.5)
      : 0,
  );

  // If we're in transit from previous node to this node
  if (zoneIdx > 0 && timeInZone < transitIgt && zoneDuration > 0) {
    const prevVisit = rp.zoneVisits[zoneIdx - 1];
    const prevPos = nodePositions.get(prevVisit.nodeId);
    if (prevPos) {
      const t = timeInZone / transitIgt;
      // Smooth ease-out
      const eased = 1 - (1 - t) * (1 - t);
      return {
        participantId: rp.id,
        x: prevPos.x + (nodePos.x - prevPos.x) * eased,
        y: prevPos.y + (nodePos.y - prevPos.y) * eased,
        currentNodeId: visit.nodeId,
        inTransit: true,
        layer,
      };
    }
  }

  // Orbiting around the node
  const orbitAngle =
    orbitPhaseOffset +
    (replayElapsedMs / REPLAY_DEFAULTS.ORBIT_PERIOD_MS) * Math.PI * 2;
  const orbitR = REPLAY_DEFAULTS.ORBIT_RADIUS;

  return {
    participantId: rp.id,
    x: nodePos.x + Math.cos(orbitAngle) * orbitR,
    y: nodePos.y + Math.sin(orbitAngle) * orbitR,
    currentNodeId: visit.nodeId,
    inTransit: false,
    layer,
  };
}

/**
 * Determine the current leader from player snapshots.
 * Highest layer wins; ties broken by order in list (earlier = first to arrive).
 */
export function computeLeader(snapshots: PlayerSnapshot[]): string | null {
  if (snapshots.length === 0) return null;
  let best = snapshots[0];
  for (let i = 1; i < snapshots.length; i++) {
    if (snapshots[i].layer > best.layer) {
      best = snapshots[i];
    }
  }
  return best.participantId;
}

/**
 * Collect all skull events from all participants, sorted by IGT.
 */
export function collectSkullEvents(
  replayParticipants: ReplayParticipant[],
): SkullEvent[] {
  const events: SkullEvent[] = [];
  for (const rp of replayParticipants) {
    for (const visit of rp.zoneVisits) {
      for (const ts of visit.deathTimestamps) {
        events.push({ nodeId: visit.nodeId, igtMs: ts, participantId: rp.id });
      }
    }
  }
  events.sort((a, b) => a.igtMs - b.igtMs);
  return events;
}

/**
 * Compute cumulative death heat for each node up to a given IGT.
 * Returns nodeId -> cumulative deaths (for heat intensity).
 */
export function computeNodeHeat(
  skullEvents: SkullEvent[],
  upToIgt: number,
): Map<string, number> {
  const heat = new Map<string, number>();
  for (const ev of skullEvents) {
    if (ev.igtMs > upToIgt) break;
    heat.set(ev.nodeId, (heat.get(ev.nodeId) ?? 0) + 1);
  }
  return heat;
}
