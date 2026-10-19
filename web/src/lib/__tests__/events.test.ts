import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SIGNUP_INTENT_TTL_MS,
  blockOrder,
  bracketLayout,
  bracketShape,
  bracketStages,
  bracketView,
  champions,
  cutLine,
  encodeSignupIntent,
  eventBand,
  eventFacts,
  fillSlots,
  formatEventDate,
  formatEventDay,
  formatEventTime,
  formatMatchTime,
  linkPath,
  liveMatchMeta,
  liveMatches,
  liveStage,
  liveZoneTitle,
  matchCasters,
  matchRows,
  newcomersPlans,
  nextStageLabels,
  openingRefreshMs,
  ordinal,
  playoffsIntro,
  playoffsPlan,
  seatCode,
  seatTag,
  forfeitNotes,
  pollIntervalMs,
  provisionalUntil,
  qualifiedMeta,
  qualifiedSections,
  raceCell,
  selectedBracketKey,
  signupIntentStands,
  soloSeedLabel,
  stageTimes,
  startsIn,
  stripStagePrefix,
  timeRemaining,
  upcomingMatches,
} from "$lib/events";
import type {
  Caster,
  EventBracket,
  EventDetail,
  EventPhase,
  EventQualified,
  EventStage,
  EventSummary,
  ParticipantStatus,
  Race,
  User,
} from "$lib/api";

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

  it("introduces the playoffs over the bracket while they are ahead or under way", () => {
    for (const phase of ["cut", "playoffs"] as const) {
      const blocks = blockOrder(phase);
      expect(blocks.indexOf("playoffs_intro"), phase).toBe(
        blocks.indexOf("bracket_ladder") - 1,
      );
    }
    for (const phase of ["upcoming", "qualifier", "finished"] as const) {
      expect(blockOrder(phase), phase).not.toContain("playoffs_intro");
    }
  });

  it("introduces SpeedFog first while the event can still be joined, and only then", () => {
    expect(blockOrder("upcoming")[0]).toBe("intro");
    expect(blockOrder("qualifier")[0]).toBe("intro");
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(blockOrder(phase), phase).not.toContain("intro");
    }
  });

  it("offers practice right before the seeds it prepares for", () => {
    for (const phase of ["upcoming", "qualifier"] as const) {
      const blocks = blockOrder(phase);
      expect(blocks.indexOf("practice"), phase).toBe(
        blocks.indexOf("seeds") - 1,
      );
    }
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(blockOrder(phase), phase).not.toContain("practice");
    }
  });
});

function detailWith(partial: Partial<EventDetail>): EventDetail {
  return {
    live_race: null,
    next_stage: null,
    current_stage_key: null,
    stages: [],
    brackets: [],
    ...partial,
  } as EventDetail;
}

function stageFixture(overrides: Partial<EventStage>): EventStage {
  return {
    key: "s",
    label: "S",
    kind: "quarter",
    bracket: "main",
    date: null,
    date_fixed: false,
    time_set: true,
    from: [],
    advance: null,
    races_expected: 3,
    complete: false,
    walkover: false,
    modes: [],
    races: [],
    results: [],
    settled_results: [],
    field: [],
    ...overrides,
  };
}

const seats = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    user: null,
    label: `Seed ${i + 1}`,
    forfeited: false,
    source: null,
    place: null,
  }));

const mainBracket: EventBracket = {
  key: "main",
  label: "Top 32",
  entry: "all",
  current_stage_key: null,
  next_stage: null,
};
const newcomersBracket: EventBracket = {
  key: "newcomers",
  label: "Newcomers",
  entry: "newcomers",
  current_stage_key: null,
  next_stage: null,
};
const runningRace = (slot: string) =>
  ({
    slot,
    index: 1,
    race: { id: slot, status: "running" },
    points: {},
    live: [],
  }) as unknown as EventStage["races"][number];
const twoBrackets: EventStage[] = [
  stageFixture({ key: "semi_a", kind: "semi", field: seats(4) }),
  stageFixture({ key: "semi_b", kind: "semi", field: seats(4) }),
  stageFixture({ key: "final", kind: "final", from: ["semi_a", "semi_b"] }),
  stageFixture({
    key: "newcomers_semi_a",
    kind: "semi",
    bracket: "newcomers",
    field: seats(4),
  }),
  stageFixture({
    key: "newcomers_semi_b",
    kind: "semi",
    bracket: "newcomers",
    field: seats(4),
  }),
  stageFixture({
    key: "newcomers_final",
    kind: "final",
    bracket: "newcomers",
    from: ["newcomers_semi_a", "newcomers_semi_b"],
    date: "2026-10-25T19:00:00Z",
  }),
];

describe("selectedBracketKey", () => {
  const base = detailWith({
    brackets: [mainBracket, newcomersBracket],
    stages: twoBrackets,
  });

  it("follows the URL when it names a bracket, the default otherwise", () => {
    expect(selectedBracketKey(base, "newcomers")).toBe("newcomers");
    expect(selectedBracketKey(base, "nope")).toBe("main");
    expect(selectedBracketKey(base, null)).toBe("main");
  });

  it("opens on the live race's bracket, else the current, else the next", () => {
    const stages = twoBrackets.map((s) =>
      s.key === "newcomers_semi_b"
        ? { ...s, races: [runningRace("newcomers_semi_b:1")] }
        : s,
    );
    const live = detailWith({
      ...base,
      stages,
      live_race: { id: "newcomers_semi_b:1" } as EventDetail["live_race"],
    });
    expect(selectedBracketKey(live, null)).toBe("newcomers");
    expect(
      selectedBracketKey(
        { ...base, current_stage_key: "newcomers_semi_a" },
        null,
      ),
    ).toBe("newcomers");
    expect(
      selectedBracketKey(
        {
          ...base,
          next_stage: {
            key: "newcomers_final",
            label: "x",
            date: "2026-10-25T19:00:00Z",
            time_set: true,
          },
        },
        null,
      ),
    ).toBe("newcomers");
  });

  it("has nothing to select without brackets", () => {
    expect(selectedBracketKey(detailWith({}), "main")).toBeNull();
  });
});

describe("bracketView", () => {
  it("keeps one bracket's stages and puts its own evening in place of the event's", () => {
    const next = {
      key: "newcomers_final",
      label: "Newcomers' final",
      date: "2026-10-25T19:00:00Z",
      time_set: true,
    };
    const detail = detailWith({
      brackets: [mainBracket, { ...newcomersBracket, next_stage: next }],
      stages: twoBrackets,
      next_stage: {
        key: "semi_a",
        label: "Semi A",
        date: "2026-10-12T19:00:00Z",
        time_set: true,
      },
    });
    const view = bracketView(detail, "newcomers");
    expect(view.stages.map((s) => s.key)).toEqual([
      "newcomers_semi_a",
      "newcomers_semi_b",
      "newcomers_final",
    ]);
    expect(view.next_stage).toEqual(next);
    expect(bracketView(detail, null)).toBe(detail);
  });
});

describe("bracketShape and newcomersPlans", () => {
  it("says a bracket's rounds in words", () => {
    expect(bracketShape(bracketStages(twoBrackets, "newcomers"))).toBe(
      "two semis, then a final",
    );
    expect(bracketShape(roundSeason)).toBe(
      "eight groups, four quarters, two semis, then a final",
    );
    expect(
      bracketShape([stageFixture({ key: "only", kind: "final" })]),
    ).toBeNull();
  });

  it("describes the newcomers brackets after the first, with their seats and final", () => {
    const plans = newcomersPlans({
      brackets: [mainBracket, newcomersBracket],
      stages: twoBrackets,
    });
    expect(plans).toHaveLength(1);
    expect(plans[0]).toMatchObject({
      key: "newcomers",
      seats: 8,
      shape: "two semis, then a final",
    });
    expect(plans[0].final?.key).toBe("newcomers_final");
    // A first bracket drawing from the newcomers is the main one, not described here.
    expect(
      newcomersPlans({
        brackets: [{ ...newcomersBracket }],
        stages: bracketStages(twoBrackets, "newcomers"),
      }),
    ).toEqual([]);
  });
});

