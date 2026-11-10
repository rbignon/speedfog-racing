import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor, within } from "@testing-library/svelte";

vi.mock("$app/state", () => ({
  page: {
    params: { id: "s1" },
    url: new URL("http://localhost/training/s1"),
  },
}));
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchTrainingSession: vi.fn(),
    fetchTrainingSessions: vi.fn(),
    fetchTrainingGhosts: vi.fn(),
    fetchSessionPlace: vi.fn(),
    resetTrainingSession: vi.fn(),
  };
});

import TrainingPage from "../../routes/training/[id]/+page.svelte";
import {
  fetchSessionPlace,
  fetchTrainingGhosts,
  fetchTrainingSession,
  fetchTrainingSessions,
  resetTrainingSession,
  type AuthUser,
  type TrainingSessionDetail,
} from "$lib/api";
import { auth } from "$lib/stores/auth.svelte";
import { trainingStore } from "$lib/stores/training.svelte";
import type { WsRaceInfo } from "$lib/websocket";

function session(status: TrainingSessionDetail["status"]) {
  return {
    id: "s1",
    user: {
      id: "u1",
      twitch_username: "runner",
      twitch_display_name: "Runner",
      twitch_avatar_url: null,
    },
    status,
    mode: "speedrun",
    pool_name: "standard",
    pool_display_name: null,
    igt_ms: 0,
    death_count: 0,
    created_at: "2026-10-30T10:00:00Z",
    finished_at: null,
    seed_total_layers: 10,
    seed_total_nodes: null,
    current_layer: 0,
    seed_number: null,
    seed_total_paths: null,
    zone_history: null,
    graph_json: null,
    pool_config: null,
  } as TrainingSessionDetail;
}

function liveStatus(status: string) {
  trainingStore.race = {
    id: "s1",
    name: "Standard",
    status,
    started_at: null,
    seeds_released_at: null,
  } as WsRaceInfo;
}

beforeEach(() => {
  auth.initialized = true;
  // The page connects to the live session: the test plays the server.
  vi.spyOn(trainingStore, "connect").mockImplementation(() => {});
  vi.spyOn(trainingStore, "disconnect").mockImplementation(() => {});
  vi.mocked(fetchTrainingSessions).mockResolvedValue([]);
  vi.mocked(fetchTrainingGhosts).mockReset();
  vi.mocked(fetchTrainingGhosts).mockResolvedValue([]);
  vi.mocked(fetchSessionPlace).mockReset();
  vi.mocked(fetchSessionPlace).mockResolvedValue(null);
});

afterEach(() => {
  auth.initialized = false;
  trainingStore.race = null;
  vi.restoreAllMocks();
});

describe("training session page: ghosts", () => {
  it("loads them once when the run finishes on the open page", async () => {
    vi.mocked(fetchTrainingSession).mockResolvedValue(session("active"));
    render(TrainingPage);
    await waitFor(() => expect(fetchTrainingSession).toHaveBeenCalled());
    liveStatus("running");
    await Promise.resolve();
    expect(fetchTrainingGhosts).not.toHaveBeenCalled();

    liveStatus("finished");
    await waitFor(() => expect(fetchTrainingGhosts).toHaveBeenCalledWith("s1"));
    liveStatus("finished");
    await Promise.resolve();
    expect(fetchTrainingGhosts).toHaveBeenCalledTimes(1);
  });

  it("loads them once for a session that loads finished", async () => {
    vi.mocked(fetchTrainingSession).mockResolvedValue(session("finished"));
    render(TrainingPage);

    await waitFor(() => expect(fetchTrainingGhosts).toHaveBeenCalledWith("s1"));
    liveStatus("finished");
    await Promise.resolve();
    expect(fetchTrainingGhosts).toHaveBeenCalledTimes(1);
  });
});

