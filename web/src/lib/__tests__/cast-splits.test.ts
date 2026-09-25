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

  it("keeps three completed splits at exactly four entries (trim is a no-op)", () => {
    // Four entries -> exactly three completed splits, the boundary where
    // `.slice(-MAX_SPLITS)` must not drop anything.
    const rows = buildCastSplits(
      [entry("n1", 0), entry("n2", 1000), entry("n3", 3000), entry("n4", 6000)],
      names,
    );
    expect(rows.map((r) => r.zone)).toEqual([
      "Caelid Catacombs",
      "Liurnia of the Lakes",
      "Stormveil Castle",
    ]);
    expect(rows.map((r) => r.durationMs)).toEqual([3000, 2000, 1000]);
  });

  it("shortens a region-prefixed name the same way RunnerCard's current-zone line does", () => {
    // Real seed data resolves a node to a whole route label, not a short
    // zone name (docs/superpowers/sdd fix round 1 finding): the region
    // prefix must be stripped, and a name still over 20 chars truncated with
    // an ellipsis, exactly like RunnerCard.zoneLabel does for current_zone.
    const routeNames = new Map([
      ["w", "Caelid - Gael Tunnel - Magma Wyrm"],
      ["x", "Gravesite Plain - Fog Rift Catacombs - Death Knight"],
      ["y", "Gravesite Plain - Belurat Gaol - Demi-Human Swordmaster Onze"],
    ]);
    const rows = buildCastSplits(
      [
        entry("w", 0),
        entry("x", 54_000),
        entry("y", 78_000),
        entry("z", 101_000),
      ],
      routeNames,
    );
    expect(rows.map((r) => r.zone)).toEqual([
      "Demi-Human Swordmas…",
      "Death Knight",
      "Magma Wyrm",
    ]);
    expect(rows.map((r) => r.durationMs)).toEqual([23_000, 24_000, 54_000]);
    // No row's zone name is longer than the panel can show on one line.
    for (const row of rows) {
      expect(row.zone.length).toBeLessThanOrEqual(20);
    }
  });
});
