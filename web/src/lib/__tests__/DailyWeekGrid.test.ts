import { fireEvent, render } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it, vi } from "vitest";
import DailyWeekGrid from "$lib/components/DailyWeekGrid.svelte";
import type { DailyWeekDay, DailyWeekResponse } from "$lib/api";
import { cellStrip } from "$lib/daily";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, fetchDailyWeek: vi.fn() };
});

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
        qualifies: true,
      },
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
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
      freeze_protected: false,
      deathless: false,
    },
  ],
  has_earlier: true,
  my_streak: null,
  winners: null,
};

describe("DailyWeekGrid", () => {
  it("renders 7 cells in Mon..Sun order", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const cells = container.querySelectorAll("[data-cell-state]");
    expect(cells).toHaveLength(7);
  });

  it("marks the today cell with the today state attribute", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    expect(todayCell).not.toBeNull();
    // Unfinished today: the traveling dot rides its segment; the line
    // always closes on a terminal square.
    expect(todayCell?.querySelector(".wl .wl-train")).not.toBeNull();
    expect(container.querySelector(".wl-term")).not.toBeNull();
  });

  it("renders the finished strip score on a past cell", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const pastCell = container.querySelector('[data-cell-state="past"]');
    const strip = pastCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-finished")).toBe(true);
    expect(strip?.querySelector(".strip-score")?.textContent ?? "").toMatch(
      /2\/3/,
    );
    expect(strip?.textContent ?? "").not.toMatch(/Done/i);
    expect(pastCell?.querySelector(".me")).toBeNull();
  });

  it("renders the viewer's finished days as verdigris week-line segments", () => {
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
                qualifies: true,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
    });
    // Past cell: mockWeek's first past day carries a finished my_result.
    const pastSeg = container.querySelector('[data-cell-state="past"] .wl');
    expect(pastSeg?.classList.contains("wl-done")).toBe(true);
    // Today finished: done segment, and the traveling dot stops.
    const todaySeg = container.querySelector('[data-cell-state="today"] .wl');
    expect(todaySeg?.classList.contains("wl-done")).toBe(true);
    expect(todaySeg?.querySelector(".wl-train")).toBeNull();
    // The week line always spans all 7 cells, one segment each.
    expect(container.querySelectorAll(".wl")).toHaveLength(7);
  });

  it("renders today's segment in brass while the viewer is riding the seed", () => {
    const week: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today"
          ? {
              ...d,
              my_result: {
                status: "playing",
                placement: null,
                total_starters: 9,
                igt_ms: 600_000,
                death_count: 2,
                qualifies: false,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
    });
    const todaySeg = container.querySelector('[data-cell-state="today"] .wl');
    expect(todaySeg?.classList.contains("wl-playing")).toBe(true);
    expect(todaySeg?.querySelector(".wl-train")).not.toBeNull();
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
                qualifies: false,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
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
      props: { week, variant: "home" },
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
      props: { week: mockWeek, variant: "home" },
    });
    const cell = container.querySelector('[data-cell-state="missing_past"]');
    expect(cell?.tagName).not.toBe("A");
  });

  it("renders future cell with a countdown text", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const cell = container.querySelector('[data-cell-state="future"]');
    expect(cell?.textContent ?? "").toMatch(/Opens in/);
  });

  it("formats the countdown as Xm Ys when under 1h", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-04-30T07:15:23Z"));
      const week: DailyWeekResponse = {
        ...mockWeek,
        days: mockWeek.days.map((d) =>
          d.state === "future" && d.date === "2026-04-30"
            ? { ...d, started_at: "2026-04-30T08:00:00Z" }
            : d,
        ),
      };
      const { container } = render(DailyWeekGrid, {
        props: { week, variant: "home" },
      });
      const cell = container.querySelector('[data-cell-state="future"]');
      expect(cell?.textContent ?? "").toMatch(/Opens in 44m 37s/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("formats the countdown as just seconds in the final minute", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-04-30T07:59:18Z"));
      const week: DailyWeekResponse = {
        ...mockWeek,
        days: mockWeek.days.map((d) =>
          d.state === "future" && d.date === "2026-04-30"
            ? { ...d, started_at: "2026-04-30T08:00:00Z" }
            : d,
        ),
      };
      const { container } = render(DailyWeekGrid, {
        props: { week, variant: "home" },
      });
      const cell = container.querySelector('[data-cell-state="future"]');
      expect(cell?.textContent ?? "").toMatch(/Opens in 42s/);
      expect(cell?.textContent ?? "").not.toMatch(/0m/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the Xh Ym format at exactly 1h remaining", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-04-30T07:00:00Z"));
      const week: DailyWeekResponse = {
        ...mockWeek,
        days: mockWeek.days.map((d) =>
          d.state === "future" && d.date === "2026-04-30"
            ? { ...d, started_at: "2026-04-30T08:00:00Z" }
            : d,
        ),
      };
      const { container } = render(DailyWeekGrid, {
        props: { week, variant: "home" },
      });
      const cell = container.querySelector('[data-cell-state="future"]');
      expect(cell?.textContent ?? "").toMatch(/Opens in 1h 00m/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the play-now strip on today when the viewer has no result", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
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
                qualifies: false,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
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
                qualifies: true,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    const strip = todayCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-finished")).toBe(true);
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
                qualifies: false,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
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
                qualifies: false,
              },
            }
          : d,
      ),
    };
    const { container } = render(DailyWeekGrid, {
      props: { week, variant: "home" },
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
      props: { week, variant: "home" },
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
      props: { week, variant: "home" },
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
      props: { week: mockWeek, variant: "home" },
    });
    expect(container.querySelector(".cell.selected")).toBeNull();
  });

  it("disables the next arrow when the displayed week starts at the current week", () => {
    // mockWeek's week_start (2026-04-27) matches the Monday of mockWeek.today
    // (2026-04-29), so we are on the current week and "next" should be off.
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const next = container.querySelector(
      'button[data-week-nav="next"]',
    ) as HTMLButtonElement | null;
    expect(next?.disabled).toBe(true);
  });

  it("hides the play-now strip on the today cell when it is selected", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: mockWeek,
        variant: "daily-detail",
        selectedDate: mockWeek.today,
      },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    const strip = todayCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-play-now")).toBe(false);
    expect(strip?.classList.contains("strip-placeholder")).toBe(true);
  });

  it("still shows the play-now strip on today when not selected", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const todayCell = container.querySelector('[data-cell-state="today"]');
    const strip = todayCell?.querySelector(".strip");
    expect(strip?.classList.contains("strip-play-now")).toBe(true);
  });

  it("disables the prev arrow when has_earlier is false", () => {
    const noEarlier: DailyWeekResponse = { ...mockWeek, has_earlier: false };
    const { container } = render(DailyWeekGrid, {
      props: { week: noEarlier, variant: "home" },
    });
    const prev = container.querySelector(
      'button[data-week-nav="prev"]',
    ) as HTMLButtonElement | null;
    expect(prev?.disabled).toBe(true);
  });

  it("enables the next arrow when the displayed week is in the past", () => {
    const pastWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-04-20", // Monday of a past week
      // today stays 2026-04-29 -> the displayed week is strictly before today's week
    };
    const { container } = render(DailyWeekGrid, {
      props: { week: pastWeek, variant: "daily-detail" },
    });
    const next = container.querySelector(
      'button[data-week-nav="next"]',
    ) as HTMLButtonElement | null;
    expect(next?.disabled).toBe(false);
  });

  it("applies live-patched props on the same week (today_count updates in place)", async () => {
    // /daily/[date] rebinds ``week`` on every WS event with a same-week_start
    // patched reference. The grid must reflect the new participants_count.
    const { container, rerender } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    const todayCell = () =>
      container.querySelector('[data-cell-state="today"]');
    expect(todayCell()?.textContent ?? "").toMatch(/2\s+players/);

    const patched: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today" ? { ...d, participants_count: 7 } : d,
      ),
    };
    await rerender({ week: patched, variant: "home" });
    expect(todayCell()?.textContent ?? "").toMatch(/7\s+players/);
  });

  it("preserves local week navigation when the parent rebinds the same week_start", async () => {
    // Regression guard: the previous unconditional ``displayedWeek = week``
    // reset clobbered the user's prev/next navigation on every WS-driven
    // rebind. Only a different parent ``week_start`` (URL change) should
    // resync the displayed week.
    const { fetchDailyWeek } = await import("$lib/api");
    const earlierWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-04-20",
      today: "2026-04-29",
      days: mockWeek.days.map((d, i) => ({
        ...d,
        date: `2026-04-${String(20 + i).padStart(2, "0")}`,
        state: "past",
      })),
      has_earlier: false,
    };
    vi.mocked(fetchDailyWeek).mockResolvedValueOnce(earlierWeek);

    const { container, rerender } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });

    const prev = container.querySelector(
      'button[data-week-nav="prev"]',
    ) as HTMLButtonElement;
    await fireEvent.click(prev);
    // After the local navigation, displayed week starts at 2026-04-20.
    expect(
      container.querySelector('[data-cell-date="2026-04-20"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-cell-date="2026-04-27"]')).toBeNull();

    // Parent rebinds with a same-week_start (live patch on the original
    // week): the user must remain on the earlier week they navigated to.
    const livePatched: DailyWeekResponse = {
      ...mockWeek,
      days: mockWeek.days.map((d) =>
        d.state === "today" ? { ...d, participants_count: 99 } : d,
      ),
    };
    await rerender({ week: livePatched, variant: "home" });
    expect(
      container.querySelector('[data-cell-date="2026-04-20"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-cell-date="2026-04-27"]')).toBeNull();
  });

  it("resyncs to the parent's week when ``week_start`` changes (URL nav)", async () => {
    // SvelteKit may reuse this component instance when navigating between
    // /daily/[date] URLs. A different parent week_start signals "anchor
    // moved", and we must follow it even if the user had a local prev/next
    // navigation in flight.
    const { fetchDailyWeek } = await import("$lib/api");
    const earlierWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-04-20",
      days: mockWeek.days.map((d, i) => ({
        ...d,
        date: `2026-04-${String(20 + i).padStart(2, "0")}`,
        state: "past",
      })),
    };
    vi.mocked(fetchDailyWeek).mockResolvedValueOnce(earlierWeek);

    const { container, rerender } = render(DailyWeekGrid, {
      props: { week: mockWeek, variant: "home" },
    });
    await fireEvent.click(
      container.querySelector(
        'button[data-week-nav="prev"]',
      ) as HTMLButtonElement,
    );

    const newAnchorWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-05-04",
      today: "2026-05-06",
      days: mockWeek.days.map((d, i) => ({
        ...d,
        date: `2026-05-${String(4 + i).padStart(2, "0")}`,
      })),
    };
    await rerender({ week: newAnchorWeek, variant: "home" });

    expect(
      container.querySelector('[data-cell-date="2026-05-06"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-cell-date="2026-04-20"]')).toBeNull();
  });
});

