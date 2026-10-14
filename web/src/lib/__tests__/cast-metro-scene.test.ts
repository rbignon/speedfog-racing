import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import { render } from "@testing-library/svelte";
import { raceStore } from "$lib/stores/race.svelte";
import { parseCastParams } from "$lib/cast/params";

vi.mock("$app/state", () => ({
  page: {
    url: new URL("http://localhost/overlay/cast/race/r-1/metro?cams=2"),
  },
}));

import MetroScene from "../../routes/overlay/cast/race/[id]/metro/+page.svelte";

const GRAPH = {
  total_layers: 2,
  nodes: {
    start: { type: "start", display_name: "Chapel of Anticipation", layer: 0 },
    boss: { type: "final_boss", display_name: "Starscourge Radahn", layer: 1 },
  },
  edges: [{ from: "start", to: "boss" }],
};

function renderScene(
  status: string,
  startedAt: string | null = null,
  query = "cams=2",
) {
  raceStore.seed = {
    graph_json: GRAPH,
    total_layers: 2,
  } as unknown as typeof raceStore.seed;
  return render(MetroScene, {
    props: {
      data: {
        race: {
          id: "r-1",
          name: "Group C - Race 3 - Standard",
          status,
          started_at: startedAt,
          participants: [],
          seed_total_layers: 2,
        },
        castParams: parseCastParams(new URL(`http://localhost/?${query}`)),
        partnerName: null,
      },
    } as never,
  });
}

afterEach(() => {
  raceStore.seed = null;
  raceStore.race = null;
  vi.useRealTimers();
});

// The scene goes on air, and a caster may not see the seed before the start
// either: the race page keeps its map from anyone but the field and the
// organizer until then, and so must the broadcast.
describe("cast metro scene: the seed's map", () => {
  it("stays off the scene before the start", () => {
    const { container } = renderScene("setup");
    expect(container.querySelector(".map svg")).toBeNull();
  });

  it("is drawn once the race runs", () => {
    const { container } = renderScene("running");
    expect(container.querySelector(".map svg")).not.toBeNull();
  });

  it("appears when the live race starts under a scene already on air", () => {
    raceStore.race = { status: "setup" } as unknown as typeof raceStore.race;
    const { container } = renderScene("setup");
    expect(container.querySelector(".map svg")).toBeNull();
    raceStore.race = { status: "running" } as unknown as typeof raceStore.race;
    flushSync();
    expect(container.querySelector(".map svg")).not.toBeNull();
  });

  // The server runs the race from the start command on, a countdown before
  // its start: the scene keeps its pre-start look until the start itself.
  it("stays off during the start countdown, then appears at the start", () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-14T19:00:00Z") });
    const { container } = renderScene("running", "2026-10-14T19:00:07Z");
    expect(container.querySelector(".map svg")).toBeNull();
    vi.advanceTimersByTime(7_100);
    flushSync();
    expect(container.querySelector(".map svg")).not.toBeNull();
  });

  // The usual broadcast: the scene is on air long before the organizer
  // starts the race, its countdown starting under it.
  function startUnder(container: HTMLElement, delayedBy = 0) {
    const map = () => container.querySelector(".map svg");
    vi.setSystemTime(Date.parse("2026-10-14T19:45:00Z"));
    raceStore.race = {
      status: "running",
      started_at: "2026-10-14T19:45:10Z",
    } as unknown as typeof raceStore.race;
    flushSync();
    vi.advanceTimersByTime(9_900 + delayedBy);
    flushSync();
    expect(map()).toBeNull();
    vi.advanceTimersByTime(200);
    flushSync();
    expect(map()).not.toBeNull();
  }

  it("appears when a countdown started under the scene ends", () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-14T19:00:00Z") });
    const { container } = renderScene("setup");
    startUnder(container);
  });

  it("waits for the scene's own delay on top of the countdown", () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-14T19:00:00Z") });
    const { container } = renderScene("setup", null, "cams=2&delay=30");
    startUnder(container, 30_000);
  });

  it("stays hidden on a status it does not know", () => {
    const { container } = renderScene("");
    expect(container.querySelector(".map svg")).toBeNull();
  });
});
