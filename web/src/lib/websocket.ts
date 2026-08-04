/**
 * WebSocket client with automatic reconnection for SpeedFog Racing.
 */

import { getStoredToken } from "$lib/api";
import type { ZoneHistoryEntry } from "$lib/zone-history";

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
  // IGT at which the player entered current_layer. Only carried by
  // leaderboard_update (omitted by race_state / player_update); fed into the
  // client-side gap recomputation. See $lib/gap.
  layer_entry_igt?: number | null;
  igt_ms: number;
  // Gap to the leader in ms (negative = ahead). Recomputed live by the race
  // store from leader_splits + layer_entry_igt; the server snapshot is ignored.
  gap_ms?: number | null;
  death_count: number;
  color_index: number;
  mod_connected: boolean;
  zone_history: ZoneHistoryEntry[] | null;
  is_live?: boolean;
  stream_url?: string | null;
  equipped_badge_id?: string | null;
  equipped_name_template_id?: string | null;
  daily_points?: number | null;
}

export interface WsRaceInfo {
  id: string;
  name: string;
  status: string;
  is_public?: boolean;
  open_registration?: boolean;
  max_participants?: number | null;
  scheduled_at?: string | null;
  started_at: string | null;
  seeds_released_at: string | null;
  late_join_window_minutes?: number | null;
  race_duration_minutes?: number | null;
  registration_closes_at?: string | null;
  race_ends_at?: string | null;
  private_dag?: boolean;
  deathless?: boolean;
  custom_rules?: string | null;
  countdown_seconds?: number;
  // Current seed id, mirrored from the wire RaceInfo for completeness; the web
  // reads the active seed from race_state, so this field is unused here.
  seed_id?: string | null;
}

export interface WsSeedInfo {
  total_layers: number;
  graph_json: Record<string, unknown> | null;
  total_nodes: number | null;
  total_paths: number | null;
}

export interface WsPendingInvite {
  id: string;
  twitch_username: string;
  created_at: string;
}

// Server -> Client messages
export interface RaceStateMessage {
  type: "race_state";
  race: WsRaceInfo;
  seed: WsSeedInfo;
  participants: WsParticipant[];
  pending_invites?: WsPendingInvite[];
}

export interface LeaderboardUpdateMessage {
  type: "leaderboard_update";
  participants: WsParticipant[];
  // Leader's per-layer entry IGTs (layer -> igt_ms), the reference splits the
  // race store uses to recompute each player's gap live. Only present here.
  leader_splits?: Record<number, number> | null;
}

export interface PlayerUpdateMessage {
  type: "player_update";
  player: WsParticipant;
}

export interface RaceStatusChangeMessage {
  type: "race_status_change";
  status: string;
  started_at: string | null;
  countdown_seconds?: number;
}

export interface RaceInfoUpdateMessage {
  type: "race_info_update";
  race: WsRaceInfo;
}

export interface SpectatorCountMessage {
  type: "spectator_count";
  count: number;
}

export interface ZoneHistoryMessage {
  type: "zone_history";
  participant_id: string;
  history: ZoneHistoryEntry[];
}

export interface ChatReplyContext {
  id: string;
  username: string;
  display_name: string | null;
  snippet: string;
}

export interface ChatReactionAggregate {
  emoji: string; // "thumbs_up" | "thumbs_down" | "laugh" | "cry"
  usernames: string[];
}

export interface ChatMessage {
  type: "chat_message";
  channel: "participants" | "public";
  // DB UUID; null/absent only for non-persisted system broadcasts.
  id?: string | null;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: string; // "organizer" | "admin" | "caster" | "participant" | "system"
  dominant_trait: string | null;
  equipped_badge_id?: string | null;
  equipped_name_template_id?: string | null;
  message: string;
  timestamp: string;
  reply_to?: ChatReplyContext | null;
  // Aggregated reactions in fixed emoji order; populated in chat_history,
  // then kept fresh by chat_reaction_update.
  reactions?: ChatReactionAggregate[];
}

export interface ChatHistoryMessage {
  type: "chat_history";
  channel: "participants" | "public";
  messages: ChatMessage[];
}

export interface ChatReactionUpdateMessage {
  type: "chat_reaction_update";
  channel: "participants" | "public";
  message_id: string;
  reactions: ChatReactionAggregate[];
}

export interface DailyStreakUpdateMessage {
  type: "daily_streak_update";
  current: number;
  best: number;
  freeze_count: number;
  // Set to the ``daily_date`` (YYYY-MM-DD) whose ``freeze_protected``
  // flag just flipped to true (currently the abandon trigger). ``null``
  // on qualification crossings. The page on ``/daily/[date]`` reads
  // this to patch the matching ``DailyWeekDay`` so the cell strip
  // shows "❄️ Freeze" without a reload.
  freeze_consumed_for: string | null;
}

