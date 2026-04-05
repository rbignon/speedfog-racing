import { describe, it, expect } from "vitest";
import {
  preserveZoneHistory,
  upsertZoneHistoryEntry,
  type ZoneHistoryEntry,
} from "$lib/zone-history";

describe("upsertZoneHistoryEntry", () => {
  it("appends to null history", () => {
    const entry: ZoneHistoryEntry = {
      node_id: "a",
      igt_ms: 1000,
      type: "fog",
    };
    const result = upsertZoneHistoryEntry(null, entry);
    expect(result).toEqual([entry]);
  });

  it("appends to empty history", () => {
    const entry: ZoneHistoryEntry = { node_id: "a", igt_ms: 1000 };
    expect(upsertZoneHistoryEntry([], entry)).toEqual([entry]);
  });

  it("appends when (node_id, igt_ms) key is new", () => {
    const history: ZoneHistoryEntry[] = [{ node_id: "a", igt_ms: 1000 }];
    const result = upsertZoneHistoryEntry(history, {
      node_id: "b",
      igt_ms: 2000,
    });
    expect(result).toHaveLength(2);
    expect(result[1]).toEqual({ node_id: "b", igt_ms: 2000 });
  });

  it("appends same node_id with different igt_ms (revisit)", () => {
    const history: ZoneHistoryEntry[] = [
      { node_id: "a", igt_ms: 1000, type: "fog" },
    ];
    const result = upsertZoneHistoryEntry(history, {
      node_id: "a",
      igt_ms: 5000,
      type: "backtrack",
    });
    expect(result).toHaveLength(2);
    expect(result[0].igt_ms).toBe(1000);
    expect(result[1].igt_ms).toBe(5000);
    expect(result[1].type).toBe("backtrack");
  });

  it("replaces matching entry in place (death attribution)", () => {
    const history: ZoneHistoryEntry[] = [
      { node_id: "a", igt_ms: 1000, type: "fog" },
      { node_id: "b", igt_ms: 2000, type: "fog" },
    ];
    const result = upsertZoneHistoryEntry(history, {
      node_id: "a",
      igt_ms: 1000,
      type: "fog",
      deaths: 3,
    });
    expect(result).toHaveLength(2);
    expect(result[0].deaths).toBe(3);
    expect(result[1].deaths).toBeUndefined();
  });

  it("returns a new array (does not mutate input)", () => {
    const history: ZoneHistoryEntry[] = [{ node_id: "a", igt_ms: 1000 }];
    const result = upsertZoneHistoryEntry(history, {
      node_id: "b",
      igt_ms: 2000,
    });
    expect(result).not.toBe(history);
    expect(history).toHaveLength(1);
  });
});

describe("preserveZoneHistory", () => {
  // Minimal shape matching WsParticipant / training participant for the
  // purposes of these tests: only the fields the helper touches.
  type P = { id: string; zone_history: ZoneHistoryEntry[] | null };

  const makeHistory = (): ZoneHistoryEntry[] => [
    { node_id: "a", igt_ms: 1000, type: "spawn" },
    { node_id: "b", igt_ms: 2000, type: "fog" },
  ];

  it("keeps the locally-held history when incoming has none (null)", () => {
    const previous = makeHistory();
    const incoming: P = { id: "p1", zone_history: null };
    const result = preserveZoneHistory(incoming, previous);
    expect(result.zone_history).toBe(previous);
    // Must be a fresh object, not a mutation of incoming.
    expect(result).not.toBe(incoming);
    expect(incoming.zone_history).toBeNull();
  });

  it("passes incoming through unchanged when it carries a history", () => {
    const previous = makeHistory();
    const fresh: ZoneHistoryEntry[] = [{ node_id: "c", igt_ms: 3000 }];
    const incoming: P = { id: "p1", zone_history: fresh };
    const result = preserveZoneHistory(incoming, previous);
    expect(result).toBe(incoming);
    expect(result.zone_history).toBe(fresh);
  });

  it("treats an empty incoming array as carried history (no override)", () => {
    // Empty array means "the server explicitly sent a history, it happens
    // to be empty" (e.g. race_state for a just-registered participant).
    const previous = makeHistory();
    const incoming: P = { id: "p1", zone_history: [] };
    const result = preserveZoneHistory(incoming, previous);
    expect(result).toBe(incoming);
    expect(result.zone_history).toEqual([]);
  });

  it("returns incoming unchanged when previous is null or undefined", () => {
    const incoming: P = { id: "p1", zone_history: null };
    expect(preserveZoneHistory(incoming, null)).toBe(incoming);
    expect(preserveZoneHistory(incoming, undefined)).toBe(incoming);
  });

  it("restores an empty-array previous (arrays are truthy)", () => {
    // When the local store holds zone_history = [] (e.g. a freshly-
    // registered participant seeded from race_state), that's still
    // valid "carried history" and should replace the incoming null so
    // the client keeps a consistent reference.
    const incoming: P = { id: "p1", zone_history: null };
    const result = preserveZoneHistory(incoming, []);
    expect(result.zone_history).toEqual([]);
  });

  // Integration-style: mirrors the way race.svelte.ts onLeaderboardUpdate
  // calls the helper in a .map() over incoming participants.
  it("restores history across a leaderboard-update-style merge", () => {
    const current: P[] = [
      { id: "p1", zone_history: makeHistory() },
      { id: "p2", zone_history: [{ node_id: "x", igt_ms: 500 }] },
      { id: "p3", zone_history: null },
    ];
    const incoming: P[] = [
      { id: "p1", zone_history: null }, // stripped by server
      { id: "p2", zone_history: null },
      { id: "p3", zone_history: null },
      { id: "p4", zone_history: null }, // new participant joining
    ];

    const historyById = new Map(current.map((p) => [p.id, p.zone_history]));
    const result = incoming.map((p) =>
      preserveZoneHistory(p, historyById.get(p.id)),
    );

    expect(result[0].zone_history).toEqual(makeHistory());
    expect(result[1].zone_history).toEqual([{ node_id: "x", igt_ms: 500 }]);
    expect(result[2].zone_history).toBeNull();
    expect(result[3].zone_history).toBeNull(); // no local history to restore
  });

  // Integration-style: mirrors race.svelte.ts onPlayerUpdate.
  it("restores history across a player-update-style merge", () => {
    const current: P[] = [
      { id: "p1", zone_history: makeHistory() },
      { id: "p2", zone_history: null },
    ];
    const incomingPlayer: P = { id: "p1", zone_history: null };
    const existing = current.find((p) => p.id === incomingPlayer.id);
    const merged = preserveZoneHistory(incomingPlayer, existing?.zone_history);
    expect(merged.zone_history).toEqual(makeHistory());
  });

  // Integration-style: mirrors training.svelte.ts singleton case.
  it("restores history for a singleton training participant", () => {
    const previous: P = { id: "s1", zone_history: makeHistory() };
    const next: P = { id: "s1", zone_history: null };
    const result = preserveZoneHistory(next, previous.zone_history);
    expect(result.zone_history).toEqual(makeHistory());
  });
});
