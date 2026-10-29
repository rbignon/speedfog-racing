import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import SpeedrunBoard from "$lib/components/stats/speedrun/SpeedrunBoard.svelte";
import {
  fetchSpeedrunBoard,
  type SpeedrunBoardResponse,
  type SpeedrunCategory,
  type SpeedrunRun,
} from "$lib/api";
import { RUN_TYPES, type SpeedrunParams } from "$lib/speedrun";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, fetchSpeedrunBoard: vi.fn() };
});

function category(pool: string): SpeedrunCategory {
  return {
    pool,
    name: pool,
    retired: false,
    description: null,
    estimated_duration: null,
    rules: null,
    released_at: null,
  };
}

function run(blind: boolean): SpeedrunRun {
  return {
    user: {
      id: "u1",
      twitch_username: "runner",
      twitch_display_name: "Runner",
      twitch_avatar_url: null,
    },
    rank: 1,
    igt_ms: 1_303_998,
    finished_at: "2026-10-20T12:00:00Z",
    race_id: "r1",
    race_name: "Race one",
    session_id: null,
    daily_date: null,
    seed_number: "363096a4243f",
    blind,
    deaths: 0,
    weapon: null,
  };
}

const PARAMS: SpeedrunParams = {
  pool: "sprint",
  sub: "set",
  deathless: false,
  types: [...RUN_TYPES],
  obsolete: false,
  view: "board",
};

const EMPTY: SpeedrunBoardResponse = {
  runs: [],
  history: [],
  record_seed: null,
};

function mount(params: SpeedrunParams = PARAMS, onchange = () => {}) {
  return render(SpeedrunBoard, {
    categories: [category("sprint"), category("dl")],
    params,
    onchange,
  });
}

describe("SpeedrunBoard subcategories", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue(EMPTY);
  });

  it("offers Set Seed and Random Seed and fetches Set Seed by default", async () => {
    mount();

    expect(
      screen.getByRole("button", { name: "Set Seed" }).classList,
    ).toContain("on");
    expect(screen.getByRole("button", { name: "Random Seed" })).toBeTruthy();
    expect(screen.getByText("sprint - Subcategories")).toBeTruthy();
    await waitFor(() =>
      expect(fetchSpeedrunBoard).toHaveBeenCalledWith(
        "sprint",
        expect.objectContaining({ sub: "set", deathless: false }),
      ),
    );
  });

  it("asks the parent for the Random Seed board when selected", async () => {
    const onchange = vi.fn();
    mount(PARAMS, onchange);

    await fireEvent.click(screen.getByRole("button", { name: "Random Seed" }));

    expect(onchange).toHaveBeenCalledWith(
      expect.objectContaining({ sub: "random" }),
    );
  });

  it("fetches the Random Seed board with the deathless filter", async () => {
    mount({ ...PARAMS, sub: "random", deathless: true });

    await waitFor(() =>
      expect(fetchSpeedrunBoard).toHaveBeenCalledWith(
        "sprint",
        expect.objectContaining({ sub: "random", deathless: true }),
      ),
    );
  });

  it("lists Solo runs and Deathless only in the Filters popover", async () => {
    mount();

    await fireEvent.click(screen.getByRole("button", { name: /Filters/ }));

    expect(screen.getByLabelText("Solo runs")).toBeTruthy();
    expect(screen.getByLabelText("Deathless only")).toBeTruthy();
  });
});

describe("SpeedrunBoard Set Seed columns and WR seed", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
  });

  it("shows the Run column with Blind and Replay chips on Set Seed only", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [
        run(true),
        { ...run(false), user: { ...run(false).user, id: "u2" } },
      ],
    });
    const { unmount } = mount();

    await screen.findByRole("columnheader", { name: "Run" });
    expect(screen.getAllByText("Blind").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Replay").length).toBeGreaterThan(0);
    unmount();

    mount({ ...PARAMS, sub: "random" });
    await waitFor(() => expect(fetchSpeedrunBoard).toHaveBeenCalledTimes(2));
    await screen.findByRole("columnheader", { name: "Time" });
    expect(screen.queryByRole("columnheader", { name: "Run" })).toBeNull();
  });

  it("shows the WR seed band from record_seed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 14 },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    expect(band.textContent).toContain("WR seed");
    expect(band.textContent).toContain("363096a4243f");
    expect(band.textContent).toContain("21m 43s");
    expect(band.textContent).toContain("Runner");
    expect(band.textContent).toContain("Blind");
    expect(band.textContent).toContain("14 runs");
    expect(band.querySelector("a")?.getAttribute("href")).toBe("/race/r1");
  });

  it("words a single run on the record seed in the singular", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(false)],
      record_seed: { seed_number: "363096a4243f", runs: 1 },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    expect(band.textContent).toContain("1 run");
    expect(band.textContent).not.toContain("1 runs");
    expect(band.textContent).toContain("Replay");
  });

  it("has no WR seed band without a record seed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue(EMPTY);
    mount();

    await screen.findByText("No runs match these filters.");
    expect(screen.queryByTestId("wr-seed")).toBeNull();
  });
});
