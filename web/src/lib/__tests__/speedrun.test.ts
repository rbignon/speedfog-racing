import { describe, it, expect } from "vitest";
import type { RunMode, SpeedrunCategory, SpeedrunRun } from "$lib/api";
import {
  RUN_TYPES,
  historyPolyline,
  historyTimeline,
  parseRaceNewParams,
  parseSpeedrunFloor,
  parseSpeedrunOverlayParams,
  parseSpeedrunParams,
  parseStartSeed,
  raceSeedPageHref,
  recentRunParams,
  resolvePool,
  seedPageHref,
  sessionSeedPageHref,
  setSeedRaceNewHref,
  speedrunAgo,
  speedrunDay,
  speedrunDaysLater,
  speedrunGainParts,
  speedrunOverlayRows,
  speedrunOverlayUrl,
  speedrunRunHref,
  speedrunRaceNewHref,
  speedrunSeedHref,
  speedrunTimeParts,
  startRunHref,
  toggleRunType,
  writeSpeedrunParams,
  type SpeedrunOverlayParams,
  type SpeedrunParams,
} from "$lib/speedrun";

const DEFAULTS: SpeedrunParams = {
  pool: null,
  sub: "set",
  deathless: false,
  types: ["race", "daily", "event", "solo"],
  obsolete: false,
  view: "board",
};

function params(overrides: Partial<SpeedrunParams>): SpeedrunParams {
  return { ...DEFAULTS, ...overrides };
}

function cat(pool: string): SpeedrunCategory {
  return {
    pool,
    name: pool,
    retired: false,
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

describe("speedrunRunHref", () => {
  it("links a Daily Seed to its day and any other race to its page", () => {
    expect(
      speedrunRunHref({
        race_id: "r1",
        daily_date: "2026-08-08",
        session_id: null,
      }),
    ).toBe("/daily/2026-08-08");
    expect(
      speedrunRunHref({ race_id: "r1", daily_date: null, session_id: null }),
    ).toBe("/race/r1");
  });

  it("links a solo run to its session", () => {
    expect(
      speedrunRunHref({ race_id: null, daily_date: null, session_id: "s1" }),
    ).toBe("/training/s1");
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
          "pool=boss_rush&sub=random&deathless=1&types=daily,race,solo&obsolete=1&view=history-list",
        ),
      ),
    ).toEqual({
      pool: "boss_rush",
      sub: "random",
      deathless: true,
      types: ["race", "daily", "solo"],
      obsolete: true,
      view: "history-list",
    });
  });

  it("reads the retired Any% and Deathless subcategories as the Set Seed board", () => {
    for (const sub of ["any", "deathless"]) {
      const parsed = parseSpeedrunParams(new URLSearchParams(`sub=${sub}`));
      expect(parsed.sub).toBe("set");
      expect(parsed.deathless).toBe(false);
    }
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
    const url = new URL(
      "http://x/speedrun?x=1&pool=old&obsolete=1&sub=random&deathless=1",
    );
    writeSpeedrunParams(url, DEFAULTS);
    expect(url.search).toBe("?x=1");
  });

  it("round-trips non-default values", () => {
    const url = new URL("http://x/speedrun?x=1");
    const p = params({
      pool: "sprint",
      sub: "random",
      deathless: true,
      types: ["race", "event", "solo"],
      obsolete: true,
      view: "history-chart",
    });
    writeSpeedrunParams(url, p);
    expect(parseSpeedrunParams(url.searchParams)).toEqual(p);
    expect(url.searchParams.get("x")).toBe("1");
  });
});

describe("resolvePool", () => {
  const cats = [cat("sprint"), cat("dl")];

  it("returns the asked pool when it exists", () => {
    expect(resolvePool(params({ pool: "dl" }), cats)).toBe("dl");
  });

  it("falls back to the first category for an unknown or missing pool", () => {
    expect(resolvePool(params({ pool: "nope" }), cats)).toBe("sprint");
    expect(resolvePool(params({}), cats)).toBe("sprint");
  });

  it("returns null without categories", () => {
    expect(resolvePool(params({}), [])).toBeNull();
  });
});

