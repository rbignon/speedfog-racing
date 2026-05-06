import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import DailyWeekGrid from "$lib/components/DailyWeekGrid.svelte";
import type { DailyWeekResponse } from "$lib/api";

const mockWeek: DailyWeekResponse = {
  week_start: "2026-04-27",
  today: "2026-04-29",
  days: [
    {
      weekday: 0,
      date: "2026-04-27",
      state: "past",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: "race-1",
      started_at: "2026-04-27T08:00:00Z",
      ends_at: "2026-04-28T08:00:00Z",
      starters_count: 3,
      participants_count: 5,
      podium: [
        {
          placement: 1,
          twitch_username: "alice",
          twitch_display_name: "Alice",
          twitch_avatar_url: null,
          igt_ms: 2_400_000,
        },
      ],
      my_result: {
        status: "finished",
        placement: 2,
        total_starters: 3,
        igt_ms: 2_700_000,
        death_count: 1,
      },
    },
    {
      weekday: 1,
      date: "2026-04-28",
      state: "missing_past",
      pool_name: null,
      pool_display_name: null,
      race_id: null,
      started_at: null,
      ends_at: null,
      starters_count: 0,
      participants_count: 0,
      podium: [],
      my_result: null,
    },
    {
      weekday: 2,
      date: "2026-04-29",
      state: "today",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: "race-today",
      started_at: "2026-04-29T08:00:00Z",
      ends_at: "2026-04-30T08:00:00Z",
      starters_count: 0,
      participants_count: 2,
      podium: [],
      my_result: null,
    },
    {
      weekday: 3,
      date: "2026-04-30",
      state: "future",
      pool_name: "hardcore",
      pool_display_name: "Hardcore",
      race_id: null,
      started_at: "2026-04-30T08:00:00Z",
      ends_at: "2026-05-01T08:00:00Z",
      starters_count: 0,
      participants_count: 0,
      podium: [],
      my_result: null,
    },
    {
      weekday: 4,
      date: "2026-05-01",
      state: "future",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: null,
      started_at: "2026-05-01T08:00:00Z",
      ends_at: "2026-05-02T08:00:00Z",
      starters_count: 0,
      participants_count: 0,
      podium: [],
      my_result: null,
    },
    {
      weekday: 5,
      date: "2026-05-02",
      state: "future",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: null,
      started_at: "2026-05-02T08:00:00Z",
      ends_at: "2026-05-03T08:00:00Z",
      starters_count: 0,
      participants_count: 0,
      podium: [],
      my_result: null,
    },
    {
      weekday: 6,
      date: "2026-05-03",
      state: "future",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: null,
      started_at: "2026-05-03T08:00:00Z",
      ends_at: "2026-05-04T08:00:00Z",
      starters_count: 0,
      participants_count: 0,
      podium: [],
      my_result: null,
    },
  ],
};

