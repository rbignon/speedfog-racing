import { describe, it, expect } from "vitest";
import {
  buildLss,
  categoryLssFile,
  lssFileName,
  seedLssFile,
  segmentTimes,
  splitTimesFromEntries,
} from "$lib/livesplit";
import type { SpeedrunSeed, SpeedrunSeedRun } from "$lib/api";

// 3 layers: start (0), two branches on layer 1, a2 on layer 2 (final boss).
function graph(finalName = "Maliketh"): Record<string, unknown> {
  return {
    total_layers: 3,
    nodes: {
      start: { type: "start", display_name: "Chapel", layer: 0 },
      a1: { type: "mini_dungeon", display_name: "Cave A", layer: 1 },
      b1: { type: "mini_dungeon", display_name: "Cave B", layer: 1 },
      a2: { type: "final_boss", display_name: finalName, layer: 2 },
    },
    edges: [
      { from: "start", to: "a1" },
      { from: "start", to: "b1" },
      { from: "a1", to: "a2" },
      { from: "b1", to: "a2" },
    ],
  };
}

function run(
  id: string,
  userId: string,
  igt: number,
  history: { node_id: string; igt_ms: number }[],
  extra: Partial<SpeedrunSeedRun> = {},
): SpeedrunSeedRun {
  return {
    run_id: id,
    user: { id: userId },
    igt_ms: igt,
    finished_at: "2026-11-01T10:00:00Z",
    ranked: true,
    rank: 1,
    zone_history: history,
    ...extra,
  } as unknown as SpeedrunSeedRun;
}

function seed(
  runs: SpeedrunSeedRun[],
  g: Record<string, unknown> | null = graph(),
): SpeedrunSeed {
  return {
    seed_number: "42",
    category: "pool",
    category_name: "Pool Name",
    total_layers: 3,
    graph_json: g,
    runs,
  } as unknown as SpeedrunSeed;
}

function doc(xml: string): Document {
  return new DOMParser().parseFromString(xml, "application/xml");
}

function comparison(d: Document, name: string): (string | null)[] {
  return [...d.querySelectorAll("Segment")].map((s) => {
    const st = [...s.querySelectorAll("SplitTime")].find(
      (e) => e.getAttribute("name") === name,
    );
    return st?.querySelector("GameTime")?.textContent ?? null;
  });
}

function names(d: Document): string[] {
  return [...d.querySelectorAll("Segment > Name")].map((n) => n.textContent!);
}

function golds(d: Document): (string | null)[] {
  return [...d.querySelectorAll("Segment")].map(
    (s) => s.querySelector("BestSegmentTime > GameTime")?.textContent ?? null,
  );
}

const DIRECT = [
  { node_id: "start", igt_ms: 0 },
  { node_id: "a1", igt_ms: 10_000 },
  { node_id: "a2", igt_ms: 40_000 },
];

