import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { flushSync } from "svelte";

import { pageState } from "./pageState.svelte";

vi.mock("$app/state", async () => {
  const { pageState } = await import("./pageState.svelte");
  return { page: pageState };
});
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/stores/weaponsCatalogue.svelte", () => ({
  loadCatalogue: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchSpeedrunOverview: vi.fn(),
    fetchSpeedrunBoard: vi.fn(),
    fetchRaces: vi.fn(),
  };
});

import SpeedrunTab from "$lib/components/stats/speedrun/SpeedrunTab.svelte";
import {
  fetchRaces,
  fetchSpeedrunBoard,
  fetchSpeedrunOverview,
} from "$lib/api";

const cat = (pool: string) => ({
  pool,
  name: pool,
  retired: false,
  description: null,
  estimated_duration: null,
  rules: null,
  released_at: null,
});

describe("SpeedrunTab URL sync", () => {
  beforeEach(() => {
    pageState.url = new URL("http://localhost/speedrun?pool=sprint&sub=random");
    vi.mocked(fetchSpeedrunOverview).mockResolvedValue({
      categories: [cat("sprint"), cat("dl")],
      runs: 0,
      players: 0,
      recent_runs: [],
      practiced_seeds: [],
      practiced_seeds_days: 7,
    } as never);
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      runs: [],
      history: [],
      record_seed: null,
    });
    vi.mocked(fetchRaces).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("follows a navigation that changes the URL under the mounted tab", async () => {
    render(SpeedrunTab);
    const random = await screen.findByRole("button", { name: "Random Seed" });
    expect(random.classList).toContain("on");

    pageState.url = new URL("http://localhost/speedrun");
    flushSync();

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Set Seed" }).classList,
      ).toContain("on"),
    );
  });

  it("hands the fetched races to the side column", async () => {
    vi.mocked(fetchRaces).mockResolvedValue([
      {
        id: "r1",
        name: "Grind",
        status: "running",
        mode: "speedrun",
        pool_name: "sprint",
        started_at: new Date().toISOString(),
        organizer: { id: "u1", twitch_username: "org" },
        participant_count: 0,
        participant_previews: [],
        casters: [],
      } as never,
    ]);
    render(SpeedrunTab);

    const heading = await screen.findByRole("heading", { name: "Live races" });
    expect(
      heading.closest("section")?.querySelector('a[href="/race/r1"]'),
    ).not.toBeNull();
  });

  it("keeps the board when the race list fails to load", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(fetchRaces).mockRejectedValue(new Error("down"));
    render(SpeedrunTab);

    expect(
      await screen.findByRole("button", { name: "Random Seed" }),
    ).toBeTruthy();
    expect(screen.queryByText("down")).toBeNull();
  });
});
