import { describe, it, expect } from "vitest";
import { buildCastLog } from "$lib/cast/log";

// zone_history entries carry the node id and the IGT at which it was entered
// (see ZoneHistoryEntry in $lib/zone-history), so the log resolves the name
// through the seed's node map.
const names = new Map([
  ["n1", "Stormveil Castle"],
  ["n2", "Liurnia of the Lakes"],
  ["n3", "Caelid Catacombs"],
]);

const runner = (
  id: string,
  history: { node: string; igt: number; deaths?: number }[],
  status = "playing",
  igt = 0,
) => ({
  id,
  twitch_username: id,
  twitch_display_name: id,
  color_index: 0,
  status,
  igt_ms: igt,
  zone_history: history.map((h) => ({
    node_id: h.node,
    igt_ms: h.igt,
    deaths: h.deaths,
  })),
});

describe("buildCastLog", () => {
  it("merges every runner's history newest first", () => {
    const rows = buildCastLog(
      [
        runner("a", [{ node: "n1", igt: 1000 }]),
        runner("b", [{ node: "n2", igt: 2000 }]),
      ],
      names,
      10,
    );
    expect(rows.map((r) => r.zone)).toEqual([
      "Liurnia of the Lakes",
      "Stormveil Castle",
    ]);
  });

  it("keeps only the newest entries once past the limit", () => {
    const rows = buildCastLog(
      [
        runner("a", [
          { node: "n1", igt: 1 },
          { node: "n2", igt: 2 },
          { node: "n3", igt: 3 },
        ]),
      ],
      names,
      2,
    );
    expect(rows.map((r) => r.zone)).toEqual([
      "Caelid Catacombs",
      "Liurnia of the Lakes",
    ]);
  });

  it("marks the entries that cost a death", () => {
    const rows = buildCastLog(
      [runner("a", [{ node: "n3", igt: 5, deaths: 2 }])],
      names,
      10,
    );
    expect(rows[0].deaths).toBe(2);
  });

  it("falls back to the node id when the seed does not name it", () => {
    const rows = buildCastLog(
      [runner("a", [{ node: "unknown", igt: 5 }])],
      names,
      10,
    );
    expect(rows[0].zone).toBe("unknown");
  });

  it("survives a runner whose history has not arrived yet", () => {
    const rows = buildCastLog(
      [{ ...runner("a", []), zone_history: null }],
      names,
      10,
    );
    expect(rows).toEqual([]);
  });

  // A race's outcomes are its biggest moments, and zone_history carries none
  // of them: each one is logged at the runner's own final IGT.
  it("logs a finish at the runner's final time", () => {
    const rows = buildCastLog(
      [
        runner("a", [{ node: "n1", igt: 1000 }], "finished", 3000),
        runner("b", [{ node: "n2", igt: 2000 }]),
      ],
      names,
      10,
    );
    expect(rows.map((r) => [r.kind, r.id, r.igtMs])).toEqual([
      ["finish", "a", 3000],
      ["zone", "b", 2000],
      ["zone", "a", 1000],
    ]);
  });

  it("logs a DNF and a DQ", () => {
    const rows = buildCastLog(
      [
        runner("a", [{ node: "n1", igt: 1000 }], "abandoned", 4000),
        runner("b", [{ node: "n2", igt: 2000 }], "disqualified", 3000),
      ],
      names,
      10,
    );
    expect(rows.map((r) => [r.kind, r.id, r.igtMs])).toEqual([
      ["dnf", "a", 4000],
      ["dq", "b", 3000],
      ["zone", "b", 2000],
      ["zone", "a", 1000],
    ]);
  });

  it("puts an outcome above an entry at the same time", () => {
    const rows = buildCastLog(
      [
        runner("a", [{ node: "n1", igt: 3000 }]),
        runner("b", [{ node: "n2", igt: 1000 }], "finished", 3000),
      ],
      names,
      10,
    );
    expect(rows.map((r) => [r.kind, r.id])).toEqual([
      ["finish", "b"],
      ["zone", "a"],
      ["zone", "b"],
    ]);
  });

  it("logs no outcome for a runner still racing", () => {
    const rows = buildCastLog(
      [runner("a", [{ node: "n1", igt: 1000 }], "playing", 5000)],
      names,
      10,
    );
    expect(rows.map((r) => r.kind)).toEqual(["zone"]);
  });
});
