import { describe, expect, it } from "vitest";
import {
  currentUserParticipant,
  dailyPathForDate,
  dailyTheme,
  dailyTitle,
  dailyUserStatus,
  fastestFinishedIgt,
} from "$lib/daily";
import type { Participant, ParticipantPreview, RaceDetail } from "$lib/api";

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

function preview(
  status: ParticipantPreview["status"],
  igt_ms: number | null,
): ParticipantPreview {
  return {
    id: "p",
    twitch_username: "p",
    twitch_display_name: null,
    twitch_avatar_url: null,
    placement: null,
    status,
    igt_ms,
  };
}

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
  it("ignores non-finished previews when picking the fastest IGT", () => {
    expect(
      fastestFinishedIgt([
        preview("registered", 1_000),
        preview("finished", 2_520_000),
        preview("finished", 2_400_000),
      ]),
    ).toBe(2_400_000);
  });

  it("returns null when no preview is finished", () => {
    expect(fastestFinishedIgt([preview("playing", 600_000)])).toBeNull();
  });

  it("builds daily archive paths from ISO dates", () => {
    expect(dailyPathForDate("2026-04-27")).toBe("/daily/2026-04-27");
  });

  it("titles dailies using the rotation date", () => {
    expect(dailyTitle("2026-04-27")).toContain("2026");
    expect(dailyTitle("2026-04-27")).toContain("Daily Seed");
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

  it("describes the status of the current user", () => {
    const me = participant({
      id: "x",
      user: { ...baseParticipant.user, id: "me" },
      status: "finished",
      igt_ms: 600_000,
    });
    expect(dailyUserStatus(detail([me]), "me")).toContain("Finished");
    expect(dailyUserStatus(detail([me]), "stranger")).toBe("Not played yet");
  });
});
