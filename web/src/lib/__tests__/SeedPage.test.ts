import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchSpeedrunSeed: vi.fn(),
    protectSeed: vi.fn(),
    unprotectSeed: vi.fn(),
    excludeSeedFromSetSeed: vi.fn(),
    restoreSeedToSetSeed: vi.fn(),
    startSpeedrunSolo: vi.fn(),
  };
});

import SeedPage from "../../routes/speedrun/seed/[seed]/+page.svelte";
import Leaderboard from "$lib/components/Leaderboard.svelte";
import SeedAdminControls from "$lib/components/stats/speedrun/SeedAdminControls.svelte";
import SeedReplayCard from "$lib/components/stats/speedrun/SeedReplayCard.svelte";
import SeedStatusChip from "$lib/components/stats/speedrun/SeedStatusChip.svelte";
import { goto } from "$app/navigation";
import { auth } from "$lib/stores/auth.svelte";
import {
  excludeSeedFromSetSeed,
  fetchSpeedrunSeed,
  protectSeed,
  restoreSeedToSetSeed,
  startSpeedrunSolo,
  unprotectSeed,
  type AuthUser,
  type SpeedrunSeed,
  type SpeedrunSeedRun,
  type SpeedrunSeedViewer,
  type TrainingSessionDetail,
} from "$lib/api";

const SEED = "363096a4243f";

const GRAPH = {
  total_layers: 2,
  nodes: {
    start: { type: "start", display_name: "Chapel of Anticipation", layer: 0 },
    boss: { type: "final_boss", display_name: "Starscourge Radahn", layer: 1 },
  },
  edges: [{ from: "start", to: "boss" }],
};

function seedRun(
  runId: string,
  username: string,
  igt: number,
  blind: boolean,
): SpeedrunSeedRun {
  return {
    run_id: runId,
    user: {
      id: `u-${username}`,
      twitch_username: username,
      twitch_display_name: null,
      twitch_avatar_url: null,
    },
    rank: null,
    ranked: true,
    igt_ms: igt,
    finished_at: "2026-10-20T12:00:00Z",
    race_id: blind ? "r1" : null,
    race_name: blind ? "Race one" : null,
    session_id: blind ? null : runId,
    blind,
    daily_date: null,
    seed_number: SEED,
    deaths: 0,
    weapon: null,
    replayable: true,
    run_type: blind ? "race" : "solo",
    zone_history: [
      { node_id: "start", igt_ms: 0 },
      { node_id: "boss", igt_ms: igt },
    ],
  };
}

function viewer(over: Partial<SpeedrunSeedViewer> = {}): SpeedrunSeedViewer {
  return {
    can_protect: true,
    protected: false,
    protected_seeds: ["aaaaaa111111"],
    protection_limit: 3,
    ...over,
  };
}

function seed(over: Partial<SpeedrunSeed> = {}): SpeedrunSeed {
  return {
    seed_number: SEED,
    category: "standard",
    category_name: "Standard",
    pool_config: null,
    total_layers: 2,
    origin: {
      race_id: "r1",
      race_name: "Race one",
      daily_date: null,
      played_at: "2026-09-23T12:00:00Z",
    },
    public: true,
    replayable: true,
    not_replayable_code: null,
    not_replayable_reason: null,
    protectable: true,
    kept_reasons: [],
    protected_by: 0,
    excluded_reason: null,
    viewer: null,
    graph_json: GRAPH,
    runs: [
      seedRun("p-1", "alice", 1_500_000, true),
      seedRun("p-2", "bob", 1_600_000, true),
      seedRun("s-1", "alice", 1_700_000, false),
    ],
    stats: {
      best_igt_ms: 1_500_000,
      median_igt_ms: 1_600_000,
      runs: 3,
      players: 2,
    },
    ...over,
  };
}

function renderPage(data: SpeedrunSeed, run: string | null = null) {
  return render(SeedPage, { props: { data: { seed: data, run } } as never });
}

