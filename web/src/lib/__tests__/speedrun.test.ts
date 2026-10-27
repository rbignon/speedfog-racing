import { describe, it, expect } from "vitest";
import type { SpeedrunCategory } from "$lib/api";
import {
  RUN_TYPES,
  historyPolyline,
  parseSpeedrunParams,
  resolveCategory,
  speedrunRaceHref,
  speedrunTimeParts,
  toggleRunType,
  writeSpeedrunParams,
  type SpeedrunParams,
} from "$lib/speedrun";

const DEFAULTS: SpeedrunParams = {
  pool: null,
  sub: "any",
  types: ["race", "daily", "event"],
  obsolete: false,
  view: "board",
};

function params(overrides: Partial<SpeedrunParams>): SpeedrunParams {
  return { ...DEFAULTS, ...overrides };
}

function cat(
  pool: string,
  subcategories: SpeedrunCategory["subcategories"],
): SpeedrunCategory {
  return {
    pool,
    name: pool,
    retired: false,
    subcategories,
    description: null,
    estimated_duration: null,
    rules: null,
  };
}

function rec(t: number, igt: number) {
  return { finished_at: new Date(t).toISOString(), igt_ms: igt };
}

describe("speedrunTimeParts", () => {
  it("shows minutes and padded seconds under an hour", () => {
    expect(speedrunTimeParts(1_303_998)).toEqual([
      { value: "21", unit: "m" },
      { value: "43", unit: "s" },
    ]);
    expect(speedrunTimeParts(65_000)).toEqual([
      { value: "1", unit: "m" },
      { value: "05", unit: "s" },
    ]);
    expect(speedrunTimeParts(3_599_999)).toEqual([
      { value: "59", unit: "m" },
      { value: "59", unit: "s" },
    ]);
  });

  it("shows hours with padded minutes and seconds", () => {
    expect(speedrunTimeParts(3_600_000)).toEqual([
      { value: "1", unit: "h" },
      { value: "00", unit: "m" },
      { value: "00", unit: "s" },
    ]);
    expect(speedrunTimeParts(3_750_000)).toEqual([
      { value: "1", unit: "h" },
      { value: "02", unit: "m" },
      { value: "30", unit: "s" },
    ]);
  });
});

describe("speedrunRaceHref", () => {
  it("links a Daily Seed to its day and any other race to its page", () => {
    expect(speedrunRaceHref({ race_id: "r1", daily_date: "2026-08-08" })).toBe(
      "/daily/2026-08-08",
    );
    expect(speedrunRaceHref({ race_id: "r1", daily_date: null })).toBe(
      "/race/r1",
    );
  });
});

describe("parseSpeedrunParams", () => {
  it("returns the defaults for an empty query", () => {
    expect(parseSpeedrunParams(new URLSearchParams(""))).toEqual(DEFAULTS);
  });

  it("reads every key and orders types canonically", () => {
    expect(
      parseSpeedrunParams(
        new URLSearchParams(
          "pool=boss_rush&sub=deathless&types=daily,race&obsolete=1&view=history",
        ),
      ),
    ).toEqual({
      pool: "boss_rush",
      sub: "deathless",
      types: ["race", "daily"],
      obsolete: true,
      view: "history",
    });
  });

  it("falls back to the defaults on garbage", () => {
    expect(
      parseSpeedrunParams(
        new URLSearchParams("types=foo,,bar&sub=x&view=y&obsolete=yes"),
      ),
    ).toEqual(DEFAULTS);
  });
});

describe("writeSpeedrunParams", () => {
  it("omits default values and keeps the tab", () => {
    const url = new URL("http://x/stats?tab=speedrun&pool=old&obsolete=1");
    writeSpeedrunParams(url, DEFAULTS);
    expect(url.search).toBe("?tab=speedrun");
  });

  it("round-trips non-default values", () => {
    const url = new URL("http://x/stats?tab=speedrun");
    const p = params({
      pool: "sprint",
      sub: "deathless",
      types: ["race", "event"],
      obsolete: true,
      view: "history",
    });
    writeSpeedrunParams(url, p);
    expect(parseSpeedrunParams(url.searchParams)).toEqual(p);
    expect(url.searchParams.get("tab")).toBe("speedrun");
  });
});

describe("resolveCategory", () => {
  const cats = [cat("sprint", ["any"]), cat("dl", ["deathless"])];

  it("falls back to the first category for an unknown pool", () => {
    expect(resolveCategory(params({ pool: "nope" }), cats)).toEqual({
      pool: "sprint",
      sub: "any",
    });
  });

  it("falls back to the pool's first subcategory when it lacks the asked one", () => {
    expect(resolveCategory(params({ pool: "dl", sub: "any" }), cats)).toEqual({
      pool: "dl",
      sub: "deathless",
    });
  });

  it("returns null without categories", () => {
    expect(resolveCategory(params({}), [])).toBeNull();
  });
});

describe("toggleRunType", () => {
  it("removes and adds a type in canonical order, never emptying the set", () => {
    expect(toggleRunType([...RUN_TYPES], "daily")).toEqual(["race", "event"]);
    expect(toggleRunType(["race"], "race")).toEqual(["race"]);
    expect(toggleRunType(["event"], "race")).toEqual(["race", "event"]);
  });
});

describe("historyPolyline", () => {
  it("is empty without records", () => {
    expect(historyPolyline([], 100)).toEqual([]);
  });

  it("runs a single record flat until now", () => {
    expect(historyPolyline([rec(10, 500)], 100)).toEqual([
      [10, 500],
      [100, 500],
    ]);
  });

  it("steps down at each new record", () => {
    expect(historyPolyline([rec(10, 500), rec(40, 450)], 100)).toEqual([
      [10, 500],
      [40, 500],
      [40, 450],
      [100, 450],
    ]);
  });
});
