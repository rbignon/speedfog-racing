import { describe, it, expect } from "vitest";
import { parseCastParams, resolveSlots } from "$lib/cast/params";

const url = (qs: string) => new URL(`https://speedfog.racing/x${qs}`);

describe("parseCastParams", () => {
  it("falls back to two cams, no delay, slot 1 focused, no guides", () => {
    const p = parseCastParams(url(""));
    expect(p).toEqual({
      slots: [null, null, null, null],
      cams: 2,
      casters: [null, null],
      delayMs: 0,
      focus: 1,
      guides: false,
      event: null,
    });
  });

  it("reads the four slot names in order", () => {
    const p = parseCastParams(url("?p1=Nicky_rr&p3=Isumami"));
    expect(p.slots).toEqual(["Nicky_rr", null, "Isumami", null]);
  });

  it("turns the delay from seconds into milliseconds", () => {
    expect(parseCastParams(url("?delay=8")).delayMs).toBe(8000);
  });

  it("clamps a delay outside the plausible range instead of trusting it", () => {
    expect(parseCastParams(url("?delay=-4")).delayMs).toBe(0);
    expect(parseCastParams(url("?delay=600")).delayMs).toBe(60000);
    expect(parseCastParams(url("?delay=abc")).delayMs).toBe(0);
  });

  it("clamps cams and focus to what a scene can hold", () => {
    expect(parseCastParams(url("?cams=5")).cams).toBe(2);
    expect(parseCastParams(url("?cams=-1")).cams).toBe(0);
    expect(parseCastParams(url("?focus=9")).focus).toBe(4);
    expect(parseCastParams(url("?focus=0")).focus).toBe(1);
  });

  it("turns the guides mode on only for guides=1", () => {
    expect(parseCastParams(url("?guides=1")).guides).toBe(true);
    expect(parseCastParams(url("?guides=0")).guides).toBe(false);
    expect(parseCastParams(url("?guides=true")).guides).toBe(false);
  });

  it("reads the two caster usernames", () => {
    const p = parseCastParams(url("?c1=fogcaster&c2=nightbell"));
    expect(p.casters).toEqual(["fogcaster", "nightbell"]);
  });

  it("reads the event slug the co-brand needs", () => {
    expect(parseCastParams(url("?event=season-one")).event).toBe("season-one");
  });
});

describe("resolveSlots", () => {
  // color_index is the join order the server stamps on each runner; the live
  // leaderboard hands them over sorted by rank instead, so these are shuffled.
  const field = [
    { twitch_username: "isumami", color_index: 2 },
    { twitch_username: "nicky_rr", color_index: 0 },
    { twitch_username: "funion_", color_index: 3 },
    { twitch_username: "mm420_", color_index: 1 },
  ];
  const byJoin = [...field].sort((a, b) => a.color_index - b.color_index);

  it("seats the runners in join order, not in the order it was handed them", () => {
    expect(resolveSlots(field, [null, null, null, null])).toEqual(byJoin);
  });

  it("matches a name whatever its case", () => {
    const seated = resolveSlots(field, ["ISUMAMI", null, null, null]);
    expect(seated[0]?.twitch_username).toBe("isumami");
  });

  it("fills the slots left open with the runners not seated yet, in join order", () => {
    const seated = resolveSlots(field, [null, "funion_", null, null]);
    expect(seated.map((p) => p?.twitch_username)).toEqual([
      "nicky_rr",
      "funion_",
      "mm420_",
      "isumami",
    ]);
  });

  it("leaves a slot empty when the name matches nobody in the race", () => {
    const seated = resolveSlots(field, ["ghost", null, null, null]);
    expect(seated[0]).toBeNull();
  });

  it("seats a runner once: the second mention of the same name loses", () => {
    const seated = resolveSlots(field, ["mm420_", "mm420_", null, null]);
    expect(seated[0]?.twitch_username).toBe("mm420_");
    expect(seated[1]?.twitch_username).not.toBe("mm420_");
  });

  it("leaves the tail empty when the race is short of runners", () => {
    const seated = resolveSlots(field.slice(0, 2), [null, null, null, null]);
    expect(seated[2]).toBeNull();
    expect(seated[3]).toBeNull();
  });
});