function selectedNames(container: HTMLElement): string[] {
  return [...container.querySelectorAll("li.participant.selected")].map(
    (li) => li.querySelector(".name-link")?.textContent?.trim() ?? "",
  );
}

beforeEach(() => {
  vi.mocked(fetchSpeedrunSeed).mockReset();
  vi.mocked(protectSeed).mockReset();
  vi.mocked(unprotectSeed).mockReset();
  vi.mocked(excludeSeedFromSetSeed).mockReset();
  vi.mocked(restoreSeedToSetSeed).mockReset();
});

describe("seed page: the run it was opened on", () => {
  it("ticks the ?run= run and only it", () => {
    const { container } = renderPage(seed(), "p-2");

    expect(container.querySelectorAll("li.participant")).toHaveLength(3);
    expect(selectedNames(container)).toEqual(["bob"]);
  });

  it("ticks nothing for a run that is not listed, nor without ?run=", () => {
    const unknown = renderPage(seed(), "elsewhere");
    expect(selectedNames(unknown.container)).toEqual([]);
    unknown.unmount();

    const none = renderPage(seed());
    expect(selectedNames(none.container)).toEqual([]);
  });
});

describe("seed page: the ticked run's own page", () => {
  function runLink(container: HTMLElement): HTMLAnchorElement | null {
    return container.querySelector(".ticked-run a:not(.user-link)");
  }

  it("links a ticked race run to its race", () => {
    const { container } = renderPage(seed(), "p-2");

    const line = container.querySelector(".ticked-run");
    expect(line?.textContent?.replace(/\s+/g, " ").trim()).toBe(
      "bob played it in Race one",
    );
    expect(runLink(container)?.getAttribute("href")).toBe("/race/r1");
  });

  it("links a ticked solo run to its session and a Daily Seed run to its day", () => {
    const solo = renderPage(seed(), "s-1");
    expect(solo.container.querySelector(".ticked-run")?.textContent).toContain(
      "played it solo",
    );
    expect(runLink(solo.container)?.getAttribute("href")).toBe("/training/s-1");
    solo.unmount();

    const daily = {
      ...seedRun("d-1", "dave", 1_400_000, true),
      run_type: "daily" as const,
      daily_date: "2026-10-01",
    };
    const day = renderPage(seed({ runs: [daily] }), "d-1");
    expect(day.container.querySelector(".ticked-run")?.textContent).toContain(
      "played it in the Daily Seed of Oct 1, 2026",
    );
    expect(runLink(day.container)?.getAttribute("href")).toBe(
      "/daily/2026-10-01",
    );
  });

  it("shows no line unless exactly one run is ticked", async () => {
    const none = renderPage(seed());
    expect(none.container.querySelector(".ticked-run")).toBeNull();
    none.unmount();

    const { container } = renderPage(seed(), "p-2");
    const alice = [...container.querySelectorAll("li.participant")][0];
    await fireEvent.click(alice, { ctrlKey: true });
    expect(selectedNames(container)).toHaveLength(2);
    expect(container.querySelector(".ticked-run")).toBeNull();
  });
});

describe("seed page: the run list's places", () => {
  it("shows the server's ranks: shared on a tie, none on a slower run", () => {
    const { container } = renderPage(
      seed({
        runs: [
          { ...seedRun("p-1", "alice", 1_500_000, true), rank: 1 },
          { ...seedRun("p-2", "bob", 1_600_000, true), rank: 2 },
          { ...seedRun("s-1", "carol", 1_600_000, false), rank: 2 },
          { ...seedRun("s-2", "alice", 1_700_000, false), rank: null },
        ],
      }),
    );

    const rows = [...container.querySelectorAll("li.participant")];
    expect(rows.map((r) => r.querySelector(".rank")?.textContent)).toEqual([
      "1.",
      "2.",
      "2.",
      "",
    ]);
    expect(rows.map((r) => r.classList.contains("obsolete"))).toEqual([
      false,
      false,
      false,
      true,
    ]);
  });
});

