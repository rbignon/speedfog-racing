import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import SpeedrunBoard from "$lib/components/stats/speedrun/SpeedrunBoard.svelte";
import { fetchSpeedrunBoard, type SpeedrunCategory } from "$lib/api";
import { RUN_TYPES, type SpeedrunParams } from "$lib/speedrun";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, fetchSpeedrunBoard: vi.fn() };
});

function category(
  pool: string,
  subcategories: SpeedrunCategory["subcategories"],
): SpeedrunCategory {
  return {
    pool,
    name: pool,
    retired: false,
    subcategories,
    description: null,
    estimated_duration: null,
    rules: null,
  };
}

const PARAMS: SpeedrunParams = {
  pool: "dl",
  sub: "any",
  types: [...RUN_TYPES],
  obsolete: false,
  view: "board",
};

describe("SpeedrunBoard subcategories", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({ runs: [], history: [] });
  });

  it("labels a deathless-only pool's board Deathless and fetches it", async () => {
    render(SpeedrunBoard, {
      categories: [category("dl", ["deathless"])],
      params: PARAMS,
      onchange: () => {},
    });

    const deathless = screen.getByRole("button", { name: "Deathless" });
    expect(deathless.classList.contains("on")).toBe(true);
    expect(screen.queryByRole("button", { name: "Any%" })).toBeNull();
    await waitFor(() =>
      expect(fetchSpeedrunBoard).toHaveBeenCalledWith(
        "dl",
        expect.objectContaining({ deathless: true }),
      ),
    );
  });

  it("hides the row for a pool without deathless runs", () => {
    render(SpeedrunBoard, {
      categories: [category("any", ["any"])],
      params: { ...PARAMS, pool: "any" },
      onchange: () => {},
    });

    expect(screen.queryByText(/Subcategories/)).toBeNull();
  });
});