describe("seedPageHref", () => {
  it("links the seed page, focused on a run when one is given", () => {
    expect(seedPageHref("363096a4243f")).toBe("/speedrun/seed/363096a4243f");
    expect(seedPageHref("363096a4243f", null)).toBe(
      "/speedrun/seed/363096a4243f",
    );
    expect(seedPageHref("363096a4243f", "p-1")).toBe(
      "/speedrun/seed/363096a4243f?run=p-1",
    );
  });

  it("encodes the seed and the run id", () => {
    expect(seedPageHref("a/b c", "x&y=1")).toBe(
      "/speedrun/seed/a%2Fb%20c?run=x%26y%3D1",
    );
  });
});

describe("speedrunSeedHref", () => {
  const run = {
    run_id: "p-1",
    race_id: "r1",
    session_id: null,
    daily_date: null,
    seed_number: "363096a4243f",
  } as SpeedrunRun;

  it("opens the seed page on the run, for race, daily and solo runs alike", () => {
    const href = "/speedrun/seed/363096a4243f?run=p-1";
    expect(speedrunSeedHref(run)).toBe(href);
    expect(speedrunSeedHref({ ...run, daily_date: "2026-10-01" })).toBe(href);
    expect(speedrunSeedHref({ ...run, race_id: null, session_id: "p-1" })).toBe(
      href,
    );
  });
});

describe("raceSeedPageHref", () => {
  const race = {
    seed_number: "363096a4243f",
    status: "running",
    mode: "normal" as RunMode,
  };

  it("links a finished race, whatever its mode", () => {
    for (const mode of ["normal", "speedrun", "set_seed"] as RunMode[]) {
      expect(raceSeedPageHref({ ...race, status: "finished", mode })).toBe(
        "/speedrun/seed/363096a4243f",
      );
    }
  });

  it("links a Set Seed race before it finishes: its seed is already public", () => {
    expect(raceSeedPageHref({ ...race, mode: "set_seed" })).toBe(
      "/speedrun/seed/363096a4243f",
    );
    expect(
      raceSeedPageHref({ ...race, status: "setup", mode: "set_seed" }),
    ).toBe("/speedrun/seed/363096a4243f");
  });

  it("has no link while a blind race runs, nor without a seed", () => {
    expect(raceSeedPageHref(race)).toBeNull();
    expect(raceSeedPageHref({ ...race, mode: "speedrun" })).toBeNull();
    expect(
      raceSeedPageHref({ ...race, status: "finished", seed_number: null }),
    ).toBeNull();
  });
});

describe("sessionSeedPageHref", () => {
  const session = {
    seed_number: "363096a4243f",
    status: "finished",
    mode: "speedrun" as RunMode,
  };
  const href = "/speedrun/seed/363096a4243f";

  it("never links a normal (practice) session", () => {
    expect(sessionSeedPageHref({ ...session, mode: "normal" })).toBeNull();
    expect(
      sessionSeedPageHref({ ...session, mode: "normal", status: "active" }),
    ).toBeNull();
  });

  it("links a Speedrun session once it is no longer active", () => {
    expect(sessionSeedPageHref(session)).toBe(href);
    expect(sessionSeedPageHref({ ...session, status: "abandoned" })).toBe(href);
    expect(sessionSeedPageHref({ ...session, status: "active" })).toBeNull();
  });

  it("links a Set Seed session, even an active one", () => {
    expect(
      sessionSeedPageHref({ ...session, mode: "set_seed", status: "active" }),
    ).toBe(href);
  });

  it("has no link without a seed", () => {
    expect(sessionSeedPageHref({ ...session, seed_number: null })).toBeNull();
  });
});

describe("ranked race creation links", () => {
  const search = (href: string) =>
    new URL(href, "http://localhost").searchParams;

  it("opens /race/new with the Speedrun option on and the pool picked", () => {
    expect(
      parseRaceNewParams(search(speedrunRaceNewHref("boss rush"))),
    ).toEqual({ seed: null, speedrun: true, pool: "boss rush" });
  });

  it("opens /race/new on a Set Seed race for the seed", () => {
    expect(parseRaceNewParams(search(setSeedRaceNewHref("363096")))).toEqual({
      seed: "363096",
      speedrun: false,
      pool: null,
    });
  });

  it("preselects a pool alone with the option off", () => {
    expect(parseRaceNewParams(search("/race/new?pool=sprint"))).toEqual({
      seed: null,
      speedrun: false,
      pool: "sprint",
    });
  });

  it("lets a seed win over the speedrun mode, and ignores blank values", () => {
    expect(
      parseRaceNewParams(
        search("/race/new?mode=speedrun&pool=sprint&seed=abc123"),
      ).speedrun,
    ).toBe(false);
    expect(parseRaceNewParams(search("/race/new?seed=%20&pool="))).toEqual({
      seed: null,
      speedrun: false,
      pool: null,
    });
    expect(parseRaceNewParams(search("/race/new?mode=set_seed")).speedrun).toBe(
      false,
    );
  });
});