describe("playoffsIntro", () => {
  // The round of 32 as configured: groups of four, three races, top 2 on.
  const season = roundSeason.map((s) =>
    s.kind === "round" ? { ...s, advance: 2 } : s,
  );

  it("names the first bracket's rounds before its final, the match, and who goes on", () => {
    const intro = playoffsIntro({
      brackets: [mainBracket, newcomersBracket],
      stages: [...season, ...bracketStages(twoBrackets, "newcomers")],
    });
    expect(intro).toMatchObject({
      places: 32,
      rounds: ["eight groups", "four quarters", "two semis"],
      match: "Four runners a match, three races an evening on the same seed",
      advance: 2,
    });
    expect(intro?.final?.key).toBe("final");
    expect(intro?.newcomers.map((n) => [n.seats, n.shape])).toEqual([
      [8, "two semis, then a final"],
    ]);
  });

  it("reads a lone final as the whole bracket, with nobody going on", () => {
    const final = stageFixture({
      key: "final",
      kind: "final",
      field: seats(4),
      races_expected: 1,
    });
    const intro = playoffsIntro({ brackets: [mainBracket], stages: [final] });
    expect(intro).toMatchObject({
      places: 4,
      rounds: [],
      match: "Four runners a match, one race an evening on the same seed",
      advance: null,
      newcomers: [],
    });
    expect(intro?.final?.key).toBe("final");
  });

  it("names every round of a bracket without a final, and counts big matches in digits", () => {
    const groups = [
      stageFixture({ key: "g1", kind: "round", field: seats(12) }),
      stageFixture({ key: "g2", kind: "round", field: seats(12) }),
    ];
    const intro = playoffsIntro({ brackets: [mainBracket], stages: groups });
    expect(intro).toMatchObject({
      places: 24,
      rounds: ["two groups"],
      final: null,
      match: "12 runners a match, three races an evening on the same seed",
    });
  });

  it("has nothing to say about an event without playoffs", () => {
    expect(playoffsIntro({ brackets: [], stages: [] })).toBeNull();
    // A bracket holding no stage yet is no playoffs either.
    expect(playoffsIntro({ brackets: [mainBracket], stages: [] })).toBeNull();
  });
});

describe("qualifiedSections", () => {
  const group = (stage_key: string) => ({
    stage_key,
    label: stage_key,
    entries: [],
  });
  const qualified: EventQualified = {
    provisional: true,
    groups: [
      group("semi_a"),
      group("semi_b"),
      group("newcomers_semi_a"),
      group("newcomers_semi_b"),
    ],
  };

  it("heads each bracket's groups with its label when there are several", () => {
    const sections = qualifiedSections(qualified, twoBrackets, [
      mainBracket,
      newcomersBracket,
    ]);
    expect(
      sections.map((s) => [s.label, s.groups.map((g) => g.stage_key)]),
    ).toEqual([
      ["Top 32", ["semi_a", "semi_b"]],
      ["Newcomers", ["newcomers_semi_a", "newcomers_semi_b"]],
    ]);
  });

  it("leaves a single bracket without a heading", () => {
    const single = qualifiedSections(
      { provisional: true, groups: [group("semi_a")] },
      bracketStages(twoBrackets, "main"),
      [mainBracket],
    );
    expect(single.map((s) => s.label)).toEqual([null]);
  });
});

// This season: quarters into semis into the final.
const quartersSeason: EventStage[] = [
  stageFixture({ key: "quarter_a", label: "Quarter A", field: seats(4) }),
  stageFixture({ key: "quarter_b", label: "Quarter B", field: seats(4) }),
  stageFixture({ key: "quarter_c", label: "Quarter C", field: seats(4) }),
  stageFixture({ key: "quarter_d", label: "Quarter D", field: seats(4) }),
  stageFixture({
    key: "semi_a",
    label: "Semi A",
    kind: "semi",
    from: ["quarter_a", "quarter_b"],
  }),
  stageFixture({
    key: "semi_b",
    label: "Semi B",
    kind: "semi",
    from: ["quarter_c", "quarter_d"],
  }),
  stageFixture({
    key: "final",
    label: "Final",
    kind: "final",
    date: "2026-10-25T19:00:00Z",
    date_fixed: true,
    time_set: true,
    from: ["semi_a", "semi_b"],
  }),
];

// Eight groups of a round of 32 into quarters, semis and the final.
const groupPairs = [
  ["a", "b"],
  ["c", "d"],
  ["e", "f"],
  ["g", "h"],
];
const roundSeason: EventStage[] = [
  ...groupPairs.flat().map((x) =>
    stageFixture({
      key: `group_${x}`,
      label: `Group ${x.toUpperCase()}`,
      kind: "round",
      field: seats(4),
    }),
  ),
  ...groupPairs.map(([a, b], i) => {
    const q = "abcd"[i];
    return stageFixture({
      key: `quarter_${q}`,
      label: `Quarter ${q.toUpperCase()}`,
      from: [`group_${a}`, `group_${b}`],
    });
  }),
  ...quartersSeason.filter((s) => s.kind !== "quarter"),
];

describe("bracketLayout", () => {
  it("centres each quarter on its two groups in a four-round tree", () => {
    const layout = bracketLayout(roundSeason);
    expect(layout.rounds.length).toBe(4);
    expect(layout.rows).toBe(8);
    const quarterB = layout.rounds[1][1];
    expect(quarterB.stage.key).toBe("quarter_b");
    expect([quarterB.row, quarterB.span]).toEqual([2, 2]);
    expect([layout.final?.row, layout.final?.span]).toEqual([0, 8]);
  });

  it("lays quarters, semis and the final out as a tree, each stage centred on its sources", () => {
    const layout = bracketLayout(quartersSeason);
    expect(layout.rounds.map((r) => r.map((c) => c.stage.key))).toEqual([
      ["quarter_a", "quarter_b", "quarter_c", "quarter_d"],
      ["semi_a", "semi_b"],
      ["final"],
    ]);
    expect(layout.rows).toBe(4);
    expect(layout.tall).toBe(true);
    const semiB = layout.rounds[1][1];
    expect([semiB.row, semiB.span]).toEqual([2, 2]);
    expect([layout.final?.row, layout.final?.span]).toEqual([0, 4]);
    const toFinal = layout.links.find((l) => l.target.stage.key === "final");
    expect(toFinal?.from).toEqual([25, 75]);
  });

  it("orders a round so that each stage's sources sit next to each other", () => {
    const crossed = quartersSeason.map((s) =>
      s.key === "semi_a"
        ? { ...s, from: ["quarter_a", "quarter_c"] }
        : s.key === "semi_b"
          ? { ...s, from: ["quarter_b", "quarter_d"] }
          : s,
    );
    const layout = bracketLayout(crossed);
    expect(layout.rounds[0].map((c) => c.stage.key)).toEqual([
      "quarter_a",
      "quarter_c",
      "quarter_b",
      "quarter_d",
    ]);
  });

  it("keeps a two-semis season short", () => {
    const layout = bracketLayout([
      stageFixture({ key: "semi_a", kind: "semi", field: seats(4) }),
      stageFixture({ key: "semi_b", kind: "semi", field: seats(4) }),
      stageFixture({ key: "final", kind: "final", from: ["semi_a", "semi_b"] }),
    ]);
    expect(layout.rows).toBe(2);
    expect(layout.tall).toBe(false);
  });

  const crossedSeason: EventStage[] = (() => {
    const quarters: Record<string, string[]> = {
      quarter_a: ["group_a", "group_b", "group_c", "group_d"],
      quarter_b: ["group_e", "group_f", "group_g", "group_h"],
      quarter_c: ["group_a", "group_b", "group_c", "group_d"],
      quarter_d: ["group_e", "group_f", "group_g", "group_h"],
    };
    const allQuarters = ["quarter_a", "quarter_b", "quarter_c", "quarter_d"];
    return roundSeason.map((s) =>
      s.key in quarters
        ? { ...s, from: quarters[s.key] }
        : s.kind === "semi"
          ? { ...s, from: allQuarters }
          : s,
    );
  })();

  it("spreads crossed rounds evenly, each next to the groups it draws on", () => {
    const layout = bracketLayout(crossedSeason);
    expect(layout.rows).toBe(8);
    expect(layout.rounds[1].map((c) => [c.stage.key, c.row, c.span])).toEqual([
      ["quarter_a", 0, 2],
      ["quarter_c", 2, 2],
      ["quarter_b", 4, 2],
      ["quarter_d", 6, 2],
    ]);
    expect(layout.rounds[2].map((c) => [c.stage.key, c.row, c.span])).toEqual([
      ["semi_a", 0, 4],
      ["semi_b", 4, 4],
    ]);
    // Only the final, fed by whole semis, keeps a connector.
    expect(layout.links.map((l) => l.target.stage.key)).toEqual(["final"]);
    expect([layout.final?.row, layout.final?.span]).toEqual([0, 8]);
  });

  it("keeps crossed rows contiguous when the stages do not divide the rows", () => {
    const three = crossedSeason
      .filter(
        (s) => s.key !== "quarter_d" && s.kind !== "semi" && s.kind !== "final",
      )
      .map((s) =>
        s.key === "quarter_c" ? { ...s, from: ["group_a", "group_e"] } : s,
      );
    const cells = bracketLayout(three).rounds[1];
    const spans = cells.map((c) => [c.row, c.row + c.span]);
    expect(spans[0][0]).toBe(0);
    expect(spans[spans.length - 1][1]).toBe(8);
    for (let i = 1; i < spans.length; i++)
      expect(spans[i][0]).toBe(spans[i - 1][1]);
  });
});

