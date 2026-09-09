import { describe, expect, it } from "vitest";
import {
  blockOrder,
  formatEventDate,
  formatEventDay,
  liveStage,
  ordinal,
  racesSectionTitle,
  shouldPoll,
  timeRemaining,
} from "$lib/events";
import type { EventDetail, EventPhase, Race } from "$lib/api";

const phases: EventPhase[] = [
  "upcoming",
  "qualifier",
  "cut",
  "playoffs",
  "finished",
];

describe("blockOrder", () => {
  it("renders the rules exactly once per phase (standalone, or inside the bracket block)", () => {
    for (const phase of phases) {
      const blocks = blockOrder(phase);
      expect(
        blocks.includes("rules") !== blocks.includes("bracket_ladder"),
        phase,
      ).toBe(true);
      expect(new Set(blocks).size, phase).toBe(blocks.length);
    }
  });

  it("shows the seeds only while they can be played", () => {
    expect(blockOrder("upcoming")).toContain("seeds");
    expect(blockOrder("qualifier")).toContain("seeds");
    expect(blockOrder("cut")).not.toContain("seeds");
    expect(blockOrder("playoffs")).not.toContain("seeds");
  });

  it("leads the playoffs with the live block and hides the bracket before them", () => {
    expect(blockOrder("playoffs")[0]).toBe("live");
    expect(blockOrder("playoffs")).toContain("bracket_ladder");
    expect(blockOrder("qualifier")).not.toContain("bracket_ladder");
    expect(blockOrder("finished")).toContain("bracket_ladder");
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

describe("racesSectionTitle", () => {
  const fmt = (iso: string) => `D(${iso})`;
  it("names the live stage while a race runs", () => {
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
    expect(racesSectionTitle(detail, fmt)).toBe("Live now · Semi B");
  });

  it("points at the next stage otherwise", () => {
    const detail = detailWith({
      next_stage: {
        key: "semi_a",
        label: "Semi A",
        date: "2026-10-04T19:00:00Z",
      },
    });
    expect(racesSectionTitle(detail, fmt)).toBe(
      "Up next · Semi A · D(2026-10-04T19:00:00Z)",
    );
  });

  it("falls back to a plain title after the last stage", () => {
    expect(racesSectionTitle(detailWith({}), fmt)).toBe("Races");
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

describe("shouldPoll and ordinal", () => {
  it("polls only while a stage race is live", () => {
    expect(shouldPoll(detailWith({ live_race: { id: "x" } as Race }))).toBe(
      true,
    );
    expect(shouldPoll(detailWith({}))).toBe(false);
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
