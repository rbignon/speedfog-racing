import { describe, it, expect, afterEach, vi } from "vitest";
import type { RaceWebSocketOptions, WsParticipant } from "$lib/websocket";

// The store's message handlers, captured from a fake client: no socket opens.
let handlers: RaceWebSocketOptions = {};
vi.mock("$lib/websocket", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/websocket")>()),
  createRaceWebSocket: (_raceId: string, options: RaceWebSocketOptions) => {
    handlers = options;
    return { connect() {}, disconnect() {}, isConnected: () => false };
  },
}));

const { raceStore } = await import("$lib/stores/race.svelte");

function runner(overrides: Partial<WsParticipant> = {}): WsParticipant {
  return {
    id: "r1",
    twitch_username: "r1",
    twitch_display_name: null,
    status: "playing",
    current_zone: null,
    current_layer: 2,
    igt_ms: 100_000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...overrides,
  };
}

describe("raceStore gap inputs", () => {
  afterEach(() => {
    raceStore.disconnect();
  });

  it("keeps a runner's splits across a player_update that omits them", () => {
    raceStore.connect("race-1");
    handlers.onLeaderboardUpdate?.({
      type: "leaderboard_update",
      participants: [
        runner({ layer_entry_igts: { 0: 0, 1: 40_000, 2: 80_000 } }),
      ],
      leader_splits: { 0: 0, 1: 40_000, 2: 80_000 },
    });
    // On async races the spectators' player_update carries no splits.
    handlers.onPlayerUpdate?.({
      type: "player_update",
      player: runner({ igt_ms: 101_000 }),
    });

    expect(raceStore.layerSplits["r1"]).toEqual({ 0: 0, 1: 40_000, 2: 80_000 });
  });
});
