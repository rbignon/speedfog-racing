import { describe, it, expect } from "vitest";
import { preserveDailyPoints } from "$lib/stores/race.svelte";

describe("preserveDailyPoints", () => {
  type P = { id: string; daily_points?: number | null };

  it("restores the previous points when the incoming message drops them", () => {
    const incoming: P = { id: "a", daily_points: null };
    expect(preserveDailyPoints(incoming, 42)).toEqual({
      id: "a",
      daily_points: 42,
    });
  });

  it("restores when the incoming field is undefined", () => {
    const incoming: P = { id: "a" };
    expect(preserveDailyPoints(incoming, 42).daily_points).toBe(42);
  });

  it("keeps the incoming points when present (does not override)", () => {
    const incoming: P = { id: "a", daily_points: 10 };
    expect(preserveDailyPoints(incoming, 42)).toBe(incoming);
  });

  it("treats 0 as a real incoming value, not a missing one", () => {
    const incoming: P = { id: "a", daily_points: 0 };
    expect(preserveDailyPoints(incoming, 42).daily_points).toBe(0);
  });

  it("passes through unchanged when there is nothing to restore", () => {
    const incoming: P = { id: "a", daily_points: null };
    expect(preserveDailyPoints(incoming, null)).toBe(incoming);
    expect(preserveDailyPoints(incoming, undefined)).toBe(incoming);
  });
});
