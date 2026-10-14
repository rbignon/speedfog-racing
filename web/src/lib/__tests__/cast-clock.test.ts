import { describe, it, expect } from "vitest";
import {
  formatElapsed,
  formatCountdown,
  formatStartsIn,
  sceneRaceStatus,
} from "$lib/cast/clock";

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

describe("formatStartsIn", () => {
  it("rounds up to the second about to tick, as a countdown reads", () => {
    expect(formatStartsIn(7_400)).toBe("0:08");
    expect(formatStartsIn(7_000)).toBe("0:07");
  });

  it("stops at zero", () => {
    expect(formatStartsIn(-5)).toBe("0:00");
  });
});

describe("sceneRaceStatus", () => {
  const startedAt = "2026-10-14T19:00:10Z";
  const start = Date.parse(startedAt);

  it("keeps a race still counting down to its start in setup", () => {
    expect(sceneRaceStatus("running", startedAt, start - 7_000)).toBe("setup");
  });

  it("runs from the start on", () => {
    expect(sceneRaceStatus("running", startedAt, start)).toBe("running");
    expect(sceneRaceStatus("running", startedAt, start + 60_000)).toBe(
      "running",
    );
  });

  it("trusts a running race whose start it does not know", () => {
    expect(sceneRaceStatus("running", null, start)).toBe("running");
  });

  it("leaves every other status as it is", () => {
    expect(sceneRaceStatus("setup", null, start)).toBe("setup");
    expect(sceneRaceStatus("finished", startedAt, start - 7_000)).toBe(
      "finished",
    );
  });
});