describe("cellStrip", () => {
  function makeDay(overrides: Partial<DailyWeekDay>): DailyWeekDay {
    return {
      weekday: 4,
      date: "2026-05-09",
      state: "past",
      pool_name: "standard",
      pool_display_name: "Standard",
      race_id: "11111111-1111-1111-1111-111111111111",
      started_at: "2026-05-09T08:00:00Z",
      ends_at: "2026-05-10T08:00:00Z",
      starters_count: 3,
      participants_count: 5,
      podium: [],
      my_result: null,
      freeze_protected: false,
      deathless: false,
      ...overrides,
    };
  }

  it("returns freeze label on a past day flagged freeze_protected", () => {
    const day = makeDay({ freeze_protected: true });
    expect(cellStrip(day, null)).toEqual({
      kind: "label",
      text: "❄ Freeze",
      variant: "freeze",
    });
  });

  it("returns dnf strip on past day where viewer abandoned with qualifies", () => {
    const day = makeDay({
      state: "past",
      my_result: {
        status: "abandoned",
        placement: null,
        total_starters: 4,
        igt_ms: null,
        death_count: 2,
        qualifies: true,
      },
    });
    expect(cellStrip(day, null)).toEqual({ kind: "dnf", igt: null });
  });

  it("returns Abandoned label on past day where viewer abandoned without qualifying", () => {
    const day = makeDay({
      state: "past",
      my_result: {
        status: "abandoned",
        placement: null,
        total_starters: 4,
        igt_ms: null,
        death_count: 0,
        qualifies: false,
      },
    });
    expect(cellStrip(day, null)).toEqual({
      kind: "label",
      text: "Abandoned",
      variant: "abandoned",
    });
  });

  it("returns PLAY NOW on today for an anonymous viewer", () => {
    const day = makeDay({ state: "today", my_result: null });
    expect(cellStrip(day, null)).toEqual({
      kind: "label",
      text: "PLAY NOW",
      variant: "play-now",
    });
  });

  it("today cell shows KEEP STREAK when viewer has an active streak", () => {
    const day = makeDay({ state: "today", my_result: null });
    expect(cellStrip(day, null, 7)).toEqual({
      kind: "label",
      text: "KEEP STREAK",
      variant: "play-now",
    });
  });

  it("today cell stays PLAY NOW when viewer has no streak", () => {
    const day = makeDay({ state: "today", my_result: null });
    expect(cellStrip(day, null, 0)).toEqual({
      kind: "label",
      text: "PLAY NOW",
      variant: "play-now",
    });
  });
});

