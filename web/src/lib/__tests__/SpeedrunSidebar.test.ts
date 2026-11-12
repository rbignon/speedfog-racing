import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { goto } from "$app/navigation";
import SpeedrunSidebar from "$lib/components/stats/speedrun/SpeedrunSidebar.svelte";
import type {
  Race,
  SpeedrunOverviewResponse,
  SpeedrunPracticedSeed,
  SpeedrunRecentRun,
} from "$lib/api";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

vi.mock("$lib/stores/weaponsCatalogue.svelte", () => ({
  getWeaponName: vi.fn(),
}));

function overview(
  practiced_seeds: SpeedrunPracticedSeed[],
  practiced_seeds_days = 7,
  recent_runs: SpeedrunRecentRun[] = [],
): SpeedrunOverviewResponse {
  return {
    categories: [],
    runs: 0,
    players: 0,
    recent_runs,
    practiced_seeds,
    practiced_seeds_days,
  };
}

const RECENT: SpeedrunRecentRun = {
  run_id: "s1",
  user: {
    id: "u1",
    twitch_username: "runner",
    twitch_display_name: "Runner",
    twitch_avatar_url: null,
  },
  rank: 4,
  igt_ms: 1_303_998,
  finished_at: "2026-11-10T12:00:00Z",
  race_id: null,
  race_name: null,
  session_id: "s1",
  daily_date: null,
  seed_number: "363096a4243f",
  blind: false,
  deaths: 0,
  weapon: null,
  replayable: true,
  pool: "sprint",
  category: "Sprint",
  deathless: false,
};

describe("SpeedrunSidebar recent PBs", () => {
  beforeEach(() => {
    vi.mocked(goto).mockReset();
  });

  const RUN_HREF = "/speedrun/seed/363096a4243f?run=s1";

  it("links every part of a PB to its run, the player's around the name, the category alone in the tab order", () => {
    render(SpeedrunSidebar, { overview: overview([], 7, [RECENT]) });

    const category = screen.getByRole("link", {
      name: "Sprint: run by Runner",
    });
    const row = category.closest<HTMLElement>(".recent")!;
    // The parts still read out their data.
    for (const name of ["4th", /^21\s*m\s*43\s*s$/]) {
      expect(within(row).getByRole("link", { name }).getAttribute("href")).toBe(
        RUN_HREF,
      );
    }
    // The player's part links it around the name.
    for (const part of [
      ".details",
      ".place",
      ".sr-player",
      ".sr-time",
      ".ago",
    ]) {
      const el = row.querySelector(part)!;
      expect(
        el.closest(`a[href="${RUN_HREF}"]`) ??
          el.querySelector(`a[href="${RUN_HREF}"]`),
      ).toBeTruthy();
    }
    const tabbable = [...row.querySelectorAll("a")].filter(
      (a) => a.getAttribute("tabindex") !== "-1",
    );
    expect(tabbable.map((a) => a.getAttribute("href"))).toEqual([
      RUN_HREF,
      "/user/runner",
    ]);
  });

  it("opens the run on a plain click between the links, not on the player's name, a modified click or a text selection", async () => {
    render(SpeedrunSidebar, { overview: overview([], 7, [RECENT]) });

    const row = screen
      .getByRole("link", { name: /^Sprint/ })
      .closest(".recent")!;
    const gap = row.querySelector(".line")!;
    for (const modifier of ["ctrlKey", "metaKey", "shiftKey"]) {
      await fireEvent.click(gap, { [modifier]: true });
    }
    await fireEvent.click(screen.getByRole("link", { name: "Runner" }));

    // Selecting the row's text ends with a click on it.
    const range = document.createRange();
    range.selectNodeContents(row);
    window.getSelection()!.addRange(range);
    await fireEvent.click(gap);
    window.getSelection()!.removeAllRanges();
    expect(goto).not.toHaveBeenCalled();

    await fireEvent.click(gap);
    expect(goto).toHaveBeenCalledWith(RUN_HREF);
  });
});

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
    });

    const first = screen.getByRole("link", { name: /363096 \(Sprint\)/ });
    expect(first.getAttribute("href")).toBe("/speedrun/seed/363096a4243f");
    expect(first.textContent).toContain("3 attempts, 2 players");
    expect(screen.getByText("1 attempt, 1 player")).toBeTruthy();
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
    });
    expect(screen.getByText("14 days")).toBeTruthy();
    unmount();

    render(SpeedrunSidebar, {
      overview: overview([seed], 1),
    });
    expect(screen.getByText("1 day")).toBeTruthy();
  });

  it("hides the panel when no seed was practiced", () => {
    render(SpeedrunSidebar, { overview: overview([]) });

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
    race_items: false,
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
    });

    expect(screen.queryByRole("heading", { name: "Live races" })).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Upcoming races" }),
    ).toBeNull();
  });
});
