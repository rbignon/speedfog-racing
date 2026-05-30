import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import WeekLeaderboard from "$lib/components/WeekLeaderboard.svelte";
import type { WeeklyLeaderboardResponse } from "$lib/api";

function fakeResponse(
  over: Partial<WeeklyLeaderboardResponse> = {},
): WeeklyLeaderboardResponse {
  return {
    week_starting: "2026-05-25",
    week_ending: "2026-05-31",
    dailies_total: 5,
    entries: [
      {
        rank: 1,
        user: {
          id: "u-1",
          twitch_username: "alice",
          twitch_display_name: "Alice",
          twitch_avatar_url: null,
          equipped_badge_id: null,
          equipped_name_template_id: null,
          equipped_phantom_skin_id: null,
        },
        total_points: 237,
        dailies_played: 5,
        total_deaths: 12,
        weapon_combos: [],
      },
    ],
    ...over,
  };
}

describe("WeekLeaderboard", () => {
  it("renders an entry with name + total points + X/Y dailies + deaths", () => {
    const { getByText } = render(WeekLeaderboard, { data: fakeResponse() });
    expect(getByText(/Alice/)).toBeTruthy();
    expect(getByText(/237\s*pts/)).toBeTruthy();
    expect(getByText(/5\s*\/\s*5/)).toBeTruthy();
    expect(getByText(/12/)).toBeTruthy();
  });

  it("renders the 'updates as dailies close' empty state when dailies_total is 0", () => {
    const { getByText } = render(WeekLeaderboard, {
      data: fakeResponse({ entries: [], dailies_total: 0 }),
    });
    expect(
      getByText(/Weekly leaderboard updates as dailies close/),
    ).toBeTruthy();
  });

  it("renders 'no qualified runs' for a past week with empty entries", () => {
    const { getByText } = render(WeekLeaderboard, {
      data: fakeResponse({ entries: [], dailies_total: 7 }),
    });
    expect(getByText(/No qualified runs that week/)).toBeTruthy();
  });

  it("highlights the viewer's own row", () => {
    const data = fakeResponse({
      entries: [
        {
          rank: 1,
          user: {
            id: "u-me",
            twitch_username: "me",
            twitch_display_name: "Me",
            twitch_avatar_url: null,
            equipped_badge_id: null,
            equipped_name_template_id: null,
            equipped_phantom_skin_id: null,
          },
          total_points: 50,
          dailies_played: 1,
          total_deaths: 0,
          weapon_combos: [],
        },
      ],
    });
    const { container } = render(WeekLeaderboard, {
      data,
      currentUserId: "u-me",
    });
    expect(container.querySelector(".row.me")).not.toBeNull();
  });
});
