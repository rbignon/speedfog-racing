/**
 * Race state store with WebSocket integration (Svelte 5 runes).
 */

import {
  createRaceWebSocket,
  type RaceWebSocket,
  type ChatMessage,
  type WsParticipant,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";
import { preserveZoneHistory } from "$lib/zone-history";

class RaceStore {
  race = $state<WsRaceInfo | null>(null);
  seed = $state<WsSeedInfo | null>(null);
  participants = $state<WsParticipant[]>([]);
  chatMessagesParticipants = $state<ChatMessage[]>([]);
  chatMessagesPublic = $state<ChatMessage[]>([]);
  chatHistoryVersion = $state(0);
  spectatorCount = $state(0);
  connected = $state(false);
  loading = $state(true);
  wsError = $state<{ code: number; reason: string } | null>(null);

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

      // Playing/Abandoned: sort by layer (descending), then IGT (ascending)
      if (a.status === "playing" || a.status === "abandoned") {
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
    this.chatMessagesParticipants = [];
    this.chatMessagesPublic = [];
    this.spectatorCount = 0;
    this.connected = false;
    this.loading = true;
    this.wsError = null;

    this.ws = createRaceWebSocket(
      raceId,
      {
        onConnect: () => {
          this.connected = true;
        },

        onDisconnect: (code?: number, reason?: string) => {
          this.connected = false;
          if (code !== undefined && code >= 4000) {
            this.wsError = { code, reason: reason || "Connection rejected" };
            this.loading = false;
          }
        },

        onRaceState: (msg) => {
          this.race = msg.race;
          this.seed = msg.seed;
          this.participants = msg.participants;
          this.loading = false;
          // Cancel pending finish check, race_state already has the data
          if (this.finishCheckTimer) {
            clearTimeout(this.finishCheckTimer);
            this.finishCheckTimer = null;
          }
        },

        onLeaderboardUpdate: (msg) => {
          // Server no longer retransmits zone_history in leaderboard_update
          // (it arrives via race_state initially + zone_history snapshots).
          // Always preserve the locally-held history when the message carries
          // none, so the DAG keeps its trail.
          const historyById = new Map(
            this.participants.map((p) => [p.id, p.zone_history]),
          );
          this.participants = msg.participants.map((p) =>
            preserveZoneHistory(p, historyById.get(p.id)),
          );
        },

        onPlayerUpdate: (msg) => {
          // Same as leaderboard_update: preserve existing zone_history when
          // the message does not carry one (which is now the default).
          const existing = this.participants.find(
            (p) => p.id === msg.player.id,
          );
          const player = preserveZoneHistory(
            msg.player,
            existing?.zone_history,
          );
          this.participants = this.participants.map((p) =>
            p.id === player.id ? player : p,
          );
        },

        onZoneHistory: (msg) => {
          this.participants = this.participants.map((p) =>
            p.id === msg.participant_id
              ? { ...p, zone_history: msg.history }
              : p,
          );
        },

        onRaceStatusChange: (msg) => {
          if (this.race) {
            this.race = {
              ...this.race,
              status: msg.status,
              started_at: msg.started_at ?? this.race.started_at,
              countdown_seconds:
                msg.countdown_seconds ?? this.race.countdown_seconds,
            };
          }
          // Safety net: if status changed to "finished" but zone_history is
          // missing (e.g. race_state broadcast failed), reconnect after a
          // short delay to get the full state from the initial handshake.
          if (msg.status === "finished") {
            this.scheduleFinishCheck();
          }
        },

        onRaceInfoUpdate: (msg) => {
          // Wholesale replacement so any field the organizer changed via
          // PATCH /races (race_ends_at extension, max_participants bump,
          // open_registration toggle, etc.) propagates to the live UI.
          this.race = msg.race;
        },

        onSpectatorCount: (msg) => {
          this.spectatorCount = msg.count;
        },

        onChatMessage: (msg) => {
          if (msg.channel === "participants") {
            this.chatMessagesParticipants = [
              ...this.chatMessagesParticipants,
              msg,
            ];
          } else {
            this.chatMessagesPublic = [...this.chatMessagesPublic, msg];
          }
        },

        onChatHistory: (msg) => {
          if (msg.channel === "participants") {
            this.chatMessagesParticipants = [...msg.messages];
          } else {
            this.chatMessagesPublic = [...msg.messages];
          }
          this.chatHistoryVersion++;
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
    this.chatMessagesParticipants = [];
    this.chatMessagesPublic = [];
    this.chatHistoryVersion = 0;
    this.spectatorCount = 0;
    this.connected = false;
    this.loading = true;
    this.wsError = null;
  }

  /**
   * Get the current race ID being watched.
   */
  getCurrentRaceId(): string | null {
    return this.currentRaceId;
  }

  /**
   * Force a WebSocket reconnect (e.g. after role change from joining a race).
   */
  reconnect(): void {
    if (this.ws && this.currentRaceId) {
      this.ws.disconnect();
      this.ws.connect();
    }
  }

  /**
   * Send a message via the WebSocket connection.
   */
  send(data: Record<string, unknown>): void {
    this.ws?.send(data);
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
