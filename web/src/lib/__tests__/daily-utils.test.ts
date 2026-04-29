import { describe, expect, it } from "vitest";
import {
  currentUserParticipant,
  dailyCloseLabel,
  dailyPathForDate,
  dailyTheme,
  dailyTitle,
  dailyUserResultPreview,
  dailyUserStatus,
  dailyWinner,
  fastestFinishedIgt,
} from "$lib/daily";
import type {
  Participant,
  ParticipantPreview,
  Race,
  RaceDetail,
} from "$lib/api";

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

  it("describes the status of the current user from my_* fields", () => {
    expect(
      dailyUserStatus({
        my_role: "participating",
        my_participant_status: "finished",
        my_igt_ms: 600_000,
      }),
    ).toContain("Finished");
    expect(
      dailyUserStatus({
        my_role: "participating",
        my_participant_status: "playing",
        my_igt_ms: null,
      }),
    ).toBe("Playing");
    expect(
      dailyUserStatus({
        my_role: null,
        my_participant_status: null,
        my_igt_ms: null,
      }),
    ).toBe("Not played yet");
    expect(
      dailyUserStatus({
        my_role: "participating",
        my_participant_status: "registered",
        my_igt_ms: null,
      }),
    ).toBe("Not started");
  });

  it("picks the placement-1 finished preview as the winner", () => {
    const winner: ParticipantPreview = {
      id: "w",
      twitch_username: "winner",
      twitch_display_name: "Winner",
      twitch_avatar_url: null,
      placement: 1,
      status: "finished",
      igt_ms: 1_200_000,
    };
    const second: ParticipantPreview = {
      ...winner,
      id: "s",
      placement: 2,
      twitch_username: "s",
    };
    const race = { participant_previews: [second, winner] } as Pick<
      Race,
      "participant_previews"
    >;
    expect(dailyWinner(race)?.id).toBe("w");
  });

  it("returns null when no preview is finished", () => {
    const race = {
      participant_previews: [
        {
          id: "p",
          twitch_username: "p",
          twitch_display_name: null,
          twitch_avatar_url: null,
          placement: null,
          status: "playing",
          igt_ms: null,
        } as ParticipantPreview,
      ],
    };
    expect(dailyWinner(race)).toBeNull();
  });

  it("formats the user's recent result with placement when finished", () => {
    const me: ParticipantPreview = {
      id: "me",
      twitch_username: "me",
      twitch_display_name: "Me",
      twitch_avatar_url: null,
      placement: 3,
      status: "finished",
      igt_ms: 1_500_000,
    };
    expect(dailyUserResultPreview({ participant_previews: [me] }, "me")).toBe(
      "25:00 (#3)",
    );
  });

  it("returns null when the user is not in the preview window", () => {
    expect(
      dailyUserResultPreview({ participant_previews: [] }, "me"),
    ).toBeNull();
    expect(
      dailyUserResultPreview({ participant_previews: [] }, null),
    ).toBeNull();
  });

  it("formats the close label as hours and minutes", () => {
    const now = new Date("2026-04-27T08:00:00Z").getTime();
    const ends = "2026-04-27T13:30:00Z";
    expect(dailyCloseLabel(ends, now)).toBe("Closes in 5h 30m");
  });

  it("clamps the close label at 0h 0m past the deadline", () => {
    const now = new Date("2026-04-28T00:00:00Z").getTime();
    const ends = "2026-04-27T08:00:00Z";
    expect(dailyCloseLabel(ends, now)).toBe("Closes in 0h 0m");
  });

  it("returns null when no race_ends_at is set", () => {
    expect(dailyCloseLabel(null, Date.now())).toBeNull();
  });
});
