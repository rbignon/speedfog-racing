import { describe, expect, it } from "vitest";
import {
  blockOrder,
  champions,
  eventFacts,
  fillSlots,
  formatEventDate,
  formatEventDay,
  liveStage,
  ordinal,
  pollIntervalMs,
  racesSection,
  stripStagePrefix,
  timeRemaining,
} from "$lib/events";
import type { EventDetail, EventPhase, EventStage, Race, User } from "$lib/api";

const phases: EventPhase[] = [
  "upcoming",
  "qualifier",
  "cut",
  "playoffs",
  "finished",
];

describe("blockOrder", () => {
  it("shows exactly one rules carrier per phase (the take-part or the bracket block)", () => {
    for (const phase of phases) {
      const blocks = blockOrder(phase);
      const carriers = blocks.filter(
        (b) => b === "take_part" || b === "bracket_ladder",
      );
      expect(carriers.length, phase).toBe(1);
      expect(new Set(blocks).size, phase).toBe(blocks.length);
    }
  });

  it("shows the seeds only while they can be played", () => {
    expect(blockOrder("upcoming")).toContain("seeds");
    expect(blockOrder("qualifier")).toContain("seeds");
    expect(blockOrder("cut")).not.toContain("seeds");
    expect(blockOrder("playoffs")).not.toContain("seeds");
  });

  it("leads the playoffs with the live block and shows the bracket from the cut on", () => {
    expect(blockOrder("playoffs")[0]).toBe("live");
    expect(blockOrder("qualifier")).not.toContain("bracket_ladder");
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(blockOrder(phase), phase).toContain("bracket_ladder");
    }
  });

  it("opens the finished page with the champions", () => {
    expect(blockOrder("finished")[0]).toBe("champions");
  });
});

function detailWith(partial: Partial<EventDetail>): EventDetail {
  return {
    live_race: null,
    next_stage: null,
    current_stage_key: null,
    stages: [],
    ...partial,
  } as EventDetail;
}

describe("eventFacts", () => {
  const stages = [
    { kind: "semi", races_expected: 3, date: "2026-10-04T19:00:00Z" },
    { kind: "newcomers", races_expected: 3, date: "2026-10-18T19:00:00Z" },
  ] as EventDetail["stages"];
  const base = {
    facts: null,
    modes: [
      { key: "standard", label: "Standard" },
      { key: "boss_rush", label: "Boss Rush" },
    ],
    seeds_per_mode: 2,
    stages,
  };

  it("uses the config's facts as they are when it sets any", () => {
    const facts = [{ title: "Playoffs", lines: ["4 Sundays", "3 races each"] }];
    expect(eventFacts({ ...base, facts }, () => "x")).toBe(facts);
    expect(eventFacts({ ...base, facts: [] }, () => "x")[0].title).toBe(
      "Qualifier",
    );
  });

  it("derives the tiles from the event's shape, the newcomers' one only with that stage", () => {
    const tiles = eventFacts(base, () => "Sun 18 Oct");
    expect(tiles.map((t) => t.title)).toEqual([
      "Qualifier",
      "Modes",
      "Playoffs",
      "Newcomers",
    ]);
    expect(tiles[0].lines).toEqual(["4 seeds", "2 modes"]);
    expect(tiles[1].lines).toEqual(["Standard", "Boss Rush"]);
    expect(tiles[2].lines).toEqual(["2 stages", "3 races each"]);
    expect(tiles[3].lines).toEqual(["Own final", "Sun 18 Oct"]);
    expect(
      eventFacts({ ...base, stages: [stages[0]] }, () => "x").map(
        (t) => t.title,
      ),
    ).not.toContain("Newcomers");
  });
});

describe("stripStagePrefix", () => {
  it("drops the stage label only when the name starts with it", () => {
    expect(stripStagePrefix("Semi A · Race 1 · Standard", "Semi A")).toBe(
      "Race 1 · Standard",
    );
    expect(stripStagePrefix("Semi B · Race 1 · Standard", "Semi A")).toBe(
      "Semi B · Race 1 · Standard",
    );
    expect(stripStagePrefix("Semi A", "Semi A")).toBe("Semi A");
    expect(stripStagePrefix("Semi A - Race 1 - Standard", "Semi A")).toBe(
      "Race 1 - Standard",
    );
  });
});