describe("training session page: board place", () => {
  it("shows where a finished ranked run places, linked to its board", async () => {
    vi.mocked(fetchTrainingSession).mockResolvedValue(session("finished"));
    vi.mocked(fetchSessionPlace).mockResolvedValue({
      category: "standard",
      category_name: "Standard",
      sub: "random",
      place: 4,
      players: 57,
      personal_best: true,
    });
    const { container } = render(TrainingPage);

    await waitFor(() =>
      expect(container.querySelector(".place-stat")).toBeTruthy(),
    );
    const stat = container.querySelector(".place-stat")!;
    expect(fetchSessionPlace).toHaveBeenCalledWith("s1");
    expect(stat.getAttribute("href")).toBe(
      "/speedrun?pool=standard&sub=random",
    );
    expect(stat.textContent?.replace(/\s+/g, "")).toContain("4th/57PB");
  });

  it("asks 2 s after a run finishes on the page, then once more", async () => {
    vi.mocked(fetchTrainingSession).mockResolvedValue(session("active"));
    render(TrainingPage);
    await waitFor(() => expect(fetchTrainingSession).toHaveBeenCalled());
    await Promise.resolve();

    vi.useFakeTimers();
    try {
      // The record check puts the run on the boards a moment later: the
      // first answer here is still null.
      liveStatus("finished");
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(1900);
      expect(fetchSessionPlace).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(100);
      expect(fetchSessionPlace).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5000);
      expect(fetchSessionPlace).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(10_000);
      expect(fetchSessionPlace).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("asks nothing for a practice session", async () => {
    vi.mocked(fetchTrainingSession).mockResolvedValue({
      ...session("finished"),
      mode: "normal",
    });
    render(TrainingPage);

    await waitFor(() => expect(fetchTrainingGhosts).toHaveBeenCalled());
    expect(fetchSessionPlace).not.toHaveBeenCalled();
  });
});

describe("training session page: reset", () => {
  function user(id: string): AuthUser {
    return {
      id,
      twitch_username: `user-${id}`,
      twitch_display_name: null,
      twitch_avatar_url: null,
      role: "user",
      locale: null,
      overlay_settings: null,
      feedback_prompted_at: null,
      race_count: 0,
      daily_count: 0,
      training_count: 0,
    };
  }

  function run(
    status: TrainingSessionDetail["status"],
    mode: TrainingSessionDetail["mode"],
    igt_ms = 0,
  ): TrainingSessionDetail {
    return { ...session(status), mode, igt_ms };
  }

  beforeEach(() => {
    vi.mocked(resetTrainingSession).mockReset();
  });

  afterEach(() => {
    auth.user = null;
  });

  it("is offered only on the owner's active Set Seed run", async () => {
    // A Random Seed attempt stays blind, a practice run counts nowhere, and
    // a finished run keeps its time on the boards.
    const cases: [TrainingSessionDetail, string, boolean][] = [
      [run("active", "set_seed"), "u1", true],
      [run("active", "speedrun"), "u1", false],
      [run("active", "normal"), "u1", false],
      [run("finished", "set_seed"), "u1", false],
      [run("active", "set_seed"), "u2", false],
    ];
    for (const [loaded, viewer, offered] of cases) {
      auth.user = user(viewer);
      vi.mocked(fetchTrainingSession).mockResolvedValue(loaded);
      const { findByText, queryByRole, unmount } = render(TrainingPage);
      await findByText("IGT");
      expect(
        queryByRole("button", { name: "Reset" }) !== null,
        `${loaded.mode} ${loaded.status} seen by ${viewer}`,
      ).toBe(offered);
      unmount();
    }
  });

  it("restarts the run once confirmed and tells how to go on in game", async () => {
    auth.user = user("u1");
    vi.mocked(fetchTrainingSession).mockResolvedValue(
      run("active", "set_seed", 90_000),
    );
    vi.mocked(resetTrainingSession).mockResolvedValue(
      run("active", "set_seed", 0),
    );
    const { findByRole } = render(TrainingPage);

    await fireEvent.click(await findByRole("button", { name: "Reset" }));
    const modal = document.querySelector<HTMLElement>(".modal")!;
    // A new character needs a fresh game launch: the mod gives the care
    // package's Ashes of War once per launch.
    expect(modal.textContent).toContain("Close the game");
    expect(modal.textContent).toContain("start a New Game");
    expect(resetTrainingSession).not.toHaveBeenCalled();
    await fireEvent.click(within(modal).getByRole("button", { name: "Reset" }));

    // The cleared progress reaches the page through its live connection.
    expect(resetTrainingSession).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(document.querySelector(".modal")).toBeNull());
  });

  it("names the refusal of a run that ended meanwhile", async () => {
    auth.user = user("u1");
    vi.mocked(fetchTrainingSession).mockResolvedValue(
      run("active", "set_seed", 90_000),
    );
    vi.mocked(resetTrainingSession).mockRejectedValue(
      new Error("Cannot reset session in status 'finished'"),
    );
    const { findByRole, findByText } = render(TrainingPage);

    await fireEvent.click(await findByRole("button", { name: "Reset" }));
    const modal = document.querySelector<HTMLElement>(".modal")!;
    await fireEvent.click(within(modal).getByRole("button", { name: "Reset" }));

    await findByText("Cannot reset session in status 'finished'");
    expect(document.querySelector(".modal")).toBeNull();
  });
});
