import { describe, it, expect } from "vitest";
import { computeZoneTimes, type ZoneTime } from "$lib/highlights";
import type { WsParticipant } from "$lib/websocket";

// Minimal participant factory
function participant(
  id: string,
  overrides: Partial<WsParticipant> = {},
): WsParticipant {
  return {
    id,
    twitch_username: id,
    twitch_display_name: id.charAt(0).toUpperCase() + id.slice(1),
    status: "finished",
    current_zone: null,
    current_layer: 3,
    igt_ms: 300000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...overrides,
  };
}

describe("computeZoneTimes", () => {
  it("computes time spent in each zone from zone_history", () => {
    const p = participant("alice", {
      igt_ms: 300000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 60000 },
        { node_id: "zone_b", igt_ms: 120000 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result).toEqual([
      { nodeId: "start", timeMs: 60000, deaths: 0 },
      { nodeId: "zone_a", timeMs: 60000, deaths: 0 },
      { nodeId: "zone_b", timeMs: 180000, deaths: 0 },
    ]);
  });

  it("includes deaths from zone_history entries", () => {
    const p = participant("alice", {
      igt_ms: 200000,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "zone_a", igt_ms: 50000, deaths: 3 },
      ],
    });
    const result = computeZoneTimes(p);
    expect(result[1].deaths).toBe(3);
  });

  it("returns empty array when zone_history is null", () => {
    const p = participant("alice", { zone_history: null });
    expect(computeZoneTimes(p)).toEqual([]);
  });

  it("handles single-entry zone_history", () => {
    const p = participant("alice", {
      igt_ms: 100000,
      zone_history: [{ node_id: "start", igt_ms: 0 }],
    });
    const result = computeZoneTimes(p);
    expect(result).toEqual([{ nodeId: "start", timeMs: 100000, deaths: 0 }]);
  });
});
