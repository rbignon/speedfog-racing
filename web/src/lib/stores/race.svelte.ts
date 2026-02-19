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
  private currentLocale: string | null = null;
  private finishCheckTimer: ReturnType<typeof setTimeout> | null = null;

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
  connect(raceId: string, locale: string = "en") {
    // If already connected to this race with same locale, do nothing
    if (
      this.currentRaceId === raceId &&
      this.currentLocale === locale &&
      this.ws?.isConnected()
    ) {
      return;
    }

    // Disconnect from previous race
    this.disconnect();

    this.currentRaceId = raceId;
    this.currentLocale = locale;
    this.race = null;
    this.seed = null;
    this.participants = [];
    this.spectatorCount = 0;
    this.connected = false;
    this.loading = true;

    this.ws = createRaceWebSocket(
      raceId,
      {
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
          // Cancel pending finish check — race_state already has the data
          if (this.finishCheckTimer) {
            clearTimeout(this.finishCheckTimer);
            this.finishCheckTimer = null;
          }
        },

        onLeaderboardUpdate: (msg) => {
          // When race is finished, preserve zone_history from existing data
          // in case this update doesn't include it (race condition defense).
          if (this.race?.status === "finished") {
            const historyMap = new Map(
              this.participants
                .filter((p) => p.zone_history)
                .map((p) => [p.id, p.zone_history]),
            );
            this.participants = msg.participants.map((p) => ({
              ...p,
              zone_history: p.zone_history ?? historyMap.get(p.id) ?? null,
            }));
          } else {
            this.participants = msg.participants;
          }
        },

        onPlayerUpdate: (msg) => {
          // Preserve zone_history when race is finished
          let player = msg.player;
          if (this.race?.status === "finished" && !player.zone_history) {
            const existing = this.participants.find((p) => p.id === player.id);
            if (existing?.zone_history) {
              player = { ...player, zone_history: existing.zone_history };
            }
          }
          this.participants = this.participants.map((p) =>
            p.id === player.id ? player : p,
          );
        },

        onRaceStatusChange: (msg) => {
          if (this.race) {
            this.race = {
              ...this.race,
              status: msg.status,
              started_at: msg.started_at ?? this.race.started_at,
            };
          }
          // Safety net: if status changed to "finished" but zone_history is
          // missing (e.g. race_state broadcast failed), reconnect after a
          // short delay to get the full state from the initial handshake.
          if (msg.status === "finished") {
            this.scheduleFinishCheck();
          }
        },

        onSpectatorCount: (msg) => {
          this.spectatorCount = msg.count;
        },
      },
      locale,
    );

    this.ws.connect();
  }

  /**
   * Disconnect from the current race's WebSocket.
   */
  disconnect() {
    if (this.finishCheckTimer) {
      clearTimeout(this.finishCheckTimer);
      this.finishCheckTimer = null;
    }
    if (this.ws) {
      this.ws.disconnect();
      this.ws = null;
    }
    this.currentRaceId = null;
    this.currentLocale = null;
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

  /**
   * After the race finishes, verify that zone_history arrived.
   * If not, force a WS reconnect to get the full state.
   */
  private scheduleFinishCheck() {
    if (this.finishCheckTimer) clearTimeout(this.finishCheckTimer);
    this.finishCheckTimer = setTimeout(() => {
      this.finishCheckTimer = null;
      const needsHistory = this.participants.some(
        (p) => p.status === "finished" && !p.zone_history,
      );
      if (needsHistory && this.ws && this.currentRaceId) {
        if (import.meta.env.DEV)
          console.log(
            "[RaceStore] zone_history missing after finish, reconnecting",
          );
        this.ws.disconnect();
        this.ws.connect();
      }
    }, 3000);
  }
}

export const raceStore = new RaceStore();
