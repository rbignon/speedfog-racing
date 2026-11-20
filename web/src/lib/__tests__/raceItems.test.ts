import { describe, it, expect } from "vitest";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { RACE_ITEMS, raceItemTierLine } from "../raceItems";

describe("RACE_ITEMS", () => {
  it("lists each item once", () => {
    const keys = RACE_ITEMS.map((i) => i.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("gives every item a tier and an icon file", () => {
    for (const item of RACE_ITEMS) {
      expect(item.tiers.length, item.key).toBeGreaterThan(0);
      // Vitest runs from web/.
      const icon = resolve("static/race_items", `${item.key}.png`);
      expect(existsSync(icon), icon).toBe(true);
    }
  });
});

describe("raceItemTierLine", () => {
  it("names a single tier", () => {
    expect(raceItemTierLine(["back"])).toBe("Drawn at the back of the race.");
  });

  it("joins two tiers with 'and'", () => {
    expect(raceItemTierLine(["middle", "back"])).toBe(
      "Drawn in the middle and at the back of the race.",
    );
  });

  it("joins three tiers with a comma then 'and'", () => {
    expect(raceItemTierLine(["front", "middle", "back"])).toBe(
      "Drawn at the front, in the middle and at the back of the race.",
    );
  });

  it("says nothing without a tier", () => {
    expect(raceItemTierLine([])).toBe("");
  });
});
