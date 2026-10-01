import { describe, it, expect, afterEach } from "vitest";
import {
  preserveDailyPoints,
  raceStore,
  reuseIfUnchanged,
} from "$lib/stores/race.svelte";
import type { WsParticipant } from "$lib/websocket";

function participant(
  id: string,
  overrides: Partial<WsParticipant> = {},
): WsParticipant {
  return {
    id,
    twitch_username: id,
    twitch_display_name: null,
    status: "finished",
    current_zone: null,
    current_layer: 3,
    igt_ms: 300_000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...overrides,
  };
}

describe("reuseIfUnchanged", () => {
  // The wire shape: every field present, nested objects re-created by each
  // message's JSON parse.
  const wire = () =>
    participant("a", {
      daily_points: null,
      name_template: { color: null, gradient: ["#fff", "#000"] },
    } as Partial<WsParticipant>);

  it("keeps the previous object when the message re-sends the same value", () => {
    const previous = wire();
    expect(reuseIfUnchanged(wire(), previous)).toBe(previous);
  });

  it("takes the incoming object when a field changed", () => {
    const incoming = { ...wire(), igt_ms: 301_000 };
    expect(reuseIfUnchanged(incoming, wire())).toBe(incoming);
  });

  it("takes the incoming object when a nested value changed", () => {
    const incoming = wire();
    (
      incoming as unknown as { name_template: { gradient: string[] } }
    ).name_template.gradient[1] = "#111";
    expect(reuseIfUnchanged(incoming, wire())).toBe(incoming);
  });

  it("takes the incoming object when a field appeared or went missing", () => {
    const previous = wire();
    const incoming: WsParticipant = { ...wire() };
    delete incoming.daily_points;
    expect(reuseIfUnchanged(incoming, previous)).toBe(incoming);
    expect(reuseIfUnchanged(previous, incoming)).toBe(previous);
  });

  it("takes the incoming object when an undefined field replaced another", () => {
    const incoming: Partial<WsParticipant> = { id: "a", stream_url: undefined };
    const previous: Partial<WsParticipant> = { id: "a", is_live: true };
    expect(reuseIfUnchanged(incoming, previous)).toBe(incoming);
  });

  it("takes the incoming object when there is no previous one", () => {
    const incoming = wire();
    expect(reuseIfUnchanged(incoming, undefined)).toBe(incoming);
  });
});

describe("raceStore.leaderboard", () => {
  afterEach(() => {
    raceStore.disconnect();
  });

  it("keeps the rows of participants a tick left alone", () => {
    const a = participant("a", { igt_ms: 100_000 });
    const b = participant("b", { status: "playing", igt_ms: 50_000 });
    const c = participant("c", { igt_ms: 200_000 });
    raceStore.participants = [a, b, c];
    const before = raceStore.leaderboard;

    const b2 = { ...b, igt_ms: 51_000 };
    raceStore.participants = [a, b2, c];
    const after = raceStore.leaderboard;

    expect(after[0]).toBe(before[0]);
    expect(after[2]).toBe(before[2]);
    expect(after[1]).not.toBe(before[1]);
    expect(after[1].igt_ms).toBe(51_000);
  });

  it("rebuilds the rows whose gap moved with the leader", () => {
    raceStore.leaderSplits = { 1: 10_000 };
    const leader = participant("leader", { igt_ms: 100_000 });
    const runnerUp = participant("runner-up", { igt_ms: 130_000 });
    raceStore.participants = [leader, runnerUp];
    const before = raceStore.leaderboard;
    expect(before[1].gap_ms).toBe(30_000);

    // A finisher's gap is relative to the leader's IGT: the runner-up object
    // is untouched, but its row must carry the new gap.
    raceStore.participants = [{ ...leader, igt_ms: 90_000 }, runnerUp];
    const after = raceStore.leaderboard;

    expect(after[1]).not.toBe(before[1]);
    expect(after[1].gap_ms).toBe(40_000);
  });
});

describe("preserveDailyPoints", () => {
  type P = { id: string; daily_points?: number | null };

  it("restores the previous points when the incoming message drops them", () => {
    const incoming: P = { id: "a", daily_points: null };
    expect(preserveDailyPoints(incoming, 42)).toEqual({
      id: "a",
      daily_points: 42,
    });
  });

  it("restores when the incoming field is undefined", () => {
    const incoming: P = { id: "a" };
    expect(preserveDailyPoints(incoming, 42).daily_points).toBe(42);
  });

  it("keeps the incoming points when present (does not override)", () => {
    const incoming: P = { id: "a", daily_points: 10 };
    expect(preserveDailyPoints(incoming, 42)).toBe(incoming);
  });

  it("treats 0 as a real incoming value, not a missing one", () => {
    const incoming: P = { id: "a", daily_points: 0 };
    expect(preserveDailyPoints(incoming, 42).daily_points).toBe(0);
  });

  it("passes through unchanged when there is nothing to restore", () => {
    const incoming: P = { id: "a", daily_points: null };
    expect(preserveDailyPoints(incoming, null)).toBe(incoming);
    expect(preserveDailyPoints(incoming, undefined)).toBe(incoming);
  });
});
