import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import { flushSync } from "svelte";

import SlateScene from "../../routes/overlay/cast/event/[slug]/[stage]/[scene=castSlate]/+page.svelte";

function entry(name: string, points: number) {
  return {
    user: {
      id: name,
      twitch_username: name,
      twitch_display_name: name,
      twitch_avatar_url: null,
    },
    newcomer: false,
    points,
    igt_total: 0,
    advances: false,
    signature_weapon: null,
  };
}

const START = "2026-10-24T19:00:00Z";

// Two races over, the third still to come: ana and bob stand above the cut.
const STAGE = {
  key: "group_b",
  label: "Group B",
  kind: "round",
  bracket: "main",
  date: START,
  date_fixed: true,
  time_set: true,
  from: [],
  advance: 2,
  races_expected: 3,
  complete: false,
  walkover: false,
  modes: ["standard", "standard", "standard"],
  races: [],
  results: [entry("ana", 200), entry("bob", 140), entry("cid", 80)],
  settled_results: [entry("ana", 200), entry("bob", 140), entry("cid", 80)],
  field: [],
};

// The stages Group B's places go on to.
const QUARTER = (key: string, label: string, place: number) => ({
  ...STAGE,
  key,
  label,
  date: null,
  time_set: false,
  results: [],
  settled_results: [],
  field: [
    { user: null, label: "", forfeited: false, source: "group_b", place },
  ],
});

const EVENT = {
  slug: "season-one",
  name: "Season One",
  partner_name: "Ignite",
  stages: [
    STAGE,
    QUARTER("quarter_a", "Quarter A", 1),
    QUARTER("quarter_b", "Quarter B", 2),
  ],
  showcases: [],
};

function renderSlate(scene: "intro" | "pause" | "end") {
  return render(SlateScene, {
    props: { data: { event: EVENT, stage: STAGE, scene } } as never,
  });
}

const texts = (container: HTMLElement, selector: string) =>
  [...container.querySelectorAll(selector)].map((el) => el.textContent?.trim());

afterEach(() => {
  vi.useRealTimers();
});

describe("cast slate scenes", () => {
  // The hero and the standings panel under it are on screen together: they
  // must name the same runners, going to the same stages.
  it("the end slate's hero carries the runners the standings mark as going on", () => {
    const { container } = renderSlate("end");
    expect(texts(container, ".headliner .hn")).toEqual(["ana", "bob"]);
    expect(texts(container, ".srow.adv .sn")).toEqual(["ana", "bob"]);
    expect(texts(container, ".headliner .chip")).toEqual(
      texts(container, ".srow.adv .stag"),
    );
  });

  it("the intro counts down to the stage's start, second by second", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(START) - 754_500);
    const { container } = renderSlate("intro");
    expect(texts(container, ".clock-text")).toEqual(["12:35"]);
    await vi.advanceTimersByTimeAsync(1000);
    flushSync();
    expect(texts(container, ".clock-text")).toEqual(["12:34"]);
  });
});
