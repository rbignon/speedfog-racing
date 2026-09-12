import { afterEach, describe, expect, it, vi } from "vitest";
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
  practiceHint,
  racesSection,
  stageTimes,
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

  it("introduces SpeedFog first while the event can still be joined, and only then", () => {
    expect(blockOrder("upcoming")[0]).toBe("intro");
    expect(blockOrder("qualifier")[0]).toBe("intro");
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(blockOrder(phase), phase).not.toContain("intro");
    }
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
  const wonBy = (index: number, id: string) =>
    ({
      slot: `final:${index}`,
      index,
      race: {
        status: "finished",
        participant_previews: [{ id, placement: 1 }],
      },
    }) as unknown as EventStage["races"][number];
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
    races: [wonBy(1, "u1"), wonBy(2, "u2"), wonBy(3, "u1")],
    results: [
      {
        user: winner,
        newcomer: false,
        points: 300,
        igt_total: 5000,
        advances: false,
        signature_weapon: { id: 8030000, name: "Bloodhound's Fang" },
      },
      {
        user: runnerUp,
        newcomer: false,
        points: 200,
        igt_total: 1,
        advances: false,
        signature_weapon: null,
      },
    ],
    field: [],
    ...overrides,
  });
  const ladder = {
    entries: [
      { rank: 7, user: winner },
      { rank: null, user: runnerUp },
    ],
  } as unknown as EventDetail["ladder"];

  it("crowns the leader of a complete final or newcomers' final only, the final first, with their story", () => {
    const crowned = champions({
      stages: [
        stageOf("semi", true),
        stageOf("newcomers", true),
        stageOf("final", true),
      ],
      ladder,
    });
    expect(crowned.map((c) => c.kind)).toEqual(["final", "newcomers"]);
    expect(crowned.map((c) => c.label)).toEqual(["Champion", "Newcomers"]);
    expect(crowned[0]).toMatchObject({
      user: winner,
      ladderRank: 7,
      wins: 2,
      racesExpected: 3,
      weapon: "Bloodhound's Fang",
    });
    expect(champions({ stages: [stageOf("final", false)], ladder })).toEqual(
      [],
    );
    // Complete but nobody scored: no winner to crown.
    expect(
      champions({ stages: [stageOf("final", true, { results: [] })], ladder }),
    ).toEqual([]);
  });

  it("counts no win for a race nobody finished, and no rank or weapon when there is none", () => {
    const nobodyFinished = {
      ...wonBy(3, "u1"),
      race: {
        status: "finished",
        participant_previews: [{ id: "u1", placement: null }],
      },
    } as unknown as EventStage["races"][number];
    const results = [
      { ...stageOf("final", true).results[0], signature_weapon: null },
    ];
    const crowned = champions({
      stages: [
        stageOf("final", true, {
          races: [wonBy(1, "u1"), nobodyFinished],
          results,
        }),
      ],
      ladder: { entries: [] } as unknown as EventDetail["ladder"],
    });
    expect(crowned[0]).toMatchObject({
      wins: 1,
      ladderRank: null,
      weapon: null,
    });
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

describe("practiceHint", () => {
  const modes = [
    { key: "standard", label: "Standard" },
    { key: "boss_rush", label: "Boss Rush" },
  ];
  const race = (mode: string, status: string | null) =>
    ({
      mode,
      my_result: status === null ? null : { status },
    }) as EventDetail["qualifier_races"][number];
  const hintFor = (...races: EventDetail["qualifier_races"]) =>
    practiceHint({ modes, qualifier_races: races, seeds_per_mode: 1 });

  it("names the modes the runner has never opened, registration included", () => {
    expect(
      hintFor(race("standard", "done"), race("boss_rush", "not_played")),
    ).toEqual({
      kind: "gap",
      modes: [modes[1]],
    });
    // Registered on the seed and never started is still a mode never run.
    expect(
      hintFor(race("standard", "done"), race("boss_rush", "joined")),
    ).toEqual({
      kind: "gap",
      modes: [modes[1]],
    });
  });

  it("waits for every seed of the event, not merely every seed attached", () => {
    // Both modes out and run, but the event holds two seeds per mode, so the
    // second card of each mode is still an empty placeholder.
    expect(
      practiceHint({
        modes,
        qualifier_races: [race("standard", "done"), race("boss_rush", "done")],
        seeds_per_mode: 2,
      }),
    ).toBeNull();
  });

  it("sends a runner who spent every seed to the daily", () => {
    expect(
      hintFor(race("standard", "done"), race("boss_rush", "done")),
    ).toEqual({
      kind: "done",
      modes: [],
    });
  });

  it("stays quiet mid-qualifier and for a viewer who is not signed in", () => {
    // A seed left in a mode already opened is not a gap, and not done either.
    expect(
      practiceHint({
        modes,
        qualifier_races: [
          race("standard", "done"),
          race("standard", "not_played"),
          race("boss_rush", "playing"),
        ],
        seeds_per_mode: 2,
      }),
    ).toBeNull();
    expect(hintFor(race("standard", null), race("boss_rush", null))).toBeNull();
    expect(hintFor()).toBeNull();
  });

  it("says nothing about a mode whose seeds are not out yet", () => {
    // Before every seed is attached, "every seed played" would be a lie, and
    // a mode with no seed is not a mode the runner skipped.
    expect(hintFor(race("standard", "done"))).toBeNull();
  });
});

describe("formatEventDate with the zone, and stageTimes", () => {
  const stagesAt = (...isos: string[]) =>
    isos.map((date, i) => ({ label: `Stage ${i + 1}`, date }));
  // The real season: four Sunday evenings, the last one the day Europe leaves
  // summer time, read from Paris.
  const season = (last: string) =>
    [
      ["Semi A", "2026-10-04T19:00:00Z"],
      ["Semi B", "2026-10-11T19:00:00Z"],
      ["Newcomers' final", "2026-10-18T19:00:00Z"],
      ["Final", last],
    ].map(([label, date]) => ({ label, date }));

  afterEach(() => vi.unstubAllEnvs());

  it("appends the zone to the plain format, leaving the rest of it alone", () => {
    const iso = "2026-10-04T20:00:00Z";
    const zoned = formatEventDate(iso, true);
    expect(zoned.startsWith(formatEventDate(iso))).toBe(true);
    expect(zoned.length).toBeGreaterThan(formatEventDate(iso).length);
  });

  it("names the one evening a daylight saving change moves", () => {
    vi.stubEnv("TZ", "Europe/Paris");
    expect(stageTimes(season("2026-10-25T19:00:00Z"))).toEqual({
      time: "21:00",
      exception: { label: "Final", time: "20:00" },
    });
  });

  it("names the odd evening wherever it sits in the season", () => {
    vi.stubEnv("TZ", "Europe/Paris");
    expect(
      stageTimes(
        stagesAt(
          "2026-10-04T19:00:00Z",
          "2026-10-11T18:00:00Z",
          "2026-10-18T19:00:00Z",
          "2026-10-25T20:00:00Z",
        ),
      ),
    ).toEqual({
      time: "21:00",
      exception: { label: "Stage 2", time: "20:00" },
    });
  });

  it("keeps the evenings together when only the zone's name changed", () => {
    // Stored an hour later so the last evening still starts at 21:00 in
    // Paris: same wall clock, CEST then CET, and one announcement covers all.
    vi.stubEnv("TZ", "Europe/Paris");
    expect(stageTimes(season("2026-10-25T20:00:00Z"))).toEqual({
      time: "21:00",
      exception: null,
    });
  });

  it("says nothing when no single evening stands out", () => {
    vi.stubEnv("TZ", "Europe/Paris");
    // Three times over four evenings (21:00, 21:00, 19:00, then 20:00 once
    // the change lands), then an even split, then two evenings that merely
    // differ: none of them leaves a majority with one evening beside it.
    expect(
      stageTimes(
        stagesAt(
          "2026-10-04T19:00:00Z",
          "2026-10-11T19:00:00Z",
          "2026-10-18T17:00:00Z",
          "2026-10-25T19:00:00Z",
        ),
      ),
    ).toBeNull();
    expect(
      stageTimes(
        stagesAt(
          "2026-10-04T19:00:00Z",
          "2026-10-11T19:00:00Z",
          "2026-10-18T18:00:00Z",
          "2026-10-25T19:00:00Z",
        ),
      ),
    ).toBeNull();
    expect(
      stageTimes(stagesAt("2026-10-04T19:00:00Z", "2026-10-11T18:00:00Z")),
    ).toBeNull();
    expect(stageTimes(stagesAt("2026-10-04T19:00:00Z"))).toBeNull();
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
