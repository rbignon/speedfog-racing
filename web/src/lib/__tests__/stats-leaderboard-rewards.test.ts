import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/svelte";
import LeaderboardTab from "$lib/components/stats/LeaderboardTab.svelte";
import { rewards } from "$lib/stores/rewards.svelte";

vi.mock("$lib/api", async () => {
  return {
    fetchLeaderboard: vi.fn(),
  };
});

import { fetchLeaderboard } from "$lib/api";

const seedCatalog = () => {
  rewards.catalog = {
    badges: [
      {
        id: "early_adopter",
        name: "Early Adopter",
        icon_filename: "early_adopter.svg",
        lifecycle: "permanent",
        sort_order: 10,
      },
    ],
    name_templates: [
      {
        id: "default",
        name: "Default",
        color: "#FFFFFF",
        gradient: null,
        name_css: null,
        background_css: null,
        sort_order: 0,
      },
      {
        id: "elo_crown",
        name: "ELO Crown",
        color: null,
        gradient: ["#FFE9A8", "#C8A44E"],
        name_css: "font-family: Georgia, serif; font-style: italic;",
        background_css:
          "radial-gradient(ellipse 60% 100% at 25% 50%, rgba(200,164,78,0.18), transparent 70%)",
        sort_order: 10,
      },
    ],
    phantom_skins: [],
  };
};

const stubResponse = (overrides: Record<string, unknown> = {}) => ({
  players: [
    {
      twitch_username: "alice",
      twitch_display_name: "Alice",
      twitch_avatar_url: null,
      elo_rating: 1700,
      elo_races: 5,
      trend_delta: 0,
      avg_opponent_elo: null,
      equipped_badge_id: null,
      equipped_name_template_id: null,
      ...overrides,
    },
  ],
  community: {
    total_races: 0,
    active_players: 0,
    ranked_players: 1,
    total_deaths: 0,
    hours_raced: 0,
  },
});

describe("/stats LeaderboardTab rewards integration", () => {
  beforeEach(() => {
    rewards.catalog = null;
    vi.mocked(fetchLeaderboard).mockReset();
  });

  it("applies template background to the row when set", async () => {
    seedCatalog();
    vi.mocked(fetchLeaderboard).mockResolvedValue(
      stubResponse({ equipped_name_template_id: "elo_crown" }),
    );
    const { container } = render(LeaderboardTab);
    await waitFor(() => {
      expect(container.querySelector("tbody tr")).not.toBeNull();
    });
    const row = container.querySelector("tbody tr");
    expect(row?.getAttribute("style") ?? "").toContain("radial-gradient");
  });

  it("applies gradient name style when a template is equipped", async () => {
    seedCatalog();
    vi.mocked(fetchLeaderboard).mockResolvedValue(
      stubResponse({ equipped_name_template_id: "elo_crown" }),
    );
    const { container } = render(LeaderboardTab);
    await waitFor(() => {
      expect(container.querySelector("a.player-name")).not.toBeNull();
    });
    const link = container.querySelector("a.player-name");
    expect(link?.getAttribute("style") ?? "").toContain("linear-gradient");
  });

  it("renders a badge icon when equipped", async () => {
    seedCatalog();
    vi.mocked(fetchLeaderboard).mockResolvedValue(
      stubResponse({ equipped_badge_id: "early_adopter" }),
    );
    const { container } = render(LeaderboardTab);
    await waitFor(() => {
      expect(container.querySelector("img.player-badge")).not.toBeNull();
    });
    const img = container.querySelector("img.player-badge");
    expect(img?.getAttribute("src")).toContain("early_adopter.svg");
  });

  it("does not render a badge or background when nothing is equipped", async () => {
    seedCatalog();
    vi.mocked(fetchLeaderboard).mockResolvedValue(stubResponse());
    const { container } = render(LeaderboardTab);
    await waitFor(() => {
      expect(container.querySelector("tbody tr")).not.toBeNull();
    });
    expect(container.querySelector("img.player-badge")).toBeNull();
    const row = container.querySelector("tbody tr");
    expect(row?.getAttribute("style") ?? "").not.toContain("linear-gradient");
  });
});
