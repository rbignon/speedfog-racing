import { describe, it, expect } from "vitest";
import {
  computeGap,
  formatGap,
  formatGapCompact,
  type GapInput,
} from "$lib/gap";

describe("computeGap", () => {
  // A mid-race baseline: leader entered layer 1 at 1:00 and layer 2 at 2:00,
  // so the leader spent 60s on layer 1. Individual tests override fields.
  const base: GapInput = {
    status: "playing",
    igtMs: 70_000,
    currentLayer: 1,
    layerEntryIgt: 65_000, // 5s behind the leader's layer-1 entry
    leaderSplits: { 1: 60_000, 2: 120_000 },
    isLeader: false,
    leaderIgtMs: 130_000,
    leaderFinished: false,
  };

  it("returns null for the leader", () => {
    expect(computeGap({ ...base, isLeader: true })).toBeNull();
  });

  it("returns null for pre-race / abandoned statuses", () => {
    for (const status of ["registered", "ready", "abandoned"]) {
      expect(computeGap({ ...base, status })).toBeNull();
    }
  });

  it("uses raw IGT delta for finished players (behind and ahead)", () => {
    expect(
      computeGap({
        ...base,
        status: "finished",
        igtMs: 140_000,
        leaderIgtMs: 120_000,
      }),
    ).toBe(20_000);
    expect(
      computeGap({
        ...base,
        status: "finished",
        igtMs: 110_000,
        leaderIgtMs: 120_000,
      }),
    ).toBe(-10_000);
  });

  it("returns null when the leader has no split for the player's layer", () => {
    expect(computeGap({ ...base, currentLayer: 5 })).toBeNull();
  });

  it("returns null when the player's layer entry IGT is unknown", () => {
    expect(computeGap({ ...base, layerEntryIgt: null })).toBeNull();
  });

  it("shows only the entry delta while within the leader's layer time budget", () => {
    // 5s late on entry, 5s into the layer: well under the leader's 60s.
    expect(computeGap(base)).toBe(5_000);
  });

  it("adds the overshoot once past the leader's layer time budget", () => {
    // Entered 5s late, then spent 70s on a layer the leader cleared in 60s:
    // 5s entry delta + 10s overshoot.
    expect(computeGap({ ...base, igtMs: 135_000 })).toBe(15_000);
  });

  it("falls back to the entry delta when the leader has not left the layer", () => {
    // No split for the next layer and the leader is still running.
    expect(computeGap({ ...base, leaderSplits: { 1: 60_000 } })).toBe(5_000);
  });

  it("uses the leader's finish IGT as exit time on the last layer", () => {
    // Leader finished at 3:00 having entered the last layer (2) at 2:00, so
    // its last-layer budget is 60s. Player entered 5s late and is 70s in:
    // 5s entry delta + 10s overshoot.
    expect(
      computeGap({
        ...base,
        currentLayer: 2,
        layerEntryIgt: 125_000,
        igtMs: 195_000,
        leaderSplits: { 2: 120_000 },
        leaderFinished: true,
        leaderIgtMs: 180_000,
      }),
    ).toBe(15_000);
  });
});

describe("formatGap", () => {
  it("signs and zero-pads sub-hour gaps", () => {
    expect(formatGap(135_000)).toBe("+2:15");
    expect(formatGap(-5_000)).toBe("-0:05");
    expect(formatGap(0)).toBe("+0:00");
  });

  it("renders the hour component on both sides", () => {
    expect(formatGap(3_723_000)).toBe("+1:02:03");
    expect(formatGap(-3_723_000)).toBe("-1:02:03");
  });
});

describe("formatGapCompact", () => {
  it("keeps M:SS precision under 10 minutes", () => {
    expect(formatGapCompact(0)).toBe("+0:00");
    expect(formatGapCompact(49_000)).toBe("+0:49");
    expect(formatGapCompact(599_000)).toBe("+9:59");
  });

  it("switches to whole minutes from 10 minutes to under 1 hour", () => {
    expect(formatGapCompact(600_000)).toBe("+10m");
    expect(formatGapCompact(681_000)).toBe("+11m"); // was +11:21
    expect(formatGapCompact(1_983_000)).toBe("+33m"); // was +33:03
    expect(formatGapCompact(3_540_000)).toBe("+59m");
  });

  it("switches to HhMM from 1 hour", () => {
    expect(formatGapCompact(3_600_000)).toBe("+1h00");
    expect(formatGapCompact(3_939_000)).toBe("+1h05"); // was +1:05:39
  });

  it("preserves the ahead sign across tiers", () => {
    expect(formatGapCompact(-49_000)).toBe("-0:49");
    expect(formatGapCompact(-681_000)).toBe("-11m");
    expect(formatGapCompact(-3_939_000)).toBe("-1h05");
  });
});