function makeWinner(i: number, name: string) {
  return {
    user: {
      id: `u-${i}`,
      twitch_username: name.toLowerCase(),
      twitch_display_name: name,
      twitch_avatar_url: null,
      equipped_badge_id: null,
      equipped_name_template_id: null,
      equipped_phantom_skin_id: null,
    },
    total_points: 200 - i,
  };
}

describe("DailyWeekGrid: winners block", () => {
  function fixtureWithWinners(winners: ReturnType<typeof makeWinner>[] | null) {
    return { ...mockWeek, winners };
  }

  it("renders nothing when winners is null (current week)", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: fixtureWithWinners(null), variant: "home" },
    });
    expect(container.querySelector(".grid-winners")).toBeNull();
  });

  it("renders nothing when winners is an empty array", () => {
    const { container } = render(DailyWeekGrid, {
      props: { week: fixtureWithWinners([]), variant: "home" },
    });
    expect(container.querySelector(".grid-winners")).toBeNull();
  });

  it("renders Alice for one winner, marked by the avatar, not a tag", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: fixtureWithWinners([makeWinner(0, "Alice")]),
        variant: "home",
      },
    });
    const block = container.querySelector(".grid-winners");
    expect(block?.textContent ?? "").toMatch(/Alice/);
    expect(block?.textContent ?? "").not.toMatch(/1st/);
  });

  it("renders Alice & Bob for two winners", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: fixtureWithWinners([
          makeWinner(0, "Alice"),
          makeWinner(1, "Bob"),
        ]),
        variant: "home",
      },
    });
    const block = container.querySelector(".grid-winners");
    expect(block?.textContent ?? "").toMatch(/Alice/);
    expect(block?.textContent ?? "").toMatch(/Bob/);
    expect(block?.textContent ?? "").toMatch(/&/);
  });

  it("renders Alice +2 for three winners", () => {
    const { container } = render(DailyWeekGrid, {
      props: {
        week: fixtureWithWinners([
          makeWinner(0, "Alice"),
          makeWinner(1, "Bob"),
          makeWinner(2, "Carol"),
        ]),
        variant: "home",
      },
    });
    const block = container.querySelector(".grid-winners");
    expect(block?.textContent ?? "").toMatch(/Alice/);
    expect(block?.textContent ?? "").toMatch(/\+2/);
  });
});

describe("DailyWeekGrid: onWeekChange", () => {
  it("reports the initial week on mount and the navigated week on prev", async () => {
    const { fetchDailyWeek } = await import("$lib/api");
    const earlierWeek: DailyWeekResponse = {
      ...mockWeek,
      week_start: "2026-04-20",
      has_earlier: false,
    };
    vi.mocked(fetchDailyWeek).mockResolvedValueOnce(earlierWeek);

    const reported: string[] = [];
    const { container } = render(DailyWeekGrid, {
      props: {
        week: mockWeek,
        variant: "home",
        onWeekChange: (w: string) => reported.push(w),
      },
    });
    await tick();
    expect(reported).toEqual(["2026-04-27"]);

    const prev = container.querySelector(
      'button[data-week-nav="prev"]',
    ) as HTMLButtonElement;
    await fireEvent.click(prev);
    await tick();
    expect(reported[reported.length - 1]).toBe("2026-04-20");
  });
});
