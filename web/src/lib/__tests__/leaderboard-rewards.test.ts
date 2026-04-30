import { describe, expect, it, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import Leaderboard from "$lib/components/Leaderboard.svelte";
import { rewards } from "$lib/stores/rewards.svelte";

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
        background_css: null,
        sort_order: 0,
      },
      {
        id: "elo_crown",
        name: "ELO Crown",
        color: null,
        gradient: ["#FFFFFF", "#FFD700"],
        background_css:
          "linear-gradient(90deg, rgba(255,255,255,0.1), rgba(255,215,0,0.06))",
        sort_order: 10,
      },
    ],
  };
};

const makeParticipant = (overrides: Record<string, unknown> = {}) => ({
  id: "p1",
  twitch_username: "alice",
  twitch_display_name: "Alice",
  status: "ready",
  current_zone: null,
  current_layer: 0,
  current_layer_tier: null,
  igt_ms: 0,
  death_count: 0,
  color_index: 0,
  mod_connected: false,
  zone_history: null,
  gap_ms: null,
  layer_entry_igt: null,
  is_live: false,
  stream_url: null,
  equipped_badge_id: null,
  equipped_name_template_id: null,
  ...overrides,
});

describe("Leaderboard rewards integration", () => {
  beforeEach(() => {
    rewards.catalog = null;
  });

  it("applies template background to a participant with elo_crown equipped", () => {
    seedCatalog();
    const { container } = render(Leaderboard, {
      props: {
        participants: [
          makeParticipant({ equipped_name_template_id: "elo_crown" }),
        ],
        mode: "running",
      },
    });
    const li = container.querySelector("li.participant");
    expect(li?.getAttribute("style") ?? "").toContain("linear-gradient");
  });

  it("does not apply template background to a default participant", () => {
    seedCatalog();
    const { container } = render(Leaderboard, {
      props: {
        participants: [makeParticipant({ equipped_name_template_id: null })],
        mode: "running",
      },
    });
    const li = container.querySelector("li.participant");
    const style = li?.getAttribute("style") ?? "";
    // The existing border-left is present, but no template linear-gradient.
    expect(style).not.toContain("linear-gradient");
  });

  it("applies gradient name style to a participant with elo_crown equipped", () => {
    seedCatalog();
    const { container } = render(Leaderboard, {
      props: {
        participants: [
          makeParticipant({ equipped_name_template_id: "elo_crown" }),
        ],
        mode: "running",
      },
    });
    const link = container.querySelector("a.name-link");
    expect(link?.getAttribute("style") ?? "").toContain("linear-gradient");
  });

  it("shows a badge icon when equipped_badge_id is set", () => {
    seedCatalog();
    const { container } = render(Leaderboard, {
      props: {
        participants: [makeParticipant({ equipped_badge_id: "early_adopter" })],
        mode: "running",
      },
    });
    const img = container.querySelector("img.participant-badge");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toContain("early_adopter.svg");
  });

  it("does not show a badge icon when no badge is equipped", () => {
    seedCatalog();
    const { container } = render(Leaderboard, {
      props: {
        participants: [makeParticipant({ equipped_badge_id: null })],
        mode: "running",
      },
    });
    const img = container.querySelector("img.participant-badge");
    expect(img).toBeNull();
  });
});