describe("parseSpeedrunFloor", () => {
  it("reads an empty field as the server default", () => {
    expect(parseSpeedrunFloor("")).toBeNull();
    expect(parseSpeedrunFloor("  ")).toBeNull();
  });

  it("takes a whole number, 0 included", () => {
    expect(parseSpeedrunFloor("0")).toBe(0);
    expect(parseSpeedrunFloor(" 12 ")).toBe(12);
  });

  it("refuses fractions, negatives and the rest before any request", () => {
    for (const raw of ["3.5", "-1", "1e3", "abc", "4 2"]) {
      expect(parseSpeedrunFloor(raw)).toBeUndefined();
    }
  });
});

describe("the Start a run window's link", () => {
  it("opens the window on the seed over the seed category's board", () => {
    const url = new URL(startRunHref("standard@25", "363096"), "http://x");
    expect(url.pathname).toBe("/speedrun");
    expect(parseStartSeed(url.searchParams)).toBe("363096");
    expect(parseSpeedrunParams(url.searchParams).pool).toBe("standard@25");
  });

  it("opens over the default board for a seed without a category", () => {
    const url = new URL(startRunHref(null, "zz 1"), "http://x");
    expect(parseStartSeed(url.searchParams)).toBe("zz 1");
    expect(url.searchParams.has("pool")).toBe(false);
  });

  it("opens no window without start=set, an empty field without a seed", () => {
    expect(parseStartSeed(new URLSearchParams("pool=sprint"))).toBeNull();
    expect(parseStartSeed(new URLSearchParams("start=random"))).toBeNull();
    expect(parseStartSeed(new URLSearchParams("start=set"))).toBe("");
  });
});

