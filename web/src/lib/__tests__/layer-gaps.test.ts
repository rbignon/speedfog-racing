import { describe, it, expect } from "vitest";
import { buildRunnerTimeline } from "$lib/layer-gaps";
import type { ZoneHistoryEntry } from "$lib/zone-history";

// A 4-layer seed: the start (0), two branches on layers 1 and 2, the final
// boss (3).
const NODE_LAYERS = new Map([
  ["start", 0],
  ["a1", 1],
  ["b1", 1],
  ["a2", 2],
  ["b2", 2],
  ["boss", 3],
]);
const T = 4;

function at(
  node_id: string,
  igt_ms: number,
  extra: Partial<ZoneHistoryEntry> = {},
): ZoneHistoryEntry {
  return { node_id, igt_ms, ...extra };
}

function timeline(
  history: ZoneHistoryEntry[] | null,
  status = "finished",
  igtMs = 100_000,
) {
  return buildRunnerTimeline(history, NODE_LAYERS, T, status, igtMs);
}

describe("buildRunnerTimeline", () => {
  it("times a direct run layer by layer, the last layer up to the finish", () => {
    const t = timeline([
      at("start", 0),
      at("a1", 10_000),
      at("a2", 40_000, { deaths: 1 }),
      at("boss", 70_000),
    ]);
    expect(t.layers.map((v) => v?.timeOnLayerMs)).toEqual([
      10_000, 30_000, 30_000, 30_000,
    ]);
    expect(t.layers.map((v) => v?.deaths)).toEqual([0, 0, 1, 0]);
    expect(t.finishIgt).toBe(100_000);
    expect(t.deepestLayer).toBe(3);
  });

  it("keeps the first arrival when a runner warps back into the same node", () => {
    // Died in a1, respawned at the start grace, ran back into a1.
    const t = timeline([
      at("start", 0),
      at("a1", 10_000, { deaths: 1 }),
      at("start", 15_000, { type: "backtrack" }),
      at("a1", 20_000),
      at("a2", 50_000),
      at("boss", 60_000),
    ]);
    expect(t.layers[1]).toMatchObject({
      arrivalIgt: 10_000,
      firstNodeId: "a1",
      exitNodeId: "a1",
      timeOnLayerMs: 40_000,
      timeThroughNodeMs: 40_000,
      deaths: 1,
    });
    // The run back through the start node is layer 1's time, not layer 0's.
    expect(t.layers[0]?.timeOnLayerMs).toBe(10_000);
  });

  it("gives a back-out to the node the runner left through, with its detour", () => {
    const t = timeline([
      at("start", 0),
      at("a1", 10_000),
      at("start", 25_000, { type: "backtrack", deaths: 1 }),
      at("b1", 30_000, { deaths: 2 }),
      at("a2", 60_000),
      at("boss", 70_000),
    ]);
    expect(t.layers[1]).toMatchObject({
      firstNodeId: "a1",
      exitNodeId: "b1",
      exitEntryIgt: 30_000,
      timeOnLayerMs: 50_000,
      timeThroughNodeMs: 30_000,
      // The death during the detour through layer 0 lands on layer 1.
      deaths: 3,
    });
    expect(t.layers[0]?.deaths).toBe(0);
  });

  it("leaves a playing runner's current layer open", () => {
    const t = timeline(
      [at("start", 0), at("a1", 10_000, { deaths: 2 })],
      "playing",
      25_000,
    );
    expect(t.layers[1]).toMatchObject({
      arrivalIgt: 10_000,
      exitNodeId: "a1",
      timeOnLayerMs: null,
      timeThroughNodeMs: null,
      deaths: 2,
    });
    expect(t.layers[2]).toBeNull();
    expect(t.deepestLayer).toBe(1);
    expect(t.finishIgt).toBeNull();
  });

  it("leaves an abandoned runner's deepest layer open, with no finish", () => {
    const t = timeline(
      [at("start", 0), at("a1", 10_000), at("a2", 30_000, { deaths: 4 })],
      "abandoned",
      90_000,
    );
    expect(t.layers[2]).toMatchObject({ timeOnLayerMs: null, deaths: 4 });
    expect(t.deepestLayer).toBe(2);
    expect(t.finishIgt).toBeNull();
  });

  it("drops a layer recorded after the next one, and the time of the layer before it", () => {
    const t = timeline([
      at("start", 0),
      at("a2", 20_000),
      at("a1", 30_000),
      at("boss", 50_000),
    ]);
    expect(t.layers[1]).toBeNull();
    expect(t.layers[0]?.timeOnLayerMs).toBeNull();
    expect(t.layers[2]?.timeOnLayerMs).toBe(30_000);
  });

  it("leaves a missing layer empty and the layer before it untimed", () => {
    const t = timeline([at("start", 0), at("a2", 30_000), at("boss", 50_000)]);
    expect(t.layers[1]).toBeNull();
    expect(t.layers[0]?.timeOnLayerMs).toBeNull();
    expect(t.layers[2]?.timeOnLayerMs).toBe(20_000);
  });

  it("ignores entries on nodes outside the graph", () => {
    const t = timeline(
      [
        at("start", 0),
        at("roundtable", 5_000, { deaths: 3 }),
        at("a1", 10_000),
      ],
      "playing",
      12_000,
    );
    expect(t.layers[0]).toMatchObject({ timeOnLayerMs: 10_000, deaths: 0 });
  });

  it("has nothing for a runner with no history", () => {
    const t = timeline(null, "ready", 0);
    expect(t.layers).toEqual([null, null, null, null]);
    expect(t.deepestLayer).toBe(-1);
  });
});