export type ServerMessage =
  | RaceStateMessage
  | LeaderboardUpdateMessage
  | PlayerUpdateMessage
  | RaceStatusChangeMessage
  | RaceInfoUpdateMessage
  | SpectatorCountMessage
  | ZoneHistoryMessage
  | ChatMessage
  | ChatHistoryMessage
  | ChatReactionUpdateMessage
  | DailyStreakUpdateMessage;

const VALID_SERVER_MESSAGE_TYPES = new Set([
  "race_state",
  "leaderboard_update",
  "player_update",
  "race_status_change",
  "race_info_update",
  "spectator_count",
  "zone_history",
  "chat_message",
  "chat_history",
  "chat_reaction_update",
  "daily_streak_update",
]);

function isServerMessage(data: unknown): data is ServerMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    typeof (data as { type: unknown }).type === "string" &&
    VALID_SERVER_MESSAGE_TYPES.has((data as { type: string }).type)
  );
}

// =============================================================================
// WebSocket Client
// =============================================================================

export interface RaceWebSocketOptions {
  onRaceState?: (msg: RaceStateMessage) => void;
  onLeaderboardUpdate?: (msg: LeaderboardUpdateMessage) => void;
  onPlayerUpdate?: (msg: PlayerUpdateMessage) => void;
  onRaceStatusChange?: (msg: RaceStatusChangeMessage) => void;
  onRaceInfoUpdate?: (msg: RaceInfoUpdateMessage) => void;
  onSpectatorCount?: (msg: SpectatorCountMessage) => void;
  onZoneHistory?: (msg: ZoneHistoryMessage) => void;
  onChatMessage?: (msg: ChatMessage) => void;
  onChatHistory?: (msg: ChatHistoryMessage) => void;
  onChatReactionUpdate?: (msg: ChatReactionUpdateMessage) => void;
  onDailyStreakUpdate?: (msg: DailyStreakUpdateMessage) => void;
  onConnect?: () => void;
  onDisconnect?: (code?: number, reason?: string) => void;
  onError?: (error: Event) => void;
}

const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000]; // ms

export class RaceWebSocket {
  private ws: WebSocket | null = null;
  private raceId: string;
  private options: RaceWebSocketOptions;
  private locale: string;
  private reconnectAttempt = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(
    raceId: string,
    options: RaceWebSocketOptions = {},
    locale: string = "en",
  ) {
    this.raceId = raceId;
    this.options = options;
    this.locale = locale;
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
    const localeParam =
      this.locale && this.locale !== "en" ? `?locale=${this.locale}` : "";
    const url = `${protocol}//${host}/ws/race/${this.raceId}${localeParam}`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      if (import.meta.env.DEV)
        console.log(`[WS] Connected to race ${this.raceId}`);
      this.reconnectAttempt = 0;

      // Send auth or no_auth so the server can skip the auth grace period
      const token = getStoredToken();
      if (this.ws?.readyState === WebSocket.OPEN) {
        if (token) {
          this.ws.send(JSON.stringify({ type: "auth", token }));
        } else {
          this.ws.send(JSON.stringify({ type: "no_auth" }));
        }
      }

      this.options.onConnect?.();
    };

    this.ws.onclose = (event) => {
      if (import.meta.env.DEV)
        console.log(
          `[WS] Disconnected from race ${this.raceId} (code=${event.code}, reason=${event.reason || "none"})`,
        );
      this.options.onDisconnect?.(event.code, event.reason);

      // 4xxx = permanent application error, do not reconnect
      if (!this.intentionallyClosed && event.code < 4000) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (event) => {
      console.error(`[WS] Error:`, event);
      this.options.onError?.(event);
    };

    this.ws.onmessage = (event) => {
      try {
        const data: unknown = JSON.parse(event.data);
        // Respond to server heartbeat pings
        if (
          typeof data === "object" &&
          data !== null &&
          "type" in data &&
          (data as { type: string }).type === "ping"
        ) {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }
        if (!isServerMessage(data)) {
          if (import.meta.env.DEV)
            console.warn("[WS] Invalid message:", event.data);
          return;
        }
        this.handleMessage(data);
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
      // Detach handlers before closing to prevent stale onclose from
      // triggering phantom reconnects when disconnect() + connect() are
      // called on the same instance (e.g. scheduleFinishCheck).
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Send a message to the server.
   */
  send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
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
      case "race_info_update":
        this.options.onRaceInfoUpdate?.(msg);
        break;
      case "spectator_count":
        this.options.onSpectatorCount?.(msg);
        break;
      case "zone_history":
        this.options.onZoneHistory?.(msg);
        break;
      case "chat_message":
        this.options.onChatMessage?.(msg);
        break;
      case "chat_history":
        this.options.onChatHistory?.(msg);
        break;
      case "chat_reaction_update":
        this.options.onChatReactionUpdate?.(msg);
        break;
      case "daily_streak_update":
        this.options.onDailyStreakUpdate?.(msg);
        break;
      default:
        if (import.meta.env.DEV)
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
    if (import.meta.env.DEV)
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
  locale: string = "en",
): RaceWebSocket {
  return new RaceWebSocket(raceId, options, locale);
}