describe("seatCode", () => {
  const stages = [stageFixture({ key: "group_a", label: "Group A" })];

  it("gives a decided fed seat its source letter and place", () => {
    expect(
      seatCode(
        {
          user: null,
          label: "1st of Group A",
          forfeited: false,
          source: "group_a",
          place: 1,
        },
        stages,
      ),
    ).toBe("A1");
  });

  it("gives a seeded seat none", () => {
    expect(
      seatCode(
        {
          user: null,
          label: "Seed 3",
          forfeited: false,
          source: null,
          place: null,
        },
        stages,
      ),
    ).toBeNull();
  });
});

describe("linkPath", () => {
  it("joins the sources on a spine and leads out of its middle", () => {
    expect(linkPath([25, 75])).toBe(
      "M0 25 H12 M0 75 H12 M12 25 V75 M12 50 H24",
    );
    expect(linkPath([50])).toBe("M0 50 H24");
  });
});

describe("playoffsPlan", () => {
  it("counts the seeded places and names the rounds scheduled with the players", () => {
    const plan = playoffsPlan(quartersSeason);
    expect(plan.places).toBe(16);
    expect(plan.agreed).toBe("quarters and semis");
    expect(plan.fixed.map((s) => s.key)).toEqual(["final"]);
  });

  it("lists every stage on its date when the config fixes them all", () => {
    const plan = playoffsPlan([
      stageFixture({
        key: "semi_a",
        kind: "semi",
        date: "2026-10-04T19:00:00Z",
        date_fixed: true,
        time_set: true,
        field: seats(4),
      }),
      stageFixture({
        key: "final",
        kind: "final",
        date: "2026-10-25T19:00:00Z",
        date_fixed: true,
        time_set: true,
        from: ["semi_a"],
      }),
    ]);
    expect(plan.agreed).toBeNull();
    expect(plan.fixed.map((s) => s.key)).toEqual(["semi_a", "final"]);
  });

  it("names a round before the quarters after its seats", () => {
    const plan = playoffsPlan(roundSeason);
    expect(plan.places).toBe(32);
    expect(plan.agreed).toBe("round of 32, quarters and semis");
  });
});

describe("qualifiedMeta", () => {
  const fmt = (iso: string) => `Day(${iso})`;
  afterEach(() => vi.unstubAllEnvs());
  const groupA = roundSeason[0];

  it("names the round when the stage is labelled like its box", () => {
    expect(qualifiedMeta(groupA, roundSeason, fmt)).toBe("Round of 32");
    expect(
      qualifiedMeta(
        { ...groupA, date: "2026-10-10T19:00:00Z" },
        roundSeason,
        fmt,
      ),
    ).toBe("Round of 32 on Day(2026-10-10T19:00:00Z)");
  });

  it("gives the day alone while the stage's time is not set", () => {
    vi.stubEnv("TZ", "America/New_York");
    expect(
      qualifiedMeta(
        { ...groupA, date: "2026-10-10T12:00:00Z", time_set: false },
        roundSeason,
        fmt,
      ),
    ).toBe("Round of 32 on Sat 10 Oct");
  });

  it("gives another stage's date alone, nothing before it has one", () => {
    const quarterA = quartersSeason[0];
    expect(
      qualifiedMeta(
        { ...quarterA, date: "2026-10-10T19:00:00Z" },
        quartersSeason,
        fmt,
      ),
    ).toBe("Day(2026-10-10T19:00:00Z)");
    expect(qualifiedMeta(quarterA, quartersSeason, fmt)).toBe("");
  });
});

