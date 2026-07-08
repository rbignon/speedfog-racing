import { describe, expect, it } from "vitest";
import type { ContentItem } from "$lib/content/types";
import {
  skipCountForZones,
  skipsForZones,
  zoneTipsForZones,
} from "$lib/content/zones";

describe("zone selectors", () => {
  const catalog: ContentItem[] = [
    {
      id: "s1",
      kind: "skip",
      zoneId: "stormveil_gate",
      legality: "legal",
      title: "s1",
      short: "s1",
    },
    {
      id: "s2",
      kind: "skip",
      zoneId: "leyndell",
      legality: "banned",
      title: "s2",
      short: "s2",
    },
    {
      id: "t1",
      kind: "tip",
      level: "beginner",
      zoneId: "stormveil",
      title: "t1",
      short: "t1",
    },
    { id: "t2", kind: "tip", level: "beginner", title: "t2", short: "t2" },
  ];

  it("matches skips whose zoneId is a member of the cluster's zones", () => {
    expect(
      skipsForZones(["stormveil", "stormveil_gate"], catalog).map((s) => s.id),
    ).toEqual(["s1"]);
    expect(skipCountForZones(["stormveil", "stormveil_gate"], catalog)).toBe(1);
    expect(skipCountForZones(["moonlight_altar"], catalog)).toBe(0);
  });

  it("returns an empty result for an empty zones array", () => {
    expect(skipsForZones([], catalog)).toEqual([]);
    expect(zoneTipsForZones([], catalog)).toEqual([]);
    expect(skipCountForZones([], catalog)).toBe(0);
  });

  it("keeps tips and skips separate: a zone id shared by both kinds only surfaces its own kind", () => {
    expect(zoneTipsForZones(["stormveil"], catalog).map((t) => t.id)).toEqual([
      "t1",
    ]);
    expect(skipsForZones(["stormveil"], catalog)).toEqual([]);
  });
});
