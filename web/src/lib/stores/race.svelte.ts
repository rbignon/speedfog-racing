/**
 * Race state store with WebSocket integration (Svelte 5 runes).
 */

import {
  createRaceWebSocket,
  type RaceWebSocket,
  type WsParticipant,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";

class RaceStore {
  race = $state<WsRaceInfo | null>(null);
  seed = $state<WsSeedInfo | null>(null);
  participants = $state<WsParticipant[]>([]);
  spectatorCount = $state(0);
  connected = $state(false);
  loading = $state(true);

  private ws: RaceWebSocket | null = null;
  private currentRaceId: string | null = null;

  leaderboard = $derived.by(() => {
    return [...this.participants].sort((a, b) => {
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
   * Connect to a race's WebSocket for live updates.
   */
  connect(raceId: string) {
    // If already connected to this race, do nothing
    if (this.currentRaceId === raceId && this.ws?.isConnected()) {
      return;
    }

    // Disconnect from previous race
    this.disconnect();

    this.currentRaceId = raceId;
    this.race = null;
    this.seed = null;
    this.participants = [];
    this.spectatorCount = 0;
    this.connected = false;
    this.loading = true;

    this.ws = createRaceWebSocket(raceId, {
      onConnect: () => {
        this.connected = true;
      },

      onDisconnect: () => {
        this.connected = false;
      },

      onRaceState: (msg) => {
        this.race = msg.race;
        this.seed = msg.seed;
        this.participants = msg.participants;
        this.loading = false;
      },

      onLeaderboardUpdate: (msg) => {
        this.participants = msg.participants;
      },

      onPlayerUpdate: (msg) => {
        this.participants = this.participants.map((p) =>
          p.id === msg.player.id ? msg.player : p,
        );
      },

      onRaceStatusChange: (msg) => {
        if (this.race) {
          this.race = { ...this.race, status: msg.status };
        }
      },

      onSpectatorCount: (msg) => {
        this.spectatorCount = msg.count;
      },
    });

    this.ws.connect();
  }

  /**
   * Disconnect from the current race's WebSocket.
   */
  disconnect() {
    if (this.ws) {
      this.ws.disconnect();
      this.ws = null;
    }
    this.currentRaceId = null;
    this.race = null;
    this.seed = null;
    this.participants = [];
    this.spectatorCount = 0;
    this.connected = false;
    this.loading = true;
  }

  /**
   * Get the current race ID being watched.
   */
  getCurrentRaceId(): string | null {
    return this.currentRaceId;
  }
}

export const raceStore = new RaceStore();
