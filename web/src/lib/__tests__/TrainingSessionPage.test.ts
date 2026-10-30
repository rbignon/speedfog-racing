import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/svelte";

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
  };
});

import TrainingPage from "../../routes/training/[id]/+page.svelte";
import {
  fetchTrainingGhosts,
  fetchTrainingSession,
  fetchTrainingSessions,
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
