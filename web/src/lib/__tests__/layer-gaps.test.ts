import { describe, it, expect } from "vitest";
import {
  buildLayerDetail,
  buildRunnerTimeline,
  computeFieldStats,
  croppedLeft,
  fieldRank,
  gapSeries,
  gapTicks,
  gateXs,
  layerAtX,
  selectionGaps,
  stepLayer,
} from "$lib/layer-gaps";
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

describe("selectionGaps", () => {
  // a enters layers 1 and 3 first, b enters layer 2 and the finish first.
  const a = timeline(
    [at("start", 0), at("a1", 10_000), at("a2", 50_000), at("boss", 70_000)],
    "finished",
    100_000,
  );
  const b = timeline(
    [at("start", 0), at("b1", 20_000), at("b2", 40_000), at("boss", 75_000)],
    "finished",
    95_000,
  );

  it("measures each layer against whoever of the selection entered it first", () => {
    const gaps = selectionGaps(
      new Map([
        ["a", a],
        ["b", b],
      ]),
      T,
    );
    expect(gaps.get("a")).toEqual([0, 0, 10_000, 0, 5_000]);
    expect(gaps.get("b")).toEqual([0, 10_000, 0, 5_000, 0]);
  });

  it("leaves a runner out of the layers they have not reached", () => {
    const c = timeline([at("start", 0), at("a1", 5_000)], "playing", 8_000);
    const gaps = selectionGaps(
      new Map([
        ["a", a],
        ["b", b],
        ["c", c],
      ]),
      T,
    );
    expect(gaps.get("c")).toEqual([0, 0, null, null, null]);
    expect(gaps.get("a")?.[1]).toBe(5_000);
    expect(gaps.get("a")?.[2]).toBe(10_000);
  });

  it("gives a selected runner who has not started no gap at all", () => {
    const gaps = selectionGaps(
      new Map([
        ["a", a],
        ["d", timeline([], "ready", 0)],
      ]),
      T,
    );
    expect(gaps.get("d")).toEqual([null, null, null, null, null]);
    expect(gaps.get("a")).toEqual([0, 0, 0, 0, 0]);
  });
});

describe("gapSeries", () => {
  it("draws a finisher up to the finish and marks deaths on finished layers", () => {
    const t = timeline(
      [
        at("start", 0),
        at("a1", 10_000, { deaths: 2 }),
        at("a2", 40_000),
        at("boss", 70_000),
      ],
      "finished",
      100_000,
    );
    const s = gapSeries(t, [0, 0, 6_000, 4_000, 2_000], "finished");
    expect(s.points.map((p) => p.index)).toEqual([0, 1, 2, 3, 4]);
    expect(s.deathMarks).toEqual([{ layer: 1, count: 2, midGapMs: 3_000 }]);
    expect(s.terminus).toBe(false);
  });

  it("ends a DNF on a terminus at its deepest layer, without its open layer's deaths", () => {
    const t = timeline(
      [at("start", 0), at("a1", 10_000), at("a2", 30_000, { deaths: 4 })],
      "abandoned",
      90_000,
    );
    const s = gapSeries(t, [0, 1_000, 3_000, null, null], "abandoned");
    expect(s.points.at(-1)).toEqual({ index: 2, gapMs: 3_000 });
    expect(s.deathMarks).toEqual([]);
    expect(s.terminus).toBe(true);
  });

  it("ends a disqualified runner on a terminus too", () => {
    const t = timeline(
      [at("start", 0), at("a1", 10_000)],
      "disqualified",
      20_000,
    );
    expect(
      gapSeries(t, [0, 0, null, null, null], "disqualified").terminus,
    ).toBe(true);
  });

  it("skips a missing layer and keeps drawing past it", () => {
    const t = timeline(
      [at("start", 0), at("a2", 30_000), at("boss", 50_000)],
      "finished",
      80_000,
    );
    const s = gapSeries(t, [0, null, 2_000, 1_000, 0], "finished");
    expect(s.points.map((p) => p.index)).toEqual([0, 2, 3, 4]);
  });
});

