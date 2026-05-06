import { describe, expect, it } from "vitest";
import {
  applyLiveDailyDayUpdate,
  currentUserParticipant,
  dailyPathForDate,
  dailyTheme,
  dailyTitle,
} from "$lib/daily";
import type {
  DailyWeekDay,
  DailyWeekResponse,
  Participant,
  RaceDetail,
} from "$lib/api";
import type { WsParticipant } from "$lib/websocket";

const baseParticipant = {
  current_layer: 0,
  death_count: 0,
  igt_ms: 0,
  color_index: 0,
  user: {
    id: "user-id",
    twitch_username: "user",
    twitch_display_name: "User",
    twitch_avatar_url: null,
  },
} as const;

function participant(overrides: Partial<Participant>): Participant {
  return {
    ...baseParticipant,
    id: "p",
    status: "registered",
    ...overrides,
  } as Participant;
}

function detail(participants: Participant[]): RaceDetail {
  // Cast through unknown so the test only fills the fields the helpers read.
  return { participants } as unknown as RaceDetail;
}

describe("daily helpers", () => {
  it("builds daily archive paths from ISO dates", () => {
    expect(dailyPathForDate("2026-04-27")).toBe("/daily/2026-04-27");
  });

  it("titles dailies using the rotation date", () => {
    expect(dailyTitle("2026-04-27")).toContain("2026");
    expect(dailyTitle("2026-04-27")).toContain("Daily Seed");
    // Includes weekday so the player can spot Mon vs Sun at a glance.
    expect(dailyTitle("2026-04-27")).toContain("Monday");
  });

  it("uses the pool name for the theme label", () => {
    expect(dailyTheme({ pool_name: "training_standard" } as RaceDetail)).toBe(
      "Training Standard",
    );
    expect(dailyTheme({ pool_name: null } as RaceDetail)).toBe("Unknown");
  });

  it("returns the matching participant for the current user", () => {
    const me = participant({
      id: "x",
      user: { ...baseParticipant.user, id: "me" },
    });
    const other = participant({
      id: "y",
      user: { ...baseParticipant.user, id: "other" },
    });
    expect(currentUserParticipant(detail([me, other]), "me")?.id).toBe("x");
    expect(currentUserParticipant(detail([me, other]), null)).toBeNull();
  });
});

function wsParticipant(overrides: Partial<WsParticipant>): WsParticipant {
  return {
    id: "p",
    twitch_username: "user",
    twitch_display_name: null,
    status: "registered",
    current_zone: null,
    current_layer: 0,
    igt_ms: 0,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...overrides,
  };
}

function dayCell(overrides: Partial<DailyWeekDay>): DailyWeekDay {
  return {
    weekday: 0,
    date: "2026-04-27",
    state: "today",
    pool_name: "standard",
    pool_display_name: "Standard",
    race_id: "race-1",
    started_at: "2026-04-27T08:00:00Z",
    ends_at: "2026-04-28T08:00:00Z",
    starters_count: 0,
    participants_count: 0,
    podium: [],
    my_result: null,
    ...overrides,
  };
}

function week(days: DailyWeekDay[]): DailyWeekResponse {
  return {
    week_start: "2026-04-27",
    today: "2026-04-27",
    days,
    has_earlier: false,
  };
}

describe("applyLiveDailyDayUpdate", () => {
  it("counts starters separately from participants on the matched day", () => {
    // The server distinguishes joined-but-never-started from actual starters
    // by igt_ms > 0; the live patch must replicate that split rather than
    // collapsing both into one count.
    const w = week([dayCell({ participants_count: 0, starters_count: 0 })]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [
        wsParticipant({ id: "a", igt_ms: 0, status: "registered" }),
        wsParticipant({ id: "b", igt_ms: 1000, status: "playing" }),
        wsParticipant({ id: "c", igt_ms: 5000, status: "finished" }),
      ],
      myParticipantId: null,
    });
    expect(result.days[0].participants_count).toBe(3);
    expect(result.days[0].starters_count).toBe(2);
  });

  it("derives placement among finishers ordered by IGT", () => {
    const w = week([dayCell({})]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [
        wsParticipant({ id: "a", status: "finished", igt_ms: 5000 }),
        wsParticipant({ id: "me", status: "finished", igt_ms: 3000 }),
        wsParticipant({ id: "c", status: "finished", igt_ms: 4000 }),
        wsParticipant({ id: "d", status: "playing", igt_ms: 2000 }),
      ],
      myParticipantId: "me",
    });
    expect(result.days[0].my_result).toEqual({
      status: "finished",
      placement: 1,
      total_starters: 4,
      igt_ms: 3000,
      death_count: 0,
    });
  });

  it("hides igt_ms while the viewer is still racing", () => {
    // Mirrors the server: my_result.igt_ms is null until status === finished.
    // A live `playing` igt_ms must not bleed into the cell, otherwise the
    // grid would render an in-progress timer in the finished-strip slot.
    const w = week([dayCell({})]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [
        wsParticipant({ id: "me", status: "playing", igt_ms: 12_345 }),
      ],
      myParticipantId: "me",
    });
    expect(result.days[0].my_result?.status).toBe("playing");
    expect(result.days[0].my_result?.igt_ms).toBeNull();
    expect(result.days[0].my_result?.placement).toBeNull();
  });

  it("returns null my_result when the viewer has no participant row", () => {
    const w = week([
      dayCell({
        my_result: {
          status: "finished",
          placement: 1,
          total_starters: 1,
          igt_ms: 1000,
          death_count: 0,
        },
      }),
    ]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [wsParticipant({ id: "someone-else" })],
      myParticipantId: "me",
    });
    expect(result.days[0].my_result).toBeNull();
  });

  it("leaves non-matching cells untouched", () => {
    const w = week([
      dayCell({ date: "2026-04-26", state: "past", participants_count: 9 }),
      dayCell({ date: "2026-04-27", state: "today", participants_count: 0 }),
    ]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [wsParticipant({ id: "a" })],
      myParticipantId: null,
    });
    expect(result.days[0]).toBe(w.days[0]);
    expect(result.days[1].participants_count).toBe(1);
  });

  it("returns the original week reference when the patch is a no-op", () => {
    // Identity short-circuit lets downstream $effect / memoization avoid
    // re-running on every WS frame that didn't actually change the cell.
    const w = week([
      dayCell({
        participants_count: 1,
        starters_count: 1,
        my_result: {
          status: "playing",
          placement: null,
          total_starters: 1,
          igt_ms: null,
          death_count: 0,
        },
      }),
    ]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-04-27",
      participants: [
        wsParticipant({ id: "me", status: "playing", igt_ms: 4000 }),
      ],
      myParticipantId: "me",
    });
    expect(result).toBe(w);
  });

  it("ignores future and missing-past cells", () => {
    // Those states have no race row, so participant counts are meaningless;
    // patching them would invent data the snapshot intentionally left empty.
    const future = dayCell({ date: "2026-05-01", state: "future" });
    const w = week([future]);
    const result = applyLiveDailyDayUpdate(w, {
      date: "2026-05-01",
      participants: [wsParticipant({ id: "a" })],
      myParticipantId: null,
    });
    expect(result).toBe(w);
  });
});
