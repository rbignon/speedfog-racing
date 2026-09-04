import { describe, expect, it } from "vitest";
import type { ContentItem } from "$lib/content/types";
import {
  EXPERIENCED_RUNS,
  isExperiencedPlayer,
  loadSeenTipIds,
  markTipSeen,
  orderTickerItems,
  SEEN_STORAGE_KEY,
} from "$lib/content/select";

function item(id: string, extra: Partial<ContentItem> = {}): ContentItem {
  return { id, kind: "tip", level: "beginner", title: id, short: id, ...extra };
}

function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    dump: () => data,
  };
}

describe("orderTickerItems", () => {
  it("excludes pool-tagged items when the pool does not match", () => {
    const items = [item("a"), item("b", { pools: ["hardcore"] })];
    expect(
      orderTickerItems(items, { poolName: "standard", seenIds: new Set() }).map(
        (i) => i.id,
      ),
    ).toEqual(["a"]);
    expect(
      orderTickerItems(items, { poolName: null, seenIds: new Set() }).map(
        (i) => i.id,
      ),
    ).toEqual(["a"]);
  });

  it("ranks matching pool-tagged items first", () => {
    const items = [item("a"), item("b", { pools: ["hardcore"] })];
    const ordered = orderTickerItems(items, {
      poolName: "hardcore",
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["b", "a"]);
  });

  it("ranks unseen items before recently seen ones", () => {
    const items = [item("a"), item("b")];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(["a"]),
    });
    expect(ordered.map((i) => i.id)).toEqual(["b", "a"]);
  });

  it("still returns every eligible item when all are seen", () => {
    const items = [item("a"), item("b")];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(["a", "b"]),
    });
    expect(ordered).toHaveLength(2);
  });

  it("ranks beginner tips before advanced ones, all else equal", () => {
    const items = [item("adv", { level: "advanced" }), item("beg")];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["beg", "adv"]);
  });

  it("drops beginner tips and game changes entirely for an experienced player", () => {
    const items = [
      item("beg"),
      item("beg-change", { kind: "game_change", category: "start" }),
      item("adv", { level: "advanced" }),
      item("adv-change", {
        kind: "game_change",
        category: "qol",
        level: "advanced",
      }),
    ];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(),
      experienced: true,
    });
    expect(ordered.map((i) => i.id).sort()).toEqual(["adv", "adv-change"]);
  });

  it("ranks a beginner game change above an advanced tip for a newcomer", () => {
    const items = [
      item("adv", { level: "advanced" }),
      item("beg-change", { kind: "game_change", category: "start" }),
    ];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["beg-change", "adv"]);
  });

  it("lets an unseen advanced tip beat a seen beginner one for a newcomer too", () => {
    const items = [item("beg"), item("adv", { level: "advanced" })];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(["beg"]),
    });
    expect(ordered.map((i) => i.id)).toEqual(["adv", "beg"]);
  });

  it("never rotates zone-scoped tips (they belong to the zone sheet)", () => {
    const items = [item("a"), item("zoned", { zoneId: "deeproot_boss" })];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["a"]);
  });

  it("drops a pool-tagged beginner item for an experienced player even in that pool", () => {
    // Mode-specific basics are still basics: an experienced player gets the
    // mode rules from the race card, not from the ticker.
    const items = [
      item("pooled-basic", { pools: ["hardcore"] }),
      item("adv", { level: "advanced" }),
    ];
    const ordered = orderTickerItems(items, {
      poolName: "hardcore",
      seenIds: new Set(),
      experienced: true,
    });
    expect(ordered.map((i) => i.id)).toEqual(["adv"]);
  });

  it("shuffles equal-score items with the provided rng", () => {
    const items = [item("a"), item("b"), item("c")];
    const ctx = { poolName: null, seenIds: new Set<string>() };
    const withLowRng = orderTickerItems(items, ctx, () => 0);
    const withHighRng = orderTickerItems(items, ctx, () => 0.999);
    expect(withLowRng.map((i) => i.id)).not.toEqual(
      withHighRng.map((i) => i.id),
    );
    for (const ordered of [withLowRng, withHighRng]) {
      expect(new Set(ordered.map((i) => i.id))).toEqual(
        new Set(["a", "b", "c"]),
      );
    }
  });

  it("never rotates kind 'skip' items, even when they would otherwise match", () => {
    const items = [
      item("a"),
      {
        id: "skip1",
        kind: "skip" as const,
        zoneId: "stormveil",
        title: "skip1",
        short: "skip1",
      },
    ];
    const ordered = orderTickerItems(items, {
      poolName: null,
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["a"]);
  });

  it("excludes a skip even when its pools tag matches the current pool", () => {
    const items = [
      item("a"),
      {
        id: "skip1",
        kind: "skip" as const,
        zoneId: "stormveil",
        title: "skip1",
        short: "skip1",
        pools: ["hardcore"],
      },
    ];
    const ordered = orderTickerItems(items, {
      poolName: "hardcore",
      seenIds: new Set(),
    });
    expect(ordered.map((i) => i.id)).toEqual(["a"]);
  });

  it("keeps the weighting dominant over the shuffle", () => {
    const items = [
      item("a"),
      item("b"),
      item("pooled", { pools: ["hardcore"] }),
    ];
    const ctx = { poolName: "hardcore", seenIds: new Set<string>(["a", "b"]) };
    for (const rng of [() => 0, () => 0.5, () => 0.999]) {
      const ordered = orderTickerItems(items, ctx, rng);
      expect(ordered[0].id).toBe("pooled");
    }
  });
});

describe("isExperiencedPlayer", () => {
  it("treats a logged-out or brand-new player as a newcomer", () => {
    expect(isExperiencedPlayer(null)).toBe(false);
    expect(
      isExperiencedPlayer({ race_count: 0, daily_count: 0, training_count: 0 }),
    ).toBe(false);
  });

  it("adds races, dailies and solos together before comparing to the threshold", () => {
    const spread = {
      race_count: 1,
      daily_count: 1,
      training_count: EXPERIENCED_RUNS - 2,
    };
    expect(
      isExperiencedPlayer({
        ...spread,
        training_count: spread.training_count - 1,
      }),
    ).toBe(false);
    expect(isExperiencedPlayer(spread)).toBe(true);
  });

  it("tolerates a cached user object from before the counts existed", () => {
    expect(isExperiencedPlayer({})).toBe(false);
  });
});

describe("seen-recently persistence", () => {
  it("returns an empty set without storage or with malformed JSON", () => {
    expect(loadSeenTipIds(null).size).toBe(0);
    const storage = fakeStorage({ [SEEN_STORAGE_KEY]: "not json" });
    expect(loadSeenTipIds(storage).size).toBe(0);
  });

  it("round-trips marked ids through storage", () => {
    const storage = fakeStorage();
    markTipSeen(storage, "a");
    markTipSeen(storage, "b");
    expect(loadSeenTipIds(storage)).toEqual(new Set(["a", "b"]));
  });

  it("dedupes and caps the stored list at 40, dropping oldest first", () => {
    const storage = fakeStorage();
    for (let i = 0; i < 45; i++) markTipSeen(storage, `tip-${i}`);
    markTipSeen(storage, "tip-44");
    const seen = loadSeenTipIds(storage);
    expect(seen.size).toBe(40);
    expect(seen.has("tip-0")).toBe(false);
    expect(seen.has("tip-44")).toBe(true);
  });
});
