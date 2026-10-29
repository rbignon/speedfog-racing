import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import SpeedrunSidebar from "$lib/components/stats/speedrun/SpeedrunSidebar.svelte";
import type { SpeedrunOverviewResponse, SpeedrunPracticedSeed } from "$lib/api";

vi.mock("$lib/stores/weaponsCatalogue.svelte", () => ({
  getWeaponName: vi.fn(),
}));

function overview(
  practiced_seeds: SpeedrunPracticedSeed[],
): SpeedrunOverviewResponse {
  return {
    categories: [],
    runs: 0,
    players: 0,
    recent_runs: [],
    practiced_seeds,
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

  it("hides the panel when no seed was practiced", () => {
    render(SpeedrunSidebar, { overview: overview([]), onpick: vi.fn() });

    expect(screen.queryByText(/Most practiced seeds/)).toBeNull();
  });
});
