import { render } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { describe, expect, it } from "vitest";
import EventBracket from "$lib/components/events/EventBracket.svelte";
import type { EventStage, Race } from "$lib/api";

function raceWith(overrides: Partial<Race> = {}): Race {
  return {
    id: "r1",
    name: "Test Race",
    organizer: {
      id: "u1",
      twitch_username: "org",
      twitch_display_name: "Org",
      twitch_avatar_url: null,
    },
    status: "setup",
    pool_name: null,
    is_public: true,
    open_registration: false,
    max_participants: null,
    created_at: "2026-08-01T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    seeds_released_at: null,
    late_join_window_minutes: null,
    race_duration_minutes: null,
    registration_closes_at: null,
    race_ends_at: null,
    private_dag: false,
    deathless: false,
    custom_rules: null,
    daily_date: null,
    exclude_from_stats: false,
    participant_count: 0,
    participant_previews: [],
    casters: [],
    can_join: false,
    my_role: null,
    event_id: null,
    event_slot: null,
    ...overrides,
  };
}

function stage(overrides: Partial<EventStage> = {}): EventStage {
  return {
    key: "semi_a",
    label: "Semi A",
    kind: "semi",
    date: "2026-10-04T20:00:00Z",
    date_fixed: true,
    from: [],
    races_expected: 3,
    complete: false,
    modes: [],
    races: [],
    results: [],
    field: new Array(8).fill(null).map((_, i) => ({
      user: null,
      label: `Seed ${i + 1}`,
    })),
    ...overrides,
  };
}

const fmtDay = (iso: string) => `Day(${iso})`;

describe("EventBracket stage state and progress", () => {
  it("signals Live for a stage with a running race, Upcoming otherwise", () => {
    const { container } = render(EventBracket, {
      stages: [
        stage({
          key: "semi_a",
          races: [
            {
              slot: "semi_a:1",
              index: 1,
              race: raceWith({ status: "running" }),
            },
          ],
        }),
        stage({ key: "semi_b", label: "Semi B" }),
      ],
      formatDay: fmtDay,
    });
    expect(container.querySelector(".signal-running")).not.toBeNull();
    expect(container.querySelector(".signal-setup")).not.toBeNull();
  });

  it("signals Finished for a complete stage even while one of its races is still running", () => {
    const { container } = render(EventBracket, {
      stages: [
        stage({
          complete: true,
          races: [
            {
              slot: "semi_a:1",
              index: 1,
              race: raceWith({ status: "running" }),
            },
          ],
        }),
      ],
      formatDay: fmtDay,
    });
    expect(container.querySelector(".signal-finished")).not.toBeNull();
    expect(container.querySelector(".signal-running")).toBeNull();
  });

  it("renders one chip per expected race, its mode coloured by the race's state", () => {
    const notStarted = render(EventBracket, {
      stages: [stage({ races_expected: 3, modes: ["Standard", "Boss Rush"] })],
      formatDay: fmtDay,
    });
    const chips = notStarted.container.querySelectorAll(".chips .chip");
    expect([...chips].map((c) => c.textContent)).toEqual([
      "Standard",
      "Boss Rush",
      "Race 3",
    ]);
    expect(notStarted.container.querySelectorAll(".chip-todo").length).toBe(3);
    expect(notStarted.container.querySelectorAll(".chips a").length).toBe(0);
    notStarted.unmount();

    const midStage = render(EventBracket, {
      stages: [
        stage({
          races_expected: 3,
          modes: ["Standard", "Boss Rush", "Sprint"],
          races: [
            {
              slot: "semi_a:1",
              index: 1,
              race: raceWith({ status: "finished" }),
            },
            {
              slot: "semi_a:2",
              index: 2,
              race: raceWith({ status: "running" }),
            },
          ],
        }),
      ],
      formatDay: fmtDay,
    });
    const states = [...midStage.container.querySelectorAll(".chips .chip")].map(
      (c) => c.className.match(/chip-(\w+)/)?.[1],
    );
    expect(states).toEqual(["done", "live", "todo"]);
    // Attached races link to their page; the empty slot does not.
    const links = midStage.container.querySelectorAll(".chips a.chip");
    expect(links.length).toBe(2);
    expect(links[0].getAttribute("href")).toBe("/race/r1");
  });
});

