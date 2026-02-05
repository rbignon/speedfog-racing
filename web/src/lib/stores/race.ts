/**
 * Race state store with WebSocket integration.
 */

import { writable, derived } from "svelte/store";
import {
  createRaceWebSocket,
  type RaceWebSocket,
  type WsParticipant,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";

// =============================================================================
// Types
// =============================================================================

export interface RaceState {
  race: WsRaceInfo | null;
  seed: WsSeedInfo | null;
  participants: WsParticipant[];
  connected: boolean;
  loading: boolean;
}

// =============================================================================
// Store
// =============================================================================

const initialState: RaceState = {
  race: null,
  seed: null,
  participants: [],
  connected: false,
  loading: true,
};

function createRaceStore() {
  const { subscribe, set, update } = writable<RaceState>(initialState);
  let ws: RaceWebSocket | null = null;
  let currentRaceId: string | null = null;

  return {
    subscribe,

    /**
     * Connect to a race's WebSocket for live updates.
     */
    connect(raceId: string) {
      // If already connected to this race, do nothing
      if (currentRaceId === raceId && ws?.isConnected()) {
        return;
      }

      // Disconnect from previous race
      this.disconnect();

      currentRaceId = raceId;
      set({ ...initialState, loading: true });

      ws = createRaceWebSocket(raceId, {
        onConnect: () => {
          update((state) => ({ ...state, connected: true }));
        },

        onDisconnect: () => {
          update((state) => ({ ...state, connected: false }));
        },

        onRaceState: (msg) => {
          update((state) => ({
            ...state,
            race: msg.race,
            seed: msg.seed,
            participants: msg.participants,
            loading: false,
          }));
        },

        onLeaderboardUpdate: (msg) => {
          update((state) => ({
            ...state,
            participants: msg.participants,
          }));
        },

        onPlayerUpdate: (msg) => {
          update((state) => {
            const participants = state.participants.map((p) =>
              p.id === msg.player.id ? msg.player : p,
            );
            return { ...state, participants };
          });
        },

        onRaceStatusChange: (msg) => {
          update((state) => {
            if (!state.race) return state;
            return {
              ...state,
              race: { ...state.race, status: msg.status },
            };
          });
        },
      });

      ws.connect();
    },

    /**
     * Disconnect from the current race's WebSocket.
     */
    disconnect() {
      if (ws) {
        ws.disconnect();
        ws = null;
      }
      currentRaceId = null;
      set(initialState);
    },

    /**
     * Get the current race ID being watched.
     */
    getCurrentRaceId(): string | null {
      return currentRaceId;
    },
  };
}

export const raceStore = createRaceStore();

// =============================================================================
// Derived stores
// =============================================================================

/**
 * Sorted leaderboard (server already sends sorted, but we ensure it here).
 */
export const leaderboard = derived(raceStore, ($state) => {
  // Server sends pre-sorted, but we can re-sort for safety
  return [...$state.participants].sort((a, b) => {
    const statusPriority: Record<string, number> = {
      finished: 0,
      playing: 1,
      ready: 2,
      registered: 3,
      abandoned: 4,
    };

    const aPriority = statusPriority[a.status] ?? 99;
    const bPriority = statusPriority[b.status] ?? 99;

    if (aPriority !== bPriority) {
      return aPriority - bPriority;
    }

    // Finished: sort by IGT (ascending)
    if (a.status === "finished") {
      return a.igt_ms - b.igt_ms;
    }

    // Playing: sort by layer (descending), then IGT (ascending)
    if (a.status === "playing") {
      if (a.current_layer !== b.current_layer) {
        return b.current_layer - a.current_layer;
      }
      return a.igt_ms - b.igt_ms;
    }

    return 0;
  });
});

/**
 * Connection status.
 */
export const isConnected = derived(raceStore, ($state) => $state.connected);

/**
 * Loading status.
 */
export const isLoading = derived(raceStore, ($state) => $state.loading);

/**
 * Current race info.
 */
export const raceInfo = derived(raceStore, ($state) => $state.race);

/**
 * Seed info (including graph for DAG visualization).
 */
export const seedInfo = derived(raceStore, ($state) => $state.seed);