describe("champions", () => {
  const winner = { id: "u1", twitch_username: "ace" } as User;
  const runnerUp = { id: "u2", twitch_username: "bee" } as User;
  const stageOf = (
    kind: EventStage["kind"],
    complete: boolean,
    overrides: Partial<EventStage> = {},
  ): EventStage => ({
    key: kind,
    label: kind,
    kind,
    date: "2026-10-25T19:00:00Z",
    races_expected: 3,
    complete,
    modes: [],
    races: [],
    results: [
      {
        user: winner,
        newcomer: false,
        points: 300,
        igt_total: 1,
        advances: false,
      },
      {
        user: runnerUp,
        newcomer: false,
        points: 200,
        igt_total: 1,
        advances: false,
      },
    ],
    field: [],
    ...overrides,
  });

  it("crowns the leader of a complete final or newcomers' final only, the final first", () => {
    const crowned = champions([
      stageOf("semi", true),
      stageOf("newcomers", true),
      stageOf("final", true),
    ]);
    expect(crowned.map((c) => c.kind)).toEqual(["final", "newcomers"]);
    expect(crowned.map((c) => c.label)).toEqual(["Champion", "Newcomers"]);
    expect(crowned[0].user).toBe(winner);
    expect(champions([stageOf("final", false)])).toEqual([]);
    // Complete but nobody scored: no winner to crown.
    expect(champions([stageOf("final", true, { results: [] })])).toEqual([]);
  });
});

describe("fillSlots", () => {
  const second = { slot: "qualifier:standard:2", index: 2 };

  it("keeps slot order when a lower slot is empty", () => {
    expect(fillSlots([second], 2)).toEqual([null, second]);
  });

  it("yields one null per slot when nothing is attached", () => {
    expect(fillSlots([], 3)).toEqual([null, null, null]);
  });
});

describe("liveStage", () => {
  it("finds the stage that owns the live race", () => {
    const race = { id: "r2" } as Race;
    const detail = detailWith({
      live_race: race,
      stages: [
        {
          key: "semi_b",
          label: "Semi B",
          races: [{ slot: "semi_b:2", index: 2, race }],
        },
      ] as EventDetail["stages"],
    });
    expect(liveStage(detail)?.key).toBe("semi_b");
  });

  it("returns null when there is no live race, or no stage claims it", () => {
    expect(liveStage(detailWith({}))).toBeNull();
    expect(
      liveStage(detailWith({ live_race: { id: "orphan" } as Race })),
    ).toBeNull();
  });
});

describe("racesSection", () => {
  const fmt = (iso: string) => `D(${iso})`;
  const semiA = {
    key: "semi_a",
    label: "Semi A",
    date: "2026-10-04T19:00:00Z",
    races_expected: 3,
    complete: false,
    races: [] as EventStage["races"],
  };
  const semiB = {
    key: "semi_b",
    label: "Semi B",
    date: "2026-10-11T19:00:00Z",
    races_expected: 3,
    complete: false,
    races: [] as EventStage["races"],
  };
  const nextB = { key: "semi_b", label: "Semi B", date: semiB.date };
  const evening = new Date("2026-10-04T20:15:00Z");
  const raceAt = (index: number, status: string) => ({
    slot: `semi_a:${index}`,
    index,
    race: { id: `r${index}`, status } as Race,
  });

  it("is live, with the race index, while one of the evening's races runs", () => {
    const detail = detailWith({
      live_race: { id: "r2" } as Race,
      current_stage_key: "semi_a",
      next_stage: nextB,
      stages: [
        { ...semiA, races: [raceAt(1, "finished"), raceAt(2, "running")] },
        semiB,
      ] as EventDetail["stages"],
    });
    expect(racesSection(detail, fmt, evening)).toEqual({
      signal: { cls: "signal-running", text: "Live now" },
      meta: "Race 2 of 3",
    });
  });

  it("stays on the evening's stage between two of its races, not the next Sunday", () => {
    const detail = detailWith({
      current_stage_key: "semi_a",
      next_stage: nextB,
      stages: [
        { ...semiA, races: [raceAt(1, "finished")] },
        semiB,
      ] as EventDetail["stages"],
    });
    const section = racesSection(detail, fmt, evening);
    expect(section?.signal.text).toBe("In progress");
    expect(section?.meta).toBe("1 of 3 races played");
  });

  it("stays up next past the stage time while none of its races has started", () => {
    const detail = detailWith({
      current_stage_key: "semi_a",
      next_stage: nextB,
      stages: [
        { ...semiA, races: [raceAt(1, "setup")] },
        semiB,
      ] as EventDetail["stages"],
    });
    expect(racesSection(detail, fmt, evening)?.signal.text).toBe("Up next");
  });

  it("points at the next stage, dated, while its evening is ahead", () => {
    const detail = detailWith({
      next_stage: { key: "semi_a", label: "Semi A", date: semiA.date },
      stages: [semiA, semiB] as EventDetail["stages"],
    });
    const section = racesSection(detail, fmt, new Date("2026-10-01T15:00:00Z"));
    expect(section?.signal.text).toBe("Up next");
    expect(section?.meta).toBe("D(2026-10-04T19:00:00Z)");
  });

  it("marks the last stage finished once everything ran, and yields null without stages", () => {
    const after = new Date("2026-10-26T00:00:00Z");
    const section = racesSection(
      detailWith({
        stages: [semiA, { ...semiB, complete: true }] as EventDetail["stages"],
      }),
      fmt,
      after,
    );
    expect(section?.signal.text).toBe("Finished");
    expect(racesSection(detailWith({}), fmt, after)).toBeNull();
  });
});

