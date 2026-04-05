import { describe, it, expect } from "vitest";
import {
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
