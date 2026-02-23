import { describe, it, expect } from "vitest";
import {
  buildReplayParticipants,
  computeLeader,
  igtToReplayMs,
} from "../timeline";
import type { WsParticipant } from "$lib/websocket";
import type { PlayerSnapshot } from "../types";
import { REPLAY_DEFAULTS } from "../types";

function makeParticipant(overrides: Partial<WsParticipant>): WsParticipant {
  return {
    id: "p1",
    twitch_username: "player1",
    twitch_display_name: "Player1",
    status: "finished",
    current_zone: null,
    current_layer: 0,
    igt_ms: 60000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: [],
    ...overrides,
  };
}

const simpleGraphJson = {
  nodes: {
    start_a: {
      type: "start",
      display_name: "Start",
      zones: [],
      layer: 0,
      tier: 1,
      weight: 1,
    },
    zone_b: {
      type: "mini_dungeon",
      display_name: "Zone B",
      zones: [],
      layer: 1,
      tier: 1,
      weight: 1,
    },
    boss_c: {
      type: "final_boss",
      display_name: "Final Boss",
      zones: [],
      layer: 2,
      tier: 3,
      weight: 1,
    },
  },
  edges: [
    { from: "start_a", to: "zone_b" },
    { from: "zone_b", to: "boss_c" },
  ],
  total_layers: 3,
};

describe("buildReplayParticipants", () => {
  it("builds zone visits with correct enter/exit IGT", () => {
    const p = makeParticipant({
      zone_history: [
        { node_id: "start_a", igt_ms: 0 },
        { node_id: "zone_b", igt_ms: 10000 },
        { node_id: "boss_c", igt_ms: 50000 },
      ],
      igt_ms: 60000,
    });

    const result = buildReplayParticipants([p], simpleGraphJson);
    expect(result).toHaveLength(1);
    expect(result[0].zoneVisits).toHaveLength(3);
    expect(result[0].zoneVisits[0]).toMatchObject({
      nodeId: "start_a",
      enterIgt: 0,
      exitIgt: 10000,
      deaths: 0,
    });
    expect(result[0].zoneVisits[1]).toMatchObject({
      nodeId: "zone_b",
      enterIgt: 10000,
      exitIgt: 50000,
      deaths: 0,
    });
    expect(result[0].zoneVisits[2].isLast).toBe(true);
  });

  it("distributes deaths uniformly across zone time", () => {
    const p = makeParticipant({
      zone_history: [
        { node_id: "start_a", igt_ms: 0 },
        { node_id: "zone_b", igt_ms: 10000, deaths: 4 },
        { node_id: "boss_c", igt_ms: 50000 },
      ],
      igt_ms: 60000,
    });

    const result = buildReplayParticipants([p], simpleGraphJson);
    const zoneB = result[0].zoneVisits[1];
    expect(zoneB.deaths).toBe(4);
    expect(zoneB.deathTimestamps).toHaveLength(4);
    // Deaths distributed: 10000 + 40000 * (i+1) / (4+1) for i=0..3
    expect(zoneB.deathTimestamps[0]).toBe(18000);
    expect(zoneB.deathTimestamps[1]).toBe(26000);
    expect(zoneB.deathTimestamps[2]).toBe(34000);
    expect(zoneB.deathTimestamps[3]).toBe(42000);
  });

  it("skips participants with no zone_history", () => {
    const p = makeParticipant({ zone_history: null });
    const result = buildReplayParticipants([p], simpleGraphJson);
    expect(result).toHaveLength(0);
  });

  it("detects final_boss node", () => {
    const p = makeParticipant({
      status: "finished",
      zone_history: [
        { node_id: "start_a", igt_ms: 0 },
        { node_id: "boss_c", igt_ms: 50000 },
      ],
      igt_ms: 60000,
    });

    const result = buildReplayParticipants([p], simpleGraphJson);
    expect(result[0].finalBossNodeId).toBe("boss_c");
  });
});

describe("igtToReplayMs", () => {
  it("maps IGT linearly to replay duration", () => {
    const maxIgt = 120000; // 2 minutes
    expect(igtToReplayMs(0, maxIgt)).toBe(0);
    expect(igtToReplayMs(60000, maxIgt)).toBe(REPLAY_DEFAULTS.DURATION_MS / 2);
    expect(igtToReplayMs(120000, maxIgt)).toBe(REPLAY_DEFAULTS.DURATION_MS);
  });

  it("clamps to bounds", () => {
    expect(igtToReplayMs(-1000, 60000)).toBe(0);
    expect(igtToReplayMs(100000, 60000)).toBe(REPLAY_DEFAULTS.DURATION_MS);
  });
});

describe("computeLeader", () => {
  it("returns the player on the highest layer", () => {
    const snapshots: PlayerSnapshot[] = [
      {
        participantId: "p1",
        x: 0,
        y: 0,
        currentNodeId: "a",
        inTransit: false,
        layer: 1,
      },
      {
        participantId: "p2",
        x: 0,
        y: 0,
        currentNodeId: "b",
        inTransit: false,
        layer: 2,
      },
    ];
    expect(computeLeader(snapshots)).toBe("p2");
  });

  it("breaks layer tie by first in list (earlier arrival)", () => {
    const snapshots: PlayerSnapshot[] = [
      {
        participantId: "p1",
        x: 0,
        y: 0,
        currentNodeId: "a",
        inTransit: false,
        layer: 2,
      },
      {
        participantId: "p2",
        x: 0,
        y: 0,
        currentNodeId: "b",
        inTransit: false,
        layer: 2,
      },
    ];
    expect(computeLeader(snapshots)).toBe("p1");
  });
});
