import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventTimeline from "$lib/components/events/EventTimeline.svelte";
import type { EventTimelineStop } from "$lib/api";

const stops: EventTimelineStop[] = [
  {
    key: "announce",
    label: "Announce",
    date: "2026-09-01T00:00:00Z",
    kind: "announce",
  },
  { key: "open", label: "Open", date: "2026-09-05T00:00:00Z", kind: "open" },
  { key: "cut", label: "Cut", date: "2026-09-20T00:00:00Z", kind: "cut" },
  { key: "semi", label: "Semi A", date: "2026-09-27T00:00:00Z", kind: "semi" },
];

describe("EventTimeline stop state", () => {
  it("marks every stop up to and including now as done, and the rest as upcoming", () => {
    const now = new Date("2026-09-10T00:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const glyphs = container.querySelectorAll(".g");
    expect(glyphs[0].classList.contains("done")).toBe(true);
    expect(glyphs[1].classList.contains("done")).toBe(true);
    expect(glyphs[2].classList.contains("done")).toBe(false);
    expect(glyphs[3].classList.contains("done")).toBe(false);
  });

  it("flags only the last done stop as current", () => {
    const now = new Date("2026-09-10T00:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const glyphs = container.querySelectorAll(".g");
    expect(glyphs[0].classList.contains("now")).toBe(false);
    expect(glyphs[1].classList.contains("now")).toBe(true);
  });

  it("treats a stop dated exactly now as done", () => {
    const now = new Date("2026-09-05T00:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const glyphs = container.querySelectorAll(".g");
    expect(glyphs[1].classList.contains("done")).toBe(true);
    expect(glyphs[1].classList.contains("now")).toBe(true);
  });

  it("marks nothing as done or current before the first stop", () => {
    const now = new Date("2026-08-01T00:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const glyphs = container.querySelectorAll(".g");
    for (const g of glyphs) {
      expect(g.classList.contains("done")).toBe(false);
      expect(g.classList.contains("now")).toBe(false);
    }
    const railDone = container.querySelector<HTMLElement>(".rail-done");
    expect(railDone?.getAttribute("style")).toContain("calc(0%");
  });

  it("rides the segment after the current stop in proportion to the elapsed time", () => {
    // Halfway from Open (5 Sept) to Cut (20 Sept): stops sit at 3, 34, 65
    // and 96 %, so the ridden stretch ends at 49.5 %, 46.5 % past the first.
    const now = new Date("2026-09-12T12:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const railDone = container.querySelector<HTMLElement>(".rail-done");
    expect(railDone?.getAttribute("style")).toContain("calc(46.5% - 6px)");
  });

  it("runs the rail from the first stop to the last one, not across the band", () => {
    const now = new Date("2026-09-10T00:00:00Z");
    const { container } = render(EventTimeline, { stops, now });
    const rail = container.querySelector<HTMLElement>(".rail");
    expect(rail?.getAttribute("style")).toContain("left: calc(3% + 6px)");
    expect(rail?.getAttribute("style")).toContain("right: calc(4% + 6px)");
  });

  it("centers a single stop at 50%", () => {
    const now = new Date("2026-09-10T00:00:00Z");
    const { container } = render(EventTimeline, { stops: [stops[0]], now });
    const stop = container.querySelector<HTMLElement>(".stop");
    expect(stop?.getAttribute("style")).toContain("left: 50%");
  });
});
