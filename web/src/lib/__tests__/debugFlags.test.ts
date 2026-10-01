import { describe, expect, it } from "vitest";
import type { Participant } from "$lib/api";
import {
  debugFlagLabel,
  detectionRows,
  mergeDebugFlags,
} from "$lib/debugFlags";

const obs = (igt_ms: number) => ({
  igt_ms,
  node_id: null,
  detected_at: "2026-10-01T20:00:00+00:00",
});

const participant = (
  id: string,
  debug_flags: Participant["debug_flags"] = null,
): Participant => ({ id, debug_flags }) as unknown as Participant;

describe("mergeDebugFlags", () => {
  it("takes REST flags and lets a live update replace a participant's map", () => {
    const merged = mergeDebugFlags(
      [
        participant("a", { one_shot: obs(1000) }),
        participant("b"),
        participant("c", { hidden: obs(500) }),
      ],
      { a: { one_shot: obs(1000), infinite_stamina: obs(4000) } },
    );
    expect(Object.keys(merged).sort()).toEqual(["a", "c"]);
    expect(Object.keys(merged.a).sort()).toEqual([
      "infinite_stamina",
      "one_shot",
    ]);
  });

  it("keeps a participant only the live update knows", () => {
    const merged = mergeDebugFlags([], { late: { one_shot: obs(1) } });
    expect(Object.keys(merged)).toEqual(["late"]);
  });
});

describe("detectionRows", () => {
  it("orders flags and runners by first observation", () => {
    const rows = detectionRows({
      late: { hidden: obs(9000) },
      early: { infinite_stamina: obs(4000), one_shot: obs(1000) },
    });
    expect(rows.map((r) => r.participantId)).toEqual(["early", "late"]);
    expect(rows[0].flags.map((f) => f.name)).toEqual([
      "one_shot",
      "infinite_stamina",
    ]);
  });
});

describe("debugFlagLabel", () => {
  it("shows the wire name of a flag this build does not know", () => {
    expect(debugFlagLabel("future_flag")).toBe("future_flag");
  });
});
