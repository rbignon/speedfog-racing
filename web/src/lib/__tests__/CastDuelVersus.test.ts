import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastDuelVersus from "$lib/components/cast/CastDuelVersus.svelte";

const baseProps = {
  rect: { x: 468, y: 554, w: 984, h: 198 },
  totalLayers: 35,
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

describe("CastDuelVersus: gap", () => {
  it("shows the trailing runner's deficit and names the leader", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ gap_ms: null }),
        b: bob({ gap_ms: 42_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+0:42");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("measures between the two seated runners, not against the field leader", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ gap_ms: 10_000 }),
        b: bob({ gap_ms: 4_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+0:06");
    expect(container.querySelector(".vlead")?.textContent).toBe("Bob leads");
  });

  it("shows an even duel without inventing a leader", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ gap_ms: 5_000 }),
        b: bob({ gap_ms: 5_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("0:00");
    expect(container.querySelector(".vlead")).toBeNull();
  });

  it("drops the gap once a side is out of the race, the survivor leading", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ gap_ms: null }),
        b: bob({ status: "abandoned", gap_ms: 30_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice leads");
  });

  it("names the winner once neither side is still racing", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "finished", gap_ms: null }),
        b: bob({ status: "finished", gap_ms: 42_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("+0:42");
    expect(container.querySelector(".vlead")?.textContent).toBe("Alice wins");
  });

  it("names the finisher the winner over a side that dropped out", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "abandoned", gap_ms: null }),
        b: bob({ status: "finished", gap_ms: 0 }),
      },
    });
    expect(container.querySelector(".vlead")?.textContent).toBe("Bob wins");
  });

  it("names no leader once both sides are out of the race", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "disqualified", gap_ms: null }),
        b: bob({ status: "abandoned", gap_ms: 30_000 }),
      },
    });
    expect(container.querySelector(".vgap")?.textContent).toBe("–");
    expect(container.querySelector(".vlead")).toBeNull();
  });

  it("claims no tie while both live gaps are still unknown", () => {
    const { container } = render(CastDuelVersus, {
      props: {
        ...baseProps,
        a: fakeParticipant({ status: "playing", gap_ms: null }),
        b: bob({ status: "playing", gap_ms: null }),
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