describe("EventBracket rows", () => {
  it("shows results (rank, advance/points) once a stage has them, ignoring the field", () => {
    const { getByText, queryByText } = render(EventBracket, {
      stages: [
        stage({
          results: [
            {
              user: {
                id: "u1",
                twitch_username: "a",
                twitch_display_name: "A",
                twitch_avatar_url: null,
              },
              newcomer: false,
              points: 100,
              igt_total: 1000,
              advances: true,
              signature_weapon: null,
            },
            {
              user: {
                id: "u2",
                twitch_username: "b",
                twitch_display_name: "B",
                twitch_avatar_url: null,
              },
              newcomer: false,
              points: 80,
              igt_total: 1200,
              advances: false,
              signature_weapon: null,
            },
          ],
        }),
      ],
      formatDay: fmtDay,
    });
    expect(getByText("adv 100")).toBeTruthy();
    expect(getByText("80")).toBeTruthy();
    expect(queryByText("Seed 1")).toBeNull();
  });

  it("reads points as provisional (brass) until the stage is complete", () => {
    const results = [
      {
        user: {
          id: "u1",
          twitch_username: "a",
          twitch_display_name: "A",
          twitch_avatar_url: null,
        },
        newcomer: false,
        points: 100,
        igt_total: 1000,
        advances: false,
        signature_weapon: null,
      },
    ];
    const running = render(EventBracket, {
      stages: [stage({ complete: false, results })],
      formatDay: fmtDay,
    });
    expect(running.container.querySelector(".right.prov")).not.toBeNull();
    expect(running.container.querySelector(".right.lead")).toBeNull();

    const done = render(EventBracket, {
      stages: [stage({ complete: true, results })],
      formatDay: fmtDay,
    });
    expect(done.container.querySelector(".right.lead")).not.toBeNull();
    expect(done.container.querySelector(".right.prov")).toBeNull();
  });

  it("falls back to the open field slots when a stage has no results yet, with no rank on an open slot", () => {
    const s = stage();
    const { container } = render(EventBracket, {
      stages: [s],
      formatDay: fmtDay,
    });
    const rows = container.querySelectorAll(".box li");
    expect(rows.length).toBe(s.field.length);
    rows.forEach((row) => {
      expect(row.querySelector(".rank")?.textContent).toBe("");
    });
  });

  it("shows a decided non-seed slot's source stage in the right cell, not as a rank", () => {
    const { container } = render(EventBracket, {
      stages: [
        stage({
          field: [
            {
              user: {
                id: "u1",
                twitch_username: "a",
                twitch_display_name: "A",
                twitch_avatar_url: null,
              },
              label: "Semi A",
            },
            { user: null, label: "Seed 2" },
          ],
        }),
      ],
      formatDay: fmtDay,
    });
    const firstRow = container.querySelector(".box li");
    expect(firstRow?.querySelector(".rank")?.textContent).toBe("");
    expect(firstRow?.querySelector(".right")?.textContent).toBe("Semi A");
  });
});

describe("EventBracket champion box", () => {
  it("marks the champion box decided and names the winner once the final is complete", () => {
    const { container } = render(EventBracket, {
      stages: [
        stage({
          key: "final",
          label: "Grand Final",
          kind: "final",
          complete: true,
          results: [
            {
              user: {
                id: "u1",
                twitch_username: "champ",
                twitch_display_name: "Champ",
                twitch_avatar_url: null,
              },
              newcomer: false,
              points: 100,
              igt_total: 1000,
              advances: false,
              signature_weapon: null,
            },
          ],
        }),
      ],
      formatDay: fmtDay,
    });
    const champBox = container.querySelector(".champ.decided");
    expect(champBox).not.toBeNull();
    expect(champBox?.querySelector(".who")?.textContent).toContain("Champ");
  });

  it("shows a TBD decided-by date while the final is not complete", () => {
    const { container, getByText } = render(EventBracket, {
      stages: [
        stage({
          key: "final",
          label: "Grand Final",
          kind: "final",
          complete: false,
          date: "2026-10-25T20:00:00Z",
        }),
      ],
      formatDay: fmtDay,
    });
    expect(container.querySelector(".champ.decided")).toBeNull();
    expect(getByText(/Decided Day\(2026-10-25T20:00:00Z\)/)).toBeTruthy();
  });
});

const quarters = ["a", "b", "c", "d"].map((x) =>
  stage({
    key: `quarter_${x}`,
    label: `Quarter ${x.toUpperCase()}`,
    kind: "quarter",
    date: null,
    date_fixed: false,
  }),
);
const season = [
  ...quarters,
  stage({
    key: "semi_a",
    label: "Semi A",
    kind: "semi",
    date: null,
    date_fixed: false,
    from: ["quarter_a", "quarter_b"],
    field: [],
  }),
  stage({
    key: "semi_b",
    label: "Semi B",
    kind: "semi",
    date: null,
    date_fixed: false,
    from: ["quarter_c", "quarter_d"],
    field: [],
  }),
  stage({
    key: "final",
    label: "Final",
    kind: "final",
    date: "2026-10-25T19:00:00Z",
    from: ["semi_a", "semi_b"],
    field: [],
  }),
];

