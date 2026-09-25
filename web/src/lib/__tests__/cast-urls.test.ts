import { describe, it, expect } from "vitest";
import { buildCastUrl } from "$lib/cast/urls";

const base = {
  raceId: "r1",
  slots: ["nicky_rr", "mm420_", "isumami", "funion_"],
  cams: 2,
  casters: ["fogcaster", "nightbell"] as [string, string],
  delayS: 8,
};

describe("buildCastUrl", () => {
  it("builds a scene URL with the seating, the casters and the delay", () => {
    expect(buildCastUrl("https://x.tv", "quad", base)).toBe(
      "https://x.tv/overlay/cast/race/r1/quad?p1=nicky_rr&p2=mm420_&p3=isumami&p4=funion_&c1=fogcaster&c2=nightbell&cams=2&delay=8",
    );
  });

  it("carries the focused slot on the focus scene only", () => {
    expect(
      buildCastUrl("https://x.tv", "focus", { ...base, focus: 3 }),
    ).toContain("focus=3");
    expect(
      buildCastUrl("https://x.tv", "quad", { ...base, focus: 3 }),
    ).not.toContain("focus=");
  });

  it("leaves out what is already the default, so the URL stays readable", () => {
    const url = buildCastUrl("https://x.tv", "quad", {
      ...base,
      cams: 2,
      delayS: 0,
    });
    expect(url).not.toContain("delay=");
    expect(url).toContain("cams=2");
  });

  it("skips a hole nobody named, leaving it to the scene's own join order", () => {
    const url = buildCastUrl("https://x.tv", "quad", {
      ...base,
      slots: ["nicky_rr", null, "isumami", null],
    });
    expect(url).toContain("p1=nicky_rr");
    expect(url).not.toContain("p2=");
    expect(url).toContain("p3=isumami");
    expect(url).not.toContain("p4=");
  });

  it("carries the event slug as a query param on a race scene when one is chosen", () => {
    const url = buildCastUrl("https://x.tv", "quad", {
      ...base,
      event: "season-one",
    });
    expect(url).toContain("event=season-one");
  });

  it("shows no co-brand on a race scene when no event is chosen", () => {
    const url = buildCastUrl("https://x.tv", "quad", base);
    expect(url).not.toContain("event=");
  });

  it("orders p1..p4, focus, c1/c2, event, cams, delay", () => {
    const url = buildCastUrl("https://x.tv", "focus", {
      ...base,
      focus: 2,
      event: "season-one",
    });
    expect(url).toBe(
      "https://x.tv/overlay/cast/race/r1/focus?p1=nicky_rr&p2=mm420_&p3=isumami&p4=funion_&focus=2&c1=fogcaster&c2=nightbell&event=season-one&cams=2&delay=8",
    );
  });

  it("names the casters on the talk scene, which has no race", () => {
    expect(
      buildCastUrl("https://x.tv", "talk", {
        ...base,
        eventSlug: "season-one",
        stageKey: "semi_b",
      }),
    ).toBe(
      "https://x.tv/overlay/cast/event/season-one/semi_b/talk?c1=fogcaster&c2=nightbell&cams=2",
    );
  });

  it("carries no seating, no event param and no delay on the talk scene", () => {
    const url = buildCastUrl("https://x.tv", "talk", {
      ...base,
      eventSlug: "season-one",
      stageKey: "semi_b",
      event: "season-one",
    });
    expect(url).not.toContain("p1=");
    expect(url).not.toContain("event=");
    expect(url).not.toContain("delay=");
  });

  it("escapes a username that needs it", () => {
    const url = buildCastUrl("https://x.tv", "quad", {
      ...base,
      slots: ["a b", "mm420_", "isumami", "funion_"],
    });
    expect(url).toContain("p1=a%20b");
  });
});