describe("computeFieldStats", () => {
  const run = (
    history: Parameters<typeof timeline>[0],
    status = "finished",
  ) => ({
    status,
    timeline: timeline(history, status, 100_000),
  });

  it("takes each node's best and median over the runners who left through it", () => {
    const stats = computeFieldStats([
      run([
        at("start", 0),
        at("a1", 10_000),
        at("a2", 20_000),
        at("boss", 30_000),
      ]),
      run([
        at("start", 0),
        at("a1", 10_000),
        at("a2", 40_000),
        at("boss", 50_000),
      ]),
      run([
        at("start", 0),
        at("a1", 10_000),
        at("a2", 30_000),
        at("boss", 50_000),
      ]),
      run([
        at("start", 0),
        at("b1", 10_000),
        at("b2", 50_000),
        at("boss", 60_000),
      ]),
    ]);
    expect(stats.get("a1")).toMatchObject({
      bestMs: 10_000,
      medianMs: 20_000,
      count: 3,
    });
    expect(stats.get("b1")).toMatchObject({ bestMs: 40_000, count: 1 });
  });

  it("averages the two middle samples of an even count", () => {
    const stats = computeFieldStats([
      run([
        at("start", 0),
        at("a1", 10_000),
        at("a2", 20_000),
        at("boss", 30_000),
      ]),
      run([
        at("start", 0),
        at("a1", 10_000),
        at("a2", 40_000),
        at("boss", 50_000),
      ]),
    ]);
    expect(stats.get("a1")?.medianMs).toBe(20_000);
  });

  it("times a back-out from its entry on the node it left through", () => {
    const stats = computeFieldStats([
      run([
        at("start", 0),
        at("a1", 10_000),
        at("start", 25_000, { type: "backtrack" }),
        at("b1", 30_000),
        at("a2", 60_000),
        at("boss", 70_000),
      ]),
    ]);
    expect(stats.get("b1")?.samples).toEqual([30_000]);
    expect(stats.has("a1")).toBe(false);
  });

  it("leaves open layers and disqualified runners out of the field", () => {
    const stats = computeFieldStats([
      run([at("start", 0), at("a1", 10_000)], "playing"),
      run(
        [at("start", 0), at("a1", 5_000), at("a2", 6_000), at("boss", 7_000)],
        "disqualified",
      ),
    ]);
    expect(stats.has("a1")).toBe(false);
    expect(stats.get("start")?.samples).toEqual([10_000]);
  });
});

describe("fieldRank", () => {
  it("shares a rank between tied samples", () => {
    const stats = {
      bestMs: 10,
      medianMs: 20,
      count: 4,
      samples: [10, 20, 20, 30],
    };
    expect([10, 20, 30, 35].map((ms) => fieldRank(stats, ms))).toEqual([
      1, 2, 4, 5,
    ]);
  });
});

describe("buildLayerDetail", () => {
  // Layer 1: a and b go straight through a1, c backs out of a1 into b1, d is
  // still playing on b1. x is a field runner outside the selection.
  const runs = {
    a: {
      status: "finished",
      igtMs: 100_000,
      history: [
        at("start", 0),
        at("a1", 10_000),
        at("a2", 20_000),
        at("boss", 30_000),
      ],
    },
    b: {
      status: "finished",
      igtMs: 100_000,
      history: [
        at("start", 0),
        at("a1", 12_000, { deaths: 1 }),
        at("a2", 37_000),
        at("boss", 50_000),
      ],
    },
    c: {
      status: "finished",
      igtMs: 100_000,
      history: [
        at("start", 0),
        at("a1", 10_000),
        at("start", 25_000, { type: "backtrack" }),
        at("b1", 30_000),
        at("a2", 60_000),
        at("boss", 70_000),
      ],
    },
    d: {
      status: "playing",
      igtMs: 18_000,
      history: [at("start", 0), at("b1", 11_000)],
    },
  };
  const runners = Object.entries(runs).map(([id, r]) => ({
    id,
    status: r.status,
    igtMs: r.igtMs,
    timeline: timeline(r.history, r.status, r.igtMs),
  }));
  const gaps = selectionGaps(
    new Map(runners.map((r) => [r.id, r.timeline])),
    T,
  );
  const field = computeFieldStats([
    ...runners,
    {
      status: "finished",
      timeline: timeline([
        at("start", 0),
        at("b1", 10_000),
        at("b2", 30_000),
        at("boss", 40_000),
      ]),
    },
  ]);
  const columns = buildLayerDetail(1, runners, gaps, field);
  const row = (id: string) =>
    columns.flatMap((c) => c.rows).find((r) => r.id === id);

  it("groups runners by the node they left through, fastest node first", () => {
    expect(columns.map((c) => c.nodeId)).toEqual(["a1", "b1"]);
    expect(columns[0].rows.map((r) => r.id)).toEqual(["a", "b"]);
    expect(columns[1].rows.map((r) => r.id)).toEqual(["c", "d"]);
  });

  it("compares each finished time with the selection's fastest, across branches", () => {
    expect(row("a")).toMatchObject({
      state: "done",
      timeMs: 10_000,
      vsBestMs: 0,
    });
    expect(row("b")).toMatchObject({
      state: "done",
      timeMs: 25_000,
      vsBestMs: 15_000,
      deaths: 1,
    });
    expect(row("c")).toMatchObject({
      state: "done",
      timeMs: 50_000,
      vsBestMs: 40_000,
    });
  });

  it("ranks a runner against the field on the node they left through", () => {
    expect(row("a")?.fieldRank).toBe(1);
    expect(row("b")?.fieldRank).toBe(2);
    // c spent 30s in b1 after the detour; x did b1 in 20s.
    expect(row("c")?.fieldRank).toBe(2);
    expect(columns[1].field).toMatchObject({ bestMs: 20_000, count: 2 });
  });

  it("names the node a runner backed out of and the detour", () => {
    expect(row("c")).toMatchObject({ backedOutOf: "a1", detourMs: 20_000 });
    expect(row("a")).toMatchObject({ backedOutOf: null, detourMs: null });
  });

  it("shows a playing runner's time so far on its layer, compared with nobody", () => {
    expect(row("d")).toMatchObject({
      state: "live",
      timeMs: 7_000,
      vsBestMs: null,
      fieldRank: null,
    });
  });

  it("gives each runner's entry gap to the first of the selection", () => {
    expect(row("a")?.entryGapMs).toBe(0);
    expect(row("b")?.entryGapMs).toBe(2_000);
    expect(row("d")?.entryGapMs).toBe(1_000);
  });

  it("calls every runner tied on the best time fastest", () => {
    const twin = { ...runners[0], id: "a-twin" };
    const [col] = buildLayerDetail(1, [runners[0], twin], gaps, field);
    expect(col.rows.map((r) => r.vsBestMs)).toEqual([0, 0]);
  });

  it("marks a runner who left the race on that layer as out", () => {
    const quit = {
      id: "q",
      status: "abandoned",
      igtMs: 90_000,
      timeline: timeline(
        [at("start", 0), at("a1", 10_000)],
        "abandoned",
        90_000,
      ),
    };
    const [col] = buildLayerDetail(
      1,
      [quit],
      new Map([["q", [0, 0, null, null, null]]]),
      field,
    );
    expect(col.rows[0]).toMatchObject({
      state: "out",
      timeMs: null,
      vsBestMs: null,
    });
  });

  it("shows no time on a layer whose exit the history missed", () => {
    const holed = {
      id: "h",
      status: "finished",
      igtMs: 90_000,
      timeline: timeline(
        [at("start", 0), at("a1", 10_000), at("boss", 50_000)],
        "finished",
        90_000,
      ),
    };
    const [col] = buildLayerDetail(1, [holed], new Map(), field);
    expect(col.rows[0]).toMatchObject({ state: "unknown", timeMs: null });
  });

  it("lists nobody on a layer no selected runner reached", () => {
    expect(buildLayerDetail(3, [runners[3]], gaps, field)).toEqual([]);
  });
});