describe("seed page: unranked runs", () => {
  it("chips an unranked run and gives it no place, beside ranked places", () => {
    const { container } = renderPage(
      seed({
        runs: [
          { ...seedRun("p-0", "dave", 1_400_000, true), ranked: false },
          { ...seedRun("p-1", "alice", 1_500_000, true), rank: 1 },
          { ...seedRun("s-1", "carol", 1_600_000, false), rank: 2 },
        ],
      }),
    );

    const rows = [...container.querySelectorAll("li.participant")];
    expect(rows.map((r) => r.querySelector(".rank")?.textContent)).toEqual([
      "",
      "1.",
      "2.",
    ]);
    expect(rows.map((r) => r.querySelector(".run-chip")?.textContent)).toEqual([
      "Unranked",
      "Blind",
      "Replay",
    ]);
  });

  it("dims a slower ranked run but not an unranked one", () => {
    const { container } = renderPage(
      seed({
        runs: [
          { ...seedRun("p-0", "dave", 1_400_000, true), ranked: false },
          { ...seedRun("p-1", "alice", 1_500_000, true), rank: 1 },
          { ...seedRun("s-2", "alice", 1_700_000, false), rank: null },
        ],
      }),
    );

    const rows = [...container.querySelectorAll("li.participant")];
    expect(rows.map((r) => r.classList.contains("obsolete"))).toEqual([
      false,
      false,
      true,
    ]);
  });
});

describe("seed page: where the seed was first played", () => {
  it("names and links its first race", () => {
    const { container } = renderPage(seed());

    const origin = container.querySelector(".origin");
    expect(origin?.textContent?.replace(/\s+/g, " ").trim()).toBe(
      "Standard · first played in Race one on Sep 23, 2026",
    );
    expect(origin?.querySelector("a")?.getAttribute("href")).toBe("/race/r1");
  });

  it("says solo when no blind race was run on it", () => {
    const { container } = renderPage(
      seed({
        origin: {
          race_id: null,
          race_name: null,
          daily_date: null,
          played_at: "2026-09-23T12:00:00Z",
        },
      }),
    );

    const origin = container.querySelector(".origin");
    expect(origin?.textContent?.replace(/\s+/g, " ").trim()).toBe(
      "Standard · first played solo on Sep 23, 2026",
    );
    expect(origin?.querySelector("a")).toBeNull();
  });
});

describe("seed page while a blind run is in progress", () => {
  it("shows no list and no map, only the waiting line", () => {
    const { container } = renderPage(
      seed({
        public: false,
        replayable: false,
        not_replayable_code: "in_progress",
        not_replayable_reason: "A blind run on this seed is still in progress.",
        graph_json: null,
        runs: [],
        stats: { best_igt_ms: null, median_igt_ms: null, runs: 0, players: 0 },
      }),
    );

    expect(screen.queryByText("Runs on this seed")).toBeNull();
    expect(container.querySelector("li.participant")).toBeNull();
    expect(container.querySelector("svg.zoomable-svg")).toBeNull();
    expect(
      screen.getByText(
        "This seed's map opens once every blind run on it is over.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Not replayable")).toBeTruthy();
  });
});

describe("seed page: protecting the seed", () => {
  it("reloads the seed so the chip's kept reasons follow", async () => {
    vi.mocked(protectSeed).mockResolvedValue(
      viewer({ protected: true, protected_seeds: ["aaaaaa111111", SEED] }),
    );
    vi.mocked(fetchSpeedrunSeed).mockResolvedValue(
      seed({
        viewer: viewer({
          protected: true,
          protected_seeds: ["aaaaaa111111", SEED],
        }),
        kept_reasons: ["Protected by 1 player"],
        protected_by: 1,
      }),
    );
    renderPage(seed({ viewer: viewer() }));

    await fireEvent.click(screen.getByRole("button", { name: "Protect" }));

    await waitFor(() => expect(fetchSpeedrunSeed).toHaveBeenCalledWith(SEED));
    await waitFor(() =>
      expect(screen.getByRole("tooltip").textContent).toContain(
        "Protected by 1 player",
      ),
    );
  });
});

