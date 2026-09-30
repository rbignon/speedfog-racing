import { describe, expect, it } from "vitest";
import type { ContentItem } from "$lib/content/types";
import {
  gameChangesForZones,
  skipCountForZones,
  skipsForZones,
  zoneTipsForZones,
} from "$lib/content/zones";

describe("zone selectors", () => {
  const catalog: ContentItem[] = [
    {
      id: "s1",
      kind: "skip",
      zoneIds: ["stormveil_gate"],
      title: "s1",
      short: "s1",
    },
    {
      id: "s2",
      kind: "skip",
      zoneIds: ["leyndell"],
      title: "s2",
      short: "s2",
    },
    {
      id: "t1",
      kind: "tip",
      level: "beginner",
      zoneIds: ["stormveil"],
      title: "t1",
      short: "t1",
    },
    { id: "t2", kind: "tip", level: "beginner", title: "t2", short: "t2" },
    {
      id: "t3",
      kind: "tip",
      level: "beginner",
      zoneIds: ["academy_courtyard", "leyndell_bedchamber"],
      title: "t3",
      short: "t3",
    },
    {
      id: "g1",
      kind: "game_change",
      category: "traversal",
      level: "advanced",
      zoneIds: ["stormveil", "belurat"],
      title: "g1",
      short: "g1",
    },
    {
      id: "g2",
      kind: "game_change",
      category: "combat",
      level: "advanced",
      title: "g2",
      short: "g2",
    },
  ];

  it("matches skips whose zone is a member of the cluster's zones", () => {
    expect(
      skipsForZones(["stormveil", "stormveil_gate"], catalog).map((s) => s.id),
    ).toEqual(["s1"]);
    expect(skipCountForZones(["stormveil", "stormveil_gate"], catalog)).toBe(1);
    expect(skipCountForZones(["moonlight_altar"], catalog)).toBe(0);
  });

  it("returns an empty result for an empty zones array", () => {
    expect(skipsForZones([], catalog)).toEqual([]);
    expect(zoneTipsForZones([], catalog)).toEqual([]);
    expect(gameChangesForZones([], catalog)).toEqual([]);
    expect(skipCountForZones([], catalog)).toBe(0);
  });

  it("matches a multi-zone item through any one of its zones", () => {
    expect(
      zoneTipsForZones(["leyndell", "leyndell_bedchamber"], catalog).map(
        (t) => t.id,
      ),
    ).toEqual(["t3"]);
    expect(
      gameChangesForZones(["belurat", "belurat_swamp"], catalog).map(
        (g) => g.id,
      ),
    ).toEqual(["g1"]);
  });

  it("keeps kinds separate: a zone shared by several kinds only surfaces the kind asked for", () => {
    expect(zoneTipsForZones(["stormveil"], catalog).map((t) => t.id)).toEqual([
      "t1",
    ]);
    expect(
      gameChangesForZones(["stormveil"], catalog).map((g) => g.id),
    ).toEqual(["g1"]);
    expect(skipsForZones(["stormveil"], catalog)).toEqual([]);
  });
});