describe("buildLss", () => {
  it("has one segment per layer and the SpeedFog game name", () => {
    const file = seedLssFile(seed([run("r1", "u1", 70_000, DIRECT)]), "u1")!;
    const d = doc(buildLss(file));
    expect(d.querySelector("parsererror")).toBeNull();
    expect(d.querySelector("Run > GameName")!.textContent).toBe("SpeedFog");
    expect(d.querySelector("Run > CategoryName")!.textContent).toBe(
      "Pool Name · Seed 42",
    );
    expect(d.querySelectorAll("Segment")).toHaveLength(3);
    const vars = [...d.querySelectorAll("CustomVariables > Variable")];
    expect(vars.map((v) => v.getAttribute("name"))).toEqual(["SpeedFog seed"]);
    expect(vars[0].textContent).toBe("42");
  });

  it("writes PB and WR split times in game time, empty when unknown", () => {
    // Layer 2 never entered: segment 1 cannot be placed.
    const history = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 10_000 },
    ];
    const file = seedLssFile(seed([run("r1", "u1", 70_000, history)]), "u1")!;
    const d = doc(buildLss(file));
    expect(comparison(d, "Personal Best")).toEqual([
      "00:00:10.0000000",
      null,
      "00:01:10.0000000",
    ]);
    expect(comparison(d, "SpeedFog WR")).toEqual(
      comparison(d, "Personal Best"),
    );
  });

  it("picks the fastest ranked run as WR and ignores a faster unranked one", () => {
    const fast = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 1_000 },
      { node_id: "a2", igt_ms: 2_000 },
    ];
    const file = seedLssFile(
      seed([
        run("slow", "u2", 90_000, DIRECT),
        run("fast", "u3", 50_000, fast, { ranked: false, rank: null }),
        run("mid", "u4", 80_000, fast),
      ]),
      null,
    )!;
    expect(file.wr).toEqual([1_000, 2_000, 80_000]);
  });

  it("picks the viewer's fastest run as PB even when unranked", () => {
    const quick = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 3_000 },
      { node_id: "a2", igt_ms: 6_000 },
    ];
    const file = seedLssFile(
      seed([
        run("w", "u2", 60_000, DIRECT),
        run("mine1", "u1", 65_000, DIRECT),
        run("mine2", "u1", 50_000, quick, { ranked: false, rank: null }),
      ]),
      "u1",
    )!;
    expect(file.pb).toEqual([3_000, 6_000, 50_000]);
    expect(file.wr).toEqual([10_000, 40_000, 60_000]);
  });

  it("has no PB and no golds for a logged-out viewer", () => {
    const file = seedLssFile(seed([run("w", "u2", 60_000, DIRECT)]), null)!;
    expect(file.pb).toBeNull();
    expect(file.golds).toBeNull();
    const d = doc(buildLss(file));
    expect(comparison(d, "Personal Best")).toEqual([null, null, null]);
    expect(golds(d)).toEqual([null, null, null]);
    expect(names(d)).toEqual(["Chapel", "Cave A", "Maliketh"]);
  });

  it("takes golds as the viewer's best time per segment across runs", () => {
    const r1 = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 10_000 },
      { node_id: "a2", igt_ms: 20_000 },
    ];
    const r2 = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 5_000 },
      { node_id: "a2", igt_ms: 30_000 },
    ];
    const file = seedLssFile(
      seed([run("r1", "u1", 50_000, r1), run("r2", "u1", 40_000, r2)]),
      "u1",
    )!;
    // r1: 10s, 10s, 30s. r2: 5s, 25s, 10s.
    expect(file.golds).toEqual([5_000, 10_000, 10_000]);
    expect(golds(doc(buildLss(file)))).toEqual([
      "00:00:05.0000000",
      "00:00:10.0000000",
      "00:00:10.0000000",
    ]);
  });

  it("measures the first gold from IGT 0, like the first split", () => {
    // The spawn entry lands a few seconds in: depth 1 still starts at 0.
    const late = [
      { node_id: "start", igt_ms: 2_000 },
      { node_id: "a1", igt_ms: 10_000 },
      { node_id: "a2", igt_ms: 20_000 },
    ];
    const file = seedLssFile(seed([run("r", "u1", 50_000, late)]), "u1")!;
    expect(file.pb![0]).toBe(10_000);
    expect(file.golds).toEqual([10_000, 10_000, 30_000]);
  });

  it("times a back-out at the next layer's first arrival and names the node taken", () => {
    // a1 first, back to the start, then b1: layer 1 is entered at 10s, left
    // through b1; layer 2 at 40s.
    const history = [
      { node_id: "start", igt_ms: 0 },
      { node_id: "a1", igt_ms: 10_000 },
      { node_id: "start", igt_ms: 15_000 },
      { node_id: "b1", igt_ms: 20_000 },
      { node_id: "a2", igt_ms: 40_000 },
    ];
    const file = seedLssFile(seed([run("r", "u1", 70_000, history)]), "u1")!;
    expect(file.pb).toEqual([10_000, 40_000, 70_000]);
    expect(file.segmentNames).toEqual(["Chapel", "Cave B", "Maliketh"]);
  });

  it("names segments as the map labels them, the fought boss on an arena", () => {
    const g = graph("Leyndell - Erdtree Entrance");
    const nodes = g.nodes as Record<string, Record<string, unknown>>;
    nodes.start.display_name = "Chapel of Anticipation";
    nodes.a1 = {
      type: "boss_arena",
      display_name: "Caelid - Gael Tunnel - Magma Wyrm",
      randomized_bosses: ["Tree Sentinel"],
      layer: 1,
    };
    const file = seedLssFile(seed([run("r", "u1", 70_000, DIRECT)], g), "u1")!;
    expect(file.segmentNames).toEqual([
      "Chapel of Anticipation",
      "Tree Sentinel",
      "Erdtree Entrance",
    ]);
  });

  it("escapes zone names in the XML", () => {
    const g = graph(`Godrick's "Hall" & <Keep>`);
    const file = seedLssFile(seed([run("r", "u1", 70_000, DIRECT)], g), "u1")!;
    const d = doc(buildLss(file));
    expect(d.querySelector("parsererror")).toBeNull();
    expect(names(d)[2]).toBe(`Godrick's "Hall" & <Keep>`);
  });

  it("is not built without a public graph", () => {
    expect(seedLssFile(seed([], null), null)).toBeNull();
  });
});