describe("SeedStatusChip", () => {
  it("explains why a seed cannot be replayed", () => {
    render(SeedStatusChip, {
      props: {
        seed: seed({
          replayable: false,
          not_replayable_code: "purged",
          not_replayable_reason: "Its files were deleted.",
          kept_reasons: ["Protected by 2 players"],
        }),
      },
    });

    expect(screen.getByText("Not replayable")).toBeTruthy();
    expect(screen.getByRole("tooltip").textContent?.trim()).toBe(
      "Its files were deleted.",
    );
  });

  it("lists what keeps a replayable seed's files", () => {
    render(SeedStatusChip, {
      props: {
        seed: seed({
          kept_reasons: ["Top 10 seed of Standard", "Protected by 2 players"],
        }),
      },
    });

    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("Files kept");
    expect(tip.textContent).toContain(
      "Top 10 seed of Standard · Protected by 2 players",
    );
  });

  it("warns that nothing keeps the files yet", () => {
    render(SeedStatusChip, { props: { seed: seed({ kept_reasons: [] }) } });

    const tip = screen.getByRole("tooltip");
    expect(tip.textContent?.trim()).toBe(
      "Files may be purged. Protect this seed to keep them.",
    );
    expect(tip.textContent).not.toContain("Files kept");
  });

  it("dismisses the open tooltip with Escape by blurring the chip", async () => {
    render(SeedStatusChip, { props: { seed: seed() } });

    const chip = screen
      .getByText("Replayable")
      .closest<HTMLElement>("[tabindex]")!;
    chip.focus();
    expect(document.activeElement).toBe(chip);

    await fireEvent.keyDown(chip, { key: "Escape" });

    expect(document.activeElement).not.toBe(chip);
  });

  it("describes a keyboard-reachable chip", () => {
    render(SeedStatusChip, { props: { seed: seed() } });

    const trigger = screen.getByText("Replayable").closest("[tabindex]");
    expect(trigger?.getAttribute("tabindex")).toBe("0");
    expect(trigger?.getAttribute("aria-describedby")).toBe(
      screen.getByRole("tooltip").id,
    );
  });
});

