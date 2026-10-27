import { describe, it, expect } from "vitest";
import { dateTicks, nearestPoint, timeTicks } from "$lib/speedrun-chart";

const MINUTE = 60_000;

describe("timeTicks", () => {
  it("picks the smallest round step that keeps at most five intervals", () => {
    // Boss Rush records: 26m 25s down to 20m 41s.
    const { min, max, ticks } = timeTicks(1_241_715, 1_585_561);
    expect([min, max]).toEqual([20 * MINUTE, 28 * MINUTE]);
    expect(ticks).toEqual([20, 22, 24, 26, 28].map((m) => m * MINUTE));
  });

  it("steps by hours on hour-long categories", () => {
    // Expedition-like records: 1h 41m to 2h 15m.
    const { ticks } = timeTicks(6_060_000, 8_100_000);
    expect(ticks).toEqual([100, 110, 120, 130, 140].map((m) => m * MINUTE));
  });

  it("frames a single record strictly inside the axis", () => {
    const value = 46 * MINUTE + 40_000;
    const { min, max, ticks } = timeTicks(value, value);
    expect(min).toBeLessThan(value);
    expect(max).toBeGreaterThan(value);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
  });
});

describe("dateTicks", () => {
  const local = (y: number, m: number, d: number) =>
    new Date(y, m, d).getTime();

  it("uses month starts, skipping months to stay under the tick budget", () => {
    const ticks = dateTicks(local(2026, 1, 17), local(2026, 9, 27));
    expect(ticks.map((t) => t.label)).toEqual(["Mar", "May", "Jul", "Sep"]);
    expect(ticks[0].time).toBe(local(2026, 2, 1));
  });

  it("names the year on January", () => {
    const ticks = dateTicks(local(2026, 10, 10), local(2027, 2, 20));
    expect(ticks.map((t) => t.label)).toEqual([
      "Dec",
      "Jan 2027",
      "Feb",
      "Mar",
    ]);
  });

  it("keeps several labels over a two-week span", () => {
    const ticks = dateTicks(
      new Date(2026, 9, 1, 10).getTime(),
      new Date(2026, 9, 14, 10).getTime(),
    );
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks.length).toBeLessThanOrEqual(6);
  });

  it("honours a smaller tick budget on a narrow chart", () => {
    const ticks = dateTicks(local(2026, 1, 17), local(2026, 9, 27), 3);
    expect(ticks.map((t) => t.label)).toEqual(["Apr", "Jul", "Oct"]);
  });

  it("still labels the axis when no step fits the budget", () => {
    const ticks = dateTicks(local(2026, 0, 2), local(2033, 0, 5));
    expect(ticks.length).toBeGreaterThan(0);
  });

  it("falls back to days over a short span, on calendar-stable days", () => {
    // Day steps align on the day count since the epoch, so a tick does not
    // move when the range shifts by a day.
    const ticks = dateTicks(local(2026, 9, 20), local(2026, 9, 27));
    expect(ticks.map((t) => t.label)).toEqual([
      "Oct 20",
      "Oct 22",
      "Oct 24",
      "Oct 26",
    ]);
  });
});

describe("nearestPoint", () => {
  it("returns the closest point in both axes, the earlier one on a tie", () => {
    const points: [number, number][] = [
      [10, 50],
      [20, 50],
      [40, 50],
    ];
    expect(nearestPoint(points, 33, 50)).toBe(2);
    expect(nearestPoint(points, 15, 50)).toBe(0);
    expect(nearestPoint([], 15, 0)).toBe(-1);
  });

  it("reaches a record stacked between two others on the same day", () => {
    // Three records set within hours: nearly the same x, different times.
    const points: [number, number][] = [
      [76, 20],
      [76.04, 60],
      [76.19, 100],
    ];
    expect(nearestPoint(points, 76, 62)).toBe(1);
  });
});
