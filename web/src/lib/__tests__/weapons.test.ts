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
  it("sorts desc by ticks and annotates percent against the input total", () => {
    const out = topCombos(
      [
        { ids: [1], ticks: 30 },
        { ids: [2], ticks: 60 },
        { ids: [3], ticks: 10 },
      ],
      2,
    );
    expect(out).toEqual([
      { ids: [2], ticks: 60, percent: 60 },
      { ids: [1], ticks: 30, percent: 30 },
    ]);
  });

  it("returns empty for empty input", () => {
    expect(topCombos([], 3)).toEqual([]);
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
