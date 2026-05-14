import { describe, it, expect } from "vitest";
import {
  RaceWebSocket,
  type DailyStreakUpdateMessage,
  type RaceInfoUpdateMessage,
  type ServerMessage,
} from "$lib/websocket";

// Drive RaceWebSocket.handleMessage directly: spinning a real WebSocket would
// add browser plumbing for no benefit since the dispatch table is the only
// thing under test here.

interface InternalRaceWebSocket {
  handleMessage(msg: ServerMessage): void;
}

describe("RaceWebSocket message dispatch", () => {
  it("routes race_info_update to onRaceInfoUpdate", () => {
    const received: RaceInfoUpdateMessage[] = [];
    const ws = new RaceWebSocket("test-race-id", {
      onRaceInfoUpdate: (msg) => received.push(msg),
    });

    const payload: RaceInfoUpdateMessage = {
      type: "race_info_update",
      race: {
        id: "race-123",
        name: "Test",
        status: "running",
        started_at: null,
        seeds_released_at: null,
        late_join_window_minutes: 30,
        race_duration_minutes: 240,
        race_ends_at: "2026-04-21T15:00:00+00:00",
        registration_closes_at: "2026-04-21T13:00:00+00:00",
        private_dag: true,
      },
    };

    (ws as unknown as InternalRaceWebSocket).handleMessage(payload);

    expect(received).toHaveLength(1);
    expect(received[0].race.race_ends_at).toBe("2026-04-21T15:00:00+00:00");
    expect(received[0].race.race_duration_minutes).toBe(240);
    expect(received[0].race.private_dag).toBe(true);
  });

  it("routes daily_streak_update to onDailyStreakUpdate", () => {
    const received: DailyStreakUpdateMessage[] = [];
    const ws = new RaceWebSocket("test-race-id", {
      onDailyStreakUpdate: (msg) => received.push(msg),
    });

    const payload: DailyStreakUpdateMessage = {
      type: "daily_streak_update",
      current: 5,
      best: 12,
      freeze_count: 1,
      freeze_consumed_for: null,
    };

    (ws as unknown as InternalRaceWebSocket).handleMessage(payload);

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual(payload);
  });

  it("routes daily_streak_update with freeze_consumed_for", () => {
    // The abandon trigger carries the affected daily_date so the page on
    // /daily/[date] can patch the matching DailyWeekDay.freeze_protected.
    const received: DailyStreakUpdateMessage[] = [];
    const ws = new RaceWebSocket("test-race-id", {
      onDailyStreakUpdate: (msg) => received.push(msg),
    });

    const payload: DailyStreakUpdateMessage = {
      type: "daily_streak_update",
      current: 5,
      best: 12,
      freeze_count: 0,
      freeze_consumed_for: "2026-05-12",
    };

    (ws as unknown as InternalRaceWebSocket).handleMessage(payload);

    expect(received).toHaveLength(1);
    expect(received[0].freeze_consumed_for).toBe("2026-05-12");
  });

  it("drops unknown message types instead of dispatching them", () => {
    // Guards the VALID_SERVER_MESSAGE_TYPES allowlist: a typo or stale
    // client must not crash or call a callback with a malformed payload.
    const callbacks: string[] = [];
    const ws = new RaceWebSocket("test-race-id", {
      onRaceState: () => callbacks.push("race_state"),
      onLeaderboardUpdate: () => callbacks.push("leaderboard_update"),
      onRaceInfoUpdate: () => callbacks.push("race_info_update"),
      onChatMessage: () => callbacks.push("chat_message"),
    });

    // Cast through unknown to bypass the discriminated union check; we
    // want to assert handleMessage's switch-default behavior on a real
    // runtime payload that doesn't match any known type.
    const stranger = {
      type: "made_up_message",
      foo: 1,
    } as unknown as ServerMessage;
    (ws as unknown as InternalRaceWebSocket).handleMessage(stranger);

    expect(callbacks).toEqual([]);
  });
});
