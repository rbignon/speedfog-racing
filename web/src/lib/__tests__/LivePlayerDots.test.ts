import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import LivePlayerDots from "$lib/dag/LivePlayerDots.svelte";
import type { PositionedNode } from "$lib/dag/types";

function fakeNode(over: Partial<PositionedNode> = {}): PositionedNode {
  return {
    id: "n1",
    type: "mini_dungeon",
    displayName: "Some Zone",
    zones: [],
    layer: 1,
    tier: 1,
    weight: 1,
    x: 100,
    y: 100,
    ...over,
  };
}

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    status: "abandoned",
    current_zone: "n1",
    current_layer: 1,
    igt_ms: 1000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...over,
  };
}

const nodeMap = new Map([["n1", fakeNode()]]);

// A runner's live dot sits on the map on every embed of LivePlayerDots (the
// race page, the plain /overlay/race/[id]/dag route, training, the metro
// cast scene): a visible name label next to it is new, and reserved for the
// one caller with room for it. This pins the default-off contract so a
// future change to the prop's default doesn't silently print names over
// every strip-sized embed that has never shown one.
describe("LivePlayerDots: player labels", () => {
  it("renders no name text when showPlayerLabels is absent", () => {
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [fakeParticipant()],
        nodeMap,
      },
    });
    expect(container.querySelector(".player-label")).toBeNull();
  });

  it("renders the runner's display name when showPlayerLabels is on", () => {
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [fakeParticipant()],
        nodeMap,
        showPlayerLabels: true,
      },
    });
    const label = container.querySelector(".player-label");
    expect(label?.textContent).toBe("Alice");
  });
});