describe("eventFacts", () => {
  const stages = [
    {
      kind: "semi",
      bracket: "main",
      races_expected: 3,
      date: "2026-10-04T19:00:00Z",
    },
    {
      kind: "final",
      bracket: "main",
      races_expected: 3,
      date: "2026-10-25T19:00:00Z",
    },
    {
      kind: "final",
      bracket: "newcomers",
      races_expected: 3,
      date: "2026-10-18T19:00:00Z",
    },
  ] as EventDetail["stages"];
  const base = {
    facts: null,
    modes: [
      { key: "standard", label: "Standard" },
      { key: "boss_rush", label: "Boss Rush" },
    ],
    seeds_per_mode: 2,
    brackets: [mainBracket, newcomersBracket],
    stages,
  };

  it("uses the config's facts as they are when it sets any", () => {
    const facts = [{ title: "Playoffs", lines: ["4 Sundays", "3 races each"] }];
    expect(eventFacts({ ...base, facts }, () => "x")).toBe(facts);
    expect(eventFacts({ ...base, facts: [] }, () => "x")[0].title).toBe(
      "Qualifier",
    );
  });

  it("derives the tiles from the event's shape, one per later bracket", () => {
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
    // A newcomers bracket of several stages is a bracket of its own.
    const semis = [
      { kind: "semi", bracket: "newcomers", races_expected: 3, date: null },
      { kind: "semi", bracket: "newcomers", races_expected: 3, date: null },
    ] as unknown as EventDetail["stages"];
    expect(
      eventFacts(
        { ...base, stages: [...semis, ...stages] },
        () => "Sun 18 Oct",
      )[3].lines,
    ).toEqual(["Own bracket", "Sun 18 Oct"]);
    expect(
      eventFacts({ ...base, brackets: [mainBracket] }, () => "x").map(
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

describe("provisionalUntil", () => {
  const lock = "2026-10-10T18:00:00Z";
  const before = new Date("2026-10-09T12:00:00Z");
  const after = new Date("2026-10-11T12:00:00Z");

  it("holds the lock while the draw can still change", () => {
    expect(
      provisionalUntil({ phase: "cut", draw_locks_at: lock }, before),
    ).toBe(lock);
    expect(
      provisionalUntil({ phase: "playoffs", draw_locks_at: lock }, before),
    ).toBe(lock);
  });

  it("is null once locked, without a lock, or before the cut", () => {
    expect(
      provisionalUntil({ phase: "cut", draw_locks_at: lock }, after),
    ).toBeNull();
    expect(
      provisionalUntil({ phase: "cut", draw_locks_at: null }, before),
    ).toBeNull();
    expect(
      provisionalUntil({ phase: "qualifier", draw_locks_at: lock }, before),
    ).toBeNull();
  });
});

describe("forfeitNotes", () => {
  const user = (name: string) => ({ id: name, twitch_username: name }) as User;
  const seat = (name: string, forfeited = false) => ({
    user: user(name),
    label: "Seed 1",
    forfeited,
    source: null,
    place: null,
  });
  const stage = (
    label: string,
    field: EventStage["field"],
    walkover = false,
  ): EventStage =>
    ({
      key: label,
      label,
      field,
      walkover,
      results: [],
      settled_results: [],
    }) as unknown as EventStage;

  it("gives one note per stage with forfeits, the others still in it", () => {
    const notes = forfeitNotes([
      stage("Group F", [seat("a"), seat("b"), seat("c"), seat("d")]),
      stage("Group G", [
        seat("e"),
        seat("ItsShura", true),
        seat("f"),
        seat("g"),
      ]),
      stage(
        "Group H",
        [seat("h", true), seat("i"), seat("j", true), seat("k")],
        true,
      ),
    ]);
    expect(notes).toEqual([
      {
        who: [user("ItsShura")],
        stage: "Group G",
        present: [user("e"), user("f"), user("g")],
        remaining: 3,
        walkover: false,
      },
      {
        who: [user("h"), user("j")],
        stage: "Group H",
        present: [user("i"), user("k")],
        remaining: 2,
        walkover: true,
      },
    ]);
  });

  it("ignores a forfeit whose runner raced the stage", () => {
    const raced = {
      ...stage("Group A", [seat("a", true), seat("b"), seat("c"), seat("d")]),
      results: [{ user: user("a") }, { user: user("b") }],
    } as EventStage;
    expect(forfeitNotes([raced])).toEqual([]);
    const partial = {
      ...stage("Group B", [seat("a", true), seat("b", true), seat("c")]),
      results: [{ user: user("a") }],
    } as EventStage;
    const notes = forfeitNotes([partial]);
    expect(notes).toHaveLength(1);
    expect(notes[0].who).toEqual([user("b")]);
  });

  it("counts undecided placeholders among those still in a fed stage", () => {
    const undecided = {
      user: null,
      label: "Group A winner",
      forfeited: false,
      source: null,
      place: null,
    };
    const none = {
      user: null,
      label: "No runner",
      forfeited: false,
      source: null,
      place: null,
    };
    const fed = stage("Semi", [seat("a", true), seat("b"), undecided, none]);
    const [note] = forfeitNotes([fed]);
    expect(note.present).toEqual([user("b")]);
    expect(note.remaining).toBe(2);
    const empty = stage("Semi", [seat("a", true), none]);
    expect(forfeitNotes([empty])[0].remaining).toBe(0);
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
    bracket: "main",
    date: "2026-10-25T19:00:00Z",
    date_fixed: true,
    time_set: true,
    from: [],
    advance: null,
    races_expected: 3,
    complete,
    walkover: false,
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
    settled_results: [],
    field: [],
    ...overrides,
  });
  const ladder = {
    entries: [
      { rank: 7, user: winner },
      { rank: null, user: runnerUp },
    ],
  } as unknown as EventDetail["ladder"];

  it("crowns each bracket's complete final in bracket order, the first as Champion", () => {
    const crowned = champions({
      brackets: [mainBracket, newcomersBracket],
      stages: [
        stageOf("semi", true),
        stageOf("final", true),
        stageOf("final", true, {
          key: "newcomers_final",
          bracket: "newcomers",
        }),
      ],
      ladder,
    });
    expect(crowned.map((c) => [c.bracket, c.first, c.label])).toEqual([
      ["main", true, "Champion"],
      ["newcomers", false, "Newcomers"],
    ]);
    expect(crowned[0]).toMatchObject({
      user: winner,
      ladderRank: 7,
      wins: 2,
      racesExpected: 3,
      weapon: "Bloodhound's Fang",
    });
    // The newcomers' final decided first: its plate alone, not the event's.
    const early = champions({
      brackets: [mainBracket, newcomersBracket],
      stages: [
        stageOf("final", false),
        stageOf("final", true, {
          key: "newcomers_final",
          bracket: "newcomers",
        }),
      ],
      ladder,
    });
    expect(early.map((c) => [c.bracket, c.first])).toEqual([
      ["newcomers", false],
    ]);
    // Complete but nobody scored: no winner to crown.
    expect(
      champions({
        brackets: [mainBracket],
        stages: [stageOf("final", true, { results: [] })],
        ladder,
      }),
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
      brackets: [mainBracket],
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

describe("liveMatches", () => {
  const now = new Date("2026-10-18T17:25:00Z");
  const at = (minutes: number) =>
    new Date(now.getTime() + minutes * 60_000).toISOString();
  const entry = (
    index: number,
    race: Partial<Race> = {},
  ): EventStage["races"][number] => ({
    slot: `s:${index}`,
    index,
    race: {
      id: `r${index}`,
      status: "setup",
      scheduled_at: null,
      started_at: null,
      finished_at: null,
      ...race,
    } as Race,
    points: {},
    live: [],
  });
  const match = (
    key: string,
    races: EventStage["races"],
    overrides: Partial<EventStage> = {},
  ) => stageFixture({ key, label: key, races, ...overrides });
  const states = (stages: EventStage[]) =>
    liveMatches(stages, now).map((m) => [m.stage.key, m.state]);

  it("puts a stage with a running race on air, with that race", () => {
    const stage = match("group_h", [
      entry(1, { status: "finished", finished_at: at(-30) }),
      entry(2, { status: "running" }),
    ]);
    const [m] = liveMatches([stage], now);
    expect(m.state).toBe("live");
    expect(m.race?.index).toBe(2);
  });

  it("keeps a match on air between two races, by its last finish or its next race's schedule", () => {
    const byFinish = match("a", [
      entry(1, { status: "finished", finished_at: at(-119) }),
      entry(2),
    ]);
    const bySchedule = match("b", [
      entry(1, { status: "finished", finished_at: at(-300) }),
      entry(2, { scheduled_at: at(120) }),
    ]);
    const lateStart = match("c", [
      entry(1, { status: "finished", finished_at: at(-300) }),
      entry(2, { scheduled_at: at(-15) }),
    ]);
    const off = match("d", [
      entry(1, { status: "finished", finished_at: at(-121) }),
      entry(2, { scheduled_at: at(121) }),
    ]);
    expect(states([byFinish, bySchedule, lateStart, off])).toEqual([
      ["a", "between"],
      ["b", "between"],
      ["c", "between"],
    ]);
  });

  it("lets a match whose next race is long overdue fall off air, and stops polling for it", () => {
    // Postponed after its first race, its next race never re-dated.
    const stage = match("p", [
      entry(1, { status: "finished", finished_at: at(-4 * 24 * 60) }),
      entry(2, { scheduled_at: at(-3 * 24 * 60) }),
    ]);
    expect(liveMatches([stage], now)).toEqual([]);
    expect(
      pollIntervalMs(detailWith({ phase: "playoffs", stages: [stage] }), now),
    ).toBeNull();
  });

  it("takes a match spread over two evenings off air between them", () => {
    const stage = match("g", [
      entry(1, { status: "finished", finished_at: at(-2 * 24 * 60) }),
      entry(2, { scheduled_at: at(24 * 60) }),
      entry(3, { scheduled_at: at(25 * 60) }),
    ]);
    expect(liveMatches([stage], now)).toEqual([]);
  });

  it("names the next race between two races, or none while it is not attached", () => {
    const attached = match("a", [
      entry(1, { status: "finished", finished_at: at(-10) }),
      entry(2, { id: "next" }),
    ]);
    // Slot 2 has no race yet; slot 3 does, but it is not the next one.
    const missing = match("b", [
      entry(1, { status: "finished", finished_at: at(-10) }),
      entry(3),
    ]);
    const [a, b] = liveMatches([attached, missing], now);
    expect(a.race?.race.id).toBe("next");
    expect(b.state).toBe("between");
    expect(b.race).toBeNull();
  });

  it("shows a finished match for an hour after its last race, never a walkover", () => {
    const done = (key: string, minutes: number) =>
      match(
        key,
        [
          entry(1, { status: "finished", finished_at: at(-minutes - 60) }),
          entry(2, { status: "finished", finished_at: at(-minutes) }),
        ],
        { complete: true, races_expected: 2 },
      );
    const walkover = stageFixture({ key: "w", complete: true, walkover: true });
    expect(states([done("fresh", 59), done("old", 61), walkover])).toEqual([
      ["fresh", "finished"],
    ]);
  });

  it("ignores a finished race without its end time", () => {
    const started = match("x", [
      entry(1, { status: "finished", finished_at: null }),
      entry(2),
    ]);
    const complete = match(
      "y",
      [entry(1, { status: "finished", finished_at: null })],
      { complete: true, races_expected: 1 },
    );
    expect(liveMatches([started, complete], now)).toEqual([]);
  });

  it("orders the matches on air by bracket and stage, the finished ones last", () => {
    const live = (key: string, bracket: string) =>
      match(key, [entry(1, { status: "running" })], { bracket });
    const done = match(
      "done",
      [entry(1, { status: "finished", finished_at: at(-5) })],
      { complete: true, races_expected: 1 },
    );
    expect(
      liveMatches(
        [
          done,
          live("group_d", "main"),
          live("group_h", "main"),
          live("newcomers_semi_a", "newcomers"),
        ],
        now,
      ).map((m) => m.stage.key),
    ).toEqual(["group_d", "group_h", "newcomers_semi_a", "done"]);
  });
});

describe("match table", () => {
  const person = (id: string, name = id): User => ({
    id,
    twitch_username: id,
    twitch_display_name: name,
    twitch_avatar_url: null,
  });
  const preview = (id: string, status: ParticipantStatus) => ({
    ...person(id),
    placement: null,
    status,
    igt_ms: null,
  });
  const entry = (
    index: number,
    race: Partial<Race>,
    extra: Partial<EventStage["races"][number]> = {},
  ): EventStage["races"][number] => ({
    slot: `s:${index}`,
    index,
    race: {
      id: `r${index}`,
      status: "setup",
      casters: [],
      participant_previews: [],
      scheduled_at: null,
      started_at: null,
      finished_at: null,
      seed_total_layers: 9,
      ...race,
    } as Race,
    points: {},
    live: [],
    ...extra,
  });
  const result = (user: User, points: number, advances = false) => ({
    user,
    newcomer: false,
    points,
    igt_total: 0,
    advances,
    signature_weapon: null,
  });
  const seat = (user: User | null, label: string, extra = {}) => ({
    user,
    label,
    forfeited: false,
    source: null,
    place: null,
    ...extra,
  });

  it("reads a finished race as points, DQ or DNF", () => {
    const race = entry(
      1,
      {
        status: "finished",
        participant_previews: [
          preview("ana", "finished"),
          preview("bob", "disqualified"),
          preview("cleo", "abandoned"),
        ],
      },
      { points: { ana: 100, bob: 0, cleo: 0 } },
    );
    expect(raceCell(race, "ana")).toEqual({ text: "100", tone: "points" });
    expect(raceCell(race, "bob")).toEqual({ text: "DQ", tone: "out" });
    expect(raceCell(race, "cleo")).toEqual({ text: "DNF", tone: "out" });
  });

  it("reads a running race as provisional points, the layer, DNF, or not started", () => {
    const live = (id: string, status: ParticipantStatus, layer: number) => ({
      ...preview(id, status),
      current_layer: layer,
    });
    const race = entry(
      2,
      { status: "running" },
      {
        points: { ana: 100, bob: 0 },
        live: [
          live("ana", "finished", 9),
          live("bob", "playing", 8),
          live("cleo", "abandoned", 3),
          live("dan", "registered", 0),
        ],
      },
    );
    expect(raceCell(race, "ana")).toEqual({ text: "100", tone: "prov" });
    expect(raceCell(race, "bob")).toEqual({ text: "L8/9", tone: "live" });
    expect(raceCell(race, "cleo")).toEqual({ text: "DNF", tone: "out" });
    expect(raceCell(race, "dan")).toEqual({ text: "·", tone: "todo" });
    const unknownDepth = {
      ...race,
      race: { ...race.race, seed_total_layers: null },
    };
    expect(raceCell(unknownDepth, "bob").text).toBe("L8");
  });

  it("leaves a race not run yet, or not attached, empty", () => {
    expect(raceCell(entry(3, {}), "ana")).toEqual({ text: "·", tone: "todo" });
    expect(raceCell(null, "ana")).toEqual({ text: "·", tone: "todo" });
  });

  it("ranks the results, tags each seat, and keeps a forfeit at the bottom", () => {
    const [ana, bob, cleo] = [person("ana"), person("bob"), person("cleo")];
    const groupE = stageFixture({ key: "group_e", label: "Group E" });
    const stage = stageFixture({
      key: "quarter_c",
      races_expected: 2,
      races: [
        entry(
          1,
          {
            status: "finished",
            participant_previews: [
              preview("bob", "finished"),
              preview("ana", "finished"),
            ],
          },
          { points: { bob: 100, ana: 70 } },
        ),
      ],
      results: [result(bob, 100), result(ana, 70)],
      field: [
        seat(ana, "Seed 3"),
        seat(bob, "1st of Group E", { source: "group_e", place: 1 }),
        seat(cleo, "Seed 30", { forfeited: true }),
        seat(null, "No runner"),
      ],
    });
    const rows = matchRows(stage, [groupE, stage]);
    expect(rows.map((r) => [r.user.id, r.rank, r.seat, r.forfeit])).toEqual([
      ["bob", 1, "E1", false],
      ["ana", 2, "#3", false],
      ["cleo", null, "#30", true],
    ]);
    expect(rows[0].cells.map((c) => c.text)).toEqual(["100", "·"]);
    expect(rows[2].total).toBeNull();
  });

  it("lists the field in seat order before the first finish", () => {
    const stage = stageFixture({
      field: [seat(person("ana"), "Seed 1"), seat(person("bob"), "Seed 8")],
    });
    expect(matchRows(stage, [stage]).map((r) => [r.user.id, r.rank])).toEqual([
      ["ana", null],
      ["bob", null],
    ]);
  });

  it("seats no tag on an empty or unlabelled seat", () => {
    expect(seatTag(seat(null, "No runner"), [])).toBeNull();
  });

  it("draws the cut under the last runner going on while the match is played", () => {
    const quarterC = stageFixture({
      key: "quarter_c",
      label: "Quarter C",
      field: [seat(null, "2nd of Group H", { source: "group_h", place: 2 })],
    });
    const quarterD = stageFixture({
      key: "quarter_d",
      label: "Quarter D",
      field: [seat(null, "1st of Group H", { source: "group_h", place: 1 })],
    });
    const groupH = stageFixture({
      key: "group_h",
      advance: 2,
      results: [result(person("a"), 100), result(person("b"), 70)],
    });
    const stages = [groupH, quarterC, quarterD];
    expect(cutLine(groupH, stages, 4)).toEqual({
      after: 1,
      label: "Top 2 go on: Quarter D / Quarter C",
    });
    expect(cutLine({ ...groupH, complete: true }, stages, 4)).toBeNull();
    expect(cutLine({ ...groupH, results: [] }, stages, 4)).toBeNull();
    expect(cutLine({ ...groupH, advance: null }, stages, 4)).toBeNull();
    expect(cutLine(groupH, stages, 2)).toBeNull();
  });

  it("gathers a match's casters once each, in race order", () => {
    const caster = (id: string): Caster => ({
      id: `c-${id}`,
      user: person(id),
      is_live: false,
      stream_url: null,
    });
    const stage = stageFixture({
      races: [
        entry(2, { casters: [caster("karssi"), caster("itzcbd")] }),
        entry(1, { casters: [caster("itzcbd")] }),
      ],
    });
    expect(matchCasters(stage).map((c) => c.user.id)).toEqual([
      "itzcbd",
      "karssi",
    ]);
  });

  it("says what a panel's match is doing", () => {
    const time = (iso: string) => iso.slice(11, 16);
    const modes = ["Standard", "Boss Rush", "UWYG"];
    const played = entry(1, {
      status: "finished",
      finished_at: "2026-10-18T17:15:00Z",
    });
    const running = entry(2, {
      status: "running",
      started_at: "2026-10-18T17:02:00Z",
    });
    expect(
      liveMatchMeta(
        {
          stage: stageFixture({ modes, races: [played, running] }),
          state: "live",
          race: running,
        },
        time,
      ),
    ).toBe("Race 2 of 3 · Boss Rush · started 17:02");
    const next = entry(2, { scheduled_at: "2026-10-18T17:30:00Z" });
    expect(
      liveMatchMeta(
        {
          stage: stageFixture({ modes, races: [played, next] }),
          state: "between",
          race: next,
        },
        time,
      ),
    ).toBe("Next: Boss Rush at 17:30");
    expect(
      liveMatchMeta(
        {
          stage: stageFixture({ races: [played] }),
          state: "between",
          race: null,
        },
        time,
      ),
    ).toBe("Next: Race 2");
    const [ana, bob, cleo] = [
      person("ana", "Ana"),
      person("bob", "Bob"),
      person("cleo", "Cleo"),
    ];
    const done = stageFixture({
      complete: true,
      races: [played],
      results: [
        result(ana, 240, true),
        result(bob, 210, true),
        result(cleo, 90),
      ],
    });
    expect(
      liveMatchMeta({ stage: done, state: "finished", race: null }, time),
    ).toBe("Ended 17:15 · Ana and Bob go on");
    expect(
      liveMatchMeta(
        { stage: { ...done, kind: "final" }, state: "finished", race: null },
        time,
      ),
    ).toBe("Ended 17:15 · Ana wins");
  });

  it("titles the zone after what it holds", () => {
    const m = (state: "live" | "finished") => ({
      stage: stageFixture({}),
      state,
      race: null,
    });
    expect(liveZoneTitle([m("finished"), m("live")])).toBe("Live matches");
    expect(liveZoneTitle([m("finished")])).toBe("Just finished");
  });
});

describe("upcomingMatches", () => {
  const now = new Date("2026-10-18T17:25:00Z");
  const at = (minutes: number) =>
    new Date(now.getTime() + minutes * 60_000).toISOString();
  const runner = (id: string) => ({
    user: {
      id,
      twitch_username: id,
      twitch_display_name: null,
      twitch_avatar_url: null,
    },
    label: `Seed ${id}`,
    forfeited: false,
    source: null,
    place: null,
  });
  const dated = (
    key: string,
    date: string,
    overrides: Partial<EventStage> = {},
  ) =>
    stageFixture({
      key,
      date,
      field: [runner("1"), runner("2")],
      ...overrides,
    });
  const keys = (
    stages: EventStage[],
    onAir: Parameters<typeof upcomingMatches>[2] = [],
  ) => upcomingMatches(stages, now, onAir).map((m) => m.stage.key);

  it("lists the dated, decided matches ahead, soonest first", () => {
    const later = dated("group_b", at(3 * 24 * 60));
    const sooner = dated("group_a", at(2 * 24 * 60));
    const undated = stageFixture({ key: "group_c", field: [runner("3")] });
    const undecided = dated("quarter_a", at(24 * 60), {
      field: [
        {
          ...runner("4"),
          user: null,
          label: "1st of Group A",
          source: "group_a",
          place: 1,
        },
      ],
    });
    const done = dated("group_e", at(-60), { complete: true });
    const walkover = dated("group_x", at(60), { walkover: true });
    expect(keys([later, sooner, undated, undecided, done, walkover])).toEqual([
      "group_a",
      "group_b",
    ]);
  });

  it("leaves out a match on air", () => {
    const stage = dated("group_h", at(-30));
    expect(keys([stage], [{ stage, state: "between", race: null }])).toEqual(
      [],
    );
  });

  it("dates a match already begun on another evening by its next race", () => {
    const stage = dated("group_g", at(-2 * 24 * 60), {
      races: [
        {
          slot: "group_g:1",
          index: 1,
          race: {
            status: "finished",
            finished_at: at(-2 * 24 * 60 + 60),
          } as Race,
          points: {},
          live: [],
        },
        {
          slot: "group_g:2",
          index: 2,
          race: { status: "setup", scheduled_at: at(24 * 60) } as Race,
          points: {},
          live: [],
        },
      ],
    });
    expect(upcomingMatches([stage], now, [])).toEqual([
      { stage, at: at(24 * 60), timeSet: true },
    ]);
  });

  it("keeps a late start for two hours", () => {
    expect(keys([dated("a", at(-119)), dated("b", at(-121))])).toEqual(["a"]);
  });

  it("keeps a day-only date until its UTC day ends", () => {
    // A day without its time stands at noon UTC.
    const day = dated("group_a", "2026-10-18T12:00:00.000Z", {
      time_set: false,
    });
    expect(
      upcomingMatches([day], new Date("2026-10-18T23:00:00Z"), []).map(
        (m) => m.timeSet,
      ),
    ).toEqual([false]);
    expect(
      upcomingMatches([day], new Date("2026-10-19T00:30:00Z"), []),
    ).toEqual([]);
  });
});

describe("formatMatchTime", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("gives the time alone on the reference's day, the day too otherwise", () => {
    vi.stubEnv("TZ", "Europe/Paris");
    // 23:30 in Paris on the 12th, then 00:30 on the 13th, then two days on.
    const evening = new Date("2026-10-12T21:30:00Z");
    expect(formatMatchTime("2026-10-12T21:00:00Z", evening)).toBe(
      formatEventTime("2026-10-12T21:00:00Z"),
    );
    expect(formatMatchTime("2026-10-12T22:30:00Z", evening)).toBe(
      formatEventDate("2026-10-12T22:30:00Z"),
    );
    expect(formatMatchTime("2026-10-14T20:00:00Z", evening)).toBe(
      formatEventDate("2026-10-14T20:00:00Z"),
    );
  });
});

describe("startsIn", () => {
  const now = new Date("2026-10-18T17:00:00Z");
  const at = (minutes: number) =>
    new Date(now.getTime() + minutes * 60_000).toISOString();

  it("says how far ahead a match starts, in its coarsest unit", () => {
    expect(startsIn(at(25), now)).toBe("in 25 min");
    expect(startsIn(at(3 * 60 + 59), now)).toBe("in 3 h");
    expect(startsIn(at(24 * 60), now)).toBe("in 1 day");
    expect(startsIn(at(2 * 24 * 60 + 600), now)).toBe("in 2 days");
    expect(startsIn(at(-5), now)).toBe("now");
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

describe("soloSeedLabel", () => {
  it("counts the pool's seeds, and how many of them the viewer ran", () => {
    expect(soloSeedLabel({ available: 8, played_by_user: null })).toBe(
      "8 seeds available",
    );
    expect(soloSeedLabel({ available: 1, played_by_user: 0 })).toBe(
      "1 seed available",
    );
    expect(soloSeedLabel({ available: 8, played_by_user: 3 })).toBe(
      "3/8 seeds played",
    );
    expect(soloSeedLabel({ available: 1, played_by_user: 1 })).toBe(
      "1/1 seed played",
    );
  });

  it("names the mode rather than counting when there is nothing to count", () => {
    // No pool of that name, the counts have not landed yet, or a pool that
    // hands out nothing, which the solo page would ignore a link to.
    expect(soloSeedLabel(undefined)).toBe("Solo seeds");
    expect(soloSeedLabel({ available: 0, played_by_user: null })).toBe(
      "Solo seeds",
    );
  });
});

describe("formatEventDate with the zone, and stageTimes", () => {
  const stagesAt = (...isos: string[]) =>
    isos.map((date, i) => ({
      label: `Stage ${i + 1}`,
      date,
      date_fixed: true,
      time_set: true,
    }));
  // The real season: four Sunday evenings, the last one the day Europe leaves
  // summer time, read from Paris.
  const season = (last: string) =>
    [
      ["Semi A", "2026-10-04T19:00:00Z"],
      ["Semi B", "2026-10-11T19:00:00Z"],
      ["Newcomers' final", "2026-10-18T19:00:00Z"],
      ["Final", last],
    ].map(([label, date]) => ({
      label,
      date,
      date_fixed: true,
      time_set: true,
    }));

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

  it("says nothing while a stage is scheduled with its players", () => {
    const stages = season("2026-10-25T19:00:00Z").map((s, i) =>
      i === 0 ? { ...s, date_fixed: false } : s,
    );
    expect(stageTimes(stages)).toBeNull();
  });

  it("says nothing while a stage's day waits on its time", () => {
    // Its noon UTC stand-in is no evening time to announce, or to set apart.
    vi.stubEnv("TZ", "Europe/Paris");
    const stages = season("2026-10-25T12:00:00Z").map((s, i) =>
      i === 3 ? { ...s, time_set: false } : s,
    );
    expect(stageTimes(stages)).toBeNull();
  });
});

describe("pollIntervalMs and ordinal", () => {
  const stageAt = (iso: string) =>
    [
      { key: "semi_a", label: "Semi A", date: iso, races: [] },
    ] as unknown as EventDetail["stages"];
  const sunday = new Date("2026-10-04T19:00:00Z");

  it("polls every minute while a match is on, between two races included", () => {
    const race = (status: string, extra: Partial<Race> = {}) => ({
      slot: "semi_a:1",
      index: 1,
      race: { status, ...extra } as Race,
      points: {},
      live: [],
    });
    const running = detailWith({
      phase: "playoffs",
      stages: [stageFixture({ races: [race("running")] })],
    });
    expect(pollIntervalMs(running, sunday)).toBe(60_000);
    const between = detailWith({
      phase: "playoffs",
      stages: [
        stageFixture({
          races: [race("finished", { finished_at: "2026-10-04T18:30:00Z" })],
        }),
      ],
    });
    expect(pollIntervalMs(between, sunday)).toBe(60_000);
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
  it("also polls around a later race's own scheduled_at, for a match spread over two evenings", () => {
    const detail = detailWith({
      phase: "playoffs",
      stages: [
        stageFixture({
          key: "quarter_b",
          date: "2026-10-09T19:00:00Z",
          races: [
            {
              slot: "quarter_b:1",
              index: 1,
              race: { scheduled_at: "2026-10-09T19:00:00Z" } as Race,
              points: {},
              live: [],
            },
            {
              slot: "quarter_b:2",
              index: 2,
              race: { scheduled_at: "2026-10-10T19:00:00Z" } as Race,
              points: {},
              live: [],
            },
          ],
        }),
      ],
    });
    // Far from the stage's own date (its first race) but close to the second.
    expect(pollIntervalMs(detail, new Date("2026-10-10T09:30:00Z"))).toBe(
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
  it("ignores a stage without a date", () => {
    const detail = detailWith({
      phase: "playoffs",
      stages: [
        { key: "q", date: null, races: [] },
      ] as unknown as EventDetail["stages"],
    });
    expect(pollIntervalMs(detail, sunday)).toBeNull();
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

describe("openingRefreshMs", () => {
  const opening = "2026-09-23T18:00:00Z";
  const hourBefore = new Date("2026-09-23T17:00:00Z");

  it("reloads an upcoming page at the opening, spread over ten seconds", () => {
    const detail = detailWith({ phase: "upcoming", starts_at: opening });
    expect(openingRefreshMs(detail, hourBefore, 0)).toBe(3_600_000);
    expect(openingRefreshMs(detail, hourBefore, 0.5)).toBe(3_605_000);
  });
  it("reloads right away when the opening has already passed", () => {
    const detail = detailWith({ phase: "upcoming", starts_at: opening });
    expect(openingRefreshMs(detail, new Date("2026-09-23T18:01:00Z"), 0)).toBe(
      0,
    );
  });
  it("sets no timer once open, nor for an opening beyond a timer's reach", () => {
    expect(
      openingRefreshMs(
        detailWith({ phase: "qualifier", starts_at: opening }),
        hourBefore,
        0,
      ),
    ).toBeNull();
    expect(
      openingRefreshMs(
        detailWith({ phase: "upcoming", starts_at: "2026-11-01T18:00:00Z" }),
        hourBefore,
        0,
      ),
    ).toBeNull();
  });
});

describe("signupIntentStands", () => {
  const now = 1_700_000_000_000;

  it("stands for the same event on a prompt return", () => {
    const raw = encodeSignupIntent("season-one", now - 5_000);
    expect(signupIntentStands(raw, "season-one", now)).toBe(true);
  });

  it("never stands for another event", () => {
    const raw = encodeSignupIntent("season-one", now - 5_000);
    expect(signupIntentStands(raw, "season-two", now)).toBe(false);
  });

  it("expires at the window's edge, and stands just inside it", () => {
    const edge = encodeSignupIntent("season-one", now - SIGNUP_INTENT_TTL_MS);
    expect(signupIntentStands(edge, "season-one", now)).toBe(false);
    const inside = encodeSignupIntent(
      "season-one",
      now - SIGNUP_INTENT_TTL_MS + 1,
    );
    expect(signupIntentStands(inside, "season-one", now)).toBe(true);
  });

  it("ignores what it did not write", () => {
    for (const raw of [
      null,
      "season-one",
      "{",
      '{"slug":"season-one"}',
      '{"slug":"season-one","at":"soon"}',
      "42",
    ]) {
      expect(signupIntentStands(raw, "season-one", now)).toBe(false);
    }
  });
});

describe("eventBand", () => {
  const fmt = (iso: string) => `@${iso}`;
  afterEach(() => vi.unstubAllEnvs());
  const eventPage = { href: "/events/season-one", label: "Event page" };
  function summaryWith(partial: Partial<EventSummary>): EventSummary {
    return {
      slug: "season-one",
      starts_at: "2026-09-23T08:00:00Z",
      qualifier_ends_at: "2026-09-30T08:00:00Z",
      phase: "upcoming",
      my_signup: false,
      players: 0,
      player_previews: [],
      next_stage: null,
      live: null,
      champion: null,
      brackets: [],
      ...partial,
    } as EventSummary;
  }

  it("lines up each bracket's qualified from the cut until the playoffs are over", () => {
    const brackets = [
      {
        key: "main",
        label: "Top 32",
        qualified: [{ id: "u1" } as User],
        eliminated: [],
        forfeited: [],
      },
      {
        key: "newcomers",
        label: "Newcomers",
        qualified: [],
        eliminated: [],
        forfeited: [],
      },
    ];
    const live = {
      race: { id: "r7", casters: [] },
      stage_label: "Group A",
      index: 1,
      races_expected: 3,
    } as unknown as EventSummary["live"];
    for (const partial of [
      { phase: "cut" as const },
      { phase: "playoffs" as const },
      { phase: "playoffs" as const, live },
    ]) {
      expect(
        eventBand(summaryWith({ ...partial, brackets }), fmt).brackets,
        JSON.stringify(partial.phase),
      ).toBe(brackets);
    }
    // The qualifier shows who is in instead, the finished band its champion.
    for (const phase of ["upcoming", "qualifier", "finished"] as const) {
      expect(
        eventBand(summaryWith({ phase, brackets }), fmt).brackets,
        phase,
      ).toEqual([]);
    }
  });

  it("advertises the opening while upcoming", () => {
    const young = eventBand(summaryWith({}), fmt);
    expect(young.signal.text).toBe("Upcoming");
    expect(young.line).toBe("Qualifier opens @2026-09-23T08:00:00Z");
    expect(young.actions).toEqual([
      { href: "/events/season-one", label: "Take part", kind: "primary" },
    ]);
  });

  it("names the deadline during the qualifier", () => {
    const open = eventBand(
      summaryWith({ phase: "qualifier", players: 41 }),
      fmt,
    );
    expect(open.signal.text).toBe("Qualifier open");
    expect(open.line).toBe("Closes @2026-09-30T08:00:00Z");
    expect(open.actions[0].label).toBe("Take part");
  });

  it("shows who is in only while the event can be joined and someone is", () => {
    for (const phase of ["upcoming", "qualifier"] as const) {
      expect(
        eventBand(summaryWith({ phase, players: 14 }), fmt).showPlayers,
        phase,
      ).toBe(true);
      expect(
        eventBand(summaryWith({ phase, players: 0 }), fmt).showPlayers,
        phase,
      ).toBe(false);
    }
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(
        eventBand(summaryWith({ phase, players: 14 }), fmt).showPlayers,
        phase,
      ).toBe(false);
    }
  });

  it("reports the viewer as in only while the event can still be joined", () => {
    for (const phase of ["upcoming", "qualifier"] as const) {
      expect(
        eventBand(summaryWith({ phase, my_signup: true }), fmt).signedUp,
        phase,
      ).toBe(true);
    }
    for (const phase of ["cut", "playoffs", "finished"] as const) {
      expect(
        eventBand(summaryWith({ phase, my_signup: true }), fmt).signedUp,
        phase,
      ).toBe(false);
    }
    expect(eventBand(summaryWith({ phase: "qualifier" }), fmt).signedUp).toBe(
      false,
    );
  });

  it("sends a signed-up viewer to the event page instead of asking again", () => {
    const state = eventBand(
      summaryWith({ phase: "qualifier", my_signup: true, players: 3 }),
      fmt,
    );
    expect(state.actions).toEqual([{ ...eventPage, kind: "primary" }]);
  });

  it("names the first evening after the cut", () => {
    const state = eventBand(
      summaryWith({
        phase: "cut",
        next_stage: {
          key: "semi_a",
          label: "Semi A",
          date: "2026-10-04T19:00:00Z",
          time_set: true,
        },
      }),
      fmt,
    );
    expect(state.signal.text).toBe("Playoffs incoming");
    expect(state.line).toBe("Semi A on @2026-10-04T19:00:00Z");
    expect(state.actions).toEqual([{ ...eventPage, kind: "primary" }]);
  });

  it("points at the live race, on Twitch when a caster streams it", () => {
    const casters = [
      { is_live: false, stream_url: null, user: { twitch_username: "quiet" } },
      {
        is_live: true,
        stream_url: "https://twitch.tv/live-one",
        user: { twitch_username: "live-one" },
      },
    ] as Race["casters"];
    const live = {
      race: { id: "r7", casters } as Race,
      stage_label: "Semi A",
      index: 2,
      races_expected: 3,
    };
    const state = eventBand(summaryWith({ phase: "playoffs", live }), fmt);
    expect(state.signal.text).toBe("Live now");
    expect(state.line).toBe("Semi A · Race 2 of 3");
    expect(state.actions).toEqual([
      {
        href: "https://twitch.tv/live-one",
        label: "Watch on Twitch",
        kind: "twitch",
      },
      { ...eventPage, kind: "outline" },
    ]);
    // Nobody live: the first caster's channel, the usual guess.
    const idleCasters = eventBand(
      summaryWith({
        phase: "playoffs",
        live: { ...live, race: { id: "r7", casters: [casters[0]] } as Race },
      }),
      fmt,
    );
    expect(idleCasters.actions[0].href).toBe("https://twitch.tv/quiet");
  });

  it("falls back to the race page when nobody casts the live race", () => {
    const state = eventBand(
      summaryWith({
        phase: "playoffs",
        live: {
          race: { id: "r7", casters: [] } as unknown as Race,
          stage_label: "Semi A",
          index: 1,
          races_expected: 3,
        },
      }),
      fmt,
    );
    expect(state.actions).toEqual([
      { href: "/race/r7", label: "Race page", kind: "primary" },
      { ...eventPage, kind: "outline" },
    ]);
  });

  it("announces the next evening between playoff races", () => {
    const state = eventBand(
      summaryWith({
        phase: "playoffs",
        next_stage: {
          key: "final",
          label: "Final",
          date: "2026-10-25T19:00:00Z",
          time_set: true,
        },
      }),
      fmt,
    );
    expect(state.signal.text).toBe("Playoffs");
    expect(state.line).toBe("Next: Final · @2026-10-25T19:00:00Z");
    expect(state.actions).toEqual([{ ...eventPage, kind: "primary" }]);
    expect(eventBand(summaryWith({ phase: "playoffs" }), fmt).line).toBeNull();
  });

  it("names the next evening's day alone while its time is not set", () => {
    vi.stubEnv("TZ", "America/Los_Angeles");
    const final = {
      key: "final",
      label: "Final",
      date: "2026-10-25T12:00:00Z",
      time_set: false,
    };
    expect(
      eventBand(summaryWith({ phase: "cut", next_stage: final }), fmt).line,
    ).toBe("Final on Sun 25 Oct");
    expect(
      eventBand(summaryWith({ phase: "playoffs", next_stage: final }), fmt)
        .line,
    ).toBe("Next: Final · Sun 25 Oct");
  });

  it("closes on the champion, and on nothing when the final never happened", () => {
    const champion = { twitch_username: "ana" } as User;
    const crowned = eventBand(
      summaryWith({ phase: "finished", champion }),
      fmt,
    );
    expect(crowned.signal.text).toBe("Finished");
    expect(crowned.line).toBe("Champion");
    expect(crowned.actions).toEqual([{ ...eventPage, kind: "primary" }]);
    expect(eventBand(summaryWith({ phase: "finished" }), fmt).line).toBeNull();
  });
});

describe("nextStageLabels", () => {
  const seat = (source: string, place: number) => ({
    user: null,
    label: "",
    forfeited: false,
    source,
    place,
  });
  const stages = [
    stageFixture({ key: "group_a", label: "Group A", advance: 2 }),
    stageFixture({
      key: "quarter_a",
      label: "Quarter A",
      field: [seat("group_a", 1)],
    }),
    stageFixture({
      key: "quarter_c",
      label: "Quarter C",
      field: [seat("group_a", 2)],
    }),
  ];

  it("names, per place, the stage that place goes on to", () => {
    expect(nextStageLabels(stages, "group_a", 2)).toEqual([
      "Quarter A",
      "Quarter C",
    ]);
  });

  it("is empty for a stage nobody goes on from", () => {
    expect(nextStageLabels(stages, "quarter_a", null)).toEqual([]);
  });
});
