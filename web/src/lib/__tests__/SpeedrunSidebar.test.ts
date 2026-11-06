import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import SpeedrunSidebar from "$lib/components/stats/speedrun/SpeedrunSidebar.svelte";
import type {
  Race,
  SpeedrunOverviewResponse,
  SpeedrunPracticedSeed,
} from "$lib/api";

vi.mock("$lib/stores/weaponsCatalogue.svelte", () => ({
  getWeaponName: vi.fn(),
}));

function overview(
  practiced_seeds: SpeedrunPracticedSeed[],
  practiced_seeds_days = 7,
): SpeedrunOverviewResponse {
  return {
    categories: [],
    runs: 0,
    players: 0,
    recent_runs: [],
    practiced_seeds,
    practiced_seeds_days,
  };
}

describe("SpeedrunSidebar practiced seeds", () => {
  it("lists each seed with its counts, singulars included, linking to its page", () => {
    render(SpeedrunSidebar, {
      overview: overview([
        {
          seed_number: "363096a4243f",
          category: "sprint",
          category_name: "Sprint",
          attempts: 3,
          players: 2,
        },
        {
          seed_number: "abcdef012345",
          category: "dl",
          category_name: "Standard",
          attempts: 1,
          players: 1,
        },
      ]),
      onpick: vi.fn(),
    });

    const first = screen.getByRole("link", { name: /363096 · Sprint/ });
    expect(first.getAttribute("href")).toBe("/speedrun/seed/363096a4243f");
    expect(first.textContent).toContain("3 attempts · 2 players");
    expect(screen.getByText("1 attempt · 1 player")).toBeTruthy();
  });

  it("labels the panel with the window the API reports", () => {
    const seed = {
      seed_number: "363096a4243f",
      category: "sprint",
      category_name: "Sprint",
      attempts: 1,
      players: 1,
    };
    const { unmount } = render(SpeedrunSidebar, {
      overview: overview([seed], 14),
      onpick: vi.fn(),
    });
    expect(screen.getByText("14 days")).toBeTruthy();
    unmount();

    render(SpeedrunSidebar, {
      overview: overview([seed], 1),
      onpick: vi.fn(),
    });
    expect(screen.getByText("1 day")).toBeTruthy();
  });

  it("hides the panel when no seed was practiced", () => {
    render(SpeedrunSidebar, { overview: overview([]), onpick: vi.fn() });

    expect(screen.queryByText(/Most practiced seeds/)).toBeNull();
  });
});

function race(id: string, overrides: Partial<Race> = {}): Race {
  return {
    id,
    name: id,
    organizer: {
      id: "u1",
      twitch_username: "org",
      twitch_display_name: "Org",
      twitch_avatar_url: null,
    },
    status: "setup",
    pool_name: "standard",
    is_public: true,
    open_registration: true,
    max_participants: null,
    created_at: "2026-11-01T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    seeds_released_at: null,
    late_join_window_minutes: null,
    race_duration_minutes: null,
    registration_closes_at: null,
    race_ends_at: null,
    igt_cutoff_ms: null,
    private_dag: false,
    deathless: false,
    custom_rules: null,
    daily_date: null,
    mode: "speedrun",
    participant_count: 0,
    participant_previews: [],
    casters: [],
    seed_total_layers: 10,
    my_participant_status: null,
    my_current_layer: null,
    my_igt_ms: null,
    my_death_count: null,
    can_join: false,
    my_role: null,
    event_id: null,
    event_slot: null,
    ...overrides,
  };
}

describe("SpeedrunSidebar races", () => {
  const inHours = (h: number) =>
    new Date(Date.now() + h * 3600_000).toISOString();

  function hrefsUnder(heading: string): string[] {
    const section = screen
      .getByRole("heading", { name: heading })
      .closest("section");
    if (!section) throw new Error(`no section for ${heading}`);
    return [...section.querySelectorAll("a")].map(
      (a) => a.getAttribute("href") ?? "",
    );
  }

  it("splits live and upcoming races, upcoming by start time, undated ones left out", () => {
    render(SpeedrunSidebar, {
      overview: overview([]),
      races: [
        race("later", { scheduled_at: inHours(3) }),
        race("live", { status: "running", started_at: inHours(-1) }),
        race("undated"),
        race("sooner", { scheduled_at: inHours(1), mode: "set_seed" }),
      ],
      onpick: vi.fn(),
    });

    expect(hrefsUnder("Live races")).toEqual(["/race/live"]);
    expect(hrefsUnder("Upcoming races")).toEqual([
      "/race/sooner",
      "/race/later",
    ]);
    expect(document.querySelector('a[href="/race/undated"]')).toBeNull();
  });

  it("shows no race group while nothing is live or scheduled", () => {
    render(SpeedrunSidebar, {
      overview: overview([]),
      races: [race("undated")],
      onpick: vi.fn(),
    });

    expect(screen.queryByRole("heading", { name: "Live races" })).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Upcoming races" }),
    ).toBeNull();
  });
});
