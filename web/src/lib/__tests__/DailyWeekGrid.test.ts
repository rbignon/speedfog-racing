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
      finishers_count: 3,
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
        total_finishers: 3,
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
      finishers_count: 0,
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
      finishers_count: 0,
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
      finishers_count: 0,
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
      finishers_count: 0,
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
      finishers_count: 0,
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
      finishers_count: 0,
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

  it("renders the played indicator on the past cell when my_result is set", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, userId: "me", variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    expect(pastCell?.classList.contains("played")).toBe(true);
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
});
