import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastDuelVersus from "$lib/components/cast/CastDuelVersus.svelte";

const MIN = 60_000;

const baseProps = {
  rect: { x: 468, y: 554, w: 984, h: 198 },
  totalLayers: 35,
  ranks: new Map([
    ["p-1", 1],
    ["p-2", 2],
  ]),
  layerEntryIgts: {} as Record<string, number>,
  layerSplits: {} as Record<string, Record<number, number>>,
};

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    status: "playing",
    current_zone: null,
    current_layer: 3,
    igt_ms: 90_000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    gap_ms: null,
    equipped_badge_id: null,
    equipped_name_template_id: null,
    ...over,
  };
}

function bob(over: Record<string, unknown> = {}) {
  return fakeParticipant({
    id: "p-2",
    twitch_username: "bob",
    twitch_display_name: "Bob",
    color_index: 1,
    ...over,
  });
}

// Both at 50:00 on layer 4, which Alice reached at 31:00 and Bob at 38:00,
// both past the field leader's time there: their gaps to that leader match.
const sharedLayer = {
  alice: fakeParticipant({
    current_layer: 4,
    igt_ms: 50 * MIN,
    gap_ms: 600_000,
  }),
  bob: bob({ current_layer: 4, igt_ms: 50 * MIN, gap_ms: 600_000 }),
  inputs: {
    layerEntryIgts: { "p-1": 31 * MIN, "p-2": 38 * MIN },
    layerSplits: {
      "p-1": { 0: 0, 4: 31 * MIN },
      "p-2": { 0: 0, 4: 38 * MIN },
    },
  },
};

describe("CastDuelVersus: gap", () => {
  it("measures the trailing runner on the leading one's splits", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        ...sharedLayer.inputs,
        a: sharedLayer.alice,
        b: sharedLayer.bob,
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+7:00");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("orders the pair by rank, not by seat", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        ...sharedLayer.inputs,
        a: sharedLayer.bob,
        b: sharedLayer.alice,
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+7:00");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("signs the gap of a runner behind on depth but ahead on IGT", () => {
    // Their IGTs drifted apart: Alice, deeper, reached layer 4 at 35:00 and
    // left it at 41:00; Bob reached it at 34:00 and is there at 38:00.
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        layerEntryIgts: { "p-1": 41 * MIN, "p-2": 34 * MIN },
        layerSplits: {
          "p-1": { 0: 0, 4: 35 * MIN, 5: 41 * MIN },
          "p-2": { 0: 0, 4: 34 * MIN },
        },
        a: fakeParticipant({ current_layer: 5, igt_ms: 45 * MIN }),
        b: bob({ current_layer: 4, igt_ms: 38 * MIN }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("-1:00");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("shows an even duel without inventing a leader", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        layerSplits: { "p-1": { 0: 0 }, "p-2": { 0: 0 } },
        a: fakeParticipant({ status: "finished", igt_ms: 66 * MIN }),
        b: bob({ status: "finished", igt_ms: 66 * MIN }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("0:00");
    expect(container.querySelector(".vlead")).toBeNull();
  });

  it("drops the gap once a side is out of the race, the survivor leading", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant(),
        b: bob({ status: "abandoned" }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("names the winner once neither side is still racing", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        layerSplits: { "p-1": { 0: 0 }, "p-2": { 0: 0 } },
        a: fakeParticipant({ status: "finished", igt_ms: 66 * MIN }),
        b: bob({ status: "finished", igt_ms: 66 * MIN + 42_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+0:42");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice wins");
  });

  it("names the finisher the winner over a side that dropped out", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "abandoned" }),
        b: bob({ status: "finished" }),
      },
    });
    expect(container.querySelector(".vlead")?.textContent).toBe("Bob wins");
  });

  it("names no leader once both sides are out of the race", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "disqualified" }),
        b: bob({ status: "abandoned" }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")).toBeNull();
  });

  it("claims no tie before the race starts", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        layerSplits: { "p-1": { 0: 0 }, "p-2": { 0: 0 } },
        a: fakeParticipant({ status: "ready", current_layer: 0, igt_ms: 0 }),
        b: bob({ status: "ready", current_layer: 0, igt_ms: 0 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")).toBeNull();
  });

  it("claims no tie while the splits are still unknown", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "playing" }),
        b: bob({ status: "playing" }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")).toBeNull();
  });
});

describe("CastDuelVersus: side columns", () => {
  // Each side's depth stands in the column next to that runner's own card,
  // the gap between them; deaths stay on the cards, not repeated here.
  it("puts each side's depth in its own outer column, and no deaths", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ death_count: 3, current_layer: 6 }),
        b: bob({ death_count: 5, current_layer: 4 }),
      },
    });
    const cols = [...container.querySelectorAll(".vcol")];
    expect(cols).toHaveLength(3);
    expect(cols[0].querySelector(".vl-a")?.textContent).toBe("7/35");
    expect(cols[1].querySelector(".vgap")).not.toBeNull();
    expect(cols[2].querySelector(".vl-b")?.textContent).toBe("5/35");
    expect(container.textContent).not.toMatch(/deaths/i);
  });

  it("renders a quiet placeholder while a seat is empty", () => {
    const { container } = render(CastDuelVersus, {
      props: { ...baseProps, a: fakeParticipant(), b: null },
    });
    expect(container.querySelector(".vgap")).toBeNull();
    expect(container.querySelector(".vempty")).not.toBeNull();
  });
});