const groups = ["a", "b", "c", "d", "e", "f", "g", "h"].map((x) =>
  stage({
    key: `group_${x}`,
    label: `Group ${x.toUpperCase()}`,
    kind: "round",
    date: null,
    date_fixed: false,
    field: new Array(4).fill(null).map((_, i) => ({
      user: null,
      label: `Seed ${i + 1}`,
    })),
  }),
);
const roundSeason = [
  ...groups,
  ...season.map((s, i) =>
    s.kind === "quarter"
      ? {
          ...s,
          from: [`group_${"aceg"[i]}`, `group_${"bdfh"[i]}`],
          field: [],
        }
      : s,
  ),
];

describe("EventBracket layout", () => {
  // Grid placement itself (rows, spans, link centres) is bracketLayout's,
  // tested in events.test.ts; jsdom does not lay grids out.
  it("puts a four-quarter season on one full-width grid with the Champion and the evening", () => {
    const { container } = render(EventBracket, {
      stages: season,
      formatDay: fmtDay,
    });
    const grid = container.querySelector(".brk.tall");
    expect(grid).not.toBeNull();
    expect(grid?.querySelectorAll(".cell").length).toBe(7);
    expect(grid?.querySelector(".champ-cell .champ")).not.toBeNull();
    // The tall grid carries the section title itself, the short one beside it.
    expect(grid?.querySelector(".title h2")?.textContent).toContain("Bracket");
  });

  it("names an unscheduled match's date as to be agreed", () => {
    const { getAllByText } = render(EventBracket, {
      stages: season,
      formatDay: fmtDay,
    });
    expect(getAllByText("Date to be agreed").length).toBe(6);
  });

  it("keeps a two-semis season in two columns", () => {
    const { container } = render(EventBracket, {
      stages: [
        stage({ key: "semi_a" }),
        stage({ key: "semi_b", label: "Semi B" }),
        stage({
          key: "final",
          label: "Final",
          kind: "final",
          from: ["semi_a", "semi_b"],
          field: [],
        }),
      ],
      formatDay: fmtDay,
    });
    expect(container.querySelector(".brk.tall")).toBeNull();
    expect(container.querySelector(".split")).not.toBeNull();
  });

  it("narrows the side column so a four-round tree keeps wide rounds", () => {
    const wide = render(EventBracket, { stages: season, formatDay: fmtDay });
    const narrow = render(EventBracket, {
      stages: roundSeason,
      formatDay: fmtDay,
    });
    const sideOf = (container: HTMLElement) =>
      (container.querySelector(".brk.tall") as HTMLElement).style
        .gridTemplateColumns;
    expect(sideOf(wide.container)).toContain("1.25fr");
    expect(sideOf(narrow.container)).toContain("0.8fr");
    expect(sideOf(narrow.container)).not.toContain("1.25fr");
  });

  const evening = createRawSnippet(() => ({ render: () => "<p>Evening</p>" }));
  const rulesCard = createRawSnippet(() => ({
    render: () => "<ul><li>Rule</li></ul>",
  }));

  it("spreads the evening over the final's column in a four-round tree", () => {
    const { container } = render(EventBracket, {
      stages: roundSeason,
      formatDay: fmtDay,
      aside: evening,
      rules: rulesCard,
    });
    const grid = container.querySelector(".brk.tall") as HTMLElement;
    // Rounds sit in columns 1, 3, 5 and 7 (the final), the side column is 9.
    expect((grid.querySelector(".aside") as HTMLElement).style.gridColumn).toBe(
      "7 / span 3",
    );
    expect((grid.querySelector(".title") as HTMLElement).style.gridColumn).toBe(
      "1 / 7",
    );
    expect((grid.querySelector(".rules") as HTMLElement).style.gridColumn).toBe(
      "1 / -1",
    );
  });

  it("keeps the evening in the side column of a three-round tree", () => {
    const { container } = render(EventBracket, {
      stages: season,
      formatDay: fmtDay,
      aside: evening,
      rules: rulesCard,
    });
    const grid = container.querySelector(".brk.tall") as HTMLElement;
    expect((grid.querySelector(".aside") as HTMLElement).style.gridColumn).toBe(
      "7",
    );
    expect((grid.querySelector(".rules") as HTMLElement).style.gridColumn).toBe(
      "1 / -1",
    );
  });
});
