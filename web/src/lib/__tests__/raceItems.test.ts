import { describe, it, expect } from "vitest";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import {
  RACE_ITEMS,
  raceItemTierLine,
  raceItemsAvailability,
} from "../raceItems";
import type { PoolInfo } from "../api";

function pool(race_items_available: number): PoolInfo {
  return {
    available: 5,
    seen: 0,
    speedrun_floor: 0,
    consumed: 0,
    discarded: 0,
    played_by_user: null,
    pool_config: null,
    race_items_available,
  };
}

describe("raceItemsAvailability", () => {
  it("enables the option on a normal race when the pool has plugin seeds", () => {
    expect(raceItemsAvailability("normal", pool(3))).toEqual({
      enabled: true,
      hint: null,
    });
  });

  it("disables it with a hint when the pool has none", () => {
    const r = raceItemsAvailability("normal", pool(0));
    expect(r.enabled).toBe(false);
    expect(r.hint).toBe("No seed with race items in this pool yet");
  });

  it("is disabled outside the normal mode", () => {
    expect(raceItemsAvailability("speedrun", pool(3)).enabled).toBe(false);
    expect(raceItemsAvailability("set_seed", pool(3)).enabled).toBe(false);
  });

  it("is disabled for an unknown pool", () => {
    expect(raceItemsAvailability("normal", undefined).enabled).toBe(false);
  });
});

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