describe("toggleRunType", () => {
  it("removes and adds a type in canonical order, never emptying the set", () => {
    expect(toggleRunType([...RUN_TYPES], "daily")).toEqual([
      "race",
      "event",
      "solo",
    ]);
    expect(toggleRunType(["race"], "race")).toEqual(["race"]);
    expect(toggleRunType(["solo"], "race")).toEqual(["race", "solo"]);
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
    run_id: `p-${user}-${day}`,
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
    session_id: null,
    daily_date: null,
    seed_number: "abc",
    blind: true,
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

/** A board of `ranks.length` players named p1, p2...; `ranks[i]` is the
 * rank shown for the i-th row (ties repeat a rank). */
function board(ranks: number[]): SpeedrunRun[] {
  return ranks.map((rank, i) => ({
    ...record(`p${i + 1}`, 1_500_000 + i * 1000, 0),
    rank,
  }));
}

const names = (runs: SpeedrunRun[]) => runs.map((r) => r.user.twitch_username);

describe("speedrunOverlayRows", () => {
  const twentyFive = board(Array.from({ length: 25 }, (_, i) => i + 1));
  const opts = { top: 3, cycle: 3, until: 20, player: null };

  it("pins the top rows and pages through the next ones up to the limit", () => {
    const rows = speedrunOverlayRows(twentyFive, opts);
    expect(names(rows.top)).toEqual(["p1", "p2", "p3"]);
    expect(rows.pages.map(names)).toEqual([
      ["p4", "p5", "p6"],
      ["p7", "p8", "p9"],
      ["p10", "p11", "p12"],
      ["p13", "p14", "p15"],
      ["p16", "p17", "p18"],
      ["p19", "p20"],
    ]);
    expect(rows.self).toBeNull();
    expect(rows.selfId).toBeNull();
  });

  it("keeps every player tied at the limit rank", () => {
    const rows = speedrunOverlayRows(board([1, 2, 3, 4, 5, 5, 7]), {
      ...opts,
      until: 5,
    });
    expect(rows.pages.flat().map((r) => r.rank)).toEqual([4, 5, 5]);
  });

  it("highlights a player in the top in place, without a pinned row", () => {
    const rows = speedrunOverlayRows(twentyFive, { ...opts, player: "p2" });
    expect(rows.self).toBeNull();
    expect(rows.selfId).toBe("p2");
    expect(rows.pages[0].map((r) => r.user.id)).toEqual(["p4", "p5", "p6"]);
  });

  it("pins a player from the cycling range and takes them out of it", () => {
    const rows = speedrunOverlayRows(twentyFive, { ...opts, player: "p5" });
    expect(rows.self?.user.id).toBe("p5");
    expect(rows.selfId).toBe("p5");
    expect(rows.pages[0].map((r) => r.user.id)).toEqual(["p4", "p6", "p7"]);
    expect(rows.pages.flat()).toHaveLength(16);
  });

  it("pins a player past the limit and leaves the cycle as is", () => {
    const rows = speedrunOverlayRows(twentyFive, { ...opts, player: "p24" });
    expect(rows.self?.user.id).toBe("p24");
    expect(rows.pages.flat()).toHaveLength(17);
  });

  it("matches the player whatever the case", () => {
    const rows = speedrunOverlayRows(
      twentyFive.map((r) =>
        r.user.id === "p9"
          ? { ...r, user: { ...r.user, twitch_username: "kemist_c10h15n" } }
          : r,
      ),
      { ...opts, player: "KEMIST_C10H15N" },
    );
    expect(rows.self?.user.id).toBe("p9");
  });

  it("shows no pinned row for a player without a run on the board", () => {
    const rows = speedrunOverlayRows(twentyFive, {
      ...opts,
      player: "stranger",
    });
    expect(rows.self).toBeNull();
    expect(rows.selfId).toBeNull();
  });

  it("has no pages without cycling rows or below a limit inside the top", () => {
    expect(
      speedrunOverlayRows(twentyFive, { ...opts, cycle: 0 }).pages,
    ).toEqual([]);
    expect(
      speedrunOverlayRows(twentyFive, { ...opts, until: 3 }).pages,
    ).toEqual([]);
  });

  it("copes with a board shorter than the top", () => {
    const rows = speedrunOverlayRows(board([1, 2]), opts);
    expect(names(rows.top)).toEqual(["p1", "p2"]);
    expect(rows.pages).toEqual([]);
  });
});

describe("speedrun overlay URL", () => {
  const DEFAULT_OVERLAY: SpeedrunOverlayParams = {
    sub: "set",
    deathless: false,
    types: ["race", "daily", "event", "solo"],
    top: 3,
    cycle: 3,
    until: 20,
    player: null,
  };

  it("leaves the defaults out", () => {
    expect(
      speedrunOverlayUrl("https://x.test", "standard", DEFAULT_OVERLAY),
    ).toBe("https://x.test/overlay/speedrun/standard");
  });

  it("reads back what it writes", () => {
    const options: SpeedrunOverlayParams = {
      sub: "random",
      deathless: true,
      types: ["race", "daily", "solo"],
      top: 5,
      cycle: 2,
      until: 50,
      player: "wospince",
    };
    const url = new URL(
      speedrunOverlayUrl("https://x.test", "sprint", options),
    );
    expect(url.pathname).toBe("/overlay/speedrun/sprint");
    expect(parseSpeedrunOverlayParams(url.searchParams)).toEqual(options);
  });

  it("writes the sub and deathless keys", () => {
    expect(
      speedrunOverlayUrl("https://x.test", "standard@25", {
        ...DEFAULT_OVERLAY,
        sub: "random",
        deathless: true,
      }),
    ).toBe(
      "https://x.test/overlay/speedrun/standard%4025?sub=random&deathless=1",
    );
  });

  it("falls back to the defaults on missing or malformed numbers", () => {
    const parsed = parseSpeedrunOverlayParams(
      new URLSearchParams("top=abc&cycle=-2&until=&player="),
    );
    expect(parsed).toEqual(DEFAULT_OVERLAY);
  });

  it("accepts zero rows, so the overlay can drop the top or the cycle", () => {
    const parsed = parseSpeedrunOverlayParams(
      new URLSearchParams("top=0&cycle=0"),
    );
    expect(parsed.top).toBe(0);
    expect(parsed.cycle).toBe(0);
  });
});

describe("recentRunParams", () => {
  it("opens the run's category on Set Seed with every filter cleared", () => {
    const current: SpeedrunParams = {
      pool: "sprint",
      sub: "random",
      deathless: true,
      types: ["daily"],
      obsolete: true,
      view: "history-chart",
    };

    expect(recentRunParams(current, "standard")).toEqual({
      ...current,
      pool: "standard",
      sub: "set",
      deathless: false,
      types: [...RUN_TYPES],
    });
  });
});
