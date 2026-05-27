import { describe, expect, it } from "vitest";
import type { ZoneHistoryEntry } from "$lib/zone-history";
import {
  aggregateAllCombos,
  aggregateZoneCombos,
  formatCombo,
  topCombos,
} from "$lib/weapons";

const ENTRY = (
  node_id: string,
  weapons: { ids: number[]; ticks: number }[] | undefined,
): ZoneHistoryEntry => ({ node_id, igt_ms: 0, weapons });

describe("aggregateAllCombos", () => {
  it("sums ticks per ids tuple across entries", () => {
    const history: ZoneHistoryEntry[] = [
      ENTRY("a", [{ ids: [2000025], ticks: 5 }]),
      ENTRY("b", [
        { ids: [2000025], ticks: 3 },
        { ids: [3070000, 2000025], ticks: 1 },
      ]),
    ];
    expect(aggregateAllCombos(history)).toEqual([
      { ids: [2000025], ticks: 8 },
      { ids: [3070000, 2000025], ticks: 1 },
    ]);
  });

  it("treats [X, Y] and [Y, X] as different combos", () => {
    const history: ZoneHistoryEntry[] = [
      ENTRY("a", [{ ids: [3070000, 2000025], ticks: 2 }]),
      ENTRY("b", [{ ids: [2000025, 3070000], ticks: 1 }]),
    ];
    const out = aggregateAllCombos(history);
    expect(out).toHaveLength(2);
  });

  it("ignores entries without weapons", () => {
    const history: ZoneHistoryEntry[] = [
      ENTRY("a", undefined),
      ENTRY("b", [{ ids: [2000025], ticks: 2 }]),
    ];
    expect(aggregateAllCombos(history)).toEqual([{ ids: [2000025], ticks: 2 }]);
  });
});

describe("aggregateZoneCombos", () => {
  it("filters to entries matching the given node_id", () => {
    const history: ZoneHistoryEntry[] = [
      ENTRY("a", [{ ids: [2000025], ticks: 3 }]),
      ENTRY("b", [{ ids: [2000025], ticks: 5 }]),
      ENTRY("a", [{ ids: [2000025], ticks: 2 }]),
    ];
    expect(aggregateZoneCombos(history, "a")).toEqual([
      { ids: [2000025], ticks: 5 },
    ]);
  });
});

describe("topCombos", () => {
  it("sorts desc by ticks and renormalises percent over the kept subset", () => {
    const out = topCombos(
      [
        { ids: [1], ticks: 30 },
        { ids: [2], ticks: 60 },
        { ids: [3], ticks: 10 },
      ],
      2,
    );
    // Kept subset is [60, 30] (sum 90). Percents renormalised to sum to 100.
    expect(out).toEqual([
      { ids: [2], ticks: 60, percent: 67 },
      { ids: [1], ticks: 30, percent: 33 },
    ]);
  });

  it("returns empty for empty input", () => {
    expect(topCombos([], 3)).toEqual([]);
  });

  it("drops combos under minPercent threshold and renormalises to 100", () => {
    const out = topCombos(
      [
        { ids: [1], ticks: 60 },
        { ids: [2], ticks: 30 },
        { ids: [3], ticks: 5 },
        { ids: [4], ticks: 2 },
        { ids: [5], ticks: 2 },
        { ids: [6], ticks: 1 },
      ],
      5,
      5,
    );
    // Only the three combos >= 5% of 100 ticks survive.
    expect(out.map((c) => c.ids[0])).toEqual([1, 2, 3]);
    // Renormalised percentages sum to exactly 100.
    expect(out.reduce((s, c) => s + c.percent, 0)).toBe(100);
  });

  it("returns empty when every combo is below minPercent", () => {
    const out = topCombos(
      [
        { ids: [1], ticks: 1 },
        { ids: [2], ticks: 1 },
        { ids: [3], ticks: 1 },
      ],
      3,
      40,
    );
    expect(out).toEqual([]);
  });

  it("falls back to default behaviour when minPercent is omitted", () => {
    const out = topCombos(
      [
        { ids: [1], ticks: 70 },
        { ids: [2], ticks: 30 },
      ],
      2,
    );
    expect(out).toEqual([
      { ids: [1], ticks: 70, percent: 70 },
      { ids: [2], ticks: 30, percent: 30 },
    ]);
  });
});

describe("formatCombo", () => {
  const naming = (id: number) =>
    id === 2000025
      ? "Longsword"
      : id === 3070000
        ? "Misericorde"
        : `Weapon #${id}`;

  it("renders a single weapon by name", () => {
    expect(formatCombo([2000025], naming)).toBe("Longsword");
  });

  it("renders a dual combo joined with +", () => {
    expect(formatCombo([3070000, 2000025], naming)).toBe(
      "Misericorde + Longsword",
    );
  });

  it("falls back to Weapon #id for unknown ids", () => {
    expect(formatCombo([9999], naming)).toBe("Weapon #9999");
  });
});
