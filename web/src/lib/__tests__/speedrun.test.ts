import { describe, it, expect } from "vitest";
import type { SpeedrunCategory, SpeedrunRun } from "$lib/api";
import {
  RUN_TYPES,
  historyPolyline,
  historyTimeline,
  parseSpeedrunParams,
  resolveCategory,
  speedrunAgo,
  speedrunDay,
  speedrunDaysLater,
  speedrunGainParts,
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
    released_at: null,
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
          "pool=boss_rush&sub=deathless&types=daily,race&obsolete=1&view=history-list",
        ),
      ),
    ).toEqual({
      pool: "boss_rush",
      sub: "deathless",
      types: ["race", "daily"],
      obsolete: true,
      view: "history-list",
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
      view: "history-chart",
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

const NOW = Date.UTC(2026, 9, 27, 12, 0, 0);
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const MIN = 60_000;
const DAY = 86_400_000;

describe("speedrunAgo", () => {
  it("counts minutes and hours, singular and plural", () => {
    expect(speedrunAgo(ago(59_000), NOW)).toBe("just now");
    expect(speedrunAgo(ago(MIN), NOW)).toBe("1 minute ago");
    expect(speedrunAgo(ago(59 * MIN), NOW)).toBe("59 minutes ago");
    expect(speedrunAgo(ago(2 * 60 * MIN), NOW)).toBe("2 hours ago");
  });

  it("switches to days, months then years", () => {
    expect(speedrunAgo(ago(DAY), NOW)).toBe("1 day ago");
    expect(speedrunAgo(ago(29 * DAY), NOW)).toBe("29 days ago");
    expect(speedrunAgo(ago(30 * DAY), NOW)).toBe("1 month ago");
    expect(speedrunAgo(ago(364 * DAY), NOW)).toBe("12 months ago");
    expect(speedrunAgo(ago(365 * DAY), NOW)).toBe("1 year ago");
    expect(speedrunAgo(ago(800 * DAY), NOW)).toBe("2 years ago");
  });
});

it("speedrunDaysLater words the gap between two records", () => {
  expect(speedrunDaysLater(0)).toBe("same day");
  expect(speedrunDaysLater(1)).toBe("1 day later");
  expect(speedrunDaysLater(4)).toBe("4 days later");
});

function record(user: string, igt: number, day: number): SpeedrunRun {
  return {
    user: {
      id: user,
      twitch_username: user,
      twitch_display_name: null,
      twitch_avatar_url: null,
    },
    rank: null,
    igt_ms: igt,
    finished_at: new Date(NOW + day * DAY + 3_600_000).toISOString(),
    race_id: `r-${user}-${day}`,
    race_name: "R",
    daily_date: null,
    seed_number: "abc",
    deaths: 0,
    weapon: null,
  };
}

describe("historyTimeline", () => {
  it("tells a new holder from a holder improving their own record", () => {
    const timeline = historyTimeline([
      record("a", 900, 0),
      record("a", 850, 4),
      record("b", 800, 4),
    ]);
    expect(
      timeline.map((e) => [e.kind, e.daysLater, e.improvedBy, e.run.user.id]),
    ).toEqual([
      ["new", null, null, "a"],
      ["improved", 4, null, "a"],
      ["new", 0, 50, "b"],
    ]);
  });

  it("is empty without records", () => {
    expect(historyTimeline([])).toEqual([]);
  });
});

describe("history list dates", () => {
  // Built with the local Date constructor: the list shows the viewer's
  // calendar days, so gaps must be counted in those days, not in 24h steps.
  const local = (day: number, hour: number, minute: number) =>
    new Date(2026, 4, day, hour, minute).toISOString();
  const at = (user: string, igt: number, finished: string): SpeedrunRun => ({
    ...record(user, igt, 0),
    finished_at: finished,
  });

  it("prints the viewer's calendar day", () => {
    expect(speedrunDay(local(4, 23, 30))).toBe("2026-05-04");
  });

  it("counts calendar days between records", () => {
    const acrossMidnight = historyTimeline([
      at("a", 900, local(4, 23, 30)),
      at("b", 800, local(5, 0, 30)),
    ]);
    expect(acrossMidnight[1].daysLater).toBe(1);
    const sameDay = historyTimeline([
      at("a", 900, local(4, 0, 10)),
      at("b", 800, local(4, 23, 50)),
    ]);
    expect(sameDay[1].daysLater).toBe(0);
  });
});

describe("record gains", () => {
  it("match the difference of the times as shown", () => {
    const timeline = historyTimeline([
      record("a", 5_324_900, 0),
      record("b", 4_470_100, 1),
    ]);
    // 1h 28m 44s to 1h 14m 30s: 14m 14s, though the raw gap is 14m 14.8s.
    expect(timeline[1].improvedBy).toBe(854_000);
  });

  it("fall back to milliseconds when the shown times are equal", () => {
    const timeline = historyTimeline([
      record("a", 1_768_380, 0),
      record("b", 1_768_000, 1),
    ]);
    expect(timeline[1].improvedBy).toBe(380);
  });

  it("print milliseconds under a second, speedrun.com minutes otherwise", () => {
    expect(speedrunGainParts(380)).toEqual([{ value: "380", unit: "ms" }]);
    expect(speedrunGainParts(16_000)).toEqual([
      { value: "0", unit: "m" },
      { value: "16", unit: "s" },
    ]);
  });
});
