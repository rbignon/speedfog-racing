import { render } from "@testing-library/svelte";
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

const fmt = (iso: string) => `D(${iso})`;
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
      formatDate: fmt,
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
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(container.querySelector(".signal-finished")).not.toBeNull();
    expect(container.querySelector(".signal-running")).toBeNull();
  });

  it("shows the races-expected count before any race is played, and the next race number mid-stage", () => {
    const notStarted = render(EventBracket, {
      stages: [stage({ races_expected: 3 })],
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(notStarted.getByText(/3 races/)).toBeTruthy();
    notStarted.unmount();

    const midStage = render(EventBracket, {
      stages: [
        stage({
          races_expected: 3,
          races: [
            {
              slot: "semi_a:1",
              index: 1,
              race: raceWith({ status: "finished" }),
            },
            { slot: "semi_a:2", index: 2, race: raceWith({ status: "setup" }) },
          ],
        }),
      ],
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(midStage.getByText(/race 2 of 3/)).toBeTruthy();
  });

  it("clamps the next-race number at races_expected once every expected race has been played", () => {
    const { getByText } = render(EventBracket, {
      stages: [
        stage({
          races_expected: 3,
          complete: false,
          races: [
            {
              slot: "semi_a:1",
              index: 1,
              race: raceWith({ status: "finished" }),
            },
            {
              slot: "semi_a:2",
              index: 2,
              race: raceWith({ status: "finished" }),
            },
            {
              slot: "semi_a:3",
              index: 3,
              race: raceWith({ status: "finished" }),
            },
          ],
        }),
      ],
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(getByText(/race 3 of 3/)).toBeTruthy();
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
            },
          ],
        }),
      ],
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(getByText("adv 100")).toBeTruthy();
    expect(getByText("80")).toBeTruthy();
    expect(queryByText("Seed 1")).toBeNull();
  });

  it("falls back to the open field slots when a stage has no results yet, with no rank on an open slot", () => {
    const s = stage();
    const { container } = render(EventBracket, {
      stages: [s],
      formatDate: fmt,
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
      formatDate: fmt,
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
            },
          ],
        }),
      ],
      formatDate: fmt,
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
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(container.querySelector(".champ.decided")).toBeNull();
    expect(getByText(/Decided D\(2026-10-25T20:00:00Z\)/)).toBeTruthy();
  });
});

describe("EventBracket modes line", () => {
  it("lists only the stages that carry modes, skipping empty ones", () => {
    const { getByText, queryByText } = render(EventBracket, {
      stages: [
        stage({ key: "semi_a", label: "Semi A", modes: ["Standard", "Hard"] }),
        stage({ key: "semi_b", label: "Semi B", modes: [] }),
      ],
      formatDate: fmt,
      formatDay: fmtDay,
    });
    expect(getByText("Semi A: Standard, Hard")).toBeTruthy();
    expect(queryByText(/Semi B:/)).toBeNull();
  });
});