describe("SeedReplayCard", () => {
  it("protects the seed and updates the quota line", async () => {
    vi.mocked(protectSeed).mockResolvedValue(
      viewer({ protected: true, protected_seeds: ["aaaaaa111111", SEED] }),
    );
    const onprotect = vi.fn();
    render(SeedReplayCard, {
      props: { seed: seed({ viewer: viewer() }), onprotect },
    });
    expect(screen.getByText(/You protect 1 of your 3 seeds\./)).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Protect" }));

    expect(protectSeed).toHaveBeenCalledWith(SEED);
    await screen.findByText(/You protect 2 of your 3 seeds\./);
    expect(screen.getByRole("button", { name: "Unprotect" })).toBeTruthy();
    expect(onprotect).toHaveBeenCalled();
  });

  it("unprotects a seed the viewer protects", async () => {
    vi.mocked(unprotectSeed).mockResolvedValue(
      viewer({ protected: false, protected_seeds: [] }),
    );
    render(SeedReplayCard, {
      props: {
        seed: seed({
          viewer: viewer({
            protected: true,
            protected_seeds: [SEED],
          }),
        }),
      },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Unprotect" }));

    expect(unprotectSeed).toHaveBeenCalledWith(SEED);
    await screen.findByText(/You protect 0 of your 3 seeds\./);
  });

  it("leaves the protect row out for a viewer without a finished run", () => {
    render(SeedReplayCard, {
      props: { seed: seed({ viewer: viewer({ can_protect: false }) }) },
    });

    expect(screen.queryByText("Protect this seed")).toBeNull();
    expect(screen.queryByRole("button", { name: "Protect" })).toBeNull();
  });

  it("disables Protect at the limit and links the protected seeds", () => {
    const mine = ["aaaaaa111111", "bbbbbb222222", "cccccc333333"];
    render(SeedReplayCard, {
      props: { seed: seed({ viewer: viewer({ protected_seeds: mine }) }) },
    });

    const button = screen.getByRole("button", {
      name: "Protect",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(
      mine.map((n) =>
        screen.getByRole("link", { name: n }).getAttribute("href"),
      ),
    ).toEqual(mine.map((n) => `/speedrun/seed/${n}`));
  });

  it("shows only the reason on a seed that cannot be replayed, but still an unprotect", () => {
    const excluded = {
      replayable: false,
      not_replayable_code: "excluded" as const,
      not_replayable_reason:
        "An admin excluded this seed from Set Seed: Softlock",
      protectable: true,
    };
    const first = render(SeedReplayCard, {
      props: { seed: seed({ ...excluded, viewer: viewer() }) },
    });

    expect(
      screen.getByText("An admin excluded this seed from Set Seed: Softlock"),
    ).toBeTruthy();
    expect(screen.queryByText(/as many times as you like/)).toBeNull();
    expect(screen.queryByText("Glitchless")).toBeNull();
    expect(screen.queryByText("Protect this seed")).toBeNull();
    expect(screen.queryByRole("button", { name: "Protect" })).toBeNull();
    first.unmount();

    // A player who protected it before keeps a way to free the slot.
    render(SeedReplayCard, {
      props: {
        seed: seed({
          replayable: false,
          not_replayable_code: "purged",
          not_replayable_reason: "Its files were deleted.",
          protectable: false,
          viewer: viewer({ protected: true, protected_seeds: [SEED] }),
        }),
      },
    });
    expect(screen.getByRole("button", { name: "Unprotect" })).toBeTruthy();
  });

  it("hides the protect row from a logged-out viewer", () => {
    render(SeedReplayCard, { props: { seed: seed({ viewer: null }) } });

    expect(screen.queryByText("Protect this seed")).toBeNull();
    expect(screen.queryByRole("button", { name: "Protect" })).toBeNull();
  });
});

describe("SeedReplayCard: starting a run", () => {
  function loggedIn(role: string): AuthUser {
    return {
      id: "u1",
      twitch_username: "runner",
      twitch_display_name: null,
      twitch_avatar_url: null,
      role,
      locale: null,
      overlay_settings: null,
      feedback_prompted_at: null,
      race_count: 0,
      daily_count: 0,
      training_count: 0,
    };
  }

  beforeEach(() => {
    vi.mocked(goto).mockReset();
    vi.mocked(startSpeedrunSolo).mockReset();
  });

  afterEach(() => {
    auth.user = null;
  });

  it("Play solo starts a Set Seed run on this seed and opens it", async () => {
    auth.user = loggedIn("user");
    vi.mocked(startSpeedrunSolo).mockResolvedValue({
      id: "s1",
    } as TrainingSessionDetail);
    render(SeedReplayCard, { props: { seed: seed() } });

    await fireEvent.click(screen.getByRole("button", { name: "Play solo" }));

    expect(startSpeedrunSolo).toHaveBeenCalledWith({ seed: SEED });
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/training/s1"));
  });

  it("shows why the run could not start", async () => {
    auth.user = loggedIn("user");
    vi.mocked(startSpeedrunSolo).mockRejectedValue(
      new Error("You already have an active solo session"),
    );
    render(SeedReplayCard, { props: { seed: seed() } });

    await fireEvent.click(screen.getByRole("button", { name: "Play solo" }));

    await screen.findByText("You already have an active solo session");
    expect(goto).not.toHaveBeenCalled();
  });

  it("offers Create race to organizers and admins only", async () => {
    auth.user = loggedIn("user");
    const first = render(SeedReplayCard, { props: { seed: seed() } });
    expect(screen.queryByRole("link", { name: "Create race" })).toBeNull();
    first.unmount();

    auth.user = loggedIn("organizer");
    render(SeedReplayCard, { props: { seed: seed() } });

    expect(
      screen.getByRole("link", { name: "Create race" }).getAttribute("href"),
    ).toBe(`/race/new?seed=${SEED}`);
  });

  it("puts the reason in place of the buttons when the seed cannot be replayed", () => {
    auth.user = loggedIn("organizer");
    render(SeedReplayCard, {
      props: {
        seed: seed({
          replayable: false,
          not_replayable_code: "purged",
          not_replayable_reason: "Its files were deleted.",
        }),
      },
    });

    expect(screen.getByText("Its files were deleted.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Play solo" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Create race" })).toBeNull();
  });

  it("asks a logged-out viewer to log in", () => {
    render(SeedReplayCard, { props: { seed: seed() } });

    expect(
      screen.getByRole("link", { name: "Login with Twitch" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Play solo" })).toBeNull();
  });
});

describe("Leaderboard run kinds", () => {
  function participant(id: string, username: string) {
    return {
      id,
      twitch_username: username,
      twitch_display_name: null,
      status: "finished",
      current_zone: null,
      current_layer: 0,
      igt_ms: 1_500_000,
      death_count: 0,
      color_index: 0,
      mod_connected: false,
      zone_history: null,
    };
  }

  it("marks each run Blind or Replay", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [participant("a", "alice"), participant("b", "bob")],
        mode: "finished",
        runKinds: { a: "blind", b: "replay" },
      },
    });

    const rows = [...container.querySelectorAll("li.participant")];
    expect(rows.map((r) => r.querySelector(".run-chip")?.textContent)).toEqual([
      "Blind",
      "Replay",
    ]);
  });

  it("shows no chip without run kinds", () => {
    const { container } = render(Leaderboard, {
      props: { participants: [participant("a", "alice")], mode: "finished" },
    });

    expect(container.querySelector(".run-chip")).toBeNull();
  });

  it("numbers rows by position without ranks, as on race pages", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [participant("a", "alice"), participant("b", "bob")],
        mode: "finished",
      },
    });

    const rows = [...container.querySelectorAll("li.participant")];
    expect(rows.map((r) => r.querySelector(".rank")?.textContent)).toEqual([
      "1.",
      "2.",
    ]);
    expect(container.querySelector(".obsolete")).toBeNull();
  });
});

describe("SeedAdminControls", () => {
  it("excludes the seed with the typed reason, then reloads", async () => {
    vi.mocked(excludeSeedFromSetSeed).mockResolvedValue();
    const onchange = vi.fn();
    render(SeedAdminControls, { props: { seed: seed(), onchange } });
    const exclude = screen.getByRole("button", {
      name: "Exclude from Set Seed",
    }) as HTMLButtonElement;
    expect(exclude.disabled).toBe(true);

    await fireEvent.input(screen.getByLabelText("Exclusion reason"), {
      target: { value: "  Shortcut freezes the board  " },
    });
    await fireEvent.click(exclude);

    expect(excludeSeedFromSetSeed).toHaveBeenCalledWith(
      SEED,
      "Shortcut freezes the board",
    );
    await waitFor(() => expect(onchange).toHaveBeenCalled());
  });

  it("restores an excluded seed, then reloads", async () => {
    vi.mocked(restoreSeedToSetSeed).mockResolvedValue();
    const onchange = vi.fn();
    render(SeedAdminControls, {
      props: {
        seed: seed({
          replayable: false,
          not_replayable_code: "excluded",
          not_replayable_reason:
            "An admin excluded this seed from Set Seed: Broken",
          excluded_reason: "Broken",
        }),
        onchange,
      },
    });
    expect(screen.getByText("Excluded from Set Seed: Broken")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    expect(restoreSeedToSetSeed).toHaveBeenCalledWith(SEED);
    await waitFor(() => expect(onchange).toHaveBeenCalled());
  });
});
