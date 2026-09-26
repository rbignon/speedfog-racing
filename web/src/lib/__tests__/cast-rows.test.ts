import { describe, it, expect } from "vitest";
import { rowCapacity, planRows, capRows } from "$lib/cast/rows";

describe("rowCapacity", () => {
  it("floors to a whole number of rows, never a fraction", () => {
    // (230 - 32) / 45 = 4.4
    expect(rowCapacity(230, 32, 45)).toBe(4);
  });

  it("returns 0 rather than a negative count when the header alone doesn't fit", () => {
    expect(rowCapacity(20, 32, 45)).toBe(0);
  });

  it("fits exactly when the height divides evenly", () => {
    expect(rowCapacity(198 + 32, 32, 33)).toBe(6);
  });
});

describe("planRows", () => {
  it("shows everything and reports no overflow when the field fits", () => {
    const plan = planRows(["a", "b", "c"], 4);
    expect(plan.visible).toEqual(["a", "b", "c"]);
    expect(plan.hiddenCount).toBe(0);
  });

  it("shows everything with none left over when the field exactly fills capacity", () => {
    const plan = planRows(["a", "b", "c", "d"], 4);
    expect(plan.visible).toEqual(["a", "b", "c", "d"]);
    expect(plan.hiddenCount).toBe(0);
  });

  it("gives up the last slot to the overflow count once the field exceeds capacity", () => {
    const items = ["a", "b", "c", "d", "e", "f", "g"];
    const plan = planRows(items, 4);
    // 3 shown (capacity - 1), 4 left over.
    expect(plan.visible).toEqual(["a", "b", "c"]);
    expect(plan.hiddenCount).toBe(4);
  });

  it("hides everything rather than going negative when capacity is 0", () => {
    const plan = planRows(["a", "b"], 0);
    expect(plan.visible).toEqual([]);
    expect(plan.hiddenCount).toBe(2);
  });
});

describe("capRows", () => {
  it("shows everything and reports no overflow when the field fits", () => {
    const plan = capRows(["a", "b", "c"], 4);
    expect(plan.visible).toEqual(["a", "b", "c"]);
    expect(plan.hiddenCount).toBe(0);
  });

  it("shows everything with none left over when the field exactly fills capacity", () => {
    const plan = capRows(["a", "b", "c", "d"], 4);
    expect(plan.visible).toEqual(["a", "b", "c", "d"]);
    expect(plan.hiddenCount).toBe(0);
  });

  it("spends every slot on a data row, unlike planRows, once the field exceeds capacity", () => {
    const items = ["a", "b", "c", "d", "e", "f", "g"];
    const plan = capRows(items, 4);
    expect(plan.visible).toEqual(["a", "b", "c", "d"]);
    expect(plan.hiddenCount).toBe(3);
  });

  it("hides everything rather than going negative when capacity is 0", () => {
    const plan = capRows(["a", "b"], 0);
    expect(plan.visible).toEqual([]);
    expect(plan.hiddenCount).toBe(2);
  });
});
