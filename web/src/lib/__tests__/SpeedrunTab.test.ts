import { describe, expect, it, vi, beforeEach } from "vitest";
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
  };
});

import SpeedrunTab from "$lib/components/stats/speedrun/SpeedrunTab.svelte";
import { fetchSpeedrunBoard, fetchSpeedrunOverview } from "$lib/api";

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
    } as never);
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      runs: [],
      history: [],
      record_seed: null,
    });
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
});
