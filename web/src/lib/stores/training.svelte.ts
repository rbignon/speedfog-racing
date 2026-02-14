/**
 * Training session state store with WebSocket integration (Svelte 5 runes).
 *
 * Connects to the training spectator WS endpoint for live updates
 * during an active training session.
 */

import { getStoredToken } from "$lib/api";
import type {
  WsParticipant,
  WsRaceInfo,
  WsSeedInfo,
  RaceStateMessage,
  LeaderboardUpdateMessage,
  RaceStatusChangeMessage,
} from "$lib/websocket";

type TrainingServerMessage =
  | RaceStateMessage
  | LeaderboardUpdateMessage
  | RaceStatusChangeMessage;

const VALID_TYPES = new Set([
  "race_state",
  "leaderboard_update",
  "race_status_change",
]);

function isTrainingMessage(data: unknown): data is TrainingServerMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    typeof (data as { type: unknown }).type === "string" &&
    VALID_TYPES.has((data as { type: string }).type)
  );
}

const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000];

class TrainingStore {
  race = $state<WsRaceInfo | null>(null);
  seed = $state<WsSeedInfo | null>(null);
  participant = $state<WsParticipant | null>(null);
  connected = $state(false);
  loading = $state(true);

  private ws: WebSocket | null = null;
  private currentSessionId: string | null = null;
  private reconnectAttempt = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  /**
   * Connect to a training session's spectator WebSocket.
   */
  connect(sessionId: string) {
    if (
      this.currentSessionId === sessionId &&
      this.ws?.readyState === WebSocket.OPEN
    ) {
      return;
    }

    this.disconnect();

    this.currentSessionId = sessionId;
    this.race = null;
    this.seed = null;
    this.participant = null;
    this.connected = false;
    this.loading = true;
    this.intentionallyClosed = false;
    this.reconnectAttempt = 0;

    this.doConnect();
  }

  disconnect() {
    this.intentionallyClosed = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.currentSessionId = null;
    this.race = null;
    this.seed = null;
    this.participant = null;
    this.connected = false;
    this.loading = true;
  }

  private doConnect() {
    const sessionId = this.currentSessionId;
    if (!sessionId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${protocol}//${host}/ws/training/${sessionId}/spectate`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      if (import.meta.env.DEV)
        console.log(`[TrainingWS] Connected to session ${sessionId}`);
      this.reconnectAttempt = 0;
      this.connected = true;

      // Send auth
      const token = getStoredToken();
      if (token && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "auth", token }));
      }
    };

    this.ws.onclose = () => {
      if (import.meta.env.DEV)
        console.log(`[TrainingWS] Disconnected from session ${sessionId}`);
      this.connected = false;

      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (event) => {
      console.error("[TrainingWS] Error:", event);
    };

    this.ws.onmessage = (event) => {
      try {
        const data: unknown = JSON.parse(event.data);
        // Ignore server heartbeat pings silently
        if (
          typeof data === "object" &&
          data !== null &&
          "type" in data &&
          (data as { type: string }).type === "ping"
        )
          return;
        if (!isTrainingMessage(data)) {
          if (import.meta.env.DEV)
            console.warn("[TrainingWS] Invalid message:", event.data);
          return;
        }
        this.handleMessage(data);
      } catch (e) {
        console.error("[TrainingWS] Failed to parse:", e);
      }
    };
  }

  private handleMessage(msg: TrainingServerMessage) {
    switch (msg.type) {
      case "race_state":
        this.race = msg.race;
        this.seed = msg.seed;
        this.participant = msg.participants[0] ?? null;
        this.loading = false;
        break;
      case "leaderboard_update":
        this.participant = msg.participants[0] ?? null;
        break;
      case "race_status_change":
        if (this.race) {
          this.race = {
            ...this.race,
            status: msg.status,
            started_at: msg.started_at ?? this.race.started_at,
          };
        }
        break;
    }
  }

  private scheduleReconnect() {
    const delay =
      RECONNECT_DELAYS[
        Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)
      ];
    if (import.meta.env.DEV)
      console.log(
        `[TrainingWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempt + 1})`,
      );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempt++;
      this.doConnect();
    }, delay);
  }
}

export const trainingStore = new TrainingStore();
