import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchSpeedrunSeed: vi.fn(),
    protectSeed: vi.fn(),
    unprotectSeed: vi.fn(),
    excludeSeedFromSetSeed: vi.fn(),
    restoreSeedToSetSeed: vi.fn(),
  };
});

import SeedPage from "../../routes/speedrun/seed/[seed]/+page.svelte";
import Leaderboard from "$lib/components/Leaderboard.svelte";
import SeedAdminControls from "$lib/components/stats/speedrun/SeedAdminControls.svelte";
import SeedReplayCard from "$lib/components/stats/speedrun/SeedReplayCard.svelte";
import SeedStatusChip from "$lib/components/stats/speedrun/SeedStatusChip.svelte";
import {
  excludeSeedFromSetSeed,
  fetchSpeedrunSeed,
  protectSeed,
  restoreSeedToSetSeed,
  unprotectSeed,
  type SpeedrunSeed,
  type SpeedrunSeedRun,
  type SpeedrunSeedViewer,
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
          not_replayable_reason: "Files purged.",
          kept_reasons: ["Protected by 2 players"],
        }),
      },
    });

    expect(screen.getByText("Not replayable")).toBeTruthy();
    expect(screen.getByRole("tooltip").textContent?.trim()).toBe(
      "Files purged.",
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

  it("tells a viewer without a finished run why they cannot protect it", () => {
    render(SeedReplayCard, {
      props: { seed: seed({ viewer: viewer({ can_protect: false }) }) },
    });

    expect(
      screen.getByText(
        "Only players who finished a run on this seed can protect it.",
      ),
    ).toBeTruthy();
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

  it("offers no protection where it keeps nothing, but still an unprotect", () => {
    const purged = {
      replayable: false,
      not_replayable_code: "purged" as const,
      not_replayable_reason: "Files purged.",
      protectable: false,
    };
    const first = render(SeedReplayCard, {
      props: { seed: seed({ ...purged, viewer: viewer() }) },
    });

    expect(
      screen.getByText("Protection only keeps the files of a replayable seed."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Protect" })).toBeNull();
    first.unmount();

    render(SeedReplayCard, {
      props: {
        seed: seed({
          ...purged,
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

  it("gives the reason when the seed cannot be replayed", () => {
    render(SeedReplayCard, {
      props: {
        seed: seed({
          replayable: false,
          not_replayable_code: "old_game_version",
          not_replayable_reason: "Built for an older game version.",
        }),
      },
    });

    expect(screen.getByText("Built for an older game version.")).toBeTruthy();
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
          not_replayable_reason: "Excluded from Set Seed: Broken",
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
