import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/svelte";
import SpeedrunBoard from "$lib/components/stats/speedrun/SpeedrunBoard.svelte";
import {
  fetchSpeedrunBoard,
  type AuthUser,
  type SpeedrunBoardResponse,
  type SpeedrunCategory,
  type SpeedrunRun,
} from "$lib/api";
import { goto } from "$app/navigation";
import { RUN_TYPES, type SpeedrunParams } from "$lib/speedrun";
import { auth } from "$lib/stores/auth.svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchSpeedrunBoard: vi.fn(),
    fetchFreshSpeedrunSeeds: vi.fn(async () => ({ fresh: true })),
    // The window's Seed ID check: left pending, the tests here never read it.
    fetchSpeedrunSeedSummary: vi.fn(() => new Promise(() => {})),
    fetchSpeedrunSoloQuota: vi.fn(async () => null),
  };
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
    run_id: "p1",
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
    replayable: true,
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

  it("closes Filters when Tools opens, and Tools on Escape", async () => {
    mount();

    await fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByLabelText("Solo runs")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: /Tools/ }));
    expect(screen.queryByLabelText("Solo runs")).toBeNull();
    expect(
      screen.getByRole("button", { name: /LiveSplit splits/ }),
    ).toBeTruthy();

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("button", { name: /LiveSplit splits/ }),
    ).toBeNull();
  });

  it("keeps the streamer tools in the Tools menu, which closes on a pick", async () => {
    mount();

    expect(screen.queryByRole("button", { name: /OBS overlay/ })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: /Tools/ }));
    expect(
      screen.getByRole("button", { name: /LiveSplit splits/ }),
    ).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: /OBS overlay/ }));

    expect(screen.getByRole("heading", { name: "OBS Overlay" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /LiveSplit splits/ }),
    ).toBeNull();
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

  it("marks the seeds that can no longer be replayed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [
        { ...run(true), seed_number: "dead00000001", replayable: false },
        {
          ...run(false),
          run_id: "p2",
          race_id: "r2",
          seed_number: "abcdef000001",
        },
      ],
      record_seed: { seed_number: "dead00000001", runs: 1, replayable: false },
    });
    mount();

    const gone = await screen.findByRole("link", { name: "dead00" });
    const kept = screen.getByRole("link", { name: "abcdef" });
    expect(gone.getAttribute("title")).toBe("No longer replayable");
    expect(kept.getAttribute("title")).toBeNull();
    const band = screen.getByTestId("wr-seed");
    expect(
      within(band)
        .getByRole("link", { name: "dead00000001" })
        .getAttribute("title"),
    ).toBe("No longer replayable");
  });

  it("shows the WR seed band from record_seed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 14, replayable: true },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    expect(band.textContent).toContain("WR seed");
    expect(band.textContent).toContain("363096a4243f");
    expect(band.textContent).toContain("21m 43s");
    expect(band.textContent).toContain("Runner");
    expect(band.textContent).toContain("Blind");
    expect(band.textContent).toContain("14 runs");
    expect(band.querySelector("a")?.getAttribute("href")).toBe(
      "/speedrun/seed/363096a4243f?run=p1",
    );
  });

  it("words a single run on the record seed in the singular", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(false)],
      record_seed: { seed_number: "363096a4243f", runs: 1, replayable: true },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    expect(band.textContent).toContain("1 run");
    expect(band.textContent).not.toContain("1 runs");
    expect(band.textContent).toContain("Replay");
  });

  it("links a solo WR seed to its seed page too", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [
        {
          ...run(true),
          run_id: "s1",
          race_id: null,
          race_name: null,
          session_id: "s1",
        },
      ],
      record_seed: { seed_number: "363096a4243f", runs: 1, replayable: true },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    const seed = band.querySelector(".seed");
    expect(seed?.textContent).toBe("363096a4243f");
    expect(seed?.getAttribute("href")).toBe(
      "/speedrun/seed/363096a4243f?run=s1",
    );
  });

  it("has no WR seed band without a record seed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue(EMPTY);
    mount();

    await screen.findByText("No runs match these filters.");
    expect(screen.queryByTestId("wr-seed")).toBeNull();
  });
});

describe("SpeedrunBoard links to seed pages", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
    vi.mocked(goto).mockReset();
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 3, replayable: true },
    });
  });

  it("links the table's seed cell to the run's seed page", async () => {
    mount();

    const row = (await screen.findByText("363096")).closest("tr")!;
    expect(row.querySelector("a.seed")?.getAttribute("href")).toBe(
      "/speedrun/seed/363096a4243f?run=p1",
    );
  });

  it("navigates to the seed page on a row click, but not on a link", async () => {
    mount();

    const row = (await screen.findByText("363096")).closest("tr")!;
    await fireEvent.click(row.querySelector("td.rank")!);
    expect(goto).toHaveBeenCalledWith("/speedrun/seed/363096a4243f?run=p1");

    vi.mocked(goto).mockClear();
    const player = row.querySelector(".player a");
    expect(player).toBeTruthy();
    await fireEvent.click(player!);
    expect(goto).not.toHaveBeenCalled();
  });

  it("does not navigate on a modified click or after a text selection", async () => {
    mount();

    const row = (await screen.findByText("363096")).closest("tr")!;
    const rank = row.querySelector("td.rank")!;
    for (const modifier of ["ctrlKey", "metaKey", "shiftKey"]) {
      await fireEvent.click(rank, { [modifier]: true });
    }
    expect(goto).not.toHaveBeenCalled();

    // Selecting the row's text ends with a click on it.
    const range = document.createRange();
    range.selectNodeContents(row);
    window.getSelection()!.addRange(range);
    await fireEvent.click(rank);
    window.getSelection()!.removeAllRanges();
    expect(goto).not.toHaveBeenCalled();

    await fireEvent.click(rank);
    expect(goto).toHaveBeenCalledTimes(1);
  });
});

