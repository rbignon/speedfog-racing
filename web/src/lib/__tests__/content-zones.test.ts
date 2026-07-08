import { describe, expect, it } from "vitest";
import type { ContentItem } from "$lib/content/types";
import {
  skipsForZone,
  skipCountForZone,
  zoneKeyOf,
  zoneTipsForZone,
} from "$lib/content/zones";

describe("zoneKeyOf", () => {
  it("strips a trailing 4-hex cluster hash", () => {
    expect(zoneKeyOf("stormveil_c3d4")).toBe("stormveil");
    expect(zoneKeyOf("graveyard_cave_e235")).toBe("graveyard_cave");
  });

  it("leaves ids without a hash suffix untouched", () => {
    expect(zoneKeyOf("stormveil")).toBe("stormveil");
    expect(zoneKeyOf("cave_of_knowledge")).toBe("cave_of_knowledge");
  });
});

describe("zone selectors", () => {
  const catalog: ContentItem[] = [
    {
      id: "s1",
      kind: "skip",
      zoneKey: "stormveil",
      legality: "legal",
      title: "s1",
      short: "s1",
    },
    {
      id: "s2",
      kind: "skip",
      zoneKey: "leyndell",
      legality: "banned",
      title: "s2",
      short: "s2",
    },
    {
      id: "t1",
      kind: "tip",
      level: "beginner",
      zoneKey: "stormveil",
      title: "t1",
      short: "t1",
    },
    { id: "t2", kind: "tip", level: "beginner", title: "t2", short: "t2" },
  ];

  it("matches skips by hash-stripped node id", () => {
    expect(skipsForZone("stormveil_c3d4", catalog).map((s) => s.id)).toEqual([
      "s1",
    ]);
    expect(skipCountForZone("stormveil_c3d4", catalog)).toBe(1);
    expect(skipCountForZone("moonlight_altar_9f2a", catalog)).toBe(0);
  });

  it("returns zone-keyed tips only", () => {
    expect(zoneTipsForZone("stormveil_c3d4", catalog).map((t) => t.id)).toEqual(
      ["t1"],
    );
  });
});
