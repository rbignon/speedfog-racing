/**
 * Race state store with WebSocket integration (Svelte 5 runes).
 */

import {
  createRaceWebSocket,
  type RaceWebSocket,
  type ChatMessage,
  type DailyStreakUpdateMessage,
  type WsParticipant,
  type WsPendingInvite,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";
import { preserveZoneHistory } from "$lib/zone-history";
import { computeGap } from "$lib/gap";

class RaceStore {
  race = $state<WsRaceInfo | null>(null);
  seed = $state<WsSeedInfo | null>(null);
  participants = $state<WsParticipant[]>([]);
  // Inputs for the live gap recomputation, captured from leaderboard_update
  // (the only message that carries them). leaderSplits is the leader's
  // per-layer entry IGTs; layerEntryIgts maps participant id -> its own layer
  // entry IGT. Both are rebuilt wholesale on each leaderboard_update.
  // Correctness relies on the server emitting a leaderboard_update on every
  // layer crossing (first-visit broadcast): that keeps each player's cached
  // layer_entry_igt consistent with the current_layer that intervening
  // player_update ticks advance, so the gap never computes against a stale
  // entry IGT.
  leaderSplits = $state<Record<number, number> | null>(null);
  layerEntryIgts = $state<Record<string, number>>({});
  // null while no race_state has arrived yet → page falls back to the
  // initial REST fetch's pending_invites until the WS catches up.
  pendingInvites = $state<WsPendingInvite[] | null>(null);
  chatMessagesParticipants = $state<ChatMessage[]>([]);
  chatMessagesPublic = $state<ChatMessage[]>([]);
  chatHistoryVersion = $state(0);
  // Latest unicast ``daily_streak_update`` payload, or null while none has
  // arrived yet. ``/daily/[date]`` reads this via $effect to patch its
  // ``my_streak`` slice when the viewer crosses the qualification on the
  // current daily; other surfaces ignore it.
  dailyStreakUpdate = $state<DailyStreakUpdateMessage | null>(null);
  spectatorCount = $state(0);
  connected = $state(false);
  loading = $state(true);
  wsError = $state<{ code: number; reason: string } | null>(null);

  private ws: RaceWebSocket | null = null;
  private currentRaceId: string | null = null;
  private currentLocale: string | null = null;
  private finishCheckTimer: ReturnType<typeof setTimeout> | null = null;

  // Render in the server's order (the server is the single source of ranking
  // truth, identical to the in-game mod) and attach each player's live gap to
  // the rank-0 leader. Re-sorting client-side would diverge from the mod and,
  // because the playing tie-break would key on the ever-changing total IGT,
  // make near-tied rows flicker every tick. The leader carries no gap.
  leaderboard = $derived.by(() => {
    const ps = this.participants;
    if (ps.length === 0) return ps;
    const splits = this.leaderSplits;
    const entries = this.layerEntryIgts;
    const leader = ps[0];
    const leaderIgtMs = leader.igt_ms;
    const leaderFinished = leader.status === "finished";
    return ps.map((p, i) => ({
      ...p,
      gap_ms: splits
        ? computeGap({
            status: p.status,
            igtMs: p.igt_ms,
            currentLayer: p.current_layer,
            layerEntryIgt: entries[p.id] ?? null,
            leaderSplits: splits,
            isLeader: i === 0,
            leaderIgtMs,
            leaderFinished,
          })
        : null,
    }));
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
    this.leaderSplits = null;
    this.layerEntryIgts = {};
    this.pendingInvites = null;
    this.chatMessagesParticipants = [];
    this.chatMessagesPublic = [];
    this.dailyStreakUpdate = null;
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
          // Older servers may not include pending_invites: keep an empty
          // array so the page can distinguish "WS sent the list" from
          // "WS hasn't broadcast yet" (null).
          this.pendingInvites = msg.pending_invites ?? [];
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
          // Capture the gap inputs this message uniquely carries. The full
          // participant list lets us rebuild layerEntryIgts wholesale, which
          // self-heals stale ids; leader_splits is absent until a leader exists.
          this.leaderSplits = msg.leader_splits ?? null;
          const entries: Record<string, number> = {};
          for (const p of msg.participants) {
            if (p.layer_entry_igt != null) entries[p.id] = p.layer_entry_igt;
          }
          this.layerEntryIgts = entries;
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
          // PATCH /races (race_duration_minutes extension, max_participants
          // bump, open_registration toggle, etc.) propagates to the live UI.
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

        onDailyStreakUpdate: (msg) => {
          this.dailyStreakUpdate = msg;
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
    this.leaderSplits = null;
    this.layerEntryIgts = {};
    this.pendingInvites = null;
    this.chatMessagesParticipants = [];
    this.chatMessagesPublic = [];
    this.chatHistoryVersion = 0;
    this.dailyStreakUpdate = null;
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
