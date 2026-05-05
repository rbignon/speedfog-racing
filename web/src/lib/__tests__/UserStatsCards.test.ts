import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import UserStatsCards from "$lib/components/UserStatsCards.svelte";
import type { UserProfile } from "$lib/api";

function profileWith(
  overrides: Partial<UserProfile["stats"]> = {},
): UserProfile {
  return {
    id: "u",
    twitch_username: "u",
    twitch_display_name: "U",
    twitch_avatar_url: null,
    role: "user",
    created_at: "2026-01-01T00:00:00Z",
    stats: {
      race_count: 120,
      daily_count: 1,
      training_count: 64,
      organized_count: 55,
      casted_count: 0,
      weekly: {
        races: [1, 2, 3, 4, 5],
        daily: [0, 0, 0, 0, 1],
        solo: [3, 2, 1, 0, 5],
        organized: [0, 1, 0, 1, 0],
        weeks_count: 5,
        capped: false,
      },
      ...overrides,
    },
  };
}

describe("UserStatsCards", () => {
  it("renders the four lifetime values", () => {
    render(UserStatsCards, { profile: profileWith() });
    expect(screen.queryByText("120")).not.toBeNull();
    expect(screen.queryByText("64")).not.toBeNull();
    expect(screen.queryByText("55")).not.toBeNull();
  });

  it("shows the Never-X empty placeholder when a category is 0", () => {
    const profile = profileWith({
      organized_count: 0,
      weekly: {
        races: [1],
        daily: [0],
        solo: [0],
        organized: [0],
        weeks_count: 1,
        capped: false,
      },
    });
    render(UserStatsCards, { profile });
    expect(screen.queryByText("Never organized")).not.toBeNull();
  });

  it("renders the four category labels", () => {
    render(UserStatsCards, { profile: profileWith() });
    for (const label of ["Races", "Daily", "Solo", "Organized"]) {
      expect(screen.queryByText(label)).not.toBeNull();
    }
  });
});
