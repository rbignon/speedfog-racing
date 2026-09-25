import { describe, it, expect } from "vitest";
import { buildCastSplits } from "$lib/cast/splits";

// zone_history entries carry the node id and the IGT at which it was entered
// (see ZoneHistoryEntry in $lib/zone-history); there is no explicit exit
// time, so a split only exists once the next entry confirms when the runner
// left that zone.
const names = new Map([
  ["n1", "Stormveil Castle"],
  ["n2", "Liurnia of the Lakes"],
  ["n3", "Caelid Catacombs"],
  ["n4", "Volcano Manor"],
]);

const entry = (node: string, igt: number) => ({ node_id: node, igt_ms: igt });

describe("buildCastSplits", () => {
  it("returns nothing for a runner with no history", () => {
    expect(buildCastSplits([], names)).toEqual([]);
  });

  it("returns nothing when a history arrives null (not yet bootstrapped)", () => {
    expect(buildCastSplits(null, names)).toEqual([]);
  });

  it("returns nothing with only the current zone known (one entry)", () => {
    expect(buildCastSplits([entry("n1", 1000)], names)).toEqual([]);
  });

  it("pairs consecutive entries into a duration, most recent first", () => {
    // Exactly three entries -> exactly two completed splits, no trimming.
    const rows = buildCastSplits(
      [entry("n1", 0), entry("n2", 5000), entry("n3", 12000)],
      names,
    );
    expect(rows).toEqual([
      { zone: "Liurnia of the Lakes", durationMs: 7000 },
      { zone: "Stormveil Castle", durationMs: 5000 },
    ]);
  });

  it("keeps only the last three splits once there are more", () => {
    // Five entries -> four completed splits; the oldest is dropped.
    const rows = buildCastSplits(
      [
        entry("n1", 0),
        entry("n2", 1000),
        entry("n3", 3000),
        entry("n4", 6000),
        entry("n1", 10000),
      ],
      names,
    );
    expect(rows.map((r) => r.zone)).toEqual([
      "Volcano Manor",
      "Caelid Catacombs",
      "Liurnia of the Lakes",
    ]);
    expect(rows.map((r) => r.durationMs)).toEqual([4000, 3000, 2000]);
  });

  it("resolves an empty zone name when the seed has not named the node yet", () => {
    const rows = buildCastSplits(
      [entry("unknown", 0), entry("n1", 1000)],
      names,
    );
    expect(rows).toEqual([{ zone: "", durationMs: 1000 }]);
  });
});