describe("DailyWeekGrid", () => {
  it("renders 7 cells in Mon..Sun order", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: "me", variant: "home" },
    });
    const cells = container.querySelectorAll("[data-cell-state]");
    expect(cells).toHaveLength(7);
  });

  it("marks the today cell with the today state attribute", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: null, variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    expect(todayCell).not.toBeNull();
  });

  it("renders the finished strip on a past cell split into icon + score", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: "me", variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    const strip = pastCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-finished")).toBe(true);
    expect(strip?.querySelector(".strip-icon")?.textContent ?? "").toBe("✓");
    expect(strip?.querySelector(".strip-score")?.textContent ?? "").toMatch(
      /2\/3/,
    );
    expect(strip?.textContent ?? "").not.toMatch(/Done/i);
    expect(pastCell?.querySelector(".me")).toBeNull();
  });

  it("renders the abandoned strip on a past abandoned cell", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "past"
          ? {
              ...d,
              my_result: {
                status: "abandoned",
                placement: null,
                total_starters: 3,
                igt_ms: null,
                death_count: 2,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    const strip = pastCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-abandoned")).toBe(true);
    expect(strip?.textContent ?? "").toMatch(/Abandoned/i);
  });

  it("renders an invisible placeholder strip on a past cell the viewer did not participate in", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "past" ? { ...d, my_result: null } : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    const strip = pastCell?.querySelector(".strip");
    expect(strip).not.toBeNull();
    expect(strip?.classList.contains("strip-placeholder")).toBe(true);
    expect(strip?.classList.contains("strip-finished")).toBe(false);
    expect(strip?.classList.contains("strip-abandoned")).toBe(false);
  });

  it("renders missing_past placeholder without a link", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: null, variant: "home" },
    });
    const cell = container.querySelector('[data-cell-state="missing_past"]');
    expect(cell?.tagName).not.toBe("A");
  });

  it("renders future cell with a countdown text", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: null, variant: "home" },
    });
    const cell = container.querySelector('[data-cell-state="future"]');
    expect(cell?.textContent ?? "").toMatch(/Opens in/);
  });

  it("renders the play-now strip on today when the viewer has no result", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: "me", variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    const strip = todayCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-play-now")).toBe(true);
    expect(strip?.textContent ?? "").toMatch(/Play now/i);
  });

  it("renders the in-progress strip on today when the viewer is registered", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              my_result: {
                status: "registered",
                placement: null,
                total_starters: 0,
                igt_ms: null,
                death_count: 0,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const strip = container.querySelector('[data-cell-state="today"] .strip');
    expect(strip?.classList.contains("strip-in-progress")).toBe(true);
    expect(strip?.textContent ?? "").toMatch(/In progress/i);
  });

  it("renders the finished strip on today with placement/IGT merged in", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              my_result: {
                status: "finished",
                placement: 4,
                total_starters: 17,
                igt_ms: 2_468_000,
                death_count: 0,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    const strip = todayCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-finished")).toBe(true);
    expect(strip?.querySelector(".strip-icon")?.textContent ?? "").toBe("✓");
    expect(strip?.querySelector(".strip-score")?.textContent ?? "").toMatch(
      /4\/17/,
    );
    expect(todayCell?.querySelector(".me")).toBeNull();
  });

  it("renders the abandoned strip on today when the viewer abandoned", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              my_result: {
                status: "abandoned",
                placement: null,
                total_starters: 0,
                igt_ms: null,
                death_count: 0,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const strip = container.querySelector('[data-cell-state="today"] .strip');
    expect(strip?.classList.contains("strip-abandoned")).toBe(true);
    expect(strip?.textContent ?? "").toMatch(/Abandoned/i);
  });

  it("does not bleed placement/IGT into a non-finished strip", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              my_result: {
                status: "registered",
                placement: null,
                total_starters: 0,
                igt_ms: null,
                death_count: 0,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const strip = container.querySelector('[data-cell-state="today"] .strip');
    expect(strip?.textContent ?? "").not.toContain("✓");
    expect(strip?.textContent ?? "").not.toMatch(/\d+\/\d+/);
  });

  it("does not render a winner on the today cell even when the podium has finishers", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              starters_count: 1,
              podium: [
                {
                  placement: 1,
                  twitch_username: "alice",
                  twitch_display_name: "Alice",
                  twitch_avatar_url: null,
                  igt_ms: 2_400_000,
                },
              ],
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    expect(todayCell?.querySelector(".winner")).toBeNull();
    expect(todayCell?.textContent ?? "").not.toContain("Alice");
  });

  it("renders only the winner on past cells, not full top 3", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "past"
          ? {
              ...d,
              podium: [
                {
                  placement: 1,
                  twitch_username: "alice",
                  twitch_display_name: "Alice",
                  twitch_avatar_url: null,
                  igt_ms: 2_400_000,
                },
                {
                  placement: 2,
                  twitch_username: "bob",
                  twitch_display_name: "Bob",
                  twitch_avatar_url: null,
                  igt_ms: 2_500_000,
                },
                {
                  placement: 3,
                  twitch_username: "carol",
                  twitch_display_name: "Carol",
                  twitch_avatar_url: null,
                  igt_ms: 2_600_000,
                },
              ],
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, userId: "me", variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    const winner = pastCell?.querySelector(".winner");
    expect(winner?.textContent ?? "").toContain("Alice");
    expect(pastCell?.textContent ?? "").not.toContain("Bob");
    expect(pastCell?.textContent ?? "").not.toContain("Carol");
  });

  it("applies the selected class to the cell whose date matches selectedDate", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: mockWeek,
        userId: "me",
        variant: "daily-detail",
        selectedDate: "2026-04-27",
      },
    });
    const selected = container.querySelector(".cell.selected");
    expect(selected).not.toBeNull();
    expect(selected?.getAttribute("data-cell-date")).toBe("2026-04-27");
    expect(selected?.getAttribute("data-cell-state")).toBe("past");
  });

  it("stacks today and selected when selectedDate matches today", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: mockWeek,
        userId: null,
        variant: "daily-detail",
        selectedDate: mockWeek.today,
      },
    });
    const cell = container.querySelector(
      `[data-cell-date="${mockWeek.today}"]`,
    );
    expect(cell?.classList.contains("today")).toBe(true);
    expect(cell?.classList.contains("selected")).toBe(true);
  });

  it("renders no selected cell when selectedDate is omitted", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: null, variant: "home" },
    });
    expect(container.querySelector(".cell.selected")).toBeNull();
  });

  it("disables the next arrow when the displayed week starts at the current week", () => {
    // mockWeek's week_start (2026-04-27) matches the Monday of mockWeek.today
    // (2026-04-29), so we are on the current week and "next" should be off.
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: null, variant: "home" },
    });
    const next = container.querySelector(
      'button[data-week-nav="next"]',
    ) as HTMLButtonElement | null;
    expect(next?.disabled).toBe(true);
  });

  it("enables the next arrow when the displayed week is in the past", () => {
    const pastWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-04-20", // Monday of a past week
      // today stays 2026-04-29 -> the displayed week is strictly before today's week
    };
    const { container } = render(DailyWeekGrid, {
      props: { week: pastWeek, userId: null, variant: "daily-detail" },
    });
    const next = container.querySelector(
      'button[data-week-nav="next"]',
    ) as HTMLButtonElement | null;
    expect(next?.disabled).toBe(false);
  });
});
