import { describe, it, expect } from "vitest";
import { formatElapsed, formatCountdown } from "$lib/cast/clock";

describe("formatElapsed", () => {
  it("counts minutes and seconds under an hour", () => {
    expect(formatElapsed(42 * 60_000 + 19_000)).toBe("42:19");
  });

  it("adds the hours once there are any", () => {
    expect(formatElapsed(3_600_000 + 5 * 60_000 + 7_000)).toBe("1:05:07");
  });

  it("shows zero rather than a negative clock before the start", () => {
    expect(formatElapsed(-5000)).toBe("0:00");
  });
});

describe("formatCountdown", () => {
  it("counts down in minutes and seconds", () => {
    expect(formatCountdown(77 * 60_000 + 41_000)).toBe("1:17:41");
  });

  it("stops at zero instead of going negative once the race is over", () => {
    expect(formatCountdown(-1)).toBe("0:00");
  });

  it("returns null when the race has no end to count to", () => {
    expect(formatCountdown(null)).toBeNull();
  });
});