describe("timeRemaining", () => {
  const now = new Date("2026-09-26T18:00:00Z");
  it("counts days and hours, then hours and minutes, then minutes", () => {
    expect(timeRemaining("2026-09-30T08:00:00Z", now)).toBe("3 days 14 h left");
    expect(timeRemaining("2026-09-26T23:20:00Z", now)).toBe("5 h 20 min left");
    expect(timeRemaining("2026-09-26T18:12:00Z", now)).toBe("12 min left");
  });
  it("reports closed seeds and unknown deadlines", () => {
    expect(timeRemaining("2026-09-26T17:59:00Z", now)).toBe("closed");
    expect(timeRemaining(null, now)).toBe("");
  });
});

describe("formatEventDay", () => {
  it("keeps the weekday, day and month but drops the time formatEventDate carries", () => {
    const iso = "2026-10-04T20:00:00Z";
    const day = formatEventDay(iso);
    expect(day).not.toMatch(/\d{1,2}:\d{2}/);
    expect(formatEventDate(iso).startsWith(day)).toBe(true);
  });
});

describe("pollIntervalMs and ordinal", () => {
  const stageAt = (iso: string) =>
    [
      { key: "semi_a", label: "Semi A", date: iso, races: [] },
    ] as unknown as EventDetail["stages"];
  const sunday = new Date("2026-10-04T19:00:00Z");

  it("polls every minute while a stage race is live during the playoffs", () => {
    expect(
      pollIntervalMs(
        detailWith({ phase: "playoffs", live_race: { id: "x" } as Race }),
        sunday,
      ),
    ).toBe(60_000);
  });
  it("polls every five minutes around a stage's date so the page sees it go live", () => {
    const detail = detailWith({
      phase: "playoffs",
      stages: stageAt("2026-10-04T19:00:00Z"),
    });
    expect(pollIntervalMs(detail, new Date("2026-10-04T09:30:00Z"))).toBe(
      300_000,
    );
    expect(pollIntervalMs(detail, new Date("2026-10-05T06:00:00Z"))).toBe(
      300_000,
    );
  });
  it("does not poll between stage days", () => {
    const detail = detailWith({
      phase: "playoffs",
      stages: stageAt("2026-10-04T19:00:00Z"),
    });
    expect(pollIntervalMs(detail, new Date("2026-10-06T19:00:00Z"))).toBeNull();
  });
  it("never polls outside the playoffs, even with a live race or a stage today", () => {
    expect(
      pollIntervalMs(
        detailWith({ phase: "finished", live_race: { id: "x" } as Race }),
        sunday,
      ),
    ).toBeNull();
    expect(
      pollIntervalMs(
        detailWith({
          phase: "qualifier",
          stages: stageAt("2026-10-04T19:00:00Z"),
        }),
        sunday,
      ),
    ).toBeNull();
  });
  it("formats English ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "23rd",
      "101st",
    ]);
  });
});