describe("category file", () => {
  it("has Depth names, the category variable and no seed variable", () => {
    const file = categoryLssFile(
      "pool@12",
      "Pool Name",
      3,
      { "0": 0, "1": 10_000, "2": 40_000, "3": 70_000 },
      { "0": 0, "1": 12_000, "3": 80_000 },
    );
    const d = doc(buildLss(file));
    expect(names(d)).toEqual(["Depth 1", "Depth 2", "Depth 3"]);
    expect(d.querySelector("Run > CategoryName")!.textContent).toBe(
      "Pool Name",
    );
    const vars = [...d.querySelectorAll("CustomVariables > Variable")];
    expect(vars.map((v) => v.getAttribute("name"))).toEqual([
      "SpeedFog category",
    ]);
    expect(vars[0].textContent).toBe("pool@12");
    expect(comparison(d, "Personal Best")).toEqual([
      "00:00:12.0000000",
      null,
      "00:01:20.0000000",
    ]);
    expect(golds(d)).toEqual(["00:00:12.0000000", null, null]);
  });

  it("has empty comparisons without board data", () => {
    const d = doc(buildLss(categoryLssFile("pool", "Pool", 2, null, null)));
    expect(comparison(d, "SpeedFog WR")).toEqual([null, null]);
    expect(golds(d)).toEqual([null, null]);
  });
});

describe("splitTimesFromEntries", () => {
  it("puts the finish on the last segment", () => {
    expect(splitTimesFromEntries({ "0": 0, "1": 5000, "3": 12000 }, 3)).toEqual(
      [5000, null, 12000],
    );
  });
});

describe("segmentTimes", () => {
  it("differences the cumulative times, unknown around a gap", () => {
    expect(segmentTimes([10, 30, null, 90])).toEqual([10, 20, null, null]);
  });

  it("is unknown when the clock went back", () => {
    expect(segmentTimes([30, 20])).toEqual([30, null]);
  });
});

describe("lssFileName", () => {
  it("names seed and category files, dropping characters unsafe in a name", () => {
    const seedFile = seedLssFile(seed([run("r", "u1", 70_000, DIRECT)]), null)!;
    expect(lssFileName(seedFile)).toBe("SpeedFog - Pool Name - Seed 42.lss");
    expect(lssFileName(categoryLssFile("p", "A/B: C", 2, null, null))).toBe(
      "SpeedFog - A B C.lss",
    );
  });
});
