/**
 * WebSocket client with automatic reconnection for SpeedFog Racing.
 */

import { getStoredToken } from "$lib/api";

// =============================================================================
// Types (matching backend WebSocket schemas)
// =============================================================================

export interface WsParticipant {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  status: string;
  current_zone: string | null;
  current_layer: number;
  igt_ms: number;
  death_count: number;
  color_index: number;
  zone_history: { node_id: string; igt_ms: number }[] | null;
}

export interface WsRaceInfo {
  id: string;
  name: string;
  status: string;
}

export interface WsSeedInfo {
  total_layers: number;
  graph_json: Record<string, unknown> | null;
  total_nodes: number | null;
  total_paths: number | null;
}

// Server -> Client messages
export interface RaceStateMessage {
  type: "race_state";
  race: WsRaceInfo;
  seed: WsSeedInfo;
  participants: WsParticipant[];
}

export interface LeaderboardUpdateMessage {
  type: "leaderboard_update";
  participants: WsParticipant[];
}

export interface PlayerUpdateMessage {
  type: "player_update";
  player: WsParticipant;
}

export interface RaceStatusChangeMessage {
  type: "race_status_change";
  status: string;
}

export interface SpectatorCountMessage {
  type: "spectator_count";
  count: number;
}

export type ServerMessage =
  | RaceStateMessage
  | LeaderboardUpdateMessage
  | PlayerUpdateMessage
  | RaceStatusChangeMessage
  | SpectatorCountMessage;

// =============================================================================
// WebSocket Client
// =============================================================================

export interface RaceWebSocketOptions {
  onRaceState?: (msg: RaceStateMessage) => void;
  onLeaderboardUpdate?: (msg: LeaderboardUpdateMessage) => void;
  onPlayerUpdate?: (msg: PlayerUpdateMessage) => void;
  onRaceStatusChange?: (msg: RaceStatusChangeMessage) => void;
  onSpectatorCount?: (msg: SpectatorCountMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000]; // ms

export class RaceWebSocket {
  private ws: WebSocket | null = null;
  private raceId: string;
  private options: RaceWebSocketOptions;
  private reconnectAttempt = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(raceId: string, options: RaceWebSocketOptions = {}) {
    this.raceId = raceId;
    this.options = options;
  }

  /**
   * Connect to the WebSocket server.
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.intentionallyClosed = false;

    // Determine WebSocket URL
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${protocol}//${host}/ws/race/${this.raceId}`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log(`[WS] Connected to race ${this.raceId}`);
      this.reconnectAttempt = 0;

      // Send auth message if logged in (optional auth per spec Section 9.1)
      const token = getStoredToken();
      if (token && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "auth", token }));
      }

      this.options.onConnect?.();
    };

    this.ws.onclose = () => {
      console.log(`[WS] Disconnected from race ${this.raceId}`);
      this.options.onDisconnect?.();

      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (event) => {
      console.error(`[WS] Error:`, event);
      this.options.onError?.(event);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ServerMessage;
        this.handleMessage(msg);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };
  }

  /**
   * Disconnect from the WebSocket server.
   */
  disconnect(): void {
    this.intentionallyClosed = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private handleMessage(msg: ServerMessage): void {
    switch (msg.type) {
      case "race_state":
        this.options.onRaceState?.(msg);
        break;
      case "leaderboard_update":
        this.options.onLeaderboardUpdate?.(msg);
        break;
      case "player_update":
        this.options.onPlayerUpdate?.(msg);
        break;
      case "race_status_change":
        this.options.onRaceStatusChange?.(msg);
        break;
      case "spectator_count":
        this.options.onSpectatorCount?.(msg);
        break;
      default:
        console.warn(
          "[WS] Unknown message type:",
          (msg as { type: string }).type,
        );
    }
  }

  private scheduleReconnect(): void {
    const delay =
      RECONNECT_DELAYS[
        Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)
      ];
    console.log(
      `[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempt + 1})`,
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempt++;
      this.connect();
    }, delay);
  }
}

/**
 * Create a WebSocket connection to a race for spectating.
 */
export function createRaceWebSocket(
  raceId: string,
  options: RaceWebSocketOptions = {},
): RaceWebSocket {
  return new RaceWebSocket(raceId, options);
}