describe("SpeedrunBoard Start a run window", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
    auth.user = {
      id: "u1",
      twitch_username: "runner",
      twitch_display_name: "Runner",
      twitch_avatar_url: null,
      role: "user",
      locale: null,
      overlay_settings: null,
      feedback_prompted_at: null,
      race_count: 0,
      daily_count: 0,
      training_count: 0,
    } satisfies AuthUser;
  });

  afterEach(() => {
    auth.user = null;
  });

  async function setSeedWindow(replayable: boolean) {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 1, replayable },
    });
    mount({ ...PARAMS, sub: "random" });
    await screen.findByTestId("wr-seed");
    await fireEvent.click(screen.getByRole("button", { name: /Start a run/ }));
    const modal = screen
      .getByRole("heading", { name: "Start a run" })
      .closest(".modal") as HTMLElement;
    await fireEvent.click(
      within(modal).getByRole("button", { name: "Set Seed" }),
    );
    return modal;
  }

  it("offers the record seed when it can be replayed", async () => {
    const modal = await setSeedWindow(true);

    expect(within(modal).getByRole("button", { name: "WR" })).toBeTruthy();
  });

  it("offers no WR button when the record seed cannot be replayed", async () => {
    const modal = await setSeedWindow(false);

    expect(within(modal).queryByRole("button", { name: "WR" })).toBeNull();
  });

  it("opens on Set Seed with the record seed typed in from Play seed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 1, replayable: true },
    });
    mount({ ...PARAMS, sub: "random" });

    const band = await screen.findByTestId("wr-seed");
    await fireEvent.click(
      within(band).getByRole("button", { name: "Play seed" }),
    );

    const modal = screen
      .getByRole("heading", { name: "Start a run" })
      .closest(".modal") as HTMLElement;
    expect(
      within(modal)
        .getByRole("button", { name: "Set Seed" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      (within(modal).getByLabelText("Seed ID") as HTMLInputElement).value,
    ).toBe("363096a4243f");
  });

  it("offers no Play seed when the record seed cannot be replayed", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 1, replayable: false },
    });
    mount();

    const band = await screen.findByTestId("wr-seed");
    expect(
      within(band).queryByRole("button", { name: "Play seed" }),
    ).toBeNull();
  });
});

describe("SpeedrunBoard record history", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
  });

  it("links each record's time to the run's own page", async () => {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValue({
      ...EMPTY,
      runs: [run(true)],
      history: [
        { ...run(true), run_id: "d1", daily_date: "2026-10-01" },
        {
          ...run(true),
          run_id: "s1",
          race_id: null,
          race_name: null,
          session_id: "s1",
          igt_ms: 1_200_000,
        },
      ],
    });
    const { container } = mount({ ...PARAMS, view: "history-list" });

    await waitFor(() =>
      expect(container.querySelectorAll("a.time")).toHaveLength(2),
    );
    expect(
      [...container.querySelectorAll("a.time")].map((a) =>
        a.getAttribute("href"),
      ),
    ).toEqual(["/daily/2026-10-01", "/training/s1"]);
  });
});

describe("SpeedrunBoard WR seed band while another board loads", () => {
  beforeEach(() => {
    vi.mocked(fetchSpeedrunBoard).mockReset();
  });

  async function switchPool(next: Promise<SpeedrunBoardResponse>) {
    vi.mocked(fetchSpeedrunBoard).mockResolvedValueOnce({
      ...EMPTY,
      runs: [run(true)],
      record_seed: { seed_number: "363096a4243f", runs: 3, replayable: true },
    });
    const view = mount();
    await screen.findByTestId("wr-seed");
    vi.mocked(fetchSpeedrunBoard).mockReturnValueOnce(next);
    await view.rerender({ params: { ...PARAMS, pool: "dl" } });
    return view;
  }

  it("hides the previous board's record while the next one loads, keeping its place", async () => {
    await switchPool(new Promise(() => {}));

    await waitFor(() => expect(fetchSpeedrunBoard).toHaveBeenCalledTimes(2));
    const band = screen.getByTestId("wr-seed");
    expect(band.classList).toContain("pending");
    expect(band.getAttribute("aria-hidden")).toBe("true");
    expect(band.hasAttribute("inert")).toBe(true);
  });

  it("hides it beside a load error", async () => {
    await switchPool(Promise.reject(new Error("Boom")));

    await screen.findByText("Boom");
    expect(screen.queryByTestId("wr-seed")).toBeNull();
  });
});