describe("gateXs", () => {
  it("puts each layer's entry halfway between columns, even unevenly spaced", () => {
    expect(gateXs([90, 190, 340])).toEqual([40, 140, 265, 415]);
  });

  it("falls back to the default column spacing for a single layer", () => {
    expect(gateXs([90])).toEqual([40, 140]);
  });
});

describe("layerAtX", () => {
  const gates = [40, 140, 265, 415];

  it("finds the column between two gates, the left gate included", () => {
    expect(layerAtX(40, gates)).toBe(0);
    expect(layerAtX(139.9, gates)).toBe(0);
    expect(layerAtX(140, gates)).toBe(1);
    expect(layerAtX(414, gates)).toBe(2);
  });

  it("finds no column outside the chart", () => {
    expect(layerAtX(39, gates)).toBeNull();
    expect(layerAtX(415, gates)).toBeNull();
  });
});

describe("gapTicks", () => {
  it("keeps a one minute range when nobody is behind", () => {
    expect(gapTicks(0)).toEqual({ stepMs: 60_000, topMs: 60_000 });
  });

  it("rounds the top up to a step", () => {
    expect(gapTicks(61_000)).toEqual({ stepMs: 60_000, topMs: 120_000 });
    expect(gapTicks(300_000)).toEqual({ stepMs: 60_000, topMs: 300_000 });
  });

  it("widens the step to keep at most five intervals", () => {
    expect(gapTicks(301_000)).toEqual({ stepMs: 120_000, topMs: 360_000 });
    expect(gapTicks(3 * 3_600_000)).toEqual({
      stepMs: 3_600_000,
      topMs: 3 * 3_600_000,
    });
  });

  it("stays on hour steps past five hours", () => {
    expect(gapTicks(6 * 3_600_000)).toEqual({
      stepMs: 3_600_000,
      topMs: 6 * 3_600_000,
    });
  });
});

describe("stepLayer", () => {
  it("starts from an end when nothing is pinned", () => {
    expect(stepLayer(null, 1, 30)).toBe(0);
    expect(stepLayer(null, -1, 30)).toBe(29);
  });

  it("stops at the first and last layers", () => {
    expect(stepLayer(0, -1, 30)).toBe(0);
    expect(stepLayer(29, 1, 30)).toBe(29);
    expect(stepLayer(12, 1, 30)).toBe(13);
  });
});

describe("croppedLeft", () => {
  it("measures how much of the chart's left side a narrow frame cuts", () => {
    // The chart keeps a 600px minimum and is centered in its frame.
    expect(croppedLeft(600, 400)).toBe(100);
  });

  it("cuts nothing when the frame holds the whole chart", () => {
    expect(croppedLeft(800, 800)).toBe(0);
    expect(croppedLeft(800, 1000)).toBe(0);
  });
});
