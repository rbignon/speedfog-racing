import { describe, it, expect } from "vitest";
import { raceItemsAvailability } from "../raceItems";
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
