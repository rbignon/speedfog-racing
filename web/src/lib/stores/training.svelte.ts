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

  private currentLocale: string | null = null;

  /**
   * Connect to a training session's spectator WebSocket.
   */
  connect(sessionId: string, locale: string = "en") {
    if (
      this.currentSessionId === sessionId &&
      this.currentLocale === locale &&
      this.ws?.readyState === WebSocket.OPEN
    ) {
      return;
    }

    this.disconnect();

    this.currentSessionId = sessionId;
    this.currentLocale = locale;
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
      // Detach handlers before closing to prevent stale onclose from
      // triggering phantom reconnects when disconnect() is followed
      // by a new connect() call (which resets intentionallyClosed).
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }

    this.currentSessionId = null;
    this.currentLocale = null;
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
    const localeParam =
      this.currentLocale && this.currentLocale !== "en"
        ? `?locale=${this.currentLocale}`
        : "";
    const url = `${protocol}//${host}/ws/training/${sessionId}/spectate${localeParam}`;

    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return; // Stale connection
      if (import.meta.env.DEV)
        console.log(`[TrainingWS] Connected to session ${sessionId}`);
      this.reconnectAttempt = 0;
      this.connected = true;

      // Send auth (token optional — anonymous spectators send without token)
      const token = getStoredToken();
      if (token) {
        ws.send(JSON.stringify({ type: "auth", token }));
      } else {
        ws.send(JSON.stringify({ type: "auth" }));
      }
    };

    ws.onclose = (event) => {
      if (this.ws !== ws) return; // Stale connection
      if (import.meta.env.DEV)
        console.log(
          `[TrainingWS] Disconnected from session ${sessionId} (code=${event.code}, reason=${event.reason || "none"})`,
        );
      this.ws = null;
      this.connected = false;

      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    ws.onerror = (event) => {
      if (this.ws !== ws) return; // Stale connection
      console.error("[TrainingWS] Error:", event);
    };

    ws.onmessage = (event) => {
      if (this.ws !== ws) return; // Stale connection
      try {
        const data: unknown = JSON.parse(event.data);
        // Respond to server heartbeat pings
        if (
          typeof data === "object" &&
          data !== null &&
          "type" in data &&
          (data as { type: string }).type === "ping"
        ) {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }
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
