import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import { raceStore } from "$lib/stores/race.svelte";
import { parseCastParams } from "$lib/cast/params";

vi.mock("$app/state", () => ({
  page: {
    url: new URL("http://localhost/overlay/cast/race/r-1/metro?cams=2"),
  },
}));

const { default: MetroScene } =
  await import("../../routes/overlay/cast/race/[id]/metro/+page.svelte");

const GRAPH = {
  total_layers: 2,
  nodes: {
    start: { type: "start", display_name: "Chapel of Anticipation", layer: 0 },
    boss: { type: "final_boss", display_name: "Starscourge Radahn", layer: 1 },
  },
  edges: [{ from: "start", to: "boss" }],
};

function renderScene(status: string) {
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
          participants: [],
          seed_total_layers: 2,
        },
        castParams: parseCastParams(new URL("http://localhost/?cams=2")),
        partnerName: null,
      },
    } as never,
  });
}

afterEach(() => {
  raceStore.seed = null;
});

// The scene goes on air, and a caster may not see the seed before the start
// either: the race page keeps its map from anyone but the field and the
// organizer until then, and so must the broadcast.
describe("cast metro scene: the seed's map", () => {
  it("stays off the scene before the start", () => {
    const { container } = renderScene("setup");
    const map = container.querySelector(".map");
    expect(map?.querySelector("svg")).toBeNull();
    expect(map?.textContent).not.toContain("Radahn");
    expect(map?.textContent).toContain("Map revealed at race start");
  });

  it("is drawn once the race runs", () => {
    const { container } = renderScene("running");
    expect(container.querySelector(".map svg")).not.toBeNull();
  });
});
